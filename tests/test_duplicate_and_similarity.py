"""Unit tests for duplicate detection, fuzzy document similarity, and context sidecars."""

import json
from datetime import datetime, timezone
from pathlib import Path
from email_ingestion.intelligence.duplicate_detector import DuplicateAnomalyDetector
from email_ingestion.intelligence.fuzzy_similarity import DocumentSimilarityEngine
from email_ingestion.intelligence.context_sidecar import ContextSidecarGenerator


def test_detect_intra_message_duplicates():
    """Verify detection when a user accidentally attaches the same file twice to one email."""
    detector = DuplicateAnomalyDetector(mode="auto_dedupe")
    attachments = [
        {"filename": "Invoice.pdf", "sha256": "aaaa1111", "size_bytes": 1024},
        {"filename": "Spec.pdf", "sha256": "bbbb2222", "size_bytes": 2048},
        {"filename": "Invoice_copy.pdf", "sha256": "aaaa1111", "size_bytes": 1024}  # Identical hash!
    ]

    duplicates = detector.detect_intra_message_duplicates(attachments)
    assert len(duplicates) == 1
    assert duplicates[0]["original_slot"] == "Invoice.pdf"
    assert duplicates[0]["duplicate_slot"] == "Invoice_copy.pdf"
    assert duplicates[0]["sha256"] == "aaaa1111"


def test_document_similarity_revision_and_diff(tmp_path):
    """Verify that similar text files with same name are detected as revisions and diffed."""
    sim_engine = DocumentSimilarityEngine(threshold=0.80)

    file_v1 = tmp_path / "Quote.txt"
    file_v1.write_text("Item 1: 5 Servers - $5000\nTotal: $5000\n", encoding="utf-8")

    file_v2 = tmp_path / "Quote_v2.txt"
    file_v2.write_text("Item 1: 5 Servers - $5000\nDiscount: 10%\nTotal: $4500\n", encoding="utf-8")

    is_revision, score, diff_text = sim_engine.compare_files(file_v1, file_v2)
    assert is_revision is True
    assert score >= 0.80
    assert diff_text is not None
    assert "-Total: $5000" in diff_text
    assert "+Total: $4500" in diff_text


def test_context_sidecar_generation(tmp_path):
    """Verify that email_context.md and context.json are cleanly generated."""
    envelope_dir = tmp_path / "test_envelope"
    envelope_dir.mkdir()

    json_path, md_path = ContextSidecarGenerator.generate_sidecars(
        envelope_dir=envelope_dir,
        sender_email="sarah@acme.com",
        sender_name="Sarah",
        subject="Monthly Invoice",
        received_at=datetime.now(timezone.utc),
        message_id="msg_999",
        thread_id="thread_888",
        body_text="Hi Jerome,\nPlease find invoice attached.",
        attachments_meta=[{"filename": "inv.pdf", "size_bytes": 100, "sha256": "abcdef", "status": "CLEAN"}],
        anomaly_warnings=["Duplicate file ignored"]
    )

    assert json_path.exists()
    assert md_path.exists()

    # Verify JSON structure
    with open(json_path) as jf:
        data = json.load(jf)
        assert data["message_id"] == "msg_999"
        assert len(data["anomalies"]) == 1

    # Verify Markdown structure
    md_content = md_path.read_text(encoding="utf-8")
    assert "Monthly Invoice" in md_content
    assert "Duplicate file ignored" in md_content
    assert "sarah@acme.com" in md_content
