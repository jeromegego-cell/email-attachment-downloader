"""Desktop and CLI notification plugin.

Displays visual desktop notifications (via Linux notify-send) or formatted
terminal alerts whenever duplicate anomalies or security quarantines occur.
"""

import subprocess
import shutil
from typing import Dict, Any, Optional
import click
from email_ingestion.plugins.base_plugin import BasePlugin
from email_ingestion.connectors.base import EmailEnvelope


class DesktopNotifierPlugin(BasePlugin):
    """Notifies the local user of critical ingestion events and anomalies."""

    @property
    def plugin_name(self) -> str:
        return "desktop_notifier"

    def __init__(self):
        self._notify_send_available = shutil.which("notify-send") is not None

    def _send_desktop_notification(self, title: str, message: str, urgency: str = "normal") -> None:
        """Send a native Linux desktop notification if notify-send exists."""
        if self._notify_send_available:
            try:
                subprocess.run(
                    ["notify-send", "-u", urgency, title, message],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            except Exception:
                pass

    def on_duplicate_detected(self, duplicate_event: Dict[str, Any]) -> Optional[str]:
        """Alert user when an accidental duplicate or resend is detected."""
        orig = duplicate_event.get("original_slot", "file")
        dup = duplicate_event.get("duplicate_slot", "file")
        msg = f"Duplicate file detected: '{orig}' and '{dup}' have identical content."
        
        # Desktop notification
        self._send_desktop_notification("Email Ingestion: Duplicate Anomaly", msg, urgency="critical")
        
        # CLI notification
        click.secho(f"[ALERT] {msg}", fg="yellow", bold=True)
        return None

    def on_quarantine(
        self,
        envelope: EmailEnvelope,
        attachment_name: str,
        reason: str
    ) -> None:
        """Alert user when a dangerous or spoofed file is isolated."""
        title = "SECURITY WARNING: Attachment Quarantined"
        body = f"Sender: {envelope.sender_email}\nFile: {attachment_name}\nReason: {reason}"
        
        self._send_desktop_notification(title, body, urgency="critical")
        click.secho(f"[SECURITY ALERT] Quarantined '{attachment_name}': {reason}", fg="red", bold=True)
