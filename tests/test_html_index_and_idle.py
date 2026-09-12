"""Tests for interactive HTML catalog generation and IMAP IDLE support."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from email_ingestion.storage.layout_manager import StorageLayoutManager
from email_ingestion.connectors.imap_connector import IMAPConnector


def test_html_index_generation(tmp_path):
    download_dir = tmp_path / "Auto_download_email"
    mgr = StorageLayoutManager(root_dir=download_dir)

    entries = [
        {
            "received_at": datetime(2026, 9, 12, 14, 0, 0, tzinfo=timezone.utc),
            "sender": "vendor@supply.com",
            "filename": "Delivery_Manifest.pdf",
            "size_bytes": 10240,
            "status": "CLEAN",
            "version_number": 1,
            "local_storage_path": str(download_dir / "vendor_supply.com" / "env1" / "Delivery_Manifest.pdf")
        },
        {
            "received_at": datetime(2026, 9, 12, 14, 30, 0, tzinfo=timezone.utc),
            "sender": "vendor@supply.com",
            "filename": "Delivery_Manifest.pdf",
            "size_bytes": 12288,
            "status": "CLEAN",
            "version_number": 2,
            "local_storage_path": str(download_dir / "vendor_supply.com" / "env2" / "Delivery_Manifest.pdf")
        },
        {
            "received_at": datetime(2026, 9, 12, 15, 0, 0, tzinfo=timezone.utc),
            "sender": "bad@phishing.net",
            "filename": "Invoice_Urgent.exe",
            "size_bytes": 50000,
            "status": "QUARANTINED",
            "version_number": 1,
            "local_storage_path": str(download_dir / "quarantine" / "hash_Invoice_Urgent.quarantine")
        }
    ]

    index_md = mgr.update_master_index(entries)
    assert index_md.exists()
    assert (download_dir / "INDEX.md").exists()

    # Verify index.html exists
    index_html = download_dir / "index.html"
    assert index_html.exists()

    html_text = index_html.read_text(encoding="utf-8")
    assert "<table id=\"attachmentsTable\"" in html_text
    assert "searchInput" in html_text
    assert "data-tab=\"QUARANTINED\"" in html_text
    assert "Delivery_Manifest.pdf" in html_text
    assert "badge-version" in html_text
    assert "v2" in html_text
    assert "bad@phishing.net" in html_text
    assert "⚠️ QUARANTINED" in html_text


def test_imap_idle_capability_and_wait():
    connector = IMAPConnector(
        host="imap.acme.com",
        username="user@acme.com",
        password="secret_password"
    )

    # When client is None
    assert connector.supports_idle() is False
    assert connector.idle_wait(timeout=1) is False

    # Mock client with IDLE capability
    mock_client = MagicMock()
    mock_client.capability.return_value = ("OK", [b"IMAP4rev1 IDLE STARTTLS"])
    connector._client = mock_client

    assert connector.supports_idle() is True

    # Test idle wait with mock socket
    mock_client._new_tag.return_value = b"A001"
    mock_client.readline.side_effect = [b"+ idling\r\n", b"A001 OK IDLE completed\r\n"]
    mock_sock = MagicMock()
    mock_client.sock = mock_sock

    import select
    from unittest.mock import patch
    with patch("select.select", return_value=([mock_sock], [], [])):
        res = connector.idle_wait(timeout=5)
        assert res is True
        mock_client.send.assert_any_call(b"A001 IDLE\r\n")
        mock_client.send.assert_any_call(b"DONE\r\n")
