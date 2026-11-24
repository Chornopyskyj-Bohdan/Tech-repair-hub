import logging
import uuid
import pika
import pytest

from src.domain.aggregate import RepairOrder
from src.domain.value_objects import DeviceSpecification, Money
from src.messaging.consumer import IdempotentBillingConsumer
from src.messaging.publisher import (
    DLQ_NAME,
    QUEUE_NAME,
    RabbitMQEventPublisher,
    declare_topology,
)
from src.messaging.schemas import RepairCompletedData, RepairOrderCompletedEventMessage
from src.messaging.storage import (
    BillingAnalyticsStorage,
    SimulatedCrashAfterCommitError,
)

AMQP_URL = "amqp://guest:guest@localhost:5672/"


def _purge_queues() -> None:
    """Очищає основну чергу та DLQ перед кожним тестом."""
    params = pika.URLParameters(AMQP_URL)
    conn = pika.BlockingConnection(params)
    try:
        ch = conn.channel()
        declare_topology(ch)
        ch.queue_purge(QUEUE_NAME)
        ch.queue_purge(DLQ_NAME)
    finally:
        if conn.is_open:
            conn.close()


def _get_dlq_message_count() -> int:
    params = pika.URLParameters(AMQP_URL)
    conn = pika.BlockingConnection(params)
    try:
        ch = conn.channel()
        q = ch.queue_declare(queue=DLQ_NAME, durable=True, passive=True)
        return q.method.message_count
    finally:
        if conn.is_open:
            conn.close()


@pytest.fixture(autouse=True)
def clean_broker():
    _purge_queues()
    yield
    _purge_queues()


def _create_completed_domain_event(serial: str = "SN-1001", cost: float = 1500.0) -> RepairOrderCompletedEventMessage:
    """Створює реальний доменний агрегат, завершує ремонт і формує подію."""
    order = RepairOrder(
        order_id=uuid.uuid4(),
        device=DeviceSpecification(brand="Apple", model="MacBook Air", serial_number=serial),
    )
    order.start_diagnostics()
    order.complete_diagnostics(Money(cost, "UAH"))
    order.approve_and_start_repair()
    order.complete_repair()

    domain_event = order.domain_events[-1]
    return RepairOrderCompletedEventMessage(
        order_id=str(domain_event.order_id),
        data=RepairCompletedData(
            brand=order.device.brand,
            model=order.device.model,
            serial_number=order.device.serial_number,
            final_cost=order.estimated_cost.amount,
            currency=order.estimated_cost.currency,
        ),
    )


def test_1_successful_event_processing(tmp_path, caplog):
    """Перевірка 1: Успішна публікація та обробка події."""
    caplog.set_level(logging.INFO)
    db_file = tmp_path / "billing_1.db"
    storage = BillingAnalyticsStorage(db_file)
    publisher = RabbitMQEventPublisher(AMQP_URL)
    consumer = IdempotentBillingConsumer(storage, AMQP_URL)

    event = _create_completed_domain_event(serial="SN-001", cost=2000.0)
    publisher.publish_event(event)

    status = consumer.process_single_message()
    stats = storage.get_stats()

    assert status == "PROCESSED"
    assert stats["completed_repairs_count"] == 1
    assert stats["processed_events_count"] == 1
    assert stats["total_revenue"] == 2000.0
    assert event.event_id in caplog.text


def test_2_duplicate_event_id_is_idempotent(tmp_path, caplog):
    """Перевірка 2: Дві публікації з однаковим event_id не створюють другого бізнес-ефекту."""
    caplog.set_level(logging.INFO)
    db_file = tmp_path / "billing_2.db"
    storage = BillingAnalyticsStorage(db_file)
    publisher = RabbitMQEventPublisher(AMQP_URL)
    consumer = IdempotentBillingConsumer(storage, AMQP_URL)

    event = _create_completed_domain_event(serial="SN-002", cost=1800.0)
    publisher.publish_event(event)
    publisher.publish_event(event)  # Повторна публікація того самого event_id

    first_status = consumer.process_single_message()
    second_status = consumer.process_single_message()
    stats = storage.get_stats()

    assert first_status == "PROCESSED"
    assert second_status == "DUPLICATE"
    assert stats["completed_repairs_count"] == 1
    assert stats["processed_events_count"] == 1
    assert stats["total_revenue"] == 1800.0
    assert "Виявлено дублікат події" in caplog.text


def test_3_failure_before_commit_recovers_on_retry(tmp_path, caplog):
    """Перевірка 3: Тимчасовий збій до commit відкочує транзакцію, повтор успішно фіксує результат."""
    caplog.set_level(logging.INFO)
    db_file = tmp_path / "billing_3.db"
    storage = BillingAnalyticsStorage(db_file)
    publisher = RabbitMQEventPublisher(AMQP_URL)
    consumer = IdempotentBillingConsumer(storage, AMQP_URL, max_retries=3, retry_delay=0.01)

    event = _create_completed_domain_event(serial="SN-003", cost=2500.0)
    publisher.publish_event(event)

    # Вмикаємо керований збій на першій спробі до commit
    consumer.fail_before_commit_once = True
    status = consumer.process_single_message()
    stats = storage.get_stats()

    assert status == "PROCESSED"
    assert stats["completed_repairs_count"] == 1
    assert stats["processed_events_count"] == 1
    assert stats["total_revenue"] == 2500.0
    assert "Тимчасова помилка (спроба 1/3)" in caplog.text


def test_4_crash_after_commit_before_ack_and_redelivery_after_restart(tmp_path, caplog):
    """Перевірка 4: Зупинка після commit до ACK -> повторна доставка після перезапуску споживача."""
    caplog.set_level(logging.INFO)
    db_file = tmp_path / "billing_4.db"
    storage_before_crash = BillingAnalyticsStorage(db_file)
    publisher = RabbitMQEventPublisher(AMQP_URL)
    consumer_before_crash = IdempotentBillingConsumer(storage_before_crash, AMQP_URL)

    event = _create_completed_domain_event(serial="SN-004", cost=3200.0)
    publisher.publish_event(event)

    # Керована точка зупинки: commit у SQLite виконано, але процес падає ДО відправки ACK
    consumer_before_crash.crash_after_commit_before_ack_once = True
    with pytest.raises(SimulatedCrashAfterCommitError):
        consumer_before_crash.process_single_message()

    # Перезапускаємо споживача (новий екземпляр підключається до того самого файлу SQLite)
    # Оскільки ACK не було надіслано, RabbitMQ повторно доставляє повідомлення
    restarted_storage = BillingAnalyticsStorage(db_file)
    restarted_consumer = IdempotentBillingConsumer(restarted_storage, AMQP_URL)

    redelivery_status = restarted_consumer.process_single_message()
    stats = restarted_storage.get_stats()

    assert redelivery_status == "DUPLICATE"
    assert stats["completed_repairs_count"] == 1
    assert stats["processed_events_count"] == 1
    assert stats["total_revenue"] == 3200.0


def test_5_invalid_message_routed_to_dlq(tmp_path, caplog):
    """Перевірка 5: Пошкоджене/невалідне повідомлення не блокує чергу і потрапляє в DLQ."""
    caplog.set_level(logging.INFO)
    db_file = tmp_path / "billing_5.db"
    storage = BillingAnalyticsStorage(db_file)
    publisher = RabbitMQEventPublisher(AMQP_URL)
    consumer = IdempotentBillingConsumer(storage, AMQP_URL)

    publisher.publish_raw('{"broken_json": true, "missing_required_fields": "oops"}')

    status = consumer.process_single_message()
    stats = storage.get_stats()

    assert status == "SENT_TO_DLQ"
    assert stats["completed_repairs_count"] == 0
    assert stats["processed_events_count"] == 0
    assert _get_dlq_message_count() == 1