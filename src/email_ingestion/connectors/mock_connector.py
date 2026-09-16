"""Mock email connector for local testing, demonstration, and offline validation.

Simulates real enterprise email scenarios including normal invoices, signature logos,
accidental duplicate attachments, revised quote drafts (v2), and spoofed executables.
"""

import io
from datetime import datetime, timezone, timedelta
from typing import List, BinaryIO, Dict
from email_ingestion.connectors.base import BaseEmailConnector, EmailEnvelope, AttachmentStub


class MockEmailConnector(BaseEmailConnector):
    """Offline test connector delivering rich synthetic email scenarios."""

    def __init__(self):
        self._connected = False
        self._delivered_message_ids = set()
        self._payload_store: Dict[str, bytes] = {}

    @property
    def provider_name(self) -> str:
        return "MOCK"

    def connect(self) -> bool:
        self._connected = True
        return True

    def fetch_new_messages(self, max_messages: int = 50) -> List[EmailEnvelope]:
        """Generate synthetic emails demonstrating all enterprise features."""
        now = datetime.now(timezone.utc)
        envelopes: List[EmailEnvelope] = []

        # ----------------------------------------------------------------------
        # Scenario 1: Standard Invoicing with legitimate PDF & inline signature logo
        # ----------------------------------------------------------------------
        msg1_id = "mock_msg_001"
        if msg1_id not in self._delivered_message_ids:
            pdf_bytes = b"%PDF-1.5 \n%Sample Invoice Data: Amount Due $4,500.00 USD for Q3 Cloud Services\n%%EOF"
            logo_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x10\x00\x00\x00\x10\x08\x06\x00\x00\x00\x1f\xf3\xffa"

            self._payload_store[f"{msg1_id}_att1"] = pdf_bytes
            self._payload_store[f"{msg1_id}_att2"] = logo_bytes

            envelopes.append(EmailEnvelope(
                id=msg1_id,
                account_id="mock_account_1",
                sender_email="sarah.connor@acme-corp.com",
                sender_name="Sarah Connor",
                subject="Invoice INV-2026-09 - Cloud Hosting",
                received_at=now - timedelta(minutes=45),
                thread_id="mock_thread_101",
                body_text="Hi Jerome,\n\nPlease find the invoice for this month's cloud hosting services attached.\nLet me know if you have any questions.\n\nSarah Connor\nAcme Corp",
                body_html='<p>Hi Jerome,</p><p>Please find the invoice attached.</p><p><img src="cid:logo_cid_001" alt="Acme Logo"></p>',
                attachments=[
                    AttachmentStub(
                        id=f"{msg1_id}_att1",
                        filename="Invoice_INV-2026-09.pdf",
                        content_type="application/pdf",
                        size_bytes=len(pdf_bytes),
                        content_disposition="attachment"
                    ),
                    AttachmentStub(
                        id=f"{msg1_id}_att2",
                        filename="logo.png",
                        content_type="image/png",
                        size_bytes=len(logo_bytes),
                        content_disposition="inline",
                        content_id="logo_cid_001"
                    )
                ]
            ))

        # ----------------------------------------------------------------------
        # Scenario 2: Accidental Duplicate Attachment (Intra-Message Twin Anomaly)
        # Sender meant to attach two distinct files but attached the exact same file twice
        # ----------------------------------------------------------------------
        msg2_id = "mock_msg_002"
        if msg2_id not in self._delivered_message_ids:
            twin_file_bytes = b"Contract terms and specifications for project Apollo. Confidential document."
            
            self._payload_store[f"{msg2_id}_att1"] = twin_file_bytes
            self._payload_store[f"{msg2_id}_att2"] = twin_file_bytes  # EXACT SAME CONTENT!

            envelopes.append(EmailEnvelope(
                id=msg2_id,
                account_id="mock_account_1",
                sender_email="alex.mercer@contracting.com",
                sender_name="Alex Mercer",
                subject="Project Apollo Agreement & Terms",
                received_at=now - timedelta(minutes=30),
                thread_id="mock_thread_102",
                body_text="Hi Jerome,\n\nAttached are the contract and the specification sheet for Project Apollo.\n\nBest,\nAlex",
                body_html=None,
                attachments=[
                    AttachmentStub(
                        id=f"{msg2_id}_att1",
                        filename="Apollo_Contract_Final.txt",
                        content_type="text/plain",
                        size_bytes=len(twin_file_bytes),
                        content_disposition="attachment"
                    ),
                    AttachmentStub(
                        id=f"{msg2_id}_att2",
                        filename="Apollo_Contract_Copy.txt",
                        content_type="text/plain",
                        size_bytes=len(twin_file_bytes),
                        content_disposition="attachment"
                    )
                ]
            ))

        # ----------------------------------------------------------------------
        # Scenario 3: Document Revision (Same filename, 90% similar content -> v2)
        # ----------------------------------------------------------------------
        msg3_id = "mock_msg_003"
        if msg3_id not in self._delivered_message_ids:
            # v1 was Invoice_INV-2026-09.pdf from Sarah, let's say Sarah sends an updated quote
            revised_quote_bytes = b"QUOTE 2026:\nItem 1: 5 Servers - $5000\nItem 2: Maintenance - $1000\nTotal: $6000\nDiscount: 10% applied\nNet: $5400"
            self._payload_store[f"{msg3_id}_att1"] = revised_quote_bytes

            envelopes.append(EmailEnvelope(
                id=msg3_id,
                account_id="mock_account_1",
                sender_email="sarah.connor@acme-corp.com",
                sender_name="Sarah Connor",
                subject="RE: Quote 2026 - Revised with 10% Discount",
                received_at=now - timedelta(minutes=10),
                thread_id="mock_thread_101",
                body_text="Hi Jerome,\n\nI updated the Quote_2026.txt file to reflect our phone discussion and applied the 10% discount.\n\nRegards,\nSarah",
                body_html=None,
                attachments=[
                    AttachmentStub(
                        id=f"{msg3_id}_att1",
                        filename="Quote_2026.txt",
                        content_type="text/plain",
                        size_bytes=len(revised_quote_bytes),
                        content_disposition="attachment"
                    )
                ]
            ))

        # ----------------------------------------------------------------------
        # Scenario 4: Malicious Spoofed Extension (Executable disguised as .pdf)
        # ----------------------------------------------------------------------
        msg4_id = "mock_msg_004"
        if msg4_id not in self._delivered_message_ids:
            # Windows PE executable magic bytes 'MZ'
            spoofed_bytes = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00This program cannot be run in DOS mode."
            self._payload_store[f"{msg4_id}_att1"] = spoofed_bytes

            envelopes.append(EmailEnvelope(
                id=msg4_id,
                account_id="mock_account_1",
                sender_email="suspicious.vendor@unknown-domain.net",
                sender_name="Quick Accounts",
                subject="URGENT: Overdue Bill Please Remit",
                received_at=now - timedelta(minutes=5),
                thread_id="mock_thread_104",
                body_text="Please review the overdue invoice immediately.",
                body_html=None,
                attachments=[
                    AttachmentStub(
                        id=f"{msg4_id}_att1",
                        filename="Urgent_Invoice.pdf",  # Disguised as PDF!
                        content_type="application/pdf",
                        size_bytes=len(spoofed_bytes),
                        content_disposition="attachment"
                    )
                ]
            ))

        return envelopes[:max_messages]

    def download_attachment_stream(
        self,
        message_id: str,
        attachment_id: str
    ) -> BinaryIO:
        """Return a readable bytes stream for the simulated attachment."""
        data = self._payload_store.get(attachment_id, b"")
        return io.BytesIO(data)

    def acknowledge_processed(self, message_id: str) -> None:
        """Mark the message as delivered to avoid infinite loops in test runs."""
        self._delivered_message_ids.add(message_id)

    def ensure_folders_exist(self, folders: List[str]) -> None:
        """Ensure simulated folders exist."""
        if not hasattr(self, "_folders"):
            self._folders: Dict[str, List[EmailEnvelope]] = {}
        for f in folders:
            if f not in self._folders:
                self._folders[f] = []

    def move_message(
        self,
        message_id: str,
        target_folder: str,
        source_folder: Optional[str] = None
    ) -> bool:
        """Simulate moving a message between folders."""
        if not hasattr(self, "_folders"):
            self._folders: Dict[str, List[EmailEnvelope]] = {}
        if target_folder not in self._folders:
            self._folders[target_folder] = []

        moved_env = None
        if source_folder and source_folder in self._folders:
            for i, env in enumerate(self._folders[source_folder]):
                if env.id == message_id:
                    moved_env = self._folders[source_folder].pop(i)
                    break
        else:
            for s_name, env_list in self._folders.items():
                for i, env in enumerate(env_list):
                    if env.id == message_id:
                        moved_env = env_list.pop(i)
                        break
                if moved_env:
                    break

        if moved_env:
            self._folders[target_folder].append(moved_env)
        return True

    def fetch_messages_from_folder(
        self,
        folder_name: str,
        max_messages: int = 50
    ) -> List[EmailEnvelope]:
        """Fetch messages currently queued in a simulated folder."""
        if not hasattr(self, "_folders"):
            self._folders: Dict[str, List[EmailEnvelope]] = {}
        return list(self._folders.get(folder_name, []))[:max_messages]

    def place_message_in_folder(self, folder_name: str, envelope: EmailEnvelope) -> None:
        """Helper for tests/demos to place an envelope into a designated folder."""
        if not hasattr(self, "_folders"):
            self._folders: Dict[str, List[EmailEnvelope]] = {}
        if folder_name not in self._folders:
            self._folders[folder_name] = []
        self._folders[folder_name].append(envelope)
