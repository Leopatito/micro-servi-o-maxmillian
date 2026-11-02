
from flask import Flask, request, jsonify
import sqlite3
import os

app = Flask(__name__)

DB_PATH = "/app/data/banco.db"


def conectar():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def criar_tabela():
    with conectar() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE
            )
        """)


@app.route("/usuarios", methods=["GET"])
def listar():
    with conectar() as conn:
        usuarios = conn.execute(
            "SELECT * FROM usuarios"
        ).fetchall()

    return jsonify([dict(u) for u in usuarios])


@app.route("/usuarios", methods=["POST"])
def criar():
    dados = request.get_json()

    if not dados or not dados.get("nome") or not dados.get("email"):
        return jsonify({"erro": "Nome e email são obrigatórios"}), 400

    try:
        with conectar() as conn:
            cursor = conn.execute(
                "INSERT INTO usuarios (nome, email) VALUES (?, ?)",
                (dados["nome"], dados["email"])
            )
            usuario_id = cursor.lastrowid

        return jsonify({"id": usuario_id, **dados}), 201

    except sqlite3.IntegrityError:
        return jsonify({"erro": "Email já cadastrado"}), 409


@app.route("/usuarios/<int:id>", methods=["DELETE"])
def deletar(id):
    with conectar() as conn:
        cursor = conn.execute(
            "DELETE FROM usuarios WHERE id = ?",
            (id,)
        )

    if cursor.rowcount == 0:
        return jsonify({"erro": "Usuário não encontrado"}), 404

    return jsonify({"mensagem": "Usuário removido"})


criar_tabela()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
