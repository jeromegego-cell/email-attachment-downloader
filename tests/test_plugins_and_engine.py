"""End-to-end tests for the plugin manager, lifecycle hooks, and full engine sync."""

import pytest
from pathlib import Path
from email_ingestion.config import EngineSettings
from email_ingestion.engine import EmailIngestionEngine
from email_ingestion.plugins.manager import PluginManager
from email_ingestion.plugins.builtin.desktop_notifier import DesktopNotifierPlugin
from email_ingestion.plugins.builtin.ai_summarizer import AISummarizerPlugin
from email_ingestion.database.session import DatabaseManager
from email_ingestion.database.models import Message, Attachment, AuditLog


def test_ai_summarizer_plugin_action_extraction():
    """Verify that AISummarizer extracts action items and builds summary."""
    plugin = AISummarizerPlugin()
    body = "Hi Jerome,\nPlease review the updated agreement.\nKindly remit payment by Friday."

    actions = plugin.extract_action_items(body)
    assert len(actions) >= 2
    assert any("review" in a.lower() for a in actions)
    assert any("remit" in a.lower() for a in actions)

    context = {
        "subject": "Agreement and Invoice",
        "body_snippet": body
    }
    enriched = plugin.on_context_enriched(context)
    assert "ai_summary" in enriched
    assert len(enriched["ai_summary"]["action_items"]) >= 2


def test_full_engine_sync_end_to_end(tmp_path):
    """Run full synchronization pipeline against synthetic enterprise scenarios."""
    db_file = tmp_path / "test_state.db"
    download_dir = tmp_path / "Auto_download_email"

    settings = EngineSettings()
    settings.database.db_url = f"sqlite:///{db_file}"
    settings.storage.download_dir = download_dir
    settings.storage.quarantine_dir = download_dir / "quarantine"
    settings.storage.staging_dir = download_dir / ".staging"
    settings.mock_provider.enabled = True
    settings.intelligence.duplicate_detection_mode = "auto_dedupe"

    engine = EmailIngestionEngine(settings)
    metrics = engine.run_sync()

    # 4 synthetic emails in mock connector
    assert metrics["messages_processed"] == 4
    assert metrics["attachments_downloaded"] >= 3
    assert metrics["quarantined"] >= 1  # The disguised executable must be quarantined!

    # Verify database records
    db = DatabaseManager(settings.database.db_url)
    with db.session() as session:
        messages = session.query(Message).all()
        assert len(messages) == 4

        attachments = session.query(Attachment).all()
        assert len(attachments) >= 4

        # Verify quarantine record exists
        quarantined = [a for a in attachments if a.quarantine_status == "QUARANTINED"]
        assert len(quarantined) == 1
        assert "Urgent_Invoice.pdf" in quarantined[0].original_filename

        # Verify duplicate anomaly was logged in audit log
        anomalies = session.query(AuditLog).filter(AuditLog.event_type == "DUPLICATE_ANOMALY").all()
        assert len(anomalies) >= 1

    # Verify sidecars exist on disk
    sidecar_mds = list(download_dir.glob("**/*email_context.md"))
    assert len(sidecar_mds) >= 2
    sidecar_jsons = list(download_dir.glob("**/*context.json"))
    assert len(sidecar_jsons) >= 2

    # Verify master index table was automatically generated
    master_index = download_dir / "INDEX.md"
    assert master_index.exists()
    index_content = master_index.read_text(encoding="utf-8")
    assert "# Master Attachment Index" in index_content
    assert "QUARANTINED" in index_content
    assert "CLEAN" in index_content


def test_imap_connector_unconfigured_and_decoding():
    """Verify IMAP connector handles unconfigured state gracefully and decodes MIME headers."""
    from email_ingestion.connectors.imap_connector import IMAPConnector
    imap = IMAPConnector()
    assert imap.provider_name == "IMAP"
    assert imap.connect() is False
    assert imap.fetch_new_messages() == []

    # Test RFC 2047 MIME header decoding
    decoded = imap._decode_mime_header("=?utf-8?B?U3ViamVjdCBUZXN0?=")
    assert decoded == "Subject Test"


