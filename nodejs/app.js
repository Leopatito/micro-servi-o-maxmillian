const express = require("express");
const { Pool } = require("pg");
const promClient = require("prom-client");

const app = express();
app.use(express.json());

promClient.collectDefaultMetrics();
const tarefasCriadas = new promClient.Counter({
  name: "tarefas_criadas_total",
  help: "Quantidade total de tarefas criadas"
});
const operacoesTarefas = new promClient.Counter({
  name: "tarefas_operacoes_total",
  help: "Quantidade de operações realizadas sobre tarefas",
  labelNames: ["operacao", "resultado"]
});

app.get("/metrics", async (req, res) => {
  res.set("Content-Type", promClient.register.contentType);
  res.end(await promClient.register.metrics());
});

const db = new Pool({
  host: process.env.PGHOST || "postgres-tarefas",
  port: Number(process.env.PGPORT || 5432),
  database: process.env.PGDATABASE || "tarefas_db",
  user: process.env.PGUSER || "tarefas_user",
  password: process.env.PGPASSWORD || "tarefas_password",
  max: 10,
});

async function initDB() {
  await db.query(`
    CREATE TABLE IF NOT EXISTS tarefas (
      id BIGSERIAL PRIMARY KEY,
      titulo TEXT NOT NULL,
      descricao TEXT,
      concluida BOOLEAN NOT NULL DEFAULT FALSE
    )
  `);
}


app.post("/tarefas", async (req, res) => {
  const { titulo, descricao } = req.body || {};
  if (typeof titulo !== "string" || !titulo.trim()) {
    operacoesTarefas.inc({ operacao: "criar", resultado: "erro" });
    return res.status(400).json({ erro: "O título é obrigatório" });
  }

  try {
    const result = await db.query(
      "INSERT INTO tarefas (titulo, descricao, concluida) VALUES ($1, $2, $3) RETURNING id",
      [titulo.trim(), descricao || "", false]
    );
    tarefasCriadas.inc();
    operacoesTarefas.inc({ operacao: "criar", resultado: "sucesso" });
    return res.status(201).json({ id: result.rows[0].id, titulo: titulo.trim(), descricao: descricao || "", concluida: false });
  } catch (error) {
    console.error("Erro ao criar tarefa:", error);
    operacoesTarefas.inc({ operacao: "criar", resultado: "erro" });
    return res.status(500).json({ erro: "Erro ao salvar no banco de dados" });
  }
});

app.get("/tarefas", async (req, res) => {
  try {
    const result = await db.query("SELECT * FROM tarefas ORDER BY id");
    const tarefas = result.rows;
    operacoesTarefas.inc({ operacao: "listar", resultado: "sucesso" });
    return res.json(tarefas.map(t => ({ ...t, concluida: Boolean(t.concluida) })));
  } catch (error) {
    console.error("Erro ao listar tarefas:", error);
    return res.status(500).json({ erro: "Erro ao consultar tarefas" });
  }
});

app.get("/tarefas/:id", async (req, res) => {
  try {
    const result = await db.query("SELECT * FROM tarefas WHERE id = $1", [req.params.id]);
    const tarefa = result.rows[0];
    if (!tarefa) return res.status(404).json({ erro: "Tarefa não encontrada" });
    return res.json({ ...tarefa, concluida: Boolean(tarefa.concluida) });
  } catch (error) {
    console.error("Erro ao consultar tarefa:", error);
    return res.status(500).json({ erro: "Erro ao consultar tarefa" });
  }
});

app.put("/tarefas/:id", async (req, res) => {
  try {
    const result = await db.query("SELECT * FROM tarefas WHERE id = $1", [req.params.id]);
    const tarefa = result.rows[0];
    if (!tarefa) return res.status(404).json({ erro: "Tarefa não encontrada" });

    const { titulo, descricao, concluida } = req.body || {};
    if (titulo !== undefined && (typeof titulo !== "string" || !titulo.trim())) {
      return res.status(400).json({ erro: "O título não pode ser vazio" });
    }
    if (concluida !== undefined && typeof concluida !== "boolean") {
      return res.status(400).json({ erro: "O campo concluida deve ser booleano" });
    }

    const atualizado = {
      titulo: titulo !== undefined ? titulo.trim() : tarefa.titulo,
      descricao: descricao !== undefined ? descricao : tarefa.descricao,
      concluida: concluida !== undefined ? concluida : Boolean(tarefa.concluida)
    };
    await db.query(
      "UPDATE tarefas SET titulo = $1, descricao = $2, concluida = $3 WHERE id = $4",
      [atualizado.titulo, atualizado.descricao, atualizado.concluida, req.params.id]
    );
    operacoesTarefas.inc({ operacao: "atualizar", resultado: "sucesso" });
    return res.json({ id: Number(req.params.id), ...atualizado });
  } catch (error) {
    console.error("Erro ao atualizar tarefa:", error);
    operacoesTarefas.inc({ operacao: "atualizar", resultado: "erro" });
    return res.status(500).json({ erro: "Erro ao atualizar tarefa" });
  }
});

app.delete("/tarefas/:id", async (req, res) => {
  try {
    const result = await db.query("DELETE FROM tarefas WHERE id = $1", [req.params.id]);
    if (result.rowCount === 0) return res.status(404).json({ erro: "Tarefa não encontrada" });
    operacoesTarefas.inc({ operacao: "excluir", resultado: "sucesso" });
    return res.status(204).send();
  } catch (error) {
    console.error("Erro ao excluir tarefa:", error);
    operacoesTarefas.inc({ operacao: "excluir", resultado: "erro" });
    return res.status(500).json({ erro: "Erro ao excluir tarefa" });
  }
});

async function start() {
  try {
    // Aguarda o PostgreSQL e prepara o schema antes de iniciar a API.
    let conectado = false;
    for (let tentativa = 1; tentativa <= 15; tentativa++) {
      try {
        await db.query("SELECT 1");
        conectado = true;
        break;
      } catch (error) {
        console.log(`Aguardando PostgreSQL (${tentativa}/15)...`);
        await new Promise(resolve => setTimeout(resolve, 2000));
      }
    }
    if (!conectado) throw new Error("Não foi possível conectar ao PostgreSQL de tarefas");
    await initDB();
    const port = Number(process.env.PORT || 3000);
    app.listen(port, "0.0.0.0", () => console.log(`Microsserviço de tarefas rodando na porta ${port}`));
  } catch (error) {
    console.error("Não foi possível iniciar o banco de tarefas:", error);
    process.exit(1);
  }
}

start();

process.on("SIGTERM", async () => { await db.end(); process.exit(0); });
