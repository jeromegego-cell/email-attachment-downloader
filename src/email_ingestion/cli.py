"""Command-line interface (CLI) for the Enterprise Email Ingestion Engine.

Provides user-friendly commands to trigger manual syncs, inspect state,
audit security alerts, and run offline demonstrations.
"""

from pathlib import Path
import click
from email_ingestion.config import get_settings
from email_ingestion.engine import EmailIngestionEngine
from email_ingestion.database.session import DatabaseManager
from email_ingestion.database.models import Message, Attachment, AuditLog


@click.group()
@click.version_option(version="0.1.0", prog_name="email-ingestion")
def cli():
    """Enterprise Email Ingestion Engine CLI."""
    pass


@cli.command("sync")
@click.option("--config", "-c", type=click.Path(exists=True), help="Path to custom config.yaml")
def sync_command(config):
    """Execute a synchronization run across all active email providers."""
    cfg_path = Path(config) if config else None
    settings = get_settings(cfg_path)
    engine = EmailIngestionEngine(settings)

    click.secho("Starting email synchronization...", fg="cyan", bold=True)
    metrics = engine.run_sync()

    click.secho("\n--- Synchronization Summary ---", fg="green", bold=True)
    click.echo(f"  Messages Processed:    {metrics['messages_processed']}")
    click.echo(f"  Attachments Downloaded: {metrics['attachments_downloaded']}")
    click.echo(f"  Files Quarantined:      {metrics['quarantined']}")


@cli.command("status")
@click.option("--config", "-c", type=click.Path(exists=True), help="Path to custom config.yaml")
def status_command(config):
    """Inspect current database state and ingestion totals."""
    cfg_path = Path(config) if config else None
    settings = get_settings(cfg_path)
    db = DatabaseManager(settings.database.db_url)

    with db.session() as session:
        msg_count = session.query(Message).count()
        att_count = session.query(Attachment).count()
        quarantine_count = session.query(Attachment).filter(Attachment.quarantine_status == "QUARANTINED").count()
        revision_count = session.query(Attachment).filter(Attachment.version_number > 1).count()
        anomalies_count = session.query(AuditLog).filter(AuditLog.event_type == "DUPLICATE_ANOMALY").count()

    click.secho("\n=== Engine State & Audit Ledger ===", fg="cyan", bold=True)
    click.echo(f"  Total Emails Ingested:    {msg_count}")
    click.echo(f"  Total Attachments Tracked:{att_count}")
    click.echo(f"  Document Revisions (v2+): {revision_count}")
    click.echo(f"  Quarantined Threats:      {quarantine_count}")
    click.echo(f"  Duplicate Anomalies:      {anomalies_count}")
    click.echo(f"  Storage Root:             {settings.storage.download_dir.resolve()}")


@cli.command("audit")
@click.option("--limit", "-n", default=10, help="Number of audit log entries to display")
@click.option("--config", "-c", type=click.Path(exists=True), help="Path to custom config.yaml")
def audit_command(limit, config):
    """Display the most recent security and duplicate audit events."""
    cfg_path = Path(config) if config else None
    settings = get_settings(cfg_path)
    db = DatabaseManager(settings.database.db_url)

    with db.session() as session:
        logs = session.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).all()

    click.secho(f"\n=== Recent Audit Events (Last {limit}) ===", fg="yellow", bold=True)
    if not logs:
        click.echo("  No audit events recorded yet.")
        return

    for log in logs:
        color = "red" if log.event_type == "QUARANTINE" else "yellow" if log.event_type == "DUPLICATE_ANOMALY" else "white"
        click.secho(f"[{log.created_at.strftime('%Y-%m-%d %H:%M:%S')}] [{log.event_type}]", fg=color, bold=True)
        click.echo(f"  {log.event_message}")


@cli.command("demo")
def demo_command():
    """Run an offline demonstration testing all enterprise features."""
    click.secho("\n===========================================================", fg="magenta", bold=True)
    click.secho("   ENTERPRISE EMAIL INGESTION ENGINE - LIVE DEMONSTRATION   ", fg="magenta", bold=True)
    click.secho("===========================================================", fg="magenta", bold=True)
    click.echo("Running synchronization with synthetic enterprise scenarios:")
    click.echo("  • Standard Invoice + Signature Logo Filter")
    click.echo("  • Intra-Email Duplicate (Mistaken twin attachment)")
    click.echo("  • Revised Document (Quote 2026 -> v2 with 10% discount)")
    click.echo("  • Spoofed Executable (PE executable disguised as PDF)")
    click.echo("")

    settings = get_settings()
    settings.mock_provider.enabled = True
    settings.intelligence.duplicate_detection_mode = "auto_dedupe"
    engine = EmailIngestionEngine(settings)

    metrics = engine.run_sync()

    click.secho("\n[OK] Demonstration Complete!", fg="green", bold=True)
    click.echo(f"  Messages processed:     {metrics['messages_processed']}")
    click.echo(f"  Attachments downloaded: {metrics['attachments_downloaded']}")
    click.echo(f"  Threats quarantined:    {metrics['quarantined']}")
    click.echo(f"\nInspect generated files in: {settings.storage.download_dir.resolve()}/")


@cli.command("reindex")
@click.option("--config", "-c", type=click.Path(exists=True), help="Path to custom config.yaml")
def reindex_command(config):
    """Rebuild the master INDEX.md catalog in the root download folder."""
    cfg_path = Path(config) if config else None
    settings = get_settings(cfg_path)
    engine = EmailIngestionEngine(settings)
    index_path = engine._refresh_master_index()
    if index_path and index_path.exists():
        click.secho(f"[OK] Master index updated successfully: {index_path}", fg="green", bold=True)
    else:
        click.secho("[INFO] No attachments found in ledger to index.", fg="yellow")


if __name__ == "__main__":
    cli()
