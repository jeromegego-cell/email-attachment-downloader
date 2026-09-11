"""Storage layout and directory organization manager.

Enforces the standardized corporate folder hierarchy:
Auto_download_email/<sanitized_sender>/<timestamp>_<hash_prefix>/
"""

import re
from datetime import datetime
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
        
        Example: '2026-09-11_13-15-00_3a8f9c'
        """
        timestamp_str = received_at.strftime("%Y-%m-%d_%H-%M-%S")
        # Use first 6-8 chars of message id or hash
        safe_hash = re.sub(r"[^\w]", "", message_id)[:8] or "000000"
        return f"{timestamp_str}_{safe_hash}"

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
        return envelope_path

    def update_master_index(self, entries: list) -> Path:
        """Generate/update an orderly, sorted master index in the root download directory.
        
        Allows anyone opening the root folder to immediately view and access all downloads chronologically.
        """
        self.root_dir.mkdir(parents=True, exist_ok=True)
        index_file = self.root_dir / "INDEX.md"

        sorted_entries = sorted(entries, key=lambda x: str(x.get("received_at", "")), reverse=True)

        lines = [
            "# Master Attachment Index",
            "",
            "All downloaded email attachments organized in chronological order.",
            "",
            "| Received Date (UTC) | Sender | Filename | Size | Status | Direct Access |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |"
        ]

        for e in sorted_entries:
            rec_date = str(e.get("received_at", "N/A"))
            sender = e.get("sender", "unknown")
            fname = e.get("filename", "unknown")
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
            sidecar_link = f" · [Context](./{envelope_dir}/email_context.md)" if sidecar_file.exists() else ""
            lines.append(f"| {rec_date} | `{sender}` | **{fname}** | {size_str} | {status} | [Download](./{rel_path}){sidecar_link} |")

        lines.append("")
        index_file.write_text("\n".join(lines), encoding="utf-8")
        return index_file
