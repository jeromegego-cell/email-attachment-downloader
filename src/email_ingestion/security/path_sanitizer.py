"""Filename sanitization and path traversal defense.

Leverages the battle-tested 'pathvalidate' library to guarantee that
untrusted filenames sent in email MIME headers cannot escape the target
directory, exploit Windows Alternate Data Streams (ADS), reserved device
names, or exceed POSIX byte-length maximums.
"""

import os
import re
import unicodedata
import urllib.parse
from pathvalidate import sanitize_filename
from pathvalidate._filename import truncate_str

# Expanded Windows DOS devices and aliases
ADDITIONAL_RESERVED_NAMES = [
    "CLOCK$", "CONIN$", "CONOUT$",
    "COM0", "LPT0"
]

# Regex to defuse Right-to-Left Override, zero-width spaces, and control characters
BIDI_AND_CONTROL_REGEX = re.compile(
    r"[\u200e\u200f\u202a-\u202e\u2066-\u2069\u200b-\u200d\ufeff\x00-\x1f\x7f-\x9f]"
)


class PathSanitizer:
    """Sanitizes incoming attachment filenames against malicious paths, ADS, and DoS."""

    @staticmethod
    def sanitize_filename(raw_filename: str, fallback_prefix: str = "attachment") -> str:
        """Sanitize an untrusted attachment filename."""
        if not raw_filename:
            return f"{fallback_prefix}.dat"

        # 1. Defuse URL percent-encoding (%2e%2e, %2f, %5c, %00)
        clean_name = urllib.parse.unquote(str(raw_filename).strip())

        # 2. Defuse null bytes by converting to underscore instead of silent truncation
        clean_name = clean_name.replace("\x00", "_")

        # 3. Unicode NFKC Normalization (converts fullwidth ／, ＼, ： to ASCII equivalents)
        clean_name = unicodedata.normalize("NFKC", clean_name)

        # 4. Strip Bidi override and invisible control characters
        clean_name = BIDI_AND_CONTROL_REGEX.sub("", clean_name)

        # 5. Extract basename across both POSIX and Windows path separators
        clean_name = clean_name.replace("\\", "/")
        clean_name = clean_name.split("/")[-1]

        def _reserved_handler(e):
            return f"safe_{e.reserved_name}"

        # 6. Apply pathvalidate with universal platform rules and reserved device handling
        stem, ext = os.path.splitext(clean_name)
        clean_stem = sanitize_filename(
            stem,
            replacement_text="_",
            platform="universal",
            additional_reserved_names=ADDITIONAL_RESERVED_NAMES,
            reserved_name_handler=_reserved_handler,
        )
        clean_ext = sanitize_filename(
            ext,
            replacement_text="_",
            platform="universal",
        ) if ext else ""

        # 7. Enforce POSIX 255-byte ceiling while preserving extension
        ext_bytes = len(clean_ext.encode("utf-8"))
        if ext_bytes >= 245:
            full = f"{clean_stem}{clean_ext}"
            clean_name = truncate_str(full, "utf-8", 255)
        else:
            truncated_stem = truncate_str(clean_stem, "utf-8", 255 - ext_bytes)
            clean_name = f"{truncated_stem}{clean_ext}"

        # 8. Strip leading and trailing periods, hyphens, and spaces
        clean_name = clean_name.strip(". -")

        return clean_name or f"{fallback_prefix}.dat"
