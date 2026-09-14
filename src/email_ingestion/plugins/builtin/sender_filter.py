"""Sender Filter plugin.

Integrates the SenderFilter security engine into the plugin lifecycle.
Evaluates incoming email envelopes against configured sender exclusion rules.
"""

from typing import Optional, List, Tuple
from pathlib import Path
from email_ingestion.plugins.base_plugin import BasePlugin
from email_ingestion.connectors.base import EmailEnvelope
from email_ingestion.security.sender_filter import SenderFilter


class SenderFilterPlugin(BasePlugin):
    """Plugin that filters incoming email envelopes against sender exclusion rules."""

    @property
    def plugin_name(self) -> str:
        return "sender_filter"

    def __init__(
        self,
        filter_instance: Optional[SenderFilter] = None,
        rules: Optional[List[str]] = None,
        exclude_file: Optional[str | Path] = None
    ) -> None:
        if filter_instance:
            self.filter = filter_instance
        else:
            self.filter = SenderFilter(rules=rules, exclude_file=exclude_file)

    def should_process_envelope(self, envelope: EmailEnvelope) -> bool:
        """Evaluate if the sender is allowed or excluded."""
        is_excluded, _ = self.filter.is_excluded(envelope.sender_email)
        return not is_excluded

    def check_sender(self, sender_email: str) -> Tuple[bool, Optional[str]]:
        """Direct check returning (is_excluded, matched_rule)."""
        return self.filter.is_excluded(sender_email)
