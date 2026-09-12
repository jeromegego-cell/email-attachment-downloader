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
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose informational logging")
@click.option("--debug", is_flag=True, help="Enable detailed debug trace logging")
@click.option("--dry-run", is_flag=True, help="Simulate ingestion without writing files or modifying database")
@click.option("--continuous", "-w", is_flag=True, help="Run continuously in background polling mode")
@click.option("--interval", "-i", type=int, default=60, help="Polling interval in seconds for continuous mode (default: 60)")
@click.option("--idle", is_flag=True, help="Use RFC 2177 IMAP IDLE for real-time push notifications")
def sync_command(config, verbose, debug, dry_run, continuous, interval, idle):
    """Execute a synchronization run across all active email providers."""
    import logging
    import time
    log_level = logging.DEBUG if debug else (logging.INFO if verbose else logging.WARNING)
    logging.basicConfig(level=log_level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    cfg_path = Path(config) if config else None
    settings = get_settings(cfg_path)
    engine = EmailIngestionEngine(settings)

    if continuous:
        mode_desc = "real-time IMAP IDLE + polling" if idle else f"interval: {interval}s"
        click.secho(f"\n[INFO] Starting continuous watcher ({mode_desc}). Press Ctrl+C to stop.", fg="cyan", bold=True)
        cycle = 1
        try:
            while True:
                now_str = time.strftime("%Y-%m-%d %H:%M:%S")
                click.echo(f"[{now_str}] Cycle #{cycle}: Scanning mailboxes...")
                metrics = engine.run_sync(dry_run=dry_run)
                if metrics["messages_processed"] > 0:
                    click.secho(
                        f"  -> Processed {metrics['messages_processed']} email(s), "
                        f"downloaded {metrics['attachments_downloaded']} attachment(s), "
                        f"quarantined {metrics['quarantined']} threat(s).",
                        fg="green", bold=True
                    )
                else:
                    click.echo("  -> No new messages found.")
                cycle += 1

                # Check if IMAP IDLE can be used for zero-delay notification
                waited_via_idle = False
                if idle:
                    for conn in engine.connectors:
                        from email_ingestion.connectors.imap_connector import IMAPConnector
                        if isinstance(conn, IMAPConnector) and conn.supports_idle():
                            click.echo(f"  [IDLE] Awaiting instant push notification from {conn.host} (max {interval}s)...")
                            conn.idle_wait(timeout=interval)
                            waited_via_idle = True
                            break

                if not waited_via_idle:
                    time.sleep(interval)
        except KeyboardInterrupt:
            click.secho("\n[INFO] Continuous synchronization stopped cleanly by user.", fg="yellow", bold=True)
            return

    if dry_run:
        click.secho("[DRY-RUN] Starting simulated email synchronization...", fg="yellow", bold=True)
    else:
        click.secho("Starting email synchronization...", fg="cyan", bold=True)

    metrics = engine.run_sync(dry_run=dry_run)

    click.secho("\n--- Synchronization Summary ---", fg="green", bold=True)
    click.echo(f"  Messages Processed:     {metrics['messages_processed']}")
    click.echo(f"  Attachments Downloaded: {metrics['attachments_downloaded']}")
    click.echo(f"  Files Quarantined:      {metrics['quarantined']}")
    if dry_run:
        click.secho("  Mode: DRY RUN (No changes written to disk or ledger)", fg="yellow")


@cli.command("watch")
@click.option("--config", "-c", type=click.Path(exists=True), help="Path to custom config.yaml")
@click.option("--interval", "-i", type=int, default=60, help="Polling interval in seconds (default: 60)")
@click.option("--idle", is_flag=True, help="Use RFC 2177 IMAP IDLE for real-time push notifications")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose informational logging")
@click.pass_context
def watch_command(ctx, config, interval, idle, verbose):
    """Run continuous background synchronization (alias for 'sync --continuous')."""
    ctx.invoke(sync_command, config=config, verbose=verbose, debug=False, dry_run=False, continuous=True, interval=interval, idle=idle)


@cli.command("configure")
@click.option("--config", "-c", default="config.yaml", help="Path to configuration file to create/update")
def configure_command(config):
    """Interactive setup wizard to configure mailboxes (Gmail, IMAP, Outlook)."""
    import yaml
    click.secho("\n=== Enterprise Email Ingestion - Configuration Wizard ===", fg="cyan", bold=True)
    click.echo("Easily configure your email credentials and preferences.\n")

    click.echo("Select your email connection provider:")
    click.echo("  1) Standard IMAP / SSL (Gmail App Password, Outlook, Corporate Mail)")
    click.echo("  2) Offline Mock Scenarios (Local testing & demo)")
    choice = click.prompt("Enter choice", type=click.Choice(["1", "2"]), default="1")

    cfg_file = Path(config)
    existing_cfg = {}
    if cfg_file.exists():
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                existing_cfg = yaml.safe_load(f) or {}
        except Exception:
            existing_cfg = {}

    if choice == "1":
        host = click.prompt("IMAP Server Host", default="imap.gmail.com")
        port = click.prompt("IMAP Port", default=993, type=int)
        username = click.prompt("Email Address / Username")
        password = click.prompt("Password or App Password (hidden)", hide_input=True)

        click.echo("\nVerifying connection credentials over TLS...")
        from email_ingestion.connectors.imap_connector import IMAPConnector
        test_conn = IMAPConnector(host=host, port=port, username=username, password=password)
        connected = test_conn.connect()
        if connected:
            click.secho("  [PASS] Successfully connected and authenticated!", fg="green", bold=True)
            test_conn.disconnect()
        else:
            click.secho("  [WARN] Could not connect with provided credentials.", fg="yellow", bold=True)
            if "gmail.com" in host.lower():
                click.echo("  Tip for Gmail: Ensure you are using a 16-character 'App Password'")
                click.echo("  (Google Account -> Security -> 2-Step Verification -> App Passwords).")
            if not click.confirm("Save configuration anyway?", default=True):
                click.echo("Aborted.")
                return

        existing_cfg.setdefault("imap", {})
        existing_cfg["imap"]["enabled"] = True
        existing_cfg["imap"]["host"] = host
        existing_cfg["imap"]["port"] = port
        existing_cfg["imap"]["username"] = username
        existing_cfg["imap"]["password"] = password
        existing_cfg["imap"]["mailbox"] = "INBOX"
        existing_cfg["imap"]["use_ssl"] = True

        existing_cfg.setdefault("mock_provider", {})
        existing_cfg["mock_provider"]["enabled"] = False
    else:
        existing_cfg.setdefault("mock_provider", {})
        existing_cfg["mock_provider"]["enabled"] = True
        if "imap" in existing_cfg:
            existing_cfg["imap"]["enabled"] = False
        click.secho("  Configured for offline Mock Demonstration mode.", fg="green")

    with open(cfg_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(existing_cfg, f, sort_keys=False)

    click.secho(f"\n[OK] Configuration successfully saved to '{config}'!", fg="green", bold=True)
    click.echo("Next steps:")
    click.echo("  email-ingestion test-connection  # Test server connectivity")
    click.echo("  email-ingestion sync             # Ingest unread emails once")
    click.echo("  email-ingestion watch            # Run autonomous background watcher")


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
    settings.database.db_url = "sqlite:///:memory:"
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


@cli.command("validate")
@click.option("--config", "-c", type=click.Path(exists=True), help="Path to custom config.yaml")
def validate_command(config):
    """Validate system configuration, database connectivity, and filesystem permissions."""
    click.secho("\n=== Running System Health & Configuration Validation ===", fg="cyan", bold=True)
    all_passed = True
    cfg_path = Path(config) if config else None

    # 1. Configuration Validation
    try:
        settings = get_settings(cfg_path)
        click.secho("  [PASS] Configuration syntax and Pydantic schema validation", fg="green")
    except Exception as e:
        click.secho(f"  [FAIL] Configuration error: {e}", fg="red")
        all_passed = False
        return

    # 2. Database Connectivity & Pragmas
    try:
        db = DatabaseManager(settings.database.db_url)
        with db.session() as s:
            from email_ingestion.database.models import Message
            s.query(Message).first()
        db.checkpoint(mode="PASSIVE")
        click.secho(f"  [PASS] Database connectivity ({settings.database.db_url}) and WAL mode", fg="green")
    except Exception as e:
        click.secho(f"  [FAIL] Database initialization failed: {e}", fg="red")
        all_passed = False

    # 3. Filesystem Permissions
    for dir_name, target_dir in [
        ("Download root", settings.storage.download_dir),
        ("Staging directory", settings.storage.staging_dir),
        ("Quarantine directory", settings.storage.quarantine_dir)
    ]:
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            test_file = target_dir / ".perm_check.tmp"
            test_file.write_bytes(b"test")
            test_file.unlink()
            click.secho(f"  [PASS] {dir_name} is writable: {target_dir}", fg="green")
        except Exception as e:
            click.secho(f"  [FAIL] {dir_name} write failure ({target_dir}): {e}", fg="red")
            all_passed = False

    if all_passed:
        click.secho("\n[SUCCESS] All preflight configuration and environment checks passed!", fg="green", bold=True)
    else:
        click.secho("\n[ERROR] One or more configuration checks failed.", fg="red", bold=True)
        raise click.Abort()


@cli.command("test-connection")
@click.option("--config", "-c", type=click.Path(exists=True), help="Path to custom config.yaml")
def test_connection_command(config):
    """Test authentication and connectivity to configured email mailboxes without downloading."""
    click.secho("\n=== Testing Active Mailbox Connectors ===", fg="cyan", bold=True)
    cfg_path = Path(config) if config else None
    settings = get_settings(cfg_path)
    engine = EmailIngestionEngine(settings)

    if not engine.connectors:
        click.secho("  [WARN] No connectors enabled or configured in settings.", fg="yellow")
        return

    for connector in engine.connectors:
        click.echo(f"  Testing connection to provider: {connector.provider_name}...")
        try:
            is_connected = connector.connect()
            if is_connected:
                click.secho(f"  [PASS] Connected successfully to {connector.provider_name}", fg="green", bold=True)
            else:
                click.secho(f"  [FAIL] Could not establish connection to {connector.provider_name}", fg="red", bold=True)
        except Exception as err:
            click.secho(f"  [FAIL] Error connecting to {connector.provider_name}: {err}", fg="red")


@cli.command("search")
@click.argument("query", default="")
@click.option("--sender", "-s", default=None, help="Filter by sender email address")
@click.option("--status", type=click.Choice(["CLEAN", "QUARANTINED"], case_sensitive=False), default=None, help="Filter by file status")
@click.option("--revisions-only", "-r", is_flag=True, help="Show only document revisions (v2+)")
@click.option("--limit", "-n", default=25, help="Maximum number of results to display (default: 25)")
@click.option("--config", "-c", type=click.Path(exists=True), help="Path to custom config.yaml")
def search_command(query, sender, status, revisions_only, limit, config):
    """Search ingested attachments and email contexts by filename, sender, subject, or hash."""
    cfg_path = Path(config) if config else None
    settings = get_settings(cfg_path)
    db = DatabaseManager(settings.database.db_url)

    results = db.search_records(
        query=query,
        sender=sender,
        status=status,
        revisions_only=revisions_only,
        limit=limit
    )

    click.secho(f"\n=== Search Results ({len(results)} found) ===", fg="cyan", bold=True)
    if not results:
        click.echo("  No matching records found.")
        return

    for idx, r in enumerate(results, 1):
        color = "green" if r["status"] == "CLEAN" else "red"
        ver_str = f" [v{r['version_number']}]" if r["version_number"] > 1 else ""
        click.secho(f"{idx}. {r['filename']}{ver_str}", fg=color, bold=True)
        click.echo(f"   Sender:   {r['sender']} ({r['sender_name'] or 'N/A'})")
        click.echo(f"   Subject:  {r['subject'] or '(No Subject)'}")
        click.echo(f"   Received: {r['received_at']}")
        size_kb = r['size_bytes'] / 1024.0
        click.echo(f"   Size:     {size_kb:.1f} KB | Status: {r['status']}")
        click.echo(f"   Path:     {r['local_storage_path']}")
        if r["quarantine_reason"]:
            click.secho(f"   Threat:   {r['quarantine_reason']}", fg="yellow")
        click.echo("")


@cli.command("stats")
@click.option("--config", "-c", type=click.Path(exists=True), help="Path to custom config.yaml")
def stats_command(config):
    """Display comprehensive gateway analytics, storage consumption, and sender statistics."""
    cfg_path = Path(config) if config else None
    settings = get_settings(cfg_path)
    db = DatabaseManager(settings.database.db_url)

    stats = db.get_storage_statistics()

    total_bytes = stats["total_bytes"]
    if total_bytes >= 1048576:
        size_str = f"{total_bytes / 1048576:.2f} MB"
    elif total_bytes >= 1024:
        size_str = f"{total_bytes / 1024:.1f} KB"
    else:
        size_str = f"{total_bytes} B"

    total_att = stats["total_attachments"]
    clean_pct = (stats["clean_count"] / total_att * 100) if total_att > 0 else 100.0

    click.secho("\n==================================================", fg="cyan", bold=True)
    click.secho("    ENTERPRISE GATEWAY OPERATIONAL ANALYTICS     ", fg="cyan", bold=True)
    click.secho("==================================================", fg="cyan", bold=True)
    click.echo(f"  Total Ingested Emails:     {stats['total_messages']:,}")
    click.echo(f"  Total Tracked Attachments: {stats['total_attachments']:,}")
    click.secho(f"  Clean Approved Files:      {stats['clean_count']:,} ({clean_pct:.1f}%)", fg="green")
    click.secho(f"  Quarantined Threats:       {stats['quarantine_count']:,}", fg="red" if stats['quarantine_count'] > 0 else "white")
    click.echo(f"  Document Revisions (v2+):  {stats['revision_count']:,}")
    click.echo(f"  Total Storage Footprint:   {size_str}")

    if stats["top_senders"]:
        click.secho("\n--- Top Senders by Attachment Volume ---", fg="yellow", bold=True)
        for s in stats["top_senders"]:
            s_bytes = s["size_bytes"]
            s_size = f"{s_bytes / 1024:.1f} KB" if s_bytes < 1048576 else f"{s_bytes / 1048576:.2f} MB"
            click.echo(f"  • {s['sender']}: {s['file_count']} files ({s_size})")

    if stats["top_mimes"]:
        click.secho("\n--- File / MIME Type Distribution ---", fg="magenta", bold=True)
        for m in stats["top_mimes"]:
            click.echo(f"  • {m['mime_type']}: {m['count']} files")
    click.echo("")


@cli.command("serve")
@click.option("--port", "-p", default=8080, help="Port to listen on (default: 8080)")
@click.option("--bind", "-b", default="127.0.0.1", help="Network address to bind (default: 127.0.0.1)")
@click.option("--no-browse", is_flag=True, help="Do not automatically open web browser")
@click.option("--config", "-c", type=click.Path(exists=True), help="Path to custom config.yaml")
def serve_command(port, bind, no_browse, config):
    """Launch local web server to browse the interactive attachment catalog in a browser."""
    import http.server
    import socketserver
    import webbrowser
    import os

    cfg_path = Path(config) if config else None
    settings = get_settings(cfg_path)
    root_dir = settings.storage.download_dir.resolve()

    if not root_dir.exists():
        root_dir.mkdir(parents=True, exist_ok=True)

    prev_cwd = os.getcwd()
    os.chdir(str(root_dir))
    handler = http.server.SimpleHTTPRequestHandler

    click.secho("\n=== Serving Interactive Attachment Catalog ===", fg="cyan", bold=True)
    click.echo(f"  Root Directory: {root_dir}")
    click.secho(f"  URL:            http://{bind}:{port}/index.html", fg="green", bold=True)
    click.echo("  Press Ctrl+C to stop the server.\n")

    if not no_browse:
        try:
            webbrowser.open(f"http://{bind}:{port}/index.html")
        except Exception:
            pass

    try:
        with socketserver.TCPServer((bind, port), handler) as httpd:
            httpd.serve_forever()
    except KeyboardInterrupt:
        click.secho("\nServer stopped cleanly.", fg="yellow")
    finally:
        os.chdir(prev_cwd)


@cli.command("export")
@click.option("--format", "-f", "export_format", type=click.Choice(["csv", "json", "zip"], case_sensitive=False), default="csv", help="Export format (csv, json, zip)")
@click.option("--output", "-o", type=click.Path(), required=False, help="Destination file path for export")
@click.option("--sender", "-s", default=None, help="Filter by sender email address")
@click.option("--config", "-c", type=click.Path(exists=True), help="Path to custom config.yaml")
def export_command(export_format, output, sender, config):
    """Export download catalog ledger to CSV/JSON or package clean files into a ZIP archive."""
    import csv
    import json
    import zipfile

    cfg_path = Path(config) if config else None
    settings = get_settings(cfg_path)
    db = DatabaseManager(settings.database.db_url)

    records = db.search_records(sender=sender, limit=10000)
    if not records:
        click.secho("[INFO] No records found to export.", fg="yellow")
        return

    default_name = f"attachment_export_{export_format.lower()}"
    if export_format == "csv":
        out_path = Path(output) if output else Path(f"{default_name}.csv")
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Received At", "Sender Email", "Sender Name", "Subject", "Filename", "Size (Bytes)", "Status", "Version", "SHA-256", "Storage Path"])
            for r in records:
                writer.writerow([
                    r["received_at"], r["sender"], r["sender_name"] or "", r["subject"] or "",
                    r["filename"], r["size_bytes"], r["status"], r["version_number"], r["sha256"], r["local_storage_path"]
                ])
        click.secho(f"[OK] Exported {len(records)} records to CSV: {out_path.resolve()}", fg="green", bold=True)

    elif export_format == "json":
        out_path = Path(output) if output else Path(f"{default_name}.json")
        serialized = []
        for r in records:
            item = dict(r)
            if item.get("received_at"):
                item["received_at"] = str(item["received_at"])
            serialized.append(item)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(serialized, f, indent=2)
        click.secho(f"[OK] Exported {len(records)} records to JSON: {out_path.resolve()}", fg="green", bold=True)

    elif export_format == "zip":
        out_path = Path(output) if output else Path(f"{default_name}.zip")
        packaged_count = 0
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for r in records:
                if r["status"] == "CLEAN":
                    file_path = Path(r["local_storage_path"])
                    if file_path.exists():
                        arc_name = f"{r['sender']}/{r['filename']}"
                        zf.write(file_path, arc_name)
                        packaged_count += 1
        click.secho(f"[OK] Packaged {packaged_count} clean attachments into ZIP archive: {out_path.resolve()}", fg="green", bold=True)


if __name__ == "__main__":
    cli()
