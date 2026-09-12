"""Standard IMAP / IMAP-SSL Email Connector.

Connects to any standard RFC 3501 IMAP mailbox (e.g. corporate mail, Gmail IMAP,
Outlook IMAP, Dovecot) using modern Python email policies and resilient connection handling.
"""

from email import policy
from email.header import decode_header, make_header
import email
import io
import logging
from datetime import datetime, timezone
from typing import List, Optional, BinaryIO, Dict, Any
from email_ingestion.connectors.base import BaseEmailConnector, EmailEnvelope, AttachmentStub
from email_ingestion.connectors.resilience import retry_with_backoff

logger = logging.getLogger(__name__)


class IMAPConnector(BaseEmailConnector):
    """Standard IMAP-SSL connector for generic email providers."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: int = 993,
        username: Optional[str] = None,
        password: Optional[str] = None,
        mailbox: str = "INBOX",
        use_ssl: bool = True,
        timeout: int = 30
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.mailbox = mailbox
        self.use_ssl = use_ssl
        self.timeout = timeout
        self._client: Any = None
        self._cached_payloads: Dict[str, bytes] = {}
        self._msg_id_to_mid: Dict[str, str] = {}

    @property
    def provider_name(self) -> str:
        return "IMAP"

    def connect(self) -> bool:
        """Connect and authenticate to the IMAP server with timeout."""
        if not (self.host and self.username and self.password):
            return False

        try:
            import imaplib
            if self.use_ssl:
                self._client = imaplib.IMAP4_SSL(self.host, self.port, timeout=self.timeout)
            else:
                self._client = imaplib.IMAP4(self.host, self.port, timeout=self.timeout)

            self._client.login(self.username, self.password)
            self._client.select(self.mailbox)
            return True
        except Exception as e:
            logger.warning(f"Failed to connect to IMAP server {self.host}: {e}")
            self._client = None
            return False

    @staticmethod
    def _decode_mime_header(header_value: Optional[str]) -> str:
        """Decode RFC 2047 MIME encoded headers safely using standard library."""
        if not header_value:
            return ""
        try:
            return str(make_header(decode_header(header_value)))
        except Exception:
            return str(header_value)

    def fetch_new_messages(self, max_messages: int = 50) -> List[EmailEnvelope]:
        """Query unseen messages and extract attachment stubs using email.policy.default."""
        if not self._client:
            return []

        envelopes: List[EmailEnvelope] = []
        try:
            status, data = self._client.search(None, "UNSEEN")
            if status != "OK" or not data or not data[0]:
                return []

            msg_ids = data[0].split()
            selected_ids = msg_ids[-max_messages:]

            for mid_bytes in selected_ids:
                mid = mid_bytes.decode() if isinstance(mid_bytes, bytes) else str(mid_bytes)
                res, msg_data = self._client.fetch(mid, "(RFC822)")
                if res != "OK" or not msg_data:
                    continue

                raw_email = msg_data[0][1]
                # Modern email parsing with automatic RFC 2047/2231 decoding
                msg = email.message_from_bytes(raw_email, policy=policy.default)

                sender = str(msg.get("From", "unknown@unknown.com"))
                subject = str(msg.get("Subject", ""))
                msg_id = (msg.get("Message-ID", f"imap_{mid}") or f"imap_{mid}").strip("<>")
                self._msg_id_to_mid[msg_id] = mid
                
                in_reply = msg.get("In-Reply-To", msg.get("References", msg_id))
                thread_id = str(in_reply).split()[0].strip("<>") if in_reply else msg_id

                # Clean datetime extraction
                date_hdr = msg.get("Date")
                if hasattr(date_hdr, "datetime") and date_hdr.datetime:
                    received_at = date_hdr.datetime.astimezone(timezone.utc)
                else:
                    try:
                        received_at = email.utils.parsedate_to_datetime(str(date_hdr)).astimezone(timezone.utc)
                    except Exception:
                        received_at = datetime.now(timezone.utc)

                # Body extraction
                body_text = ""
                body_html = ""
                plain_part = msg.get_body(preferencelist=("plain",))
                if plain_part:
                    try:
                        content = plain_part.get_content()
                        if isinstance(content, str):
                            body_text = content
                    except Exception:
                        pass

                html_part = msg.get_body(preferencelist=("html",))
                if html_part:
                    try:
                        content = html_part.get_content()
                        if isinstance(content, str):
                            body_html = content
                    except Exception:
                        pass

                # Attachments extraction using modern iter_attachments()
                attachments: List[AttachmentStub] = []
                for part_idx, part in enumerate(msg.iter_attachments()):
                    clean_filename = part.get_filename() or f"attachment_{part_idx}.dat"
                    try:
                        payload = part.get_content()
                        if isinstance(payload, str):
                            payload = payload.encode("utf-8")
                    except Exception:
                        payload = b""

                    if payload is not None:
                        size_bytes = len(payload)
                        attachment_stub_id = f"{mid}_{part_idx}"
                        self._cached_payloads[f"{msg_id}_{attachment_stub_id}"] = payload
                        disposition = str(part.get("Content-Disposition", "") or "")

                        attachments.append(AttachmentStub(
                            id=attachment_stub_id,
                            filename=clean_filename,
                            content_type=part.get_content_type(),
                            size_bytes=size_bytes,
                            content_disposition="attachment" if "attachment" in disposition.lower() else "inline",
                            content_id=str(part.get("Content-ID", "") or "").strip("<>")
                        ))

                if attachments:
                    envelopes.append(EmailEnvelope(
                        id=msg_id,
                        account_id=f"imap_{self.username}",
                        sender_email=sender,
                        sender_name=sender.split("<")[0].strip() if "<" in sender else sender,
                        subject=subject,
                        received_at=received_at,
                        thread_id=thread_id,
                        body_text=body_text,
                        body_html=body_html,
                        attachments=attachments
                    ))

            return envelopes
        except Exception as err:
            logger.warning(f"Error fetching messages via IMAP: {err}")
            return envelopes

    def download_attachment_stream(self, message_id: str, attachment_id: str) -> BinaryIO:
        """Return the in-memory stream of the downloaded attachment."""
        cache_key = f"{message_id}_{attachment_id}"
        payload = self._cached_payloads.pop(cache_key, b"")
        return io.BytesIO(payload)

    def acknowledge_processed(self, message_id: str) -> None:
        r"""Acknowledge message processing by flagging the message as \Seen."""
        if not self._client or message_id not in self._msg_id_to_mid:
            return
        try:
            mid = self._msg_id_to_mid[message_id]
            self._client.store(mid, "+FLAGS", "\\Seen")
        except Exception as e:
            logger.debug(f"Could not flag message {message_id} as \\Seen: {e}")

    def disconnect(self) -> None:
        """Safely close and log out of the IMAP connection."""
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            try:
                self._client.logout()
            except Exception:
                pass
            self._client = None
        self._cached_payloads.clear()
        self._msg_id_to_mid.clear()
