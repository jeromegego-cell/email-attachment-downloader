"""Built-in plugins for the Enterprise Email Ingestion Engine."""
from email_ingestion.plugins.builtin.desktop_notifier import DesktopNotifierPlugin
from email_ingestion.plugins.builtin.ai_summarizer import AISummarizerPlugin

__all__ = ["DesktopNotifierPlugin", "AISummarizerPlugin"]
