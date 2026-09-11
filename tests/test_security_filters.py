"""Unit tests for defensive security modules: PathSanitizer, SignatureFilter, MagicVerifier, ArchiveGuard."""

import io
import zipfile
import pytest
from pathlib import Path
from email_ingestion.security.path_sanitizer import PathSanitizer
from email_ingestion.security.signature_filter import SignatureFilter
from email_ingestion.security.magic_verifier import MagicVerifier
from email_ingestion.security.archive_guard import ArchiveGuard


def test_path_sanitizer_directory_traversal():
    """Verify that path traversal attempts are neutralized."""
    evil_names = [
        "../../etc/passwd",
        "..\\..\\Windows\\System32\\cmd.exe",
        "/absolute/path/invoice.pdf",
        "foo/bar/baz.pdf"
    ]
    for evil in evil_names:
        clean = PathSanitizer.sanitize_filename(evil)
        assert "/" not in clean
        assert "\\" not in clean
        assert not clean.startswith("..")


def test_path_sanitizer_windows_reserved_words():
    """Verify that Windows reserved device names are escaped."""
    reserved = ["CON.pdf", "prn.txt", "aux.docx", "NUL.csv", "com1.log"]
    for r in reserved:
        clean = PathSanitizer.sanitize_filename(r)
        assert clean.lower().startswith("safe_")


def test_signature_filter_inline_cid():
    """Verify that inline images with matching CID in HTML are flagged as signatures."""
    sig_filter = SignatureFilter(max_size_bytes=15360)
    html = '<p>Best regards,</p><img src="cid:logo_123" alt="logo">'

    is_sig = sig_filter.is_signature_attachment(
        filename="logo.png",
        content_disposition="inline",
        content_id="<logo_123>",
        file_size_bytes=4096,
        html_body=html
    )
    assert is_sig is True


def test_signature_filter_legitimate_attachment():
    """Verify that real PDF attachments are NOT dropped."""
    sig_filter = SignatureFilter(max_size_bytes=15360)
    html = '<p>Please find attached invoice.</p>'

    is_sig = sig_filter.is_signature_attachment(
        filename="Invoice_Q3.pdf",
        content_disposition="attachment",
        content_id=None,
        file_size_bytes=524288,
        html_body=html
    )
    assert is_sig is False


def test_magic_verifier_spoofed_executable(tmp_path):
    """Verify that an executable disguised as a PDF is detected as dangerous."""
    fake_pdf = tmp_path / "invoice.pdf"
    # Write DOS/Windows PE executable magic bytes
    fake_pdf.write_bytes(b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00This program cannot be run in DOS mode.")

    is_safe, mime, reason = MagicVerifier.inspect_file(fake_pdf)
    assert is_safe is False
    assert "executable" in reason.lower() or "application/x-dosexec" in mime


def test_archive_guard_zip_bomb(tmp_path):
    """Verify that archives with suspicious compression ratios are rejected."""
    guard = ArchiveGuard(max_ratio=10.0)
    zip_path = tmp_path / "test_bomb.zip"

    # Create a small zip with huge repeated zeros (high compression ratio)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("zero.txt", b"0" * 100000)

    # 100,000 bytes compressed to ~100 bytes = ~1000:1 ratio
    is_safe, reason = guard.inspect_zip_archive(zip_path)
    assert is_safe is False
    assert "zip bomb" in reason.lower()


def test_magic_verifier_raw_executable_rejection(tmp_path):
    """Verify that raw .exe and .scr files are rejected by default."""
    raw_exe = tmp_path / "malware.exe"
    raw_exe.write_bytes(b"MZ\x90\x00some_payload")
    is_safe, mime, reason = MagicVerifier.inspect_file(raw_exe)
    assert is_safe is False
    assert "dangerous" in reason.lower() or "executable" in reason.lower()


def test_path_sanitizer_unicode_and_bidi():
    """Verify that fullwidth slashes and bidi overrides are stripped."""
    # Fullwidth solidus '／' (U+FF0F)
    fullwidth = "invoices\uff0fpayload.pdf"
    clean = PathSanitizer.sanitize_filename(fullwidth)
    assert "payload.pdf" in clean
    assert "/" not in clean and "\\" not in clean

    # Right-to-Left override (U+202E)
    bidi_spoof = "contract_\u202egnp.exe"
    clean_bidi = PathSanitizer.sanitize_filename(bidi_spoof)
    assert "\u202e" not in clean_bidi


def test_archive_guard_zip_slip_rejection(tmp_path):
    """Verify that zip slip paths are caught."""
    guard = ArchiveGuard()
    zip_path = tmp_path / "zip_slip.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("../../evil.sh", b"echo pwned")

    is_safe, reason = guard.inspect_archive(zip_path)
    assert is_safe is False
    assert "traversal" in reason.lower()

