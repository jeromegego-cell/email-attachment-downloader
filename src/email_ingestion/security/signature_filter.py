"""Signature and decorative icon filtering pipeline.

Examines attachment MIME headers, dimensions, and HTML CID references to
drop company banners, social media icons, and tracking pixels from downloads.
"""

import re
from typing import Optional, Set


class SignatureFilter:
    """Detects and drops decorative signature graphics and logos."""

    # Generic signature image filename patterns
    SIGNATURE_PATTERNS = [
        r"^image\d{3}\.(png|jpg|jpeg|gif)$",
        r"^(logo|sig|signature|banner|icon|badge|footer|social|facebook|twitter|linkedin|instagram)\w*\.(png|jpg|jpeg|gif)$",
    ]

    def __init__(self, max_size_bytes: int = 15360):
        self.max_size_bytes = max_size_bytes
        self.compiled_patterns = [re.compile(p, re.IGNORECASE) for p in self.SIGNATURE_PATTERNS]

    @staticmethod
    def extract_cids_from_html(html_body: Optional[str]) -> Set[str]:
        """Extract all Content-ID (CID) strings referenced in `<img src="cid:...">` tags."""
        if not html_body:
            return set()
        # Find matches like cid:image001.png@01D78F...
        matches = re.findall(r'<img[^>]+src=["\']cid:([^"\'@>]+)(?:@[^"\'>]+)?["\']', html_body, re.IGNORECASE)
        return {m.strip("<>").lower() for m in matches}

    def is_signature_attachment(
        self,
        filename: str,
        content_disposition: Optional[str],
        content_id: Optional[str],
        file_size_bytes: int,
        html_body: Optional[str] = None
    ) -> bool:
        """Evaluate whether an attachment is a decorative email signature or social icon.
        
        Criteria:
        1. If Content-Disposition is 'inline' and Content-ID is referenced in HTML body -> Signature.
        2. If file is small (< 15 KB) and matches generic signature patterns -> Signature.
        """
        clean_name = filename.lower().strip()
        clean_disposition = (content_disposition or "").lower().strip()
        clean_cid = (content_id or "").strip("<> ").lower()

        # Rule 1: Inline image referenced in HTML body via CID
        if "inline" in clean_disposition and clean_cid and html_body:
            cids_in_html = self.extract_cids_from_html(html_body)
            if clean_cid in cids_in_html:
                return True

        # Rule 2: Small image file (< threshold) matching common logo/signature filename patterns
        if file_size_bytes <= self.max_size_bytes:
            for pattern in self.compiled_patterns:
                if pattern.match(clean_name):
                    return True

        return False
