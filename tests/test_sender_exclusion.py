"""Unit and integration tests for the Sender Exclusion System.

Verifies:
- RFC 5322 parsing and email normalization via email-validator
- Wildcard, glob, and brace pattern matching via wcmatch
- File-based rule loading and saving
- Plugin lifecycle veto handling
- Full end-to-end sync integration with database ledger and audit logging
- CLI exclude commands (list, add, remove, test)
"""

from pathlib import Path
from datetime import datetime, timezone
import pytest
from click.testing import CliRunner

from email_ingestion.security.sender_filter import SenderFilter
from email_ingestion.plugins.builtin.sender_filter import SenderFilterPlugin
from email_ingestion.plugins.manager import PluginManager
from email_ingestion.connectors.base import EmailEnvelope, AttachmentStub, BaseEmailConnector
from email_ingestion.config import EngineSettings, StorageSettings, FilterSettings
from email_ingestion.engine import EmailIngestionEngine
from email_ingestion.database.models import Message, AuditLog
from email_ingestion.cli import cli


def test_normalize_address_standard():
    """Verify email-validator parses RFC 5322 headers into normalized address and domain."""
    norm, domain = SenderFilter.normalize_address("John Doe <john.doe@example.com>")
    assert norm == "john.doe@example.com"
    assert domain == "example.com"


def test_normalize_address_case_insensitivity():
    """Verify normalization converts domains and handles mixed case."""
    norm, domain = SenderFilter.normalize_address("ALERT-SYSTEM@Marketing.ACME.COM")
    assert norm == "alert-system@marketing.acme.com"
    assert domain == "marketing.acme.com"


def test_normalize_address_malformed_fallback():
    """Verify malformed or test strings do not crash and fall back safely."""
    norm, domain = SenderFilter.normalize_address("plain_string_without_at")
    assert norm == "plain_string_without_at"
    assert domain == ""


def test_exact_sender_matching():
    """Verify exact email address matching."""
    s_filter = SenderFilter(rules=["blocked@vendor.com"])
    
    is_ex, rule = s_filter.is_excluded("blocked@vendor.com")
    assert is_ex is True
    assert rule == "blocked@vendor.com"

    is_ex_mixed, _ = s_filter.is_excluded("BLOCKED@vendor.com")
    assert is_ex_mixed is True

    is_allowed, _ = s_filter.is_excluded("allowed@vendor.com")
    assert is_allowed is False


def test_domain_wildcard_matching():
    """Verify domain wildcards (*@domain.com and @domain.com)."""
    s_filter = SenderFilter(rules=["*@spam.com", "@marketing.acme.com"])

    assert s_filter.is_excluded("user@spam.com")[0] is True
    assert s_filter.is_excluded("ceo@marketing.acme.com")[0] is True
    assert s_filter.is_excluded("sub.marketing@marketing.acme.com")[0] is True
    assert s_filter.is_excluded("legit@acme.com")[0] is False


def test_glob_and_prefix_matching():
    """Verify prefix and infix globs powered by wcmatch."""
    s_filter = SenderFilter(rules=["no-reply*@*", "*newsletter*@*"])

    assert s_filter.is_excluded("no-reply@service.com")[0] is True
    assert s_filter.is_excluded("no-reply-alerts@internal.corp")[0] is True
    assert s_filter.is_excluded("weekly-newsletter-team@company.org")[0] is True
    assert s_filter.is_excluded("reply@service.com")[0] is False


def test_wcmatch_brace_expansion():
    """Verify wcmatch brace expansion matches alternate subdomains or hosts."""
    s_filter = SenderFilter(rules=["*@{alerts,promo,deals}.acme.com"])

    assert s_filter.is_excluded("bot@alerts.acme.com")[0] is True
    assert s_filter.is_excluded("sales@promo.acme.com")[0] is True
    assert s_filter.is_excluded("offers@deals.acme.com")[0] is True
    assert s_filter.is_excluded("support@help.acme.com")[0] is False


def test_file_load_and_save(tmp_path):
    """Verify loading from and persisting to plaintext exclusion files."""
    rule_file = tmp_path / "test_excludes.txt"
    rule_file.write_text(
        "# Comment line\n"
        "bad@domain.com\n"
        "\n"
        "*@blacklisted.org\n",
        encoding="utf-8"
    )

    s_filter = SenderFilter(exclude_file=rule_file)
    assert s_filter.is_excluded("bad@domain.com")[0] is True
    assert s_filter.is_excluded("anyone@blacklisted.org")[0] is True
    assert s_filter.is_excluded("good@domain.com")[0] is False

    # Add rule and save
    s_filter.add_rule("new-blocked@test.com")
    out_file = tmp_path / "saved_excludes.txt"
    s_filter.save_to_file(out_file)

    saved_text = out_file.read_text(encoding="utf-8")
    assert "new-blocked@test.com" in saved_text
    assert "bad@domain.com" in saved_text


def test_plugin_veto_lifecycle():
    """Verify SenderFilterPlugin integrates with PluginManager lifecycle."""
    s_filter = SenderFilter(rules=["spammer@external.com"])
    plugin = SenderFilterPlugin(filter_instance=s_filter)
    pm = PluginManager()
    pm.register_plugin(plugin)

    bad_envelope = EmailEnvelope(
        id="msg_bad",
        account_id="test_acc",
        sender_email="spammer@external.com",
        subject="Promo",
        received_at=datetime.now(timezone.utc)
    )
    good_envelope = EmailEnvelope(
        id="msg_good",
        account_id="test_acc",
        sender_email="legit@external.com",
        subject="Invoice",
        received_at=datetime.now(timezone.utc)
    )

    allowed_bad, veto_name = pm.should_process_envelope(bad_envelope)
    assert allowed_bad is False
    assert veto_name == "sender_filter"

    allowed_good, _ = pm.should_process_envelope(good_envelope)
    assert allowed_good is True


class DummyConnector(BaseEmailConnector):
    """Synthetic test connector yielding one excluded email and one valid email."""
    
    @property
    def provider_name(self) -> str:
        return "DUMMY"

    def connect(self) -> bool:
        return True

    def fetch_new_messages(self, max_messages: int = 50):
        return [
            EmailEnvelope(
                id="msg_excluded_001",
                account_id="dummy_acc",
                sender_email="no-reply@notifications.com",
                sender_name="Notification Bot",
                subject="Daily Digest",
                received_at=datetime.now(timezone.utc),
                attachments=[
                    AttachmentStub(
                        id="att_001",
                        filename="digest.pdf",
                        content_type="application/pdf",
                        size_bytes=1024
                    )
                ]
            ),
            EmailEnvelope(
                id="msg_allowed_002",
                account_id="dummy_acc",
                sender_email="billing@vendor.com",
                sender_name="Vendor Billing",
                subject="Invoice #1099",
                received_at=datetime.now(timezone.utc),
                attachments=[
                    AttachmentStub(
                        id="att_002",
                        filename="invoice_1099.pdf",
                        content_type="application/pdf",
                        size_bytes=2048
                    )
                ]
            )
        ]

    def download_attachment_stream(self, message_id: str, attachment_id: str):
        import io
        return io.BytesIO(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF")

    def acknowledge_processed(self, message_id: str) -> bool:
        return True


def test_engine_sync_with_excluded_sender(tmp_path):
    """End-to-end engine test verifying excluded emails are recorded as EXCLUDED and no files are downloaded."""
    db_path = tmp_path / "test_exclusion.db"
    download_dir = tmp_path / "downloads"

    settings = EngineSettings(
        environment="development",
        storage=StorageSettings(
            download_dir=download_dir,
            quarantine_dir=download_dir / "quarantine",
            staging_dir=download_dir / ".staging"
        ),
        filters=FilterSettings(
            enabled=True,
            excluded_senders=["no-reply@*"]
        ),
        database={"db_url": f"sqlite:///{db_path}"},
        mock_provider={"enabled": False},
        plugins=[]
    )

    engine = EmailIngestionEngine(settings)
    engine.connectors = [DummyConnector()]

    metrics = engine.run_sync()

    # Metrics verification
    assert metrics["senders_excluded"] == 1
    assert metrics["messages_processed"] == 1
    assert metrics["attachments_downloaded"] == 1

    # Verify excluded email was NOT downloaded to disk
    excluded_sender_dir = download_dir / "no-reply_notifications.com"
    assert not excluded_sender_dir.exists()

    # Verify allowed email WAS downloaded to disk
    allowed_sender_dir = download_dir / "billing_vendor.com"
    assert allowed_sender_dir.exists()

    # Verify SQLite state ledger recorded EXCLUDED status
    with engine.db.session() as db:
        excluded_msg = db.query(Message).filter(Message.id == "msg_excluded_001").first()
        assert excluded_msg is not None
        assert excluded_msg.status == "EXCLUDED"
        assert excluded_msg.sender_email == "no-reply@notifications.com"

        # Verify AuditLog event recorded
        audit = db.query(AuditLog).filter(
            AuditLog.message_id == "msg_excluded_001",
            AuditLog.event_type == "SENDER_EXCLUDED"
        ).first()
        assert audit is not None
        assert "no-reply@notifications.com" in audit.event_message


def test_cli_exclude_commands(tmp_path):
    """Verify CLI exclude commands (list, add, remove, test) work via Click CliRunner."""
    cfg_file = tmp_path / "test_config.yaml"
    exclude_file = tmp_path / "excludes.txt"
    exclude_file.write_text("existing@spam.com\n", encoding="utf-8")

    cfg_file.write_text(
        f"filters:\n"
        f"  enabled: true\n"
        f"  exclude_file: '{exclude_file}'\n"
        f"  excluded_senders:\n"
        f"    - '*@marketing.com'\n",
        encoding="utf-8"
    )

    runner = CliRunner()

    # 1. Test 'exclude list'
    res_list = runner.invoke(cli, ["exclude", "list", "-c", str(cfg_file)])
    assert res_list.exit_code == 0
    assert "*@marketing.com" in res_list.output
    assert "existing@spam.com" in res_list.output

    # 2. Test 'exclude test'
    res_test_blocked = runner.invoke(cli, ["exclude", "test", "news@marketing.com", "-c", str(cfg_file)])
    assert res_test_blocked.exit_code == 0
    assert "EXCLUDED" in res_test_blocked.output

    res_test_allowed = runner.invoke(cli, ["exclude", "test", "friend@safe.org", "-c", str(cfg_file)])
    assert res_test_allowed.exit_code == 0
    assert "ALLOWED" in res_test_allowed.output

    # 3. Test 'exclude add'
    res_add = runner.invoke(cli, ["exclude", "add", "newbot@evil.com", "-c", str(cfg_file)])
    assert res_add.exit_code == 0
    assert "Added exclusion rule" in res_add.output

    # Verify saved to file
    assert "newbot@evil.com" in exclude_file.read_text(encoding="utf-8")

    # 4. Test 'exclude remove'
    res_rem = runner.invoke(cli, ["exclude", "remove", "newbot@evil.com", "-c", str(cfg_file)])
    assert res_rem.exit_code == 0
    assert "Removed exclusion rule" in res_rem.output
    assert "newbot@evil.com" not in exclude_file.read_text(encoding="utf-8")
