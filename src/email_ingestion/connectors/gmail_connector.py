"""Google Workspace and Gmail API Connector.

Connects to Gmail using official Google Client Libraries (google-api-python-client)
and handles OAuth 2.0 / Service Account credentials.
"""

import base64
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, BinaryIO
from email_ingestion.connectors.base import BaseEmailConnector, EmailEnvelope, AttachmentStub
from email_ingestion.connectors.resilience import retry_with_backoff


class GmailConnector(BaseEmailConnector):
    """Production Gmail connector using official Google APIs."""

    def __init__(
        self,
        credentials_json: Optional[str] = None,
        user_email: str = "me"
    ):
        self.credentials_json = credentials_json
        self.user_email = user_email
        self._service = None

    @property
    def provider_name(self) -> str:
        return "GMAIL"

    def connect(self) -> bool:
        """Authenticate with Google Workspace using google-auth."""
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build

            if self.credentials_json and Path(self.credentials_json).exists():
                creds = service_account.Credentials.from_service_account_file(
                    self.credentials_json,
                    scopes=["https://www.googleapis.com/auth/gmail.modify"]
                )
                self._service = build("gmail", "v1", credentials=creds)
                return True
            else:
                # If credentials file not found, mark as offline/unconfigured
                return False
        except ImportError:
            return False
        except Exception:
            return False

    def fetch_new_messages(self, max_messages: int = 100) -> List[EmailEnvelope]:
        """Fetch emails containing attachments via Gmail messages.list with pagination."""
        if not self._service:
            return []

        envelopes: List[EmailEnvelope] = []
        page_token = None

        try:
            while len(envelopes) < max_messages:
                results = self._service.users().messages().list(
                    userId=self.user_email,
                    q="has:attachment",
                    maxResults=min(50, max_messages - len(envelopes)),
                    pageToken=page_token
                ).execute()

                messages = results.get("messages", [])
                if not messages:
                    break

                for msg_meta in messages:
                    msg = self._service.users().messages().get(
                        userId=self.user_email,
                        id=msg_meta["id"],
                        format="full"
                    ).execute()

                    envelope = self._parse_gmail_message(msg)
                    if envelope:
                        envelopes.append(envelope)
                        if len(envelopes) >= max_messages:
                            break

                page_token = results.get("nextPageToken")
                if not page_token:
                    break

            return envelopes
        except Exception as err:
            import logging
            logging.getLogger(__name__).warning(f"Gmail API error fetching messages: {err}")
            return envelopes

    def _parse_gmail_message(self, msg: dict) -> Optional[EmailEnvelope]:
        """Extract structured metadata and attachment stubs from Gmail payload."""
        payload = msg.get("payload", {})
        headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}

        sender = headers.get("from", "unknown@unknown.com")
        subject = headers.get("subject", "")
        thread_id = msg.get("threadId")
        internal_date = int(msg.get("internalDate", 0)) / 1000.0
        received_at = datetime.fromtimestamp(internal_date, tz=timezone.utc)

        # Parse multipart parts for attachments
        attachments: List[AttachmentStub] = []
        body_text = ""
        body_html = ""

        def traverse_parts(parts):
            nonlocal body_text, body_html
            for part in parts:
                filename = part.get("filename")
                mime_type = part.get("mimeType", "")
                body = part.get("body", {})

                if filename and "attachmentId" in body:
                    att_id = body["attachmentId"]
                    size = body.get("size", 0)
                    part_headers = {h["name"].lower(): h["value"] for h in part.get("headers", [])}
                    disposition = part_headers.get("content-disposition", "attachment")
                    content_id = part_headers.get("content-id")

                    attachments.append(AttachmentStub(
                        id=att_id,
                        filename=filename,
                        content_type=mime_type,
                        size_bytes=size,
                        content_disposition=disposition,
                        content_id=content_id
                    ))
                elif mime_type == "text/plain" and "data" in body:
                    body_text += base64.urlsafe_b64decode(body["data"].encode("UTF-8")).decode("utf-8", errors="ignore")
                elif mime_type == "text/html" and "data" in body:
                    body_html += base64.urlsafe_b64decode(body["data"].encode("UTF-8")).decode("utf-8", errors="ignore")

                if "parts" in part:
                    traverse_parts(part["parts"])

        if "parts" in payload:
            traverse_parts(payload["parts"])

        if not attachments:
            return None

        return EmailEnvelope(
            id=msg["id"],
            account_id=f"gmail_{self.user_email}",
            sender_email=sender,
            sender_name=None,
            subject=subject,
            received_at=received_at,
            thread_id=thread_id,
            body_text=body_text or None,
            body_html=body_html or None,
            attachments=attachments,
            raw_headers=headers
        )

    @retry_with_backoff(retries=3, base_delay=1.0)
    def download_attachment_stream(
        self,
        message_id: str,
        attachment_id: str
    ) -> BinaryIO:
        """Download raw bytes from Gmail and return an in-memory stream."""
        if not self._service:
            return io.BytesIO(b"")

        attachment = self._service.users().messages().attachments().get(
            userId=self.user_email,
            messageId=message_id,
            id=attachment_id
        ).execute()

        raw_data = base64.urlsafe_b64decode(attachment["data"].encode("UTF-8"))
        return io.BytesIO(raw_data)

    def acknowledge_processed(self, message_id: str) -> None:
        """Mark processed message as read by removing the UNREAD label in Gmail."""
        if not self._service:
            return
        try:
            self._service.users().messages().modify(
                userId=self.user_email,
                id=message_id,
                body={"removeLabelIds": ["UNREAD"]}
            ).execute()
        except Exception:
            pass
