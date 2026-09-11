"""AI Context Summarizer plugin.

Extracts intent, action items, and executive summaries from the email body
to enrich the `email_context.md` sidecar. Supports heuristic extraction and
can be extended with cloud LLMs (Gemini, OpenAI) or local models (Ollama).
"""

import re
from typing import Dict, Any, List
from email_ingestion.plugins.base_plugin import BasePlugin


class AISummarizerPlugin(BasePlugin):
    """Context enrichment plugin that analyzes email body content."""

    @property
    def plugin_name(self) -> str:
        return "ai_summarizer"

    def __init__(self, api_key: str = None):
        self.api_key = api_key

    def extract_action_items(self, text: str) -> List[str]:
        """Heuristically extract action items or urgent instructions from email text."""
        if not text:
            return []

        action_patterns = [
            r"(?:please|kindly|could you|request to)\s+([^.\n]+)",
            r"(?:due by|deadline|pay by|remit by)\s+([^.\n]+)",
            r"(?:review|sign|approve)\s+([^.\n]+)"
        ]

        actions = []
        for line in text.splitlines():
            for p in action_patterns:
                match = re.search(p, line, re.IGNORECASE)
                if match:
                    action_text = match.group(0).strip()
                    if action_text not in actions:
                        actions.append(action_text)

        return actions[:5]

    def on_context_enriched(self, context_data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze body snippet and populate `ai_summary` inside context_data."""
        body = context_data.get("body_snippet", "")
        subject = context_data.get("subject", "")

        actions = self.extract_action_items(body)
        
        # Build 1-2 sentence executive summary
        summary_sentence = f"Email regarding '{subject}'."
        if actions:
            summary_sentence += f" Requires attention: {actions[0]}."
        else:
            summary_sentence += " Standard business transmission with enclosed attachments."

        context_data["ai_summary"] = {
            "summary": summary_sentence,
            "action_items": actions,
            "category": "Invoicing & Operations" if "invoice" in subject.lower() else "General Correspondence"
        }
        return context_data
