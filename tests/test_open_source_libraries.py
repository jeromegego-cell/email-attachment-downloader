"""Unit tests verifying integration and behavior of standard open-source libraries.

Validates:
- tenacity: Exponential backoff, jitter, and exception filtering
- pathvalidate: Cross-platform filename sanitization and reserved device handling
- rapidfuzz: SIMD-accelerated text similarity and revision detection
- email-reply-parser: Reply stripping from email body threads
- email.policy.default & email.header: Standard RFC 2047/2231 MIME parsing
"""

import pytest
from pathlib import Path
from email_ingestion.connectors.resilience import retry_with_backoff
from email_ingestion.security.path_sanitizer import PathSanitizer
from email_ingestion.intelligence.fuzzy_similarity import DocumentSimilarityEngine
from email_ingestion.intelligence.context_sidecar import ContextSidecarGenerator
from email_ingestion.connectors.imap_connector import IMAPConnector


def test_tenacity_retry_with_backoff_success():
    """Verify tenacity retries transient errors and succeeds upon recovery."""
    attempts = 0

    @retry_with_backoff(retries=3, base_delay=0.01, max_delay=0.05, retryable_exceptions=(ConnectionError,))
    def unstable_operation():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ConnectionError("Temporary network reset")
        return "success"

    result = unstable_operation()
    assert result == "success"
    assert attempts == 3


def test_tenacity_retry_with_backoff_exhausted():
    """Verify tenacity reraises after exceeding maximum retry attempts."""
    attempts = 0

    @retry_with_backoff(retries=2, base_delay=0.01, max_delay=0.05, retryable_exceptions=(TimeoutError,))
    def always_failing():
        nonlocal attempts
        attempts += 1
        raise TimeoutError("Persistent timeout")

    with pytest.raises(TimeoutError):
        always_failing()

    # 1 initial try + 2 retries = 3 total invocations
    assert attempts == 3


def test_pathvalidate_integration():
    """Verify PathSanitizer leverages pathvalidate to defuse illegal OS filenames."""
    dirty_names = [
        ("AUX.tar.gz", "safe_AUX.tar.gz"),
        ("CONIN$.dat", "safe_CONIN$.dat"),
        ("report:stream:$DATA.pdf", "report_stream_$DATA.pdf"),
        ("file?name*.docx", "file_name_.docx"),
        ("   spaced_name.pdf   ", "spaced_name.pdf"),
        ("....dot_prefix.csv", "dot_prefix.csv"),
    ]

    for raw, expected in dirty_names:
        clean = PathSanitizer.sanitize_filename(raw)
        assert clean == expected, f"Failed: {raw} -> got {clean}, expected {expected}"


def test_rapidfuzz_document_similarity(tmp_path):
    """Verify RapidFuzz computes SIMD-accelerated similarity and diff generation."""
    engine = DocumentSimilarityEngine(threshold=0.80)

    doc_v1 = tmp_path / "contract.txt"
    doc_v2 = tmp_path / "contract_revised.txt"

    doc_v1.write_text("Clause 1: Payment within 30 days.\nClause 2: Warranty 1 year.\n", encoding="utf-8")
    doc_v2.write_text("Clause 1: Payment within 45 days.\nClause 2: Warranty 1 year.\n", encoding="utf-8")

    is_rev, score, diff = engine.compare_files(doc_v1, doc_v2)
    assert is_rev is True
    assert 0.85 <= score <= 0.99
    assert diff is not None
    assert "-Clause 1: Payment within 30 days." in diff
    assert "+Clause 1: Payment within 45 days." in diff


def test_email_reply_parser_thread_stripping():
    """Verify email-reply-parser strips historical quoted chains from body text."""
    full_thread = (
        "Hi Jerome,\n\n"
        "Here is the updated attachment requested.\n\n"
        "Best,\n"
        "Alice\n\n"
        "On Sep 10, 2026, at 10:00 AM, Jerome <jerome@example.com> wrote:\n"
        "> Could you please send over the latest financial statement?\n"
        "> Thanks!\n"
    )

    clean_text = ContextSidecarGenerator.clean_reply_text(full_thread)
    assert "Here is the updated attachment requested." in clean_text
    assert "On Sep 10, 2026" not in clean_text
    assert "> Could you please send over" not in clean_text


def test_imap_make_header_decoding():
    """Verify IMAPConnector._decode_mime_header decodes encoded words via standard library."""
    # Base64 encoded UTF-8
    b64_header = "=?utf-8?B?Q29uZmlkZW50aWFsIEZpbmFuY2lhbCBSZXBvcnQ=?="
    assert IMAPConnector._decode_mime_header(b64_header) == "Confidential Financial Report"

    # Quoted-Printable encoded ISO-8859-1
    qp_header = "=?iso-8859-1?Q?Caf=E9_Menu?="
    assert IMAPConnector._decode_mime_header(qp_header) == "Café Menu"
