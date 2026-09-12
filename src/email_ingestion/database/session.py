"""Database session and connection management.

Configures SQLite with Write-Ahead Logging (WAL) and extended busy timeouts
to prevent database lock contention across concurrent workers.
"""

from contextlib import contextmanager
from typing import Generator, Optional
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from email_ingestion.database.models import Base, Message, Attachment, AuditLog


class DatabaseManager:
    """Thread-safe database manager for ACID transaction handling."""

    def __init__(self, db_url: str = "sqlite:///email_ingestion_state.db"):
        self.db_url = db_url
        connect_args = {}
        if self.db_url.startswith("sqlite"):
            connect_args = {
                "check_same_thread": False,
                "timeout": 30.0  # 30-second busy timeout
            }

        self.engine = create_engine(
            self.db_url,
            connect_args=connect_args,
            pool_pre_ping=True,
            echo=False,
            future=True
        )

        # Enable WAL mode and performance pragmas for SQLite
        if self.db_url.startswith("sqlite"):
            @event.listens_for(self.engine, "connect")
            def set_sqlite_pragmas(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                try:
                    cursor.execute("PRAGMA journal_mode=WAL;")
                    cursor.execute("PRAGMA synchronous=NORMAL;")
                    cursor.execute("PRAGMA busy_timeout=30000;")
                finally:
                    cursor.close()

        self.session_factory = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
            class_=Session
        )
        self.init_db()

    def init_db(self) -> None:
        """Create database tables if they do not exist."""
        Base.metadata.create_all(bind=self.engine)

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        """Provide a transactional database session scope."""
        session: Session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def message_exists(self, message_id: str) -> bool:
        """Check if an email message has already been processed."""
        with self.session() as db:
            return db.query(Message).filter(Message.id == message_id).first() is not None

    def find_attachment_by_hash(self, sha256_hash: str) -> Optional[Attachment]:
        """Find an existing attachment record matching a SHA-256 hash."""
        with self.session() as db:
            return db.query(Attachment).filter(
                Attachment.file_hash_sha256 == sha256_hash,
                Attachment.quarantine_status != "QUARANTINED"
            ).first()

    def find_latest_attachment_by_name(
        self,
        sender_email: str,
        filename: str,
        thread_id: Optional[str] = None
    ) -> Optional[Attachment]:
        """Find the most recent attachment from a given sender with the same filename.
        
        Thread-Scoped: If thread_id is provided, constrains lookup to the same conversation thread
        to prevent accidental collisions between different projects.
        """
        with self.session() as db:
            query = (
                db.query(Attachment)
                .join(Message, Attachment.message_id == Message.id)
                .filter(
                    Message.sender_email == sender_email,
                    Attachment.original_filename == filename,
                    Attachment.quarantine_status != "QUARANTINED"
                )
            )
            if thread_id:
                query = query.filter(Message.thread_id == thread_id)

            return query.order_by(Attachment.version_number.desc()).first()

    def log_audit_event(
        self,
        event_type: str,
        message_text: str,
        message_id: Optional[str] = None,
        details_json: Optional[str] = None
    ) -> None:
        """Record an immutable audit log entry in the state database."""
        with self.session() as db:
            audit = AuditLog(
                message_id=message_id,
                event_type=event_type,
                event_message=message_text,
                details_json=details_json
            )
            db.add(audit)

    def get_all_attachments_for_index(self) -> list:
        """Fetch all attachment records joined with their parent email messages for index generation."""
        with self.session() as db:
            results = (
                db.query(Attachment, Message)
                .join(Message, Attachment.message_id == Message.id)
                .order_by(Message.received_at.desc())
                .all()
            )
            entries = []
            for att, msg in results:
                entries.append({
                    "received_at": msg.received_at,
                    "sender": msg.sender_email,
                    "filename": att.sanitized_filename or att.original_filename,
                    "size_bytes": att.file_size_bytes,
                    "status": att.quarantine_status,
                    "local_storage_path": att.local_storage_path,
                    "version_number": att.version_number or 1
                })
            return entries

    def checkpoint(self, mode: str = "PASSIVE") -> None:
        """Execute a WAL checkpoint to flush SQLite write-ahead logs to the primary database file."""
        if self.db_url.startswith("sqlite"):
            try:
                with self.engine.connect() as conn:
                    conn.exec_driver_sql(f"PRAGMA wal_checkpoint({mode});")
            except Exception:
                pass

    def close(self) -> None:
        """Safely flush WAL checkpoints and dispose database connection pool."""
        try:
            self.checkpoint(mode="TRUNCATE")
        except Exception:
            pass
        self.engine.dispose()

