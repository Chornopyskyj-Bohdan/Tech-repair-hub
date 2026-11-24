import sqlite3
from pathlib import Path
from src.messaging.schemas import RepairOrderCompletedEventMessage


class TemporaryDatabaseError(Exception):
    """Імітація тимчасового збою БД (наприклад, блокування транзакції)."""


class SimulatedCrashAfterCommitError(Exception):
    """Керована точка зупинки: збій споживача після commit, але до відправки ACK брокеру."""


class BillingAnalyticsStorage:
    """Локальне SQLite-сховище споживача з атомарною ідемпотентністю."""

    def __init__(self, db_path: str | Path = "billing_analytics.db"):
        self.db_path = str(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS processed_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS completed_repairs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT UNIQUE NOT NULL,
                    event_id TEXT NOT NULL,
                    device_info TEXT NOT NULL,
                    revenue REAL NOT NULL,
                    currency TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS failed_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    raw_body TEXT NOT NULL,
                    error_reason TEXT NOT NULL,
                    failed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()

    def apply_repair_completed(
        self,
        event: RepairOrderCompletedEventMessage,
        fail_before_commit: bool = False,
    ) -> bool:
        """
        Атомарно записує event_id та фінансовий результат в одній транзакції.
        Повертає True, якщо подію оброблено вперше, або False, якщо це дублікат.
        """
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")

            existing = conn.execute(
                "SELECT 1 FROM processed_events WHERE event_id = ?",
                (event.event_id,),
            ).fetchone()
            if existing:
                conn.rollback()
                return False

            conn.execute(
                "INSERT INTO processed_events (event_id, event_type) VALUES (?, ?)",
                (event.event_id, event.event_type),
            )

            device_info = f"{event.data.brand} {event.data.model} ({event.data.serial_number})"
            conn.execute(
                """
                INSERT OR IGNORE INTO completed_repairs
                (order_id, event_id, device_info, revenue, currency)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event.order_id,
                    event.event_id,
                    device_info,
                    event.data.final_cost,
                    event.data.currency,
                ),
            )

            if fail_before_commit:
                raise TemporaryDatabaseError("Керований збій БД до фіксації транзакції (commit)")

            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def save_failed_message(self, raw_body: str, error_reason: str) -> None:
        """Зберігає повідомлення для розбору після вичерпання спроб повтору."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO failed_messages (raw_body, error_reason) VALUES (?, ?)",
                (raw_body, error_reason),
            )
            conn.commit()

    def get_stats(self) -> dict:
        with self._connect() as conn:
            repairs_count = conn.execute("SELECT COUNT(*) FROM completed_repairs").fetchone()[0]
            events_count = conn.execute("SELECT COUNT(*) FROM processed_events").fetchone()[0]
            failed_count = conn.execute("SELECT COUNT(*) FROM failed_messages").fetchone()[0]
            total_revenue = conn.execute(
                "SELECT COALESCE(SUM(revenue), 0.0) FROM completed_repairs"
            ).fetchone()[0]
        return {
            "completed_repairs_count": repairs_count,
            "processed_events_count": events_count,
            "failed_messages_count": failed_count,
            "total_revenue": total_revenue,
        }
    