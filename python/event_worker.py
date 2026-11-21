"""Consumidor independente dos eventos de criação de usuários."""
import json
import logging
import os
import time

import pika

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("eventos-worker")

HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
USER = os.getenv("RABBITMQ_USER", "app")
PASSWORD = os.getenv("RABBITMQ_PASSWORD", "app_password")
QUEUE = "usuarios.criados"


def conectar():
    credentials = pika.PlainCredentials(USER, PASSWORD)
    parameters = pika.ConnectionParameters(
        host=HOST,
        credentials=credentials,
        heartbeat=30,
        blocked_connection_timeout=10,
        connection_attempts=5,
        retry_delay=2,
    )
    return pika.BlockingConnection(parameters)


def processar_evento(channel, method, properties, body):
    try:
        usuario = json.loads(body.decode("utf-8"))
        logger.info(
            "Evento recebido: usuario.criado | id=%s | nome=%s | email=%s",
            usuario.get("id"), usuario.get("nome"), usuario.get("email"),
        )
        # Aqui poderia ser adicionada outra reação ao evento sem acoplar os serviços.
        channel.basic_ack(delivery_tag=method.delivery_tag)
    except Exception:
        logger.exception("Falha ao processar evento; mensagem será reenfileirada")
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)


def main():
    while True:
        connection = None
        try:
            connection = conectar()
            channel = connection.channel()
            channel.queue_declare(queue=QUEUE, durable=True)
            channel.basic_qos(prefetch_count=1)
            channel.basic_consume(queue=QUEUE, on_message_callback=processar_evento)
            logger.info("Aguardando eventos na fila %s", QUEUE)
            channel.start_consuming()
        except KeyboardInterrupt:
            break
        except Exception:
            logger.exception("Conexão com RabbitMQ perdida; nova tentativa em 5 segundos")
            time.sleep(5)
        finally:
            if connection and connection.is_open:
                connection.close()


if __name__ == "__main__":
    main()
