"""Storage layout and directory organization manager.

Enforces the standardized corporate folder hierarchy:
Auto_download_email/<sanitized_sender>/<timestamp>_<hash_prefix>/
"""

import hashlib
import os
import re
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple


class StorageLayoutManager:
    """Manages the disk directory layout for downloaded email attachments and sidecars."""

    def __init__(self, root_dir: Path = Path("Auto_download_email")):
        self.root_dir = Path(root_dir)

    def sanitize_sender_folder(self, sender_email: str) -> str:
        """Convert an email address into a safe folder name.
        
        Example: 'john.doe@company.com' -> 'john.doe_company.com'
        """
        # Strip brackets if present (e.g., '<john@example.com>')
        clean_email = sender_email.strip("<> \t\r\n").lower()
        # Replace '@' with '_'
        sanitized = clean_email.replace("@", "_")
        # Strip any characters that are not alphanumeric, underscore, period, or hyphen
        sanitized = re.sub(r"[^\w\.-]", "_", sanitized)
        sanitized = sanitized.strip(". ")
        return sanitized or "unknown_sender"

    def format_delivery_folder_name(
        self,
        received_at: datetime,
        message_id: str
    ) -> str:
        """Create a collision-proof delivery envelope folder name.
        
        Example: '2026-09-11_13-15-00_3a8f9c12'
        """
        timestamp_str = received_at.strftime("%Y-%m-%d_%H-%M-%S")
        micro = f"_{received_at.microsecond:06d}" if getattr(received_at, "microsecond", 0) else ""
        msg_hash = hashlib.sha256(str(message_id).encode("utf-8", errors="ignore")).hexdigest()[:8]
        return f"{timestamp_str}{micro}_{msg_hash}"

    def get_envelope_directory(
        self,
        sender_email: str,
        received_at: datetime,
        message_id: str
    ) -> Path:
        """Return the absolute path to the delivery envelope folder, creating parents if needed."""
        sender_dir = self.sanitize_sender_folder(sender_email)
        envelope_name = self.format_delivery_folder_name(received_at, message_id)
        
        envelope_path = self.root_dir / sender_dir / envelope_name
        envelope_path.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.root_dir, 0o700)
            os.chmod(self.root_dir / sender_dir, 0o700)
            os.chmod(envelope_path, 0o700)
        except OSError:
            pass
        return envelope_path

    def update_master_index(self, entries: list) -> Path:
        """Generate/update an orderly, sorted master index in the root download directory.
        
        Allows anyone opening the root folder to immediately view and access all downloads chronologically.
        """
        self.root_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.root_dir, 0o700)
        except OSError:
            pass

        index_file = self.root_dir / "INDEX.md"
        temp_index = self.root_dir / ".tmp_INDEX.md"

        sorted_entries = sorted(entries, key=lambda x: str(x.get("received_at", "")), reverse=True)

        total_count = len(sorted_entries)
        clean_count = sum(1 for e in sorted_entries if e.get("status") == "CLEAN")
        quarantine_count = sum(1 for e in sorted_entries if e.get("status") == "QUARANTINED")
        revision_count = sum(1 for e in sorted_entries if e.get("version_number", 1) > 1)
        total_bytes = sum(e.get("size_bytes", 0) for e in sorted_entries)
        if total_bytes >= 1048576:
            total_size_str = f"{total_bytes / 1048576:.2f} MB"
        elif total_bytes >= 1024:
            total_size_str = f"{total_bytes / 1024:.1f} KB"
        else:
            total_size_str = f"{total_bytes} B"

        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        lines = [
            "# Master Attachment Index",
            "",
            "All downloaded email attachments organized in chronological order.",
            "",
            "## 📊 Gateway Executive Summary",
            "| Total Files Tracked | Clean Downloads | Quarantined Threats | Document Revisions | Storage Consumed | Last Refreshed (UTC) |",
            "| :---: | :---: | :---: | :---: | :---: | :---: |",
            f"| **{total_count}** | {clean_count} | {quarantine_count} | {revision_count} | {total_size_str} | `{now_utc}` |",
            "",
        ]

        # Sender Quick-Jump Table
        sender_groups = {}
        for e in sorted_entries:
            s = str(e.get("sender", "unknown")).strip()
            status = e.get("status", "CLEAN")
            if s not in sender_groups:
                sender_groups[s] = {"count": 0, "quarantined": 0}
            sender_groups[s]["count"] += 1
            if status == "QUARANTINED":
                sender_groups[s]["quarantined"] += 1

        if sender_groups:
            lines.append("## 📁 Sender Directory Quick-Jump")
            lines.append("| Sender | Ingested Files | Health Status | Direct Folder Link |")
            lines.append("| :--- | :---: | :---: | :--- |")
            for s, stats in sender_groups.items():
                sender_dir = self.sanitize_sender_folder(s)
                if stats["quarantined"] > 0:
                    health = f"⚠️ {stats['quarantined']} Quarantined"
                    link = f"[Inspect Vault](./quarantine/) · [Sender Folder](./{urllib.parse.quote(sender_dir)}/)"
                else:
                    health = "✅ CLEAN"
                    link = f"[Open Folder](./{urllib.parse.quote(sender_dir)}/)"
                escaped_s = s.replace("|", "\\|")
                lines.append(f"| `{escaped_s}` | {stats['count']} | {health} | {link} |")
            lines.append("")

        lines.append("## 📜 Chronological Download Ledger")
        lines.append("| Received Date (UTC) | Sender | Filename | Size | Status | Direct Access |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")

        for e in sorted_entries:
            rec_date = str(e.get("received_at", "N/A"))
            sender = str(e.get("sender", "unknown")).replace("|", "\\|").replace("\n", " ")
            fname = str(e.get("filename", "unknown")).replace("|", "\\|").replace("\n", " ")
            size_b = e.get("size_bytes", 0)
            size_str = f"{size_b / 1024:.1f} KB" if size_b >= 1024 else f"{size_b} B"
            status = e.get("status", "CLEAN")
            
            raw_path_str = str(e.get("local_storage_path", e.get("relative_path", "")))
            local_path = Path(raw_path_str)
            try:
                rel_path = local_path.relative_to(self.root_dir)
            except ValueError:
                if raw_path_str.startswith(str(self.root_dir)):
                    rel_path = Path(raw_path_str[len(str(self.root_dir)):].lstrip("/\\"))
                else:
                    rel_path = local_path

            envelope_dir = Path(rel_path).parent
            sidecar_file = self.root_dir / envelope_dir / "email_context.md"

            quoted_rel_path = urllib.parse.quote(rel_path.as_posix())
            quoted_env_dir = urllib.parse.quote(envelope_dir.as_posix())

            if status == "QUARANTINED":
                report_name = f"{Path(rel_path).stem}.report.md"
                report_file = self.root_dir / "quarantine" / report_name
                if report_file.exists():
                    access_links = f"[Report](./quarantine/{urllib.parse.quote(report_name)}) · [Download](./{quoted_rel_path})"
                else:
                    access_links = f"[Download](./{quoted_rel_path})"
            else:
                sidecar_link = f" · [Context](./{quoted_env_dir}/email_context.md)" if sidecar_file.exists() else ""
                access_links = f"[Download](./{quoted_rel_path}){sidecar_link}"

            lines.append(f"| {rec_date} | `{sender}` | **{fname}** | {size_str} | {status} | {access_links} |")

        lines.append("")
        content = "\n".join(lines)

        # Atomic file write for index to prevent corrupt partial writes
        temp_index.write_text(content, encoding="utf-8")
        try:
            os.chmod(temp_index, 0o600)
        except OSError:
            pass
        os.replace(temp_index, index_file)
        return index_file
