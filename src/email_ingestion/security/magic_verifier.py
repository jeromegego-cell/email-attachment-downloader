"""File header sniffing and magic byte verification.

Uses pure-Python puremagic to inspect true file headers and detect
spoofed extensions, dangerous executables, and encrypted files.
"""

from pathlib import Path
from typing import Tuple, Optional, Set
import puremagic


class MagicVerifier:
    """Verifies actual binary content headers against declared filename extensions."""

    # Explicitly disallowed executable or script MIME types
    DANGEROUS_MIMES: Set[str] = {
        "application/x-dosexec",
        "application/vnd.microsoft.portable-executable",
        "application/x-executable",
        "application/x-msdownload",
        "application/x-sharedlib",
        "application/x-bat",
        "application/x-sh",
        "application/x-csh",
        "application/javascript",
        "text/javascript",
        "application/x-ms-shortcut",
    }

    # Dangerous extensions that must never be accepted as benign documents
    DANGEROUS_EXTENSIONS: Set[str] = {
        ".exe", ".dll", ".bat", ".cmd", ".com", ".scr", ".sh", ".bin",
        ".vbs", ".ps1", ".hta", ".cpl", ".msi", ".jar", ".iso", ".vhd",
        ".wsf", ".gadget", ".reg", ".pif"
    }

    # Standard safe extension mapping
    SAFE_EXTENSION_MIMES = {
        ".pdf": {"application/pdf"},
        ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/zip"},
        ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/zip"},
        ".csv": {"text/plain", "text/csv", "application/csv"},
        ".png": {"image/png"},
        ".jpg": {"image/jpeg"},
        ".jpeg": {"image/jpeg"},
        ".txt": {"text/plain", "text/csv", "text/tab-separated-values", "application/octet-stream"},
        ".zip": {"application/zip"},
    }

    @classmethod
    def inspect_file(cls, file_path: Path) -> Tuple[bool, str, Optional[str]]:
        """Inspect true magic bytes of a file on disk.
        
        Returns:
            Tuple of (is_safe: bool, detected_mime: str, quarantine_reason: Optional[str])
        """
        if not file_path.exists():
            return False, "unknown", "File does not exist"

        file_size = file_path.stat().st_size
        if file_size == 0:
            return True, "application/octet-stream", None

        file_ext = file_path.suffix.lower()

        # Rule 1: Outright rejection of dangerous extensions (e.g. .exe, .scr, .bat)
        if file_ext in cls.DANGEROUS_EXTENSIONS:
            return False, "application/x-executable", f"File declares dangerous executable extension: {file_ext}"

        # Rule 2: Fast byte signature check for binary executable headers
        try:
            with open(file_path, "rb") as f:
                header = f.read(1024)

            # Windows PE (MZ)
            if header.startswith(b"MZ"):
                return False, "application/vnd.microsoft.portable-executable", "Windows/DOS executable header (MZ) detected"
            # Linux ELF
            if header.startswith(b"\x7fELF"):
                return False, "application/x-executable", "Linux ELF executable header detected"
            # Mach-O
            if header[:4] in {b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe"}:
                return False, "application/x-mach-binary", "Mach-O executable header detected"

        except Exception as err:
            return False, "unknown", f"Failed reading file header: {str(err)}"

        # Rule 3: Inspection via puremagic
        try:
            detected_matches = puremagic.magic_file(str(file_path))
            if not detected_matches:
                # Text files or custom data without strict magic
                if file_ext in {".txt", ".csv", ".json", ".xml", ".diff"}:
                    return True, "text/plain", None
                return True, "application/octet-stream", None

            top_match = detected_matches[0]
            detected_mime = top_match.mime_type or "application/octet-stream"

            for match in detected_matches:
                # Disallow if any match detects dangerous mime or extension
                if match.mime_type in cls.DANGEROUS_MIMES or match.extension in cls.DANGEROUS_EXTENSIONS:
                    return False, match.mime_type or "application/x-executable", f"Dangerous executable magic detected ({match.mime_type or match.extension})"

            # Rule 4: Parity check for declared safe document types
            if file_ext in cls.SAFE_EXTENSION_MIMES:
                allowed_mimes = cls.SAFE_EXTENSION_MIMES[file_ext]
                # If puremagic strongly matched a completely different media type (e.g. audio/video or archive for a pdf)
                if not any(m.mime_type in allowed_mimes for m in detected_matches):
                    # Special exception: puremagic sometimes classifies tiny PDFs as octet-stream
                    if file_ext == ".pdf" and b"%PDF-" in header:
                        return True, "application/pdf", None
                    return False, detected_mime, f"MIME mismatch: declared {file_ext} but detected {detected_mime}"

            return True, detected_mime, None

        except Exception as err:
            # Fail-closed policy: unexpected parser error quarantines file safely
            return False, "application/octet-stream", f"Security inspection exception: {str(err)}"
