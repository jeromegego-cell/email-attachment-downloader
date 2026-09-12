"""Tests for full-text search, storage statistics, and CLI commands."""

import json
from pathlib import Path
from click.testing import CliRunner
import pytest

from email_ingestion.database.session import DatabaseManager
from email_ingestion.database.models import Message, Attachment, Account, utc_now
from email_ingestion.cli import cli


@pytest.fixture
def populated_db(tmp_path):
    db_file = tmp_path / "test_state.db"
    db_url = f"sqlite:///{db_file}"
    db = DatabaseManager(db_url)

    with db.session() as s:
        acc = Account(id="acc_1", provider="IMAP", email_address="test@example.com")
        s.add(acc)

        msg1 = Message(
            id="msg_001",
            account_id="acc_1",
            sender_email="alice@partner.com",
            sender_name="Alice Smith",
            subject="Quarterly Financial Statement 2026",
            received_at=utc_now(),
            raw_body_snippet="Attached is the audited quarterly financial report."
        )
        s.add(msg1)

        att1 = Attachment(
            id="att_001",
            message_id="msg_001",
            original_filename="Financial_Report_Q3.pdf",
            sanitized_filename="Financial_Report_Q3.pdf",
            file_hash_sha256="1111222233334444555566667777888899990000aaaabbbbccccddddeeeeffff",
            file_size_bytes=10240,
            detected_mime_type="application/pdf",
            local_storage_path=str(tmp_path / "Financial_Report_Q3.pdf"),
            quarantine_status="CLEAN",
            version_number=1
        )
        s.add(att1)

        msg2 = Message(
            id="msg_002",
            account_id="acc_1",
            sender_email="mallory@attacker.com",
            sender_name="Quick Accounts",
            subject="URGENT: Invoice Details",
            received_at=utc_now(),
            raw_body_snippet="Please execute payload."
        )
        s.add(msg2)

        att2 = Attachment(
            id="att_002",
            message_id="msg_002",
            original_filename="Invoice.exe",
            sanitized_filename="Invoice.exe",
            file_hash_sha256="deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
            file_size_bytes=20480,
            detected_mime_type="application/x-dosexec",
            local_storage_path=str(tmp_path / "Invoice.quarantine"),
            quarantine_status="QUARANTINED",
            quarantine_reason="Executable disguised file blocked",
            version_number=1
        )
        s.add(att2)

    return db, str(db_file)


def test_database_search_records(populated_db):
    db, _ = populated_db

    # Search by keyword
    res = db.search_records(query="Financial")
    assert len(res) == 1
    assert res[0]["filename"] == "Financial_Report_Q3.pdf"

    # Search by sender
    res_sender = db.search_records(sender="attacker.com")
    assert len(res_sender) == 1
    assert res_sender[0]["status"] == "QUARANTINED"

    # Search by status
    res_clean = db.search_records(status="CLEAN")
    assert len(res_clean) == 1
    assert res_clean[0]["filename"] == "Financial_Report_Q3.pdf"

    res_quar = db.search_records(status="QUARANTINED")
    assert len(res_quar) == 1
    assert res_quar[0]["quarantine_reason"] == "Executable disguised file blocked"


def test_database_storage_statistics(populated_db):
    db, _ = populated_db
    stats = db.get_storage_statistics()

    assert stats["total_messages"] == 2
    assert stats["total_attachments"] == 2
    assert stats["clean_count"] == 1
    assert stats["quarantine_count"] == 1
    assert stats["total_bytes"] == 30720
    assert len(stats["top_senders"]) == 2
    assert len(stats["top_mimes"]) == 2


def test_cli_search_and_stats(populated_db, tmp_path):
    _, db_file = populated_db
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(f"""
database:
  db_url: "sqlite:///{db_file}"
storage:
  download_dir: "{tmp_path}/Auto_download_email"
""")

    runner = CliRunner()

    # Test search
    res_search = runner.invoke(cli, ["search", "Financial", "-c", str(cfg_file)])
    assert res_search.exit_code == 0
    assert "Financial_Report_Q3.pdf" in res_search.output
    assert "Alice Smith" in res_search.output

    # Test stats
    res_stats = runner.invoke(cli, ["stats", "-c", str(cfg_file)])
    assert res_stats.exit_code == 0
    assert "ENTERPRISE GATEWAY OPERATIONAL ANALYTICS" in res_stats.output
    assert "Total Ingested Emails:     2" in res_stats.output
    assert "Total Tracked Attachments: 2" in res_stats.output


def test_cli_export_csv_and_json(populated_db, tmp_path):
    _, db_file = populated_db
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(f"""
database:
  db_url: "sqlite:///{db_file}"
storage:
  download_dir: "{tmp_path}/Auto_download_email"
""")

    runner = CliRunner()
    csv_out = tmp_path / "export.csv"
    res_csv = runner.invoke(cli, ["export", "--format", "csv", "--output", str(csv_out), "-c", str(cfg_file)])
    assert res_csv.exit_code == 0
    assert csv_out.exists()
    content = csv_out.read_text()
    assert "Financial_Report_Q3.pdf" in content
    assert "Invoice.exe" in content

    json_out = tmp_path / "export.json"
    res_json = runner.invoke(cli, ["export", "--format", "json", "--output", str(json_out), "-c", str(cfg_file)])
    assert res_json.exit_code == 0
    assert json_out.exists()
    data = json.loads(json_out.read_text())
    assert len(data) == 2
