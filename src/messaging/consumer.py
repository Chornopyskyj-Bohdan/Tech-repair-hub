import logging
import time
import pika
from pydantic import ValidationError

from src.messaging.publisher import QUEUE_NAME, declare_topology
from src.messaging.schemas import RepairOrderCompletedEventMessage
from src.messaging.storage import (
    BillingAnalyticsStorage,
    SimulatedCrashAfterCommitError,
    TemporaryDatabaseError,
)

logger = logging.getLogger("techrepair.consumer")


class IdempotentBillingConsumer:
    """Ідемпотентний споживач подій із ручним ACK та обробкою помилок."""

    def __init__(
        self,
        storage: BillingAnalyticsStorage,
        amqp_url: str = "amqp://guest:guest@localhost:5672/",
        max_retries: int = 3,
        retry_delay: float = 0.05,
    ):
        self.storage = storage
        self.amqp_url = amqp_url
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        # Керовані прапорці для тестування точок збою (Завдання 5)
        self.fail_before_commit_once = False
        self.crash_after_commit_before_ack_once = False

    def process_single_message(self) -> str:
        """
        Вичитує одне повідомлення з черги та обробляє його.
        Повертає статус: 'PROCESSED', 'DUPLICATE', 'SENT_TO_DLQ', 'FAILED_STORED' або 'EMPTY'.
        """
        params = pika.URLParameters(self.amqp_url)
        connection = pika.BlockingConnection(params)
        try:
            channel = connection.channel()
            declare_topology(channel)
            channel.basic_qos(prefetch_count=1)

            method_frame, _properties, body = channel.basic_get(
                queue=QUEUE_NAME, auto_ack=False
            )
            if method_frame is None:
                return "EMPTY"

            raw_text = body.decode("utf-8", errors="replace")

            # 1. Валідація схеми: невалідні повідомлення одразу в DLQ (requeue=False)
            try:
                event = RepairOrderCompletedEventMessage.model_validate_json(raw_text)
            except ValidationError as exc:
                logger.warning("Невалідне повідомлення відправлено у DLQ: %s", exc)
                channel.basic_nack(delivery_tag=method_frame.delivery_tag, requeue=False)
                return "SENT_TO_DLQ"

            # 2. Обробка з обмеженою кількістю спроб для тимчасових помилок
            last_error: Exception | None = None
            for attempt in range(1, self.max_retries + 1):
                try:
                    fail_now = self.fail_before_commit_once
                    if self.fail_before_commit_once:
                        self.fail_before_commit_once = False

                    is_new = self.storage.apply_repair_completed(
                        event, fail_before_commit=fail_now
                    )

                    # Імітація раптової зупинки процесу після commit, але ДО ACK
                    if self.crash_after_commit_before_ack_once:
                        self.crash_after_commit_before_ack_once = False
                        logger.error(
                            "[event_id=%s] Збій процесу після commit до ACK!", event.event_id
                        )
                        raise SimulatedCrashAfterCommitError("Crash after commit before ACK")

                    # Ручний ACK виконується ТІЛЬКИ після успішного commit у SQLite
                    channel.basic_ack(delivery_tag=method_frame.delivery_tag)

                    if is_new:
                        logger.info(
                            "[event_id=%s] Подію успішно оброблено, ACK надіслано (order_id=%s)",
                            event.event_id,
                            event.order_id,
                        )
                        return "PROCESSED"
                    else:
                        logger.info(
                            "[event_id=%s] Виявлено дублікат події — пропущено без змін БД, ACK надіслано",
                            event.event_id,
                        )
                        return "DUPLICATE"

                except TemporaryDatabaseError as exc:
                    last_error = exc
                    logger.warning(
                        "[event_id=%s] Тимчасова помилка (спроба %d/%d): %s",
                        event.event_id,
                        attempt,
                        self.max_retries,
                        exc,
                    )
                    if attempt < self.max_retries:
                        time.sleep(self.retry_delay)

            # 3. Якщо вичерпано всі спроби — фіксуємо повідомлення для розбору та підтверджуємо брокеру
            error_msg = f"Вичерпано {self.max_retries} спроби: {last_error}"
            logger.error("[event_id=%s] %s", event.event_id, error_msg)
            self.storage.save_failed_message(raw_text, error_msg)
            channel.basic_ack(delivery_tag=method_frame.delivery_tag)
            return "FAILED_STORED"
        finally:
            if connection.is_open:
                connection.close()