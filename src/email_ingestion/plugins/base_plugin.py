"""Base plugin interface and lifecycle hook specifications.

Satisfies supervisor requirement: The entire system is built as an extensible
plugin engine where developers can add custom behaviors at each stage of the lifecycle.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from email_ingestion.connectors.base import EmailEnvelope, AttachmentStub


class BasePlugin(ABC):
    """Abstract base class for all email ingestion plugins.
    
    Subclasses can implement any subset of lifecycle hooks to inspect,
    modify, or respond to events during the ingestion workflow.
    """

    @property
    @abstractmethod
    def plugin_name(self) -> str:
        """Unique identifier name for this plugin."""
        pass

    def on_email_received(self, envelope: EmailEnvelope) -> None:
        """Hook triggered immediately after an email envelope is fetched from the provider."""
        pass

    def on_attachment_scanned(
        self,
        envelope: EmailEnvelope,
        attachment: AttachmentStub,
        is_signature: bool
    ) -> bool:
        """Hook triggered during signature filtering.
        
        Return False to suppress download, or True to allow.
        """
        return not is_signature

    def on_duplicate_detected(self, duplicate_event: Dict[str, Any]) -> Optional[str]:
        """Hook triggered when an accidental duplicate or resend is detected.
        
        May return an action string override ('KEEP_FIRST', 'KEEP_BOTH', 'SKIP').
        """
        return None

    def on_context_enriched(self, context_data: Dict[str, Any]) -> Dict[str, Any]:
        """Hook triggered when building the sidecar to append AI or custom metadata."""
        return context_data

    def on_quarantine(
        self,
        envelope: EmailEnvelope,
        attachment_name: str,
        reason: str
    ) -> None:
        """Hook triggered when a malicious or extension-spoofed file is quarantined."""
        pass

    def on_ingestion_complete(self, record: Dict[str, Any]) -> None:
        """Hook triggered after an attachment and sidecars are safely committed to disk & DB."""
        pass
