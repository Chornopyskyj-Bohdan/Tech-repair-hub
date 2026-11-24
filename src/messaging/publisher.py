import pika
from src.messaging.schemas import RepairOrderCompletedEventMessage

EXCHANGE_NAME = "techrepair.events"
QUEUE_NAME = "repair.completed.queue"
ROUTING_KEY = "repair.order.completed"

DLX_NAME = "techrepair.dlx"
DLQ_NAME = "repair.completed.dlq"


def declare_topology(channel: pika.adapters.blocking_connection.BlockingChannel) -> None:
    """Оголошує durable exchange, чергу споживача та Dead Letter Queue (DLQ)."""
    channel.exchange_declare(exchange=DLX_NAME, exchange_type="fanout", durable=True)
    channel.queue_declare(queue=DLQ_NAME, durable=True)
    channel.queue_bind(queue=DLQ_NAME, exchange=DLX_NAME)

    channel.exchange_declare(exchange=EXCHANGE_NAME, exchange_type="direct", durable=True)
    channel.queue_declare(
        queue=QUEUE_NAME,
        durable=True,
        arguments={"x-dead-letter-exchange": DLX_NAME},
    )
    channel.queue_bind(queue=QUEUE_NAME, exchange=EXCHANGE_NAME, routing_key=ROUTING_KEY)


class RabbitMQEventPublisher:
    """Публікатор подій із підтвердженням від брокера (Publisher Confirms)."""

    def __init__(self, amqp_url: str = "amqp://guest:guest@localhost:5672/"):
        self.amqp_url = amqp_url

    def publish_event(self, event: RepairOrderCompletedEventMessage) -> None:
        self.publish_raw(event.model_dump_json(), message_id=event.event_id)

    def publish_raw(self, raw_payload: str, message_id: str | None = None) -> None:
        params = pika.URLParameters(self.amqp_url)
        connection = pika.BlockingConnection(params)
        try:
            channel = connection.channel()
            declare_topology(channel)
            channel.confirm_delivery()

            channel.basic_publish(
                exchange=EXCHANGE_NAME,
                routing_key=ROUTING_KEY,
                body=raw_payload.encode("utf-8"),
                properties=pika.BasicProperties(
                    delivery_mode=2,  # persistent повідомлення на диск
                    content_type="application/json",
                    message_id=message_id,
                ),
                mandatory=True,
            )
        finally:
            if connection.is_open:
                connection.close()