"""Sender exclusion and address filtering using standard open-source libraries.

Employs email-validator for RFC 5322/6531 address parsing and normalization,
combined with wcmatch for high-performance wildcard and glob pattern matching.
"""

from pathlib import Path
from typing import List, Tuple, Optional, Set
import email.utils
import logging
import email_validator
from wcmatch import glob

logger = logging.getLogger(__name__)


class SenderFilter:
    """Evaluates incoming email senders against exclusion rules and pattern blacklists."""

    def __init__(
        self,
        rules: Optional[List[str]] = None,
        exclude_file: Optional[str | Path] = None
    ) -> None:
        self._rules: List[str] = []
        self._exclude_file: Optional[Path] = Path(exclude_file) if exclude_file else None

        if rules:
            for rule in rules:
                self.add_rule(rule)

        if self._exclude_file and self._exclude_file.exists():
            self.load_from_file(self._exclude_file)

    @classmethod
    def normalize_address(cls, raw_sender: str) -> Tuple[str, str]:
        """Normalize an email address using email.utils.parseaddr and email-validator.
        
        Returns:
            Tuple of (normalized_email, domain) in lowercase.
        """
        if not raw_sender:
            return "", ""

        # Step 1: RFC 5322 extraction (e.g. "John Doe <john@corp.com>" -> "john@corp.com")
        _, clean_addr = email.utils.parseaddr(raw_sender)
        candidate = (clean_addr or raw_sender).strip()

        # Step 2: Use email-validator for robust normalization and domain extraction
        try:
            validated = email_validator.validate_email(candidate, check_deliverability=False)
            return validated.normalized.lower(), (validated.domain or "").lower()
        except Exception:
            # Fallback for non-standard test addresses or malformed strings
            parts = candidate.lower().split("@")
            domain = parts[1] if len(parts) > 1 else ""
            return candidate.lower(), domain

    def add_rule(self, pattern: str) -> None:
        """Add a new exclusion pattern if not already present."""
        cleaned = pattern.strip()
        if cleaned and cleaned not in self._rules:
            self._rules.append(cleaned)
            logger.debug(f"Added sender exclusion rule: {cleaned}")

    def remove_rule(self, pattern: str) -> bool:
        """Remove an exclusion pattern. Returns True if removed."""
        cleaned = pattern.strip()
        if cleaned in self._rules:
            self._rules.remove(cleaned)
            logger.debug(f"Removed sender exclusion rule: {cleaned}")
            return True
        return False

    def get_all_rules(self) -> List[str]:
        """Return all active exclusion rules."""
        return list(self._rules)

    def is_excluded(self, raw_sender: str) -> Tuple[bool, Optional[str]]:
        """Check if a raw sender address matches any exclusion rule.
        
        Returns:
            Tuple of (is_excluded: bool, matched_rule: Optional[str])
        """
        if not self._rules or not raw_sender:
            return False, None

        normalized_email, domain = self.normalize_address(raw_sender)
        if not normalized_email:
            return False, None

        for rule in self._rules:
            pattern = rule.strip()
            if not pattern or pattern.startswith("#"):
                continue

            # Case 1: Exact domain match via "@domain.com"
            if pattern.startswith("@"):
                pat_domain = pattern[1:].lower()
                if domain == pat_domain or domain.endswith("." + pat_domain):
                    return True, rule
                # Also treat as wildcard
                pattern = "*" + pattern

            # Case 2: Glob / Wildcard match via wcmatch (supports *, ?, [seq], {a,b})
            flags = glob.IGNORECASE | glob.BRACE | glob.EXTGLOB
            if glob.globmatch(normalized_email, pattern, flags=flags):
                return True, rule

            # Also check if pattern matches domain directly (e.g. pattern "example.com")
            if pattern.lower() == domain:
                return True, rule

        return False, None

    def load_from_file(self, file_path: Path) -> int:
        """Load exclusion rules from a plaintext file (one pattern per line).
        
        Ignores blank lines and comments starting with '#'.
        Returns count of new rules loaded.
        """
        if not file_path.exists():
            return 0

        count = 0
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    if stripped not in self._rules:
                        self.add_rule(stripped)
                        count += 1
        logger.info(f"Loaded {count} exclusion rules from {file_path}")
        return count

    def save_to_file(self, file_path: Path) -> None:
        """Persist all active exclusion rules to a plaintext file."""
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("# Enterprise Email Ingestion - Excluded Senders & Pattern Blacklist\n")
            f.write("# Supports exact addresses, domain wildcards (*@domain.com), and globs (no-reply*@*)\n\n")
            for rule in self._rules:
                f.write(f"{rule}\n")
