"""Plugin manager and lifecycle event dispatcher.

Safely coordinates registered plugins and broadcasts lifecycle hooks.
Ensures that an exception in one plugin does not crash the entire ingestion loop.
"""

import logging
from typing import List, Dict, Any, Optional
from email_ingestion.plugins.base_plugin import BasePlugin
from email_ingestion.connectors.base import EmailEnvelope, AttachmentStub

logger = logging.getLogger(__name__)


class PluginManager:
    """Dispatches lifecycle events to all registered plugins."""

    def __init__(self):
        self._plugins: List[BasePlugin] = []

    def register_plugin(self, plugin: BasePlugin) -> None:
        """Register a new plugin instance."""
        self._plugins.append(plugin)
        logger.info(f"Registered plugin: {plugin.plugin_name}")

    def notify_email_received(self, envelope: EmailEnvelope) -> None:
        """Broadcast email received event."""
        for p in self._plugins:
            try:
                p.on_email_received(envelope)
            except Exception as err:
                logger.error(f"Plugin '{p.plugin_name}' error in on_email_received: {err}")

    def notify_duplicate_detected(self, duplicate_event: Dict[str, Any]) -> Optional[str]:
        """Broadcast duplicate detected event. First plugin with non-None response wins."""
        for p in self._plugins:
            try:
                action = p.on_duplicate_detected(duplicate_event)
                if action:
                    return action
            except Exception as err:
                logger.error(f"Plugin '{p.plugin_name}' error in on_duplicate_detected: {err}")
        return None

    def enrich_context(self, context_data: Dict[str, Any]) -> Dict[str, Any]:
        """Allow plugins to sequentially enrich or append context metadata."""
        current_data = context_data
        for p in self._plugins:
            try:
                current_data = p.on_context_enriched(current_data)
            except Exception as err:
                logger.error(f"Plugin '{p.plugin_name}' error in on_context_enriched: {err}")
        return current_data

    def notify_quarantine(
        self,
        envelope: EmailEnvelope,
        attachment_name: str,
        reason: str
    ) -> None:
        """Broadcast file quarantine event."""
        for p in self._plugins:
            try:
                p.on_quarantine(envelope, attachment_name, reason)
            except Exception as err:
                logger.error(f"Plugin '{p.plugin_name}' error in on_quarantine: {err}")

    def notify_ingestion_complete(self, record: Dict[str, Any]) -> None:
        """Broadcast completion event."""
        for p in self._plugins:
            try:
                p.on_ingestion_complete(record)
            except Exception as err:
                logger.error(f"Plugin '{p.plugin_name}' error in on_ingestion_complete: {err}")
