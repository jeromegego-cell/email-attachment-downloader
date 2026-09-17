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
        "application/x-ole-storage",
    }

    # Dangerous extensions that must never be accepted as benign documents
    DANGEROUS_EXTENSIONS: Set[str] = {
        ".exe", ".dll", ".bat", ".cmd", ".com", ".scr", ".sh", ".bin",
        ".vbs", ".ps1", ".hta", ".cpl", ".msi", ".jar", ".iso", ".vhd",
        ".wsf", ".gadget", ".reg", ".pif", ".lnk", ".appx", ".deb", ".rpm",
        ".js", ".jse", ".vbe", ".wsh", ".msc", ".inf", ".scf",
        ".docm", ".xlsm", ".pptm", ".dotm", ".xltm"
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

        file_ext = file_path.suffix.lower()

        # Rule 1: Outright rejection of dangerous extensions (e.g. .exe, .scr, .bat, .lnk, .docm)
        if file_ext in cls.DANGEROUS_EXTENSIONS:
            return False, "application/x-executable", f"File declares dangerous executable or macro extension: {file_ext}"

        file_size = file_path.stat().st_size

        # Rule 2: Zero-byte file handling
        if file_size == 0:
            if file_ext in cls.SAFE_EXTENSION_MIMES and file_ext not in {".txt", ".csv"}:
                return False, "application/octet-stream", f"Zero-byte truncated file claiming document extension: {file_ext}"
            if file_ext in {".txt", ".csv", ".json", ".xml", ".diff", ".log"}:
                return True, "text/plain", None
            return True, "application/octet-stream", None

        # Rule 3: Fast byte signature check for binary executables, shortcuts, and scripts
        try:
            with open(file_path, "rb") as f:
                header = f.read(8192)

            # Windows PE (MZ)
            if header.startswith(b"MZ"):
                return False, "application/vnd.microsoft.portable-executable", "Windows/DOS executable header (MZ) detected"
            # Linux ELF
            if header.startswith(b"\x7fELF"):
                return False, "application/x-executable", "Linux ELF executable header detected"
            # Mach-O
            if header[:4] in {b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe"}:
                return False, "application/x-mach-binary", "Mach-O executable header detected"
            # Windows LNK shortcut
            if header.startswith(b"\x4c\x00\x00\x00\x01\x14\x02\x00"):
                return False, "application/x-ms-shortcut", "Windows LNK shortcut file detected"

            # Check for embedded script execution in markup/browser formats (scan up to 2MB to prevent truncation bypass)
            if file_ext in {".svg", ".html", ".htm", ".xml"}:
                with open(file_path, "rb") as f_text:
                    sample = f_text.read(2097152).lower()
                dangerous_tags = [
                    b"<script", b"javascript:", b"vbscript:",
                    b"<hta:application", b"onload=", b"onerror=",
                    b"<iframe", b"data:text/html"
                ]
                if any(tag in sample for tag in dangerous_tags):
                    return False, "text/html", f"Active script execution payload detected in {file_ext}"

            # Check for PDF active code execution (/JavaScript, /Launch) (scan up to 5MB to prevent truncation bypass)
            # Note: /EmbeddedFiles is allowed as it is required by official EU ZUGFeRD/Factur-X e-invoicing standards
            if file_ext == ".pdf" and b"%PDF-" in header:
                with open(file_path, "rb") as f_pdf:
                    pdf_sample = f_pdf.read(5242880).lower()
                if any(x in pdf_sample for x in [b"/javascript", b"/js ", b"/launch"]):
                    return False, "application/pdf", "Dangerous active script or /Launch action embedded in PDF"

            # Check for legacy Office OLE compound document VBA macros (.doc, .xls, .ppt)
            if header.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
                with open(file_path, "rb") as f_ole:
                    ole_sample = f_ole.read(2097152)
                vba_markers = [b"_VBA_PROJECT", b"VBA\x00", b"dir\x00", b"Attribut\x00e\x00 \x00V\x00B\x00_"]
                if any(marker in ole_sample for marker in vba_markers):
                    return False, "application/vnd.ms-office.vba", "Legacy Office document containing embedded VBA macro code"

        except Exception as err:
            return False, "unknown", f"Failed reading file header: {str(err)}"

        # Rule 4: Deep inspection of ZIP-based Office XML documents for disguised VBA macros
        if file_ext in {".docx", ".xlsx", ".pptx"}:
            try:
                import zipfile
                if zipfile.is_zipfile(file_path):
                    with zipfile.ZipFile(file_path, "r") as zf:
                        for entry in zf.namelist():
                            lower_entry = entry.lower()
                            if "vbaproject.bin" in lower_entry or "vbalegacy" in lower_entry:
                                return False, "application/vnd.ms-office.vba", f"Dangerous VBA macro payload detected inside disguised {file_ext}"
            except Exception:
                pass

        # Rule 5: Inspection via puremagic
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

            # Rule 6: Parity check for declared safe document types
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
