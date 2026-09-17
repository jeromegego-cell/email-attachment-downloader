"""Unit tests verifying audit remediations and defensive edge case fixes.

Covers:
1. Same-envelope identical filename disambiguation (no data loss).
2. Legitimate PDF electronic invoice (/EmbeddedFiles) accepted as safe.
3. Plain text (.txt) files containing code snippets/logs accepted as safe.
4. SignatureFilter CID extraction with and without @domain.
5. ArchiveGuard small archive ratio tolerance and double-dot filename safety.
6. DocumentSimilarityEngine binary file fallback.
"""

import io
import zipfile
from pathlib import Path
from datetime import datetime, timezone
import pytest

from email_ingestion.security.magic_verifier import MagicVerifier
from email_ingestion.security.signature_filter import SignatureFilter
from email_ingestion.security.archive_guard import ArchiveGuard
from email_ingestion.intelligence.fuzzy_similarity import DocumentSimilarityEngine
from email_ingestion.connectors.base import BaseEmailConnector, EmailEnvelope, AttachmentStub
from email_ingestion.config import EngineSettings, StorageSettings
from email_ingestion.engine import EmailIngestionEngine


class MultiDuplicateAttachConnector(BaseEmailConnector):
    """Connector that provides an email with two attachments sharing the same filename."""

    @property
    def provider_name(self) -> str:
        return "MOCK_DUP_NAMES"

    def connect(self) -> bool:
        return True

    def fetch_new_messages(self, max_messages: int = 50) -> list[EmailEnvelope]:
        return [
            EmailEnvelope(
                id="msg_same_name_001",
                account_id="acc_1",
                sender_email="vendor@services.com",
                sender_name="Vendor",
                subject="Multiple Invoices",
                received_at=datetime.now(timezone.utc),
                attachments=[
                    AttachmentStub(
                        id="att_1",
                        filename="invoice.pdf",
                        content_type="application/pdf",
                        size_bytes=100,
                        content_disposition="attachment"
                    ),
                    AttachmentStub(
                        id="att_2",
                        filename="invoice.pdf",  # EXACT SAME FILENAME!
                        content_type="application/pdf",
                        size_bytes=120,
                        content_disposition="attachment"
                    )
                ]
            )
        ]

    def download_attachment_stream(self, message_id: str, attachment_id: str) -> io.BytesIO:
        if attachment_id == "att_1":
            return io.BytesIO(b"%PDF-1.5 Invoice #1 Content\n%%EOF")
        else:
            return io.BytesIO(b"%PDF-1.5 Invoice #2 Content Different Data\n%%EOF")

    def acknowledge_processed(self, message_id: str) -> None:
        pass


def test_same_envelope_duplicate_filename_disambiguation(tmp_path):
    """Verify that multiple attachments in one email with the same name do NOT overwrite each other."""
    db_file = tmp_path / "dup_test.db"
    download_dir = tmp_path / "downloads"

    settings = EngineSettings(
        environment="development",
        storage=StorageSettings(
            download_dir=download_dir,
            quarantine_dir=download_dir / "quarantine",
            staging_dir=download_dir / ".staging"
        ),
        database={"db_url": f"sqlite:///{db_file}"},
        mock_provider={"enabled": False},
        plugins=[]
    )

    engine = EmailIngestionEngine(settings)
    connector = MultiDuplicateAttachConnector()
    engine.connectors = [connector]

    metrics = engine.run_sync()

    assert metrics["messages_processed"] == 1
    assert metrics["attachments_downloaded"] == 2

    # Check that BOTH files exist on disk with distinct names
    envelope_dirs = [d for d in download_dir.glob("*/*") if d.is_dir() and not d.name.startswith(".")]
    assert len(envelope_dirs) == 1
    files_on_disk = [f.name for f in envelope_dirs[0].iterdir() if f.is_file() and not f.name.endswith(".md") and not f.name.endswith(".json")]
    
    assert "invoice.pdf" in files_on_disk
    assert "invoice_1.pdf" in files_on_disk

    # Verify both files have different contents (neither was overwritten)
    content1 = (envelope_dirs[0] / "invoice.pdf").read_bytes()
    content2 = (envelope_dirs[0] / "invoice_1.pdf").read_bytes()
    assert content1 != content2
    assert b"Invoice #1" in content1
    assert b"Invoice #2" in content2


def test_pdf_embedded_files_einvoice_allowed(tmp_path):
    """Verify European ZUGFeRD / Factur-X standard PDFs containing /EmbeddedFiles are marked safe."""
    zugferd_pdf = tmp_path / "zugferd_invoice.pdf"
    zugferd_pdf.write_bytes(
        b"%PDF-1.7\n"
        b"1 0 obj\n<< /Type /Catalog /EmbeddedFiles 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Names [(factur-x.xml) 3 0 R] >>\nendobj\n"
        b"%%EOF"
    )

    is_safe, mime, reason = MagicVerifier.inspect_file(zugferd_pdf)
    assert is_safe is True
    assert mime == "application/pdf"
    assert reason is None


def test_text_file_with_code_allowed(tmp_path):
    """Verify plain text and log files containing script keywords (<script>, etc.) are NOT quarantined."""
    txt_file = tmp_path / "server_debug.log"
    txt_file.write_text("ERROR: Client requested <script>alert('test')</script> at /api/v1\nStatus 400 Bad Request")

    is_safe, mime, reason = MagicVerifier.inspect_file(txt_file)
    assert is_safe is True
    assert reason is None


def test_signature_filter_cid_matching_with_and_without_domain():
    """Verify signature filter correctly matches CIDs regardless of @domain in HTML or header."""
    sig_filter = SignatureFilter(max_size_bytes=15360)

    # Case A: HTML has full CID with domain, Header has full CID with domain
    html_a = '<p>Regards</p><img src="cid:logo_acme@01D89F">'
    assert sig_filter.is_signature_attachment(
        filename="logo.png",
        content_disposition="inline",
        content_id="<logo_acme@01D89F>",
        file_size_bytes=4096,
        html_body=html_a
    ) is True

    # Case B: HTML has bare CID without domain, Header has @domain
    html_b = '<p>Regards</p><img src="cid:logo_acme">'
    assert sig_filter.is_signature_attachment(
        filename="logo.png",
        content_disposition="inline",
        content_id="<logo_acme@01D89F>",
        file_size_bytes=4096,
        html_body=html_b
    ) is True


def test_archive_guard_double_dot_filename_allowed(tmp_path):
    """Verify that benign files with double dots in filename (e.g. notes..v2.txt) are not rejected as Zip Slip."""
    guard = ArchiveGuard()
    zip_path = tmp_path / "legit_dots.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("annual_report..2026.csv", b"col1,col2\nval1,val2\n")

    is_safe, reason = guard.inspect_archive(zip_path)
    assert is_safe is True
    assert reason is None


def test_archive_guard_legitimate_archive_allowed(tmp_path):
    """Verify that legitimate business archives (e.g. compressed CSV/invoices) are safely accepted."""
    guard = ArchiveGuard()  # default max_ratio=10.0
    zip_path = tmp_path / "monthly_reports.zip"
    csv_lines = ["InvoiceID,Customer,Date,Description,Amount,Status\n"]
    for i in range(100):
        csv_lines.append(f"INV-{1000+i},Customer_{i*7%13},2026-09-{1+i%28:02d},Shipment batch #{i*91},{(i*37.5)+10.25:.2f},Processed\n")
    csv_content = "".join(csv_lines).encode("utf-8")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("monthly_reports.csv", csv_content)

    is_safe, reason = guard.inspect_archive(zip_path)
    assert is_safe is True
    assert reason is None


def test_fuzzy_similarity_binary_file_fallback(tmp_path):
    """Verify that binary files with null bytes are correctly treated as binary rather than garbled text."""
    engine = DocumentSimilarityEngine(threshold=0.80)
    bin1 = tmp_path / "doc_v1.bin"
    bin2 = tmp_path / "doc_v2.bin"

    bin1.write_bytes(b"\x00\x01\x02\x03" * 100)
    bin2.write_bytes(b"\x00\x01\x02\x03" * 100)

    is_rev, score, diff = engine.compare_files(bin1, bin2)
    assert is_rev is True
    assert score == 1.0
    assert diff is None  # No textual diff for binary files
