"""SQLAlchemy models for the ACID state ledger.

Maintains an immutable record of all processed accounts, messages,
attachments, revisions, and security audit logs.
"""

from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy import (
    Column,
    String,
    Integer,
    DateTime,
    ForeignKey,
    Text,
    Float,
    Boolean
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def utc_now() -> datetime:
    """Helper to return standard timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


class Account(Base):
    """Represents a monitored mailbox or provider connection."""
    __tablename__ = "accounts"

    id = Column(String(64), primary_key=True, comment="Unique account identifier")
    provider = Column(String(32), nullable=False, comment="GMAIL, M365, or MOCK")
    email_address = Column(String(255), nullable=False, unique=True)
    delta_token = Column(Text, nullable=True, comment="Delta sync token or historyId")
    last_sync_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    # Relationships
    messages = relationship("Message", back_populates="account", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Account(id={self.id}, provider={self.provider}, email={self.email_address})>"


class Message(Base):
    """Represents an ingested email message envelope."""
    __tablename__ = "messages"

    id = Column(String(128), primary_key=True, comment="Provider Message ID (e.g. Graph ID or Gmail ID)")
    account_id = Column(String(64), ForeignKey("accounts.id"), nullable=False)
    thread_id = Column(String(128), nullable=True)
    sender_email = Column(String(255), nullable=False, index=True)
    sender_name = Column(String(255), nullable=True)
    subject = Column(Text, nullable=True)
    received_at = Column(DateTime(timezone=True), nullable=False, index=True)
    status = Column(String(32), default="PROCESSED", comment="PROCESSED, SKIPPED, or FAILED")
    has_attachments = Column(Boolean, default=False)
    raw_body_snippet = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    # Relationships
    account = relationship("Account", back_populates="messages")
    attachments = relationship("Attachment", back_populates="message", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="message", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Message(id={self.id}, sender={self.sender_email}, subject={self.subject[:30] if self.subject else 'None'})>"


class Attachment(Base):
    """Represents an attachment associated with an ingested message."""
    __tablename__ = "attachments"

    id = Column(String(128), primary_key=True, comment="Composite or provider attachment ID")
    message_id = Column(String(128), ForeignKey("messages.id"), nullable=False)
    original_filename = Column(String(255), nullable=False)
    sanitized_filename = Column(String(255), nullable=False)
    file_hash_sha256 = Column(String(64), nullable=False, index=True, comment="Cryptographic SHA-256")
    file_size_bytes = Column(Integer, nullable=False)
    detected_mime_type = Column(String(128), nullable=True)
    
    # Versioning & Revision Intelligence
    version_number = Column(Integer, default=1, comment="Version increment for same-name revisions")
    parent_attachment_id = Column(String(128), ForeignKey("attachments.id"), nullable=True)
    similarity_score = Column(Float, nullable=True, comment="Fuzzy similarity score against parent version")
    
    # Storage & Security Status
    local_storage_path = Column(Text, nullable=False)
    quarantine_status = Column(String(32), default="CLEAN", comment="CLEAN, QUARANTINED, or DUPLICATE_SKIPPED")
    quarantine_reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    # Relationships
    message = relationship("Message", back_populates="attachments")

    def __repr__(self) -> str:
        return f"<Attachment(id={self.id}, filename={self.sanitized_filename}, hash={self.file_hash_sha256[:8]})>"


class AuditLog(Base):
    """Immutable audit trail for every ingestion action, anomaly, or warning."""
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(String(128), ForeignKey("messages.id"), nullable=True)
    event_type = Column(String(64), nullable=False, index=True, comment="INFO, WARNING, DUPLICATE_ANOMALY, QUARANTINE")
    event_message = Column(Text, nullable=False)
    details_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    # Relationships
    message = relationship("Message", back_populates="audit_logs")

    def __repr__(self) -> str:
        return f"<AuditLog(id={self.id}, type={self.event_type}, at={self.created_at})>"
