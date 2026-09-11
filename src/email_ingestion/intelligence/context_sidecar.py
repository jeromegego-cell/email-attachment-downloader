"""Context sidecar generator for downloaded attachments.

Generates `email_context.md` (human-readable) and `context.json` (machine-readable)
alongside downloaded attachments in the delivery envelope using atomic commits
and strict 0600 POSIX permissions.
"""

import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple


class ContextSidecarGenerator:
    """Creates structured context sidecars capturing the original email metadata and body."""

    # Basic DLP Patterns for masking sensitive data in sidecars
    DLP_PATTERNS = [
        (re.compile(r"\b(?:\d[ -]*?){13,16}\b"), "[REDACTED_PAYMENT_CARD]"),
        (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),
        (re.compile(r"(?i)\b(password|passwd|pwd)\s*[:=]\s*\S+"), r"\1: [REDACTED_SECRET]"),
    ]

    @classmethod
    def sanitize_body_for_privacy(cls, text: Optional[str]) -> str:
        """Mask common sensitive credentials and PII patterns from email text."""
        if not text:
            return ""
        clean = text
        for pattern, replacement in cls.DLP_PATTERNS:
            clean = pattern.sub(replacement, clean)
        return clean

    @classmethod
    def _write_file_atomically(cls, dest_path: Path, content: str) -> None:
        """Write text content atomically with 0600 permissions."""
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = dest_path.parent / f".tmp_{uuid.uuid4().hex}_{dest_path.name}"
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(content)
            try:
                os.chmod(temp_path, 0o600)
            except OSError:
                pass
            os.replace(temp_path, dest_path)
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            raise

    @classmethod
    def generate_sidecars(
        cls,
        envelope_dir: Path,
        sender_email: str,
        sender_name: Optional[str],
        subject: Optional[str],
        received_at: datetime,
        message_id: str,
        thread_id: Optional[str],
        body_text: Optional[str],
        attachments_meta: List[Dict[str, Any]],
        anomaly_warnings: Optional[List[str]] = None,
        revision_info: Optional[Dict[str, Any]] = None,
        ai_summary: Optional[Dict[str, Any]] = None
    ) -> Tuple[Path, Path]:
        """Write both `email_context.md` and `context.json` to the target delivery folder."""
        
        # Apply DLP sanitization to email body preview
        sanitized_body = cls.sanitize_body_for_privacy(body_text)

        # 1. Build Machine-Readable context.json
        context_data = {
            "version": "1.0",
            "message_id": message_id,
            "thread_id": thread_id,
            "received_at": received_at.isoformat(),
            "sender": {
                "email": sender_email,
                "name": sender_name or ""
            },
            "subject": subject or "",
            "body_snippet": (sanitized_body[:500] + "...") if len(sanitized_body) > 500 else sanitized_body,
            "attachments": attachments_meta,
            "anomalies": anomaly_warnings or [],
            "revision": revision_info or {},
            "ai_summary": ai_summary or {}
        }

        json_path = envelope_dir / "context.json"
        cls._write_file_atomically(json_path, json.dumps(context_data, indent=2, ensure_ascii=False))

        # 2. Build Human-Readable email_context.md
        md_lines = []
        md_lines.append(f"# Email Delivery Context: {subject or '(No Subject)'}")
        md_lines.append("")

        # Anomaly Warning Banner if applicable
        if anomaly_warnings:
            md_lines.append("> [!WARNING]")
            for warning in anomaly_warnings:
                md_lines.append(f"> **Anomaly Alert:** {warning}")
            md_lines.append("")

        # Revision Note if applicable
        if revision_info and revision_info.get("is_revision"):
            md_lines.append("> [!NOTE]")
            score = revision_info.get("similarity_score", 0.0) * 100
            parent_ver = revision_info.get("parent_version", 1)
            new_ver = revision_info.get("version_number", 2)
            md_lines.append(f"> **Document Revision:** Identified as version `{new_ver}` ({score:.1f}% similarity to version `{parent_ver}`).")
            md_lines.append("")

        md_lines.append("## Email Information")
        md_lines.append(f"- **From:** {sender_name or ''} `<{sender_email}>`")
        md_lines.append(f"- **Received:** {received_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        md_lines.append(f"- **Subject:** {subject or '(No Subject)'}")
        md_lines.append(f"- **Message ID:** `{message_id}`")
        if thread_id:
            md_lines.append(f"- **Thread ID:** `{thread_id}`")
        md_lines.append("")

        # AI Summary block if generated
        if ai_summary and ai_summary.get("summary"):
            md_lines.append("## AI Executive Summary")
            md_lines.append(f"> {ai_summary.get('summary')}")
            if ai_summary.get("action_items"):
                md_lines.append("")
                md_lines.append("**Key Action Items:**")
                for item in ai_summary.get("action_items", []):
                    md_lines.append(f"- [ ] {item}")
            md_lines.append("")

        md_lines.append("## Original Email Content")
        if sanitized_body:
            clean_body = sanitized_body.strip()
            quoted_body = "\n".join(f"> {line}" for line in clean_body.splitlines())
            md_lines.append(quoted_body)
        else:
            md_lines.append("> *(Email contained no plain text body content)*")
        md_lines.append("")

        md_lines.append("## Enclosed Attachments")
        for att in attachments_meta:
            fname = att.get("filename", "unknown")
            fsize = att.get("size_bytes", 0)
            fhash = att.get("sha256", "")[:12]
            fstatus = att.get("status", "CLEAN")
            md_lines.append(f"- **`{fname}`** ({fsize:,} bytes) — SHA-256: `{fhash}...` — Status: `{fstatus}`")

        md_lines.append("")
        md_path = envelope_dir / "email_context.md"
        cls._write_file_atomically(md_path, "\n".join(md_lines))

        return json_path, md_path
