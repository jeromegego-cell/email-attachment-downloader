"""Base connector interface and standardized data transfer objects.

All provider connectors (Gmail, Microsoft Graph, Mock) implement this interface,
ensuring that the core ingestion pipeline remains completely decoupled from
specific vendor SDKs or protocol variations.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, BinaryIO, Dict, Any


@dataclass
class AttachmentStub:
    """Represents attachment metadata fetched from the email provider."""
    id: str
    filename: str
    content_type: str
    size_bytes: int
    content_disposition: Optional[str] = None  # 'attachment' or 'inline'
    content_id: Optional[str] = None           # CID for inline images
    is_item_attachment: bool = False           # True if attached email or calendar item


@dataclass
class EmailEnvelope:
    """Standardized representation of an ingested email message."""
    id: str
    account_id: str
    sender_email: str
    sender_name: Optional[str] = None
    subject: str = ""
    received_at: Optional[datetime] = None
    thread_id: Optional[str] = None
    body_text: Optional[str] = ""
    body_html: Optional[str] = ""
    attachments: List[AttachmentStub] = field(default_factory=list)
    raw_headers: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.received_at is None:
            self.received_at = datetime.now(timezone.utc)


class BaseEmailConnector(ABC):
    """Abstract base class for all email provider connectors."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Unique provider name (e.g. 'GMAIL', 'M365', 'MOCK')."""
        pass

    @abstractmethod
    def connect(self) -> bool:
        """Authenticate and verify connectivity with the email service."""
        pass

    @abstractmethod
    def fetch_new_messages(self, max_messages: int = 50) -> List[EmailEnvelope]:
        """Fetch pending email envelopes that contain attachments."""
        pass

    @abstractmethod
    def download_attachment_stream(
        self,
        message_id: str,
        attachment_id: str
    ) -> BinaryIO:
        """Stream the raw binary payload of an attachment directly into a memory/file stream."""
        pass

    @abstractmethod
    def acknowledge_processed(self, message_id: str) -> None:
        """Optionally apply a label or update the provider state after successful processing."""
        pass
