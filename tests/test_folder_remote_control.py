"""Unit and integration tests for Zero-UI 'Folder Remote Control' mailbox workflow.

Verifies:
- [To Download] one-time pass semantic: downloads attachments once, does NOT whitelist sender.
- [Approved Senders] permanent whitelist: adds sender to allowlist and downloads attachments.
- [Blocked Senders] permanent blacklist: adds sender to blacklist and discards attachments.
- [Needs Review] auto-triage: unknown senders held safely in holding area until user decision.
- Email movement across folders to [Completed].
"""

import io
from pathlib import Path
from datetime import datetime, timezone
import pytest

from email_ingestion.config import (
    EngineSettings,
    StorageSettings,
    FilterSettings,
    FolderControlSettings,
)
from email_ingestion.engine import EmailIngestionEngine
from email_ingestion.connectors.base import BaseEmailConnector, EmailEnvelope, AttachmentStub
from email_ingestion.connectors.mock_connector import MockEmailConnector
from email_ingestion.database.models import Message, AuditLog


class ControllableMockConnector(BaseEmailConnector):
    """Mock connector designed for testing folder remote control transitions."""

    def __init__(self):
        self.provider_name_val = "MOCK_CONTROL"
        self._inbox: list[EmailEnvelope] = []
        self._folders: dict[str, list[EmailEnvelope]] = {}
        self._payloads: dict[str, bytes] = {}
        self.acknowledged: list[str] = []

    @property
    def provider_name(self) -> str:
        return self.provider_name_val

    def connect(self) -> bool:
        return True

    def fetch_new_messages(self, max_messages: int = 50) -> list[EmailEnvelope]:
        msgs = list(self._inbox[:max_messages])
        self._inbox = self._inbox[max_messages:]
        return msgs

    def download_attachment_stream(self, message_id: str, attachment_id: str) -> io.BytesIO:
        payload = self._payloads.get(attachment_id, b"%PDF-1.5 test document\n%%EOF")
        return io.BytesIO(payload)

    def acknowledge_processed(self, message_id: str) -> None:
        self.acknowledged.append(message_id)

    def ensure_folders_exist(self, folders: list[str]) -> None:
        for f in folders:
            if f not in self._folders:
                self._folders[f] = []

    def move_message(self, message_id: str, target_folder: str, source_folder: str | None = None) -> bool:
        if target_folder not in self._folders:
            self._folders[target_folder] = []

        moved = None
        if source_folder and source_folder in self._folders:
            for i, env in enumerate(self._folders[source_folder]):
                if env.id == message_id:
                    moved = self._folders[source_folder].pop(i)
                    break
        else:
            for s_name, env_list in self._folders.items():
                for i, env in enumerate(env_list):
                    if env.id == message_id:
                        moved = env_list.pop(i)
                        break
                if moved:
                    break

        if not moved:
            moved = EmailEnvelope(
                id=message_id,
                account_id="acc_1",
                sender_email="unknown@example.com",
                subject="Moved item"
            )

        self._folders[target_folder].append(moved)
        return True

    def fetch_messages_from_folder(self, folder_name: str, max_messages: int = 50) -> list[EmailEnvelope]:
        return list(self._folders.get(folder_name, []))[:max_messages]

    def add_to_folder(self, folder_name: str, envelope: EmailEnvelope, payload: bytes = b"%PDF-1.5 test document\n%%EOF"):
        if folder_name not in self._folders:
            self._folders[folder_name] = []
        self._folders[folder_name].append(envelope)
        for att in envelope.attachments:
            self._payloads[att.id] = payload


@pytest.fixture
def folder_control_engine(tmp_path):
    db_file = tmp_path / "fc_test.db"
    download_dir = tmp_path / "Auto_download_email"
    approved_file = tmp_path / "approved_senders.txt"
    exclude_file = tmp_path / "excluded_senders.txt"

    settings = EngineSettings(
        environment="development",
        storage=StorageSettings(
            download_dir=download_dir,
            quarantine_dir=download_dir / "quarantine",
            staging_dir=download_dir / ".staging"
        ),
        filters=FilterSettings(
            enabled=True,
            excluded_senders=[],
            exclude_file=str(exclude_file),
            approved_senders=[],
            approved_file=str(approved_file)
        ),
        folder_control=FolderControlSettings(
            enabled=True,
            to_download_folder="[To Download]",
            approved_folder="[Approved Senders]",
            blocked_folder="[Blocked Senders]",
            review_folder="[Needs Review]",
            completed_folder="[Completed]",
            auto_triage_unknown_to_review=False
        ),
        database={"db_url": f"sqlite:///{db_file}"},
        mock_provider={"enabled": False},
        plugins=[]
    )

    connector = ControllableMockConnector()
    engine = EmailIngestionEngine(settings)
    engine.connectors = [connector]
    return engine, connector, tmp_path


def test_to_download_one_time_pass_semantic(folder_control_engine):
    """Verify [To Download] processes attachments once, moves to [Completed], and does NOT whitelist sender."""
    engine, connector, tmp_path = folder_control_engine

    env = EmailEnvelope(
        id="one_time_msg_001",
        account_id="acc_1",
        sender_email="guest_contractor@temporary.com",
        sender_name="Guest Contractor",
        subject="One-Time Architectural Diagram",
        received_at=datetime.now(timezone.utc),
        attachments=[
            AttachmentStub(
                id="att_ot_1",
                filename="Architecture_Diagram.pdf",
                content_type="application/pdf",
                size_bytes=2048,
                content_disposition="attachment"
            )
        ]
    )

    # Place in [To Download]
    connector.add_to_folder("[To Download]", env)

    metrics = engine.run_sync()

    # 1. Verification: message and attachment processed
    assert metrics["one_time_pass"] == 1
    assert metrics["messages_processed"] == 1
    assert metrics["attachments_downloaded"] == 1

    # 2. CRITICAL VERIFICATION: Sender is NOT whitelisted
    is_app, _ = engine.sender_filter.is_approved("guest_contractor@temporary.com")
    assert is_app is False, "Sender must NOT be whitelisted from [To Download] one-time pass!"

    # 3. Email moved out of [To Download] into [Completed]
    assert len(connector.fetch_messages_from_folder("[To Download]")) == 0
    completed_msgs = connector.fetch_messages_from_folder("[Completed]")
    assert len(completed_msgs) == 1
    assert completed_msgs[0].id == "one_time_msg_001"

    # 4. Audit ledger records ONE_TIME_PASS_PROCESSED
    with engine.db.session() as s:
        audit = s.query(AuditLog).filter(AuditLog.message_id == "one_time_msg_001").first()
        assert audit is not None
        assert audit.event_type == "ONE_TIME_PASS_PROCESSED"


def test_approved_senders_permanent_whitelist(folder_control_engine):
    """Verify [Approved Senders] downloads files, adds sender to whitelist, and moves to [Completed]."""
    engine, connector, tmp_path = folder_control_engine

    env = EmailEnvelope(
        id="whitelist_msg_001",
        account_id="acc_1",
        sender_email="trusted_partner@vendor.com",
        sender_name="Trusted Partner",
        subject="Monthly Maintenance Invoice",
        received_at=datetime.now(timezone.utc),
        attachments=[
            AttachmentStub(
                id="att_wl_1",
                filename="Invoice_Monthly.pdf",
                content_type="application/pdf",
                size_bytes=2048,
                content_disposition="attachment"
            )
        ]
    )

    connector.add_to_folder("[Approved Senders]", env)

    metrics = engine.run_sync()

    assert metrics["senders_approved"] == 1
    assert metrics["messages_processed"] == 1
    assert metrics["attachments_downloaded"] == 1

    # Verification: sender is PERMANENTLY approved
    is_app, _ = engine.sender_filter.is_approved("trusted_partner@vendor.com")
    assert is_app is True

    # Email moved to [Completed]
    assert len(connector.fetch_messages_from_folder("[Approved Senders]")) == 0
    assert len(connector.fetch_messages_from_folder("[Completed]")) == 1


def test_blocked_senders_permanent_blacklist(folder_control_engine):
    """Verify [Blocked Senders] adds sender to blacklist, discards files, and moves to [Completed]."""
    engine, connector, tmp_path = folder_control_engine

    env = EmailEnvelope(
        id="spam_msg_001",
        account_id="acc_1",
        sender_email="spammer@phishing-attack.com",
        sender_name="Spam Bot",
        subject="You won a prize",
        received_at=datetime.now(timezone.utc),
        attachments=[
            AttachmentStub(
                id="att_sp_1",
                filename="Prize.pdf",
                content_type="application/pdf",
                size_bytes=1024,
                content_disposition="attachment"
            )
        ]
    )

    connector.add_to_folder("[Blocked Senders]", env)

    metrics = engine.run_sync()

    assert metrics["senders_excluded"] == 1
    assert metrics["attachments_downloaded"] == 0

    # Verification: sender is PERMANENTLY excluded
    is_ex, _ = engine.sender_filter.is_excluded("spammer@phishing-attack.com")
    assert is_ex is True

    # Email moved to [Completed]
    assert len(connector.fetch_messages_from_folder("[Blocked Senders]")) == 0
    assert len(connector.fetch_messages_from_folder("[Completed]")) == 1


def test_auto_triage_unknown_sender_to_needs_review(folder_control_engine):
    """Verify that when auto_triage is enabled, unknown senders in Inbox are held in [Needs Review]."""
    engine, connector, tmp_path = folder_control_engine
    engine.settings.folder_control.auto_triage_unknown_to_review = True

    unknown_env = EmailEnvelope(
        id="unknown_msg_001",
        account_id="acc_1",
        sender_email="stranger@outside-company.com",
        sender_name="Stranger",
        subject="Unsolicited Proposal",
        received_at=datetime.now(timezone.utc),
        attachments=[
            AttachmentStub(
                id="att_un_1",
                filename="Proposal.pdf",
                content_type="application/pdf",
                size_bytes=1024,
                content_disposition="attachment"
            )
        ]
    )

    connector._inbox.append(unknown_env)

    metrics = engine.run_sync()

    # Did not download attachments
    assert metrics["triaged_to_review"] == 1
    assert metrics["attachments_downloaded"] == 0

    # Moved to [Needs Review]
    review_msgs = connector.fetch_messages_from_folder("[Needs Review]")
    assert len(review_msgs) == 1
    assert review_msgs[0].id == "unknown_msg_001"

    # Now simulate employee dragging this email from [Needs Review] into [To Download]
    connector._folders["[Needs Review]"] = []
    connector.add_to_folder("[To Download]", unknown_env)

    # Next sync executes one-time pass!
    second_metrics = engine.run_sync()
    assert second_metrics["one_time_pass"] == 1
    assert second_metrics["attachments_downloaded"] == 1
    # Sender is STILL not whitelisted!
    is_app, _ = engine.sender_filter.is_approved("stranger@outside-company.com")
    assert is_app is False
