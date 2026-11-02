const express = require("express");
const sqlite3 = require("sqlite3");
const { open } = require("sqlite");

const app = express();
app.use(express.json());

// Função para inicializar o banco de dados
let db;
async function initDB() {
    db = await open({
        filename: './tarefas.db',
        driver: sqlite3.Database
    });

    // Cria a tabela se ela não existir
    await db.exec(`
        CREATE TABLE IF NOT EXISTS tarefas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            descricao TEXT,
            concluida BOOLEAN DEFAULT 0
        )
    `);
}

// 1. CRIAR uma nova tarefa (Create)
app.post("/tarefas", async (req, res) => {
    const { titulo, descricao } = req.body;
    
    if (!titulo) {
        return res.status(400).json({ erro: "O título é obrigatório" });
    }

    try {
        const result = await db.run(
            'INSERT INTO tarefas (titulo, descricao, concluida) VALUES (?, ?, ?)',
            [titulo, descricao || "", 0]
        );
        
        return res.status(201).json({ id: result.lastID, titulo, descricao, concluida: 0 });
    } catch (error) {
        return res.status(500).json({ erro: "Erro ao salvar no banco de dados" });
    }
});

// 2. LISTAR todas as tarefas (Read)
app.get("/tarefas", async (req, res) => {
    const tarefas = await db.all('SELECT * FROM tarefas');
    // Converte o valor de concluida (0 ou 1 do SQLite) para booleano (false ou true)
    const tarefasFormatadas = tarefas.map(t => ({ ...t, concluida: !!t.concluida }));
    return res.json(tarefasFormatadas);
});

// 3. BUSCAR uma tarefa específica pelo ID (Read)
app.get("/tarefas/:id", async (req, res) => {
    const tarefa = await db.get('SELECT * FROM tarefas WHERE id = ?', [req.params.id]);

    if (!tarefa) {
        return res.status(404).json({ erro: "Tarefa não encontrada" });
    }
    
    tarefa.concluida = !!tarefa.concluida;
    return res.json(tarefa);
});

// 4. ATUALIZAR uma tarefa (Update)
app.put("/tarefas/:id", async (req, res) => {
    const id = req.params.id;
    const { titulo, descricao, concluida } = req.body;

    const tarefaExistente = await db.get('SELECT * FROM tarefas WHERE id = ?', [id]);
    if (!tarefaExistente) {
        return res.status(404).json({ erro: "Tarefa não encontrada" });
    }

    // Mantém os valores antigos caso algum campo não seja enviado
    const novoTitulo = titulo !== undefined ? titulo : tarefaExistente.titulo;
    const novaDescricao = descricao !== undefined ? descricao : tarefaExistente.descricao;
    const novaConcluida = concluida !== undefined ? (concluida ? 1 : 0) : tarefaExistente.concluida;

    await db.run(
        'UPDATE tarefas SET titulo = ?, descricao = ?, concluida = ? WHERE id = ?',
        [novoTitulo, novaDescricao, novaConcluida, id]
    );

    return res.json({ id, titulo: novoTitulo, descricao: novaDescricao, concluida: !!novaConcluida });
});

// 5. DELETAR uma tarefa (Delete)
app.delete("/tarefas/:id", async (req, res) => {
    const result = await db.run('DELETE FROM tarefas WHERE id = ?', [req.params.id]);

    if (result.changes === 0) {
        return res.status(404).json({ erro: "Tarefa não encontrada" });
    }

    return res.status(204).send();
});

// Inicia o banco de dados e depois o servidor
initDB().then(() => {
    const PORT = 3000;
    app.listen(PORT, () => {
        console.log(`Microsserviço com SQLite rodando na porta ${PORT}`);
    });
});