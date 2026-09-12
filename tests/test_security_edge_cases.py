"""Advanced security edge case tests for the Enterprise Email Ingestion Gateway.

Tests defenses against:
- Truncated and zero-byte payload anomalies
- Windows LNK / shortcut exploits
- Office VBA macro document disguise
- Active HTML / SVG script injections
- URL percent-encoded directory traversal
- Null byte filename injection
- POSIX 255-byte name length boundary limits
- Tar Slip, sparse file, and archive bomb limits
- Cross-device atomic commits and staging sweeps
"""

import io
import os
import tarfile
import zipfile
import pytest
from pathlib import Path

from email_ingestion.security.magic_verifier import MagicVerifier
from email_ingestion.security.path_sanitizer import PathSanitizer
from email_ingestion.security.archive_guard import ArchiveGuard
from email_ingestion.storage.atomic_writer import AtomicFileWriter


def test_zero_byte_files(tmp_path):
    """Verify appropriate handling of zero-byte files."""
    # 1. Zero-byte dangerous file (.exe) must be rejected
    zero_exe = tmp_path / "zero.exe"
    zero_exe.write_bytes(b"")
    is_safe, mime, reason = MagicVerifier.inspect_file(zero_exe)
    assert is_safe is False
    assert "dangerous" in reason.lower()

    # 2. Zero-byte structured document (.pdf, .docx) must be rejected as truncated
    zero_pdf = tmp_path / "zero.pdf"
    zero_pdf.write_bytes(b"")
    is_safe, mime, reason = MagicVerifier.inspect_file(zero_pdf)
    assert is_safe is False
    assert "zero-byte" in reason.lower() or "truncated" in reason.lower()

    # 3. Zero-byte plain text or csv is benign
    zero_txt = tmp_path / "zero.txt"
    zero_txt.write_bytes(b"")
    is_safe, mime, reason = MagicVerifier.inspect_file(zero_txt)
    assert is_safe is True
    assert mime == "text/plain"


def test_windows_lnk_shortcut_detection(tmp_path):
    """Verify that Windows shortcut (.lnk) headers are identified and blocked."""
    # Real Windows LNK header
    lnk_header = b"\x4c\x00\x00\x00\x01\x14\x02\x00" + b"\x00" * 68
    
    # 1. Declared as .lnk
    lnk_file = tmp_path / "shortcut.lnk"
    lnk_file.write_bytes(lnk_header)
    is_safe, mime, reason = MagicVerifier.inspect_file(lnk_file)
    assert is_safe is False

    # 2. Disguised as .pdf
    fake_pdf = tmp_path / "shortcut_disguised.pdf"
    fake_pdf.write_bytes(lnk_header)
    is_safe, mime, reason = MagicVerifier.inspect_file(fake_pdf)
    assert is_safe is False
    assert "lnk shortcut" in reason.lower()


def test_disguised_office_macro_rejection(tmp_path):
    """Verify that macro-enabled Office files (.docm) disguised as standard .docx are blocked."""
    docm_disguised = tmp_path / "Q3_Report.docx"
    with zipfile.ZipFile(docm_disguised, "w") as zf:
        zf.writestr("[Content_Types].xml", b"<Types></Types>")
        zf.writestr("word/document.xml", b"<w:document></w:document>")
        zf.writestr("word/vbaProject.bin", b"DANGEROUS_VBA_PAYLOAD_BYTES")

    is_safe, mime, reason = MagicVerifier.inspect_file(docm_disguised)
    assert is_safe is False
    assert "vba macro" in reason.lower()


def test_active_script_in_svg_rejection(tmp_path):
    """Verify that SVG or HTML files with executable script tags are blocked."""
    evil_svg = tmp_path / "graphic.svg"
    evil_svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><script>alert("xss")</script></svg>',
        encoding="utf-8"
    )
    is_safe, mime, reason = MagicVerifier.inspect_file(evil_svg)
    assert is_safe is False
    assert "script execution" in reason.lower()


def test_path_sanitizer_url_encoding_and_null_bytes():
    """Verify handling of percent-encoded path traversals and null byte attacks."""
    # 1. Percent-encoded traversal: %2e%2e%2f -> ../
    url_traversal = "%2e%2e%2f%2e%2e%2fetc%2fpasswd"
    clean_traversal = PathSanitizer.sanitize_filename(url_traversal)
    assert "passwd" in clean_traversal
    assert "/" not in clean_traversal
    assert ".." not in clean_traversal

    # 2. Null byte injection: invoice.pdf\0.exe
    null_byte = "invoice.pdf\x00.exe"
    clean_null = PathSanitizer.sanitize_filename(null_byte)
    assert "\x00" not in clean_null
    assert clean_null == "invoice.pdf_.exe"


def test_path_sanitizer_windows_devices_expanded():
    """Verify expanded Windows reserved devices: com0, lpt0, conin$, conout$."""
    devices = ["COM0.pdf", "lpt0.docx", "CONIN$.txt", "conout$.csv", "clock$.log"]
    for dev in devices:
        clean = PathSanitizer.sanitize_filename(dev)
        assert clean.lower().startswith("safe_")


def test_path_sanitizer_posix_length_truncation():
    """Verify that filenames exceeding 255 UTF-8 bytes are truncated safely without corrupting extensions."""
    long_stem = "A" * 300
    filename = f"{long_stem}.pdf"
    clean = PathSanitizer.sanitize_filename(filename)

    assert len(clean.encode("utf-8")) <= 255
    assert clean.endswith(".pdf")
    assert not clean.endswith(".")
    assert not clean.endswith(" ")


def test_archive_guard_streaming_tar_slip_and_symlink(tmp_path):
    """Verify that Tar Slip and symlink attacks in TAR archives are blocked."""
    guard = ArchiveGuard()
    tar_path = tmp_path / "slip.tar"

    with tarfile.open(tar_path, "w") as tf:
        # 1. Symlink entry
        symlink_info = tarfile.TarInfo(name="symlink_entry")
        symlink_info.type = tarfile.SYMTYPE
        symlink_info.linkname = "/etc/shadow"
        tf.addfile(symlink_info)

    is_safe, reason = guard.inspect_archive(tar_path)
    assert is_safe is False
    assert "symlink" in reason.lower() or "traversal" in reason.lower()


def test_atomic_writer_staging_cleanup(tmp_path):
    """Verify that stale temporary files are cleaned up."""
    staging = tmp_path / "staging"
    blobs = tmp_path / "blobs"
    writer = AtomicFileWriter(staging_dir=staging, cas_blob_dir=blobs)

    # Create dummy staging file
    part_file = staging / "tmp_old_123.part"
    part_file.write_bytes(b"abandoned_part")

    # Override mtime to 2 hours ago
    old_time = os.path.getmtime(part_file) - 7200
    os.utime(part_file, (old_time, old_time))

    purged = writer.cleanup_stale_staging(max_age_seconds=3600)
    assert purged == 1
    assert not part_file.exists()


def test_macro_enabled_office_docm_rejection(tmp_path):
    """Verify that macro-enabled formats (.docm, .xlsm) are blocked."""
    docm = tmp_path / "Invoice.docm"
    docm.write_bytes(b"PK\x03\x04dummy_zip_content")
    is_safe, mime, reason = MagicVerifier.inspect_file(docm)
    assert is_safe is False
    assert "dangerous executable or macro extension" in reason.lower()


def test_pdf_embedded_javascript_rejection(tmp_path):
    """Verify that PDFs containing embedded active JavaScript or /Launch actions are quarantined."""
    evil_pdf = tmp_path / "invoice_with_script.pdf"
    evil_pdf.write_bytes(
        b"%PDF-1.5\n"
        b"1 0 obj\n"
        b"<< /Type /Catalog /Pages 2 0 R /OpenAction << /S /JavaScript /JS (app.alert('pwned');) >> >>\n"
        b"endobj\n"
        b"%%EOF\n"
    )
    is_safe, mime, reason = MagicVerifier.inspect_file(evil_pdf)
    assert is_safe is False
    assert "javascript" in reason.lower() or "launch" in reason.lower()


def test_pdf_payload_past_8192_bytes_rejection(tmp_path):
    """Verify that PDF active script payloads placed past 8192 bytes (padding) are detected."""
    evil_pdf = tmp_path / "delayed_payload.pdf"
    # Pad 10KB of benign PDF comments before the malicious object
    padding = b"% " + (b"A" * 10240) + b"\n"
    evil_pdf.write_bytes(
        b"%PDF-1.5\n" +
        padding +
        b"10 0 obj\n"
        b"<< /Type /Action /S /Launch /F (cmd.exe) >>\n"
        b"endobj\n"
        b"%%EOF\n"
    )
    is_safe, mime, reason = MagicVerifier.inspect_file(evil_pdf)
    assert is_safe is False
    assert "launch" in reason.lower() or "javascript" in reason.lower()


def test_legacy_office_ole_vba_macro_rejection(tmp_path):
    """Verify that legacy Office documents (.doc, .xls) containing OLE VBA macros are quarantined."""
    evil_doc = tmp_path / "PurchaseOrder.doc"
    # OLE Compound Document signature + embedded VBA stream marker
    ole_header = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + (b"\x00" * 512)
    vba_payload = b"_VBA_PROJECT\x00Sub AutoOpen()\x00End Sub\x00"
    evil_doc.write_bytes(ole_header + vba_payload)

    is_safe, mime, reason = MagicVerifier.inspect_file(evil_doc)
    assert is_safe is False
    assert "vba macro" in reason.lower()


def test_archive_null_byte_rejection(tmp_path):
    """Verify that archives with null byte injection in member names are blocked."""
    from unittest.mock import patch, MagicMock

    zip_path = tmp_path / "test.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("test.txt", b"safe content")

    mock_info = MagicMock()
    mock_info.filename = "benign.txt\x00.exe"
    mock_info.external_attr = 0
    mock_info.file_size = 50

    with patch("zipfile.ZipFile.infolist", return_value=[mock_info]):
        guard = ArchiveGuard()
        is_safe, reason = guard.inspect_archive(zip_path)
        assert is_safe is False
        assert "traversal" in reason.lower() or "detected" in reason.lower()


def test_sender_folder_rfc5322_parsing():
    """Verify that complex RFC 5322 sender headers are parsed cleanly into safe folder names."""
    from email_ingestion.storage.layout_manager import StorageLayoutManager
    layout = StorageLayoutManager()

    folder = layout.sanitize_sender_folder("Sarah Connor <sarah.connor@acme-corp.com>")
    assert folder == "sarah.connor_acme-corp.com"

    folder2 = layout.sanitize_sender_folder("<orders@vendor.com>")
    assert folder2 == "orders_vendor.com"

    folder3 = layout.sanitize_sender_folder("billing@company.com")
    assert folder3 == "billing_company.com"

