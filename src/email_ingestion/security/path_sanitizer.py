"""Filename sanitization and path traversal defense.

Guarantees that untrusted filenames sent in email MIME headers cannot
escape the target directory, exploit Windows Alternate Data Streams (ADS),
or exceed POSIX byte-length maximums.
"""

import os
import re
import unicodedata
import urllib.parse

# Windows reserved device names (case-insensitive)
RESERVED_DEVICE_NAMES = {
    "con", "prn", "aux", "nul", "clock$", "conin$", "conout$",
    "com0", "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
    "lpt0", "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9"
}

# Regex to remove Right-to-Left Override, zero-width spaces, and control characters
BIDI_AND_CONTROL_REGEX = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069\u200b-\u200d\ufeff\x00-\x1f\x7f-\x9f]")


class PathSanitizer:
    """Sanitizes incoming attachment filenames against malicious paths, ADS, and DoS."""

    @staticmethod
    def sanitize_filename(raw_filename: str, fallback_prefix: str = "attachment") -> str:
        """Sanitize an untrusted attachment filename."""
        if not raw_filename:
            return f"{fallback_prefix}.dat"

        # 1. URL percent-decoding (resolves %2e%2e, %2f, %5c, %00 attacks)
        clean_name = urllib.parse.unquote(str(raw_filename).strip())

        # 2. Defuse null bytes by converting to underscore instead of silent elimination
        clean_name = clean_name.replace("\x00", "_")

        # 3. Unicode NFKC Normalization (converts fullwidth ／, ＼, ： to ASCII equivalents)
        clean_name = unicodedata.normalize("NFKC", clean_name)

        # 4. Strip Bidi override, zero-width spaces, and control characters
        clean_name = BIDI_AND_CONTROL_REGEX.sub("", clean_name)

        # 5. Take basename across both POSIX and Windows path separators
        clean_name = clean_name.replace("\\", "/")
        clean_name = clean_name.split("/")[-1]

        # 6. Replace forbidden filesystem characters and ADS colons
        clean_name = re.sub(r'[/\\:*?"<>|]', "_", clean_name)

        # 7. Strip leading periods, hyphens, and spaces (prevents hidden files & CLI argument injection)
        clean_name = clean_name.lstrip(". -")

        # 8. Strip trailing dots and spaces (prevents Windows Win32 API bypass)
        clean_name = clean_name.rstrip(". ")

        if not clean_name:
            return f"{fallback_prefix}.dat"

        # 9. Check root stem and basename without extension against Windows reserved device names
        root_stem = clean_name.split(".")[0].lower()
        full_stem = os.path.splitext(clean_name)[0].lower()
        if root_stem in RESERVED_DEVICE_NAMES or full_stem in RESERVED_DEVICE_NAMES:
            clean_name = f"safe_{clean_name}"

        # 10. Truncate by UTF-8 BYTE length (POSIX NAME_MAX = 255 bytes limit)
        max_bytes = 255
        encoded = clean_name.encode("utf-8")
        if len(encoded) > max_bytes:
            name_part, ext_part = os.path.splitext(clean_name)
            ext_bytes = ext_part.encode("utf-8")
            if len(ext_bytes) >= max_bytes - 10:
                clean_name = encoded[:max_bytes].decode("utf-8", errors="ignore")
            else:
                allowed_name_bytes = max_bytes - len(ext_bytes)
                truncated_name = name_part.encode("utf-8")[:allowed_name_bytes].decode("utf-8", errors="ignore")
                clean_name = f"{truncated_name}{ext_part}"

            # Post-truncation clean up to ensure boundary truncation didn't leave illegal edges
            clean_name = clean_name.strip(". -")

        return clean_name or f"{fallback_prefix}.dat"
