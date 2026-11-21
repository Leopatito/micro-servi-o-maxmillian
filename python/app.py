from concurrent.futures import ThreadPoolExecutor
import json
import os
from contextlib import contextmanager
import psycopg2
from psycopg2.extras import RealDictCursor
import time

import pika
from flask import Flask, request, jsonify, Response
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST

app = Flask(__name__)
PGHOST = os.getenv("PGHOST", "postgres-usuarios")
PGPORT = int(os.getenv("PGPORT", "5432"))
PGDATABASE = os.getenv("PGDATABASE", "usuarios_db")
PGUSER = os.getenv("PGUSER", "usuarios_user")
PGPASSWORD = os.getenv("PGPASSWORD", "usuarios_password")
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "app")
RABBITMQ_PASSWORD = os.getenv("RABBITMQ_PASSWORD", "app_password")
executor = ThreadPoolExecutor(max_workers=2)

usuarios_criados = Counter("usuarios_criados_total", "Quantidade total de usuários criados")
operacoes_usuarios = Counter(
    "usuarios_operacoes_total", "Operações realizadas sobre usuários", ["operacao", "resultado"]
)


@contextmanager
def conectar():
    conn = psycopg2.connect(
        host=PGHOST, port=PGPORT, dbname=PGDATABASE,
        user=PGUSER, password=PGPASSWORD,
        cursor_factory=RealDictCursor,
    )
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def criar_tabela():
    with conectar() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS usuarios (
                    id BIGSERIAL PRIMARY KEY,
                    nome TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE
                )
            """)


def publicar_evento_usuario_criado(usuario):
    """Publica o evento sem bloquear a resposta HTTP da API."""
    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASSWORD)
    parameters = pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        credentials=credentials,
        heartbeat=30,
        blocked_connection_timeout=10,
        connection_attempts=5,
        retry_delay=2,
    )
    connection = None
    try:
        connection = pika.BlockingConnection(parameters)
        channel = connection.channel()
        channel.queue_declare(queue="usuarios.criados", durable=True)
        channel.basic_publish(
            exchange="",
            routing_key="usuarios.criados",
            body=json.dumps(usuario, ensure_ascii=False).encode("utf-8"),
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=2,
                message_id=str(usuario["id"]),
            ),
        )
        app.logger.info("Evento usuario.criado publicado para o usuário %s", usuario["id"])
    except Exception:
        app.logger.exception("Não foi possível publicar o evento usuario.criado")
    finally:
        if connection and connection.is_open:
            connection.close()


@app.route("/metrics")
def metrics():
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


@app.route("/usuarios", methods=["GET"])
def listar():
    try:
        with conectar() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM usuarios ORDER BY id")
                usuarios = cursor.fetchall()
        operacoes_usuarios.labels(operacao="listar", resultado="sucesso").inc()
        return jsonify([dict(usuario) for usuario in usuarios])
    except psycopg2.Error:
        app.logger.exception("Erro ao listar usuários")
        return jsonify({"erro": "Erro ao consultar usuários"}), 500


@app.route("/usuarios", methods=["POST"])
def criar():
    dados = request.get_json(silent=True) or {}
    nome = dados.get("nome")
    email = dados.get("email")
    if not isinstance(nome, str) or not nome.strip() or not isinstance(email, str) or not email.strip():
        operacoes_usuarios.labels(operacao="criar", resultado="erro").inc()
        return jsonify({"erro": "Nome e email são obrigatórios"}), 400

    try:
        with conectar() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO usuarios (nome, email) VALUES (%s, %s) RETURNING id",
                    (nome.strip(), email.strip().lower()),
                )
                novo_id = cursor.fetchone()["id"]
            usuario = {"id": novo_id, "nome": nome.strip(), "email": email.strip().lower()}
        usuarios_criados.inc()
        operacoes_usuarios.labels(operacao="criar", resultado="sucesso").inc()
        executor.submit(publicar_evento_usuario_criado, usuario)
        return jsonify(usuario), 201
    except psycopg2.errors.UniqueViolation:
        operacoes_usuarios.labels(operacao="criar", resultado="erro").inc()
        return jsonify({"erro": "Email já cadastrado"}), 409
    except psycopg2.Error:
        app.logger.exception("Erro ao criar usuário")
        operacoes_usuarios.labels(operacao="criar", resultado="erro").inc()
        return jsonify({"erro": "Erro ao salvar usuário"}), 500


@app.route("/usuarios/<int:id>", methods=["PUT"])
def atualizar(id):
    dados = request.get_json(silent=True) or {}
    if not dados:
        return jsonify({"erro": "Informe ao menos um campo para atualizar"}), 400

    try:
        with conectar() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM usuarios WHERE id = %s", (id,))
                usuario = cursor.fetchone()
                if usuario is None:
                    return jsonify({"erro": "Usuário não encontrado"}), 404

                nome = dados.get("nome", usuario["nome"])
                email = dados.get("email", usuario["email"])
                if not isinstance(nome, str) or not nome.strip() or not isinstance(email, str) or not email.strip():
                    return jsonify({"erro": "Nome e email não podem ser vazios"}), 400

                cursor.execute(
                    "UPDATE usuarios SET nome = %s, email = %s WHERE id = %s",
                    (nome.strip(), email.strip().lower(), id),
                )
                atualizado = {"id": id, "nome": nome.strip(), "email": email.strip().lower()}

        operacoes_usuarios.labels(operacao="atualizar", resultado="sucesso").inc()
        return jsonify(atualizado)
    except psycopg2.errors.UniqueViolation:
        operacoes_usuarios.labels(operacao="atualizar", resultado="erro").inc()
        return jsonify({"erro": "Email já cadastrado por outro usuário"}), 409
    except psycopg2.Error:
        app.logger.exception("Erro ao atualizar usuário")
        operacoes_usuarios.labels(operacao="atualizar", resultado="erro").inc()
        return jsonify({"erro": "Erro ao atualizar usuário"}), 500


@app.route("/usuarios/<int:id>", methods=["DELETE"])
def deletar(id):
    try:
        with conectar() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM usuarios WHERE id = %s", (id,))
                linhas_afetadas = cursor.rowcount
        if linhas_afetadas == 0:
            return jsonify({"erro": "Usuário não encontrado"}), 404
        operacoes_usuarios.labels(operacao="excluir", resultado="sucesso").inc()
        return jsonify({"mensagem": "Usuário removido"})
    except psycopg2.Error:
        app.logger.exception("Erro ao excluir usuário")
        operacoes_usuarios.labels(operacao="excluir", resultado="erro").inc()
        return jsonify({"erro": "Erro ao excluir usuário"}), 500


def inicializar_banco():
    for tentativa in range(1, 16):
        try:
            criar_tabela()
            app.logger.info("Conectado ao PostgreSQL de usuários")
            return
        except psycopg2.Error:
            app.logger.warning("Aguardando PostgreSQL (%s/15)...", tentativa)
            time.sleep(2)
    raise RuntimeError("Não foi possível conectar ao PostgreSQL de usuários")


if __name__ == "__main__":
    inicializar_banco()
    app.run(host="0.0.0.0", port=5000)
