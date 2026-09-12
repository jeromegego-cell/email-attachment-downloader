"""Storage layout and directory organization manager.

Enforces the standardized corporate folder hierarchy:
Auto_download_email/<sanitized_sender>/<timestamp>_<hash_prefix>/
"""

import hashlib
import html
import os
import re
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple, List, Dict, Any


class StorageLayoutManager:
    """Manages the disk directory layout for downloaded email attachments and sidecars."""

    def __init__(self, root_dir: Path = Path("Auto_download_email")):
        self.root_dir = Path(root_dir)

    def sanitize_sender_folder(self, sender_email: str) -> str:
        """Convert an email address into a safe folder name.
        
        Example: 'john.doe@company.com' -> 'john.doe_company.com'
        """
        # Strip brackets if present (e.g., '<john@example.com>')
        clean_email = sender_email.strip("<> \t\r\n").lower()
        # Replace '@' with '_'
        sanitized = clean_email.replace("@", "_")
        # Strip any characters that are not alphanumeric, underscore, period, or hyphen
        sanitized = re.sub(r"[^\w\.-]", "_", sanitized)
        sanitized = sanitized.strip(". ")
        return sanitized or "unknown_sender"

    def format_delivery_folder_name(
        self,
        received_at: datetime,
        message_id: str
    ) -> str:
        """Create a collision-proof delivery envelope folder name.
        
        Example: '2026-09-11_13-15-00_3a8f9c12'
        """
        timestamp_str = received_at.strftime("%Y-%m-%d_%H-%M-%S")
        micro = f"_{received_at.microsecond:06d}" if getattr(received_at, "microsecond", 0) else ""
        msg_hash = hashlib.sha256(str(message_id).encode("utf-8", errors="ignore")).hexdigest()[:8]
        return f"{timestamp_str}{micro}_{msg_hash}"

    def get_envelope_directory(
        self,
        sender_email: str,
        received_at: datetime,
        message_id: str
    ) -> Path:
        """Return the absolute path to the delivery envelope folder, creating parents if needed."""
        sender_dir = self.sanitize_sender_folder(sender_email)
        envelope_name = self.format_delivery_folder_name(received_at, message_id)
        
        envelope_path = self.root_dir / sender_dir / envelope_name
        envelope_path.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.root_dir, 0o700)
            os.chmod(self.root_dir / sender_dir, 0o700)
            os.chmod(envelope_path, 0o700)
        except OSError:
            pass
        return envelope_path

    def update_master_index(self, entries: list) -> Path:
        """Generate/update an orderly, sorted master index in the root download directory.
        
        Allows anyone opening the root folder to immediately view and access all downloads chronologically.
        """
        self.root_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.root_dir, 0o700)
        except OSError:
            pass

        index_file = self.root_dir / "INDEX.md"
        temp_index = self.root_dir / ".tmp_INDEX.md"

        sorted_entries = sorted(entries, key=lambda x: str(x.get("received_at", "")), reverse=True)

        total_count = len(sorted_entries)
        clean_count = sum(1 for e in sorted_entries if e.get("status") == "CLEAN")
        quarantine_count = sum(1 for e in sorted_entries if e.get("status") == "QUARANTINED")
        revision_count = sum(1 for e in sorted_entries if e.get("version_number", 1) > 1)
        total_bytes = sum(e.get("size_bytes", 0) for e in sorted_entries)
        if total_bytes >= 1048576:
            total_size_str = f"{total_bytes / 1048576:.2f} MB"
        elif total_bytes >= 1024:
            total_size_str = f"{total_bytes / 1024:.1f} KB"
        else:
            total_size_str = f"{total_bytes} B"

        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        lines = [
            "# Master Attachment Index",
            "",
            "All downloaded email attachments organized in chronological order.",
            "",
            "## 📊 Gateway Executive Summary",
            "| Total Files Tracked | Clean Downloads | Quarantined Threats | Document Revisions | Storage Consumed | Last Refreshed (UTC) |",
            "| :---: | :---: | :---: | :---: | :---: | :---: |",
            f"| **{total_count}** | {clean_count} | {quarantine_count} | {revision_count} | {total_size_str} | `{now_utc}` |",
            "",
        ]

        # Sender Quick-Jump Table
        sender_groups = {}
        for e in sorted_entries:
            s = str(e.get("sender", "unknown")).strip()
            status = e.get("status", "CLEAN")
            if s not in sender_groups:
                sender_groups[s] = {"count": 0, "quarantined": 0}
            sender_groups[s]["count"] += 1
            if status == "QUARANTINED":
                sender_groups[s]["quarantined"] += 1

        if sender_groups:
            lines.append("## 📁 Sender Directory Quick-Jump")
            lines.append("| Sender | Ingested Files | Health Status | Direct Folder Link |")
            lines.append("| :--- | :---: | :---: | :--- |")
            for s, stats in sender_groups.items():
                sender_dir = self.sanitize_sender_folder(s)
                if stats["quarantined"] > 0:
                    health = f"⚠️ {stats['quarantined']} Quarantined"
                    link = f"[Inspect Vault](./quarantine/) · [Sender Folder](./{urllib.parse.quote(sender_dir)}/)"
                else:
                    health = "✅ CLEAN"
                    link = f"[Open Folder](./{urllib.parse.quote(sender_dir)}/)"
                escaped_s = s.replace("|", "\\|")
                lines.append(f"| `{escaped_s}` | {stats['count']} | {health} | {link} |")
            lines.append("")

        lines.append("## 📜 Chronological Download Ledger")
        lines.append("| Received Date (UTC) | Sender | Filename | Size | Status | Direct Access |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")

        for e in sorted_entries:
            rec_date = str(e.get("received_at", "N/A"))
            sender = str(e.get("sender", "unknown")).replace("|", "\\|").replace("\n", " ")
            fname = str(e.get("filename", "unknown")).replace("|", "\\|").replace("\n", " ")
            size_b = e.get("size_bytes", 0)
            size_str = f"{size_b / 1024:.1f} KB" if size_b >= 1024 else f"{size_b} B"
            status = e.get("status", "CLEAN")
            
            raw_path_str = str(e.get("local_storage_path", e.get("relative_path", "")))
            local_path = Path(raw_path_str)
            try:
                rel_path = local_path.relative_to(self.root_dir)
            except ValueError:
                if raw_path_str.startswith(str(self.root_dir)):
                    rel_path = Path(raw_path_str[len(str(self.root_dir)):].lstrip("/\\"))
                else:
                    rel_path = local_path

            envelope_dir = Path(rel_path).parent
            sidecar_file = self.root_dir / envelope_dir / "email_context.md"

            quoted_rel_path = urllib.parse.quote(rel_path.as_posix())
            quoted_env_dir = urllib.parse.quote(envelope_dir.as_posix())

            if status == "QUARANTINED":
                report_name = f"{Path(rel_path).stem}.report.md"
                report_file = self.root_dir / "quarantine" / report_name
                if report_file.exists():
                    access_links = f"[Report](./quarantine/{urllib.parse.quote(report_name)}) · [Download](./{quoted_rel_path})"
                else:
                    access_links = f"[Download](./{quoted_rel_path})"
            else:
                sidecar_link = f" · [Context](./{quoted_env_dir}/email_context.md)" if sidecar_file.exists() else ""
                access_links = f"[Download](./{quoted_rel_path}){sidecar_link}"

            lines.append(f"| {rec_date} | `{sender}` | **{fname}** | {size_str} | {status} | {access_links} |")

        lines.append("")
        content = "\n".join(lines)

        # Atomic file write for markdown index to prevent corrupt partial writes
        temp_index.write_text(content, encoding="utf-8")
        try:
            os.chmod(temp_index, 0o600)
        except OSError:
            pass
        os.replace(temp_index, index_file)

        # Generate companion interactive HTML web dashboard
        try:
            html_content = self._generate_interactive_html(
                sorted_entries=sorted_entries,
                total_count=total_count,
                clean_count=clean_count,
                quarantine_count=quarantine_count,
                revision_count=revision_count,
                total_size_str=total_size_str,
                now_utc=now_utc,
                sender_groups=sender_groups
            )
            html_file = self.root_dir / "index.html"
            temp_html = self.root_dir / ".tmp_index.html"
            temp_html.write_text(html_content, encoding="utf-8")
            try:
                os.chmod(temp_html, 0o600)
            except OSError:
                pass
            os.replace(temp_html, html_file)
        except Exception as html_err:
            pass

        return index_file

    def _generate_interactive_html(
        self,
        sorted_entries: list,
        total_count: int,
        clean_count: int,
        quarantine_count: int,
        revision_count: int,
        total_size_str: str,
        now_utc: str,
        sender_groups: dict
    ) -> str:
        """Render a self-contained, responsive HTML5 dashboard with real-time search and filtering."""
        sender_chips_html = []
        for s, stats in sender_groups.items():
            sender_dir = self.sanitize_sender_folder(s)
            esc_s = html.escape(s)
            badge_cls = "badge-danger" if stats["quarantined"] > 0 else "badge-clean"
            sender_chips_html.append(
                f'<button class="sender-chip" onclick="filterBySender(\'{esc_s}\')">'
                f'<span>{esc_s}</span> '
                f'<span class="chip-count {badge_cls}">{stats["count"]}</span>'
                f'</button>'
            )
        sender_chips_str = "".join(sender_chips_html)

        rows_html = []
        for e in sorted_entries:
            rec_date = html.escape(str(e.get("received_at", "N/A")))
            sender = html.escape(str(e.get("sender", "unknown")))
            fname = html.escape(str(e.get("filename", "unknown")))
            size_b = e.get("size_bytes", 0)
            size_str = f"{size_b / 1024:.1f} KB" if size_b >= 1024 else f"{size_b} B"
            status = e.get("status", "CLEAN")
            version = e.get("version_number", 1)

            raw_path_str = str(e.get("local_storage_path", e.get("relative_path", "")))
            local_path = Path(raw_path_str)
            try:
                rel_path = local_path.relative_to(self.root_dir)
            except ValueError:
                if raw_path_str.startswith(str(self.root_dir)):
                    rel_path = Path(raw_path_str[len(str(self.root_dir)):].lstrip("/\\"))
                else:
                    rel_path = local_path

            envelope_dir = Path(rel_path).parent
            sidecar_file = self.root_dir / envelope_dir / "email_context.md"

            quoted_rel_path = urllib.parse.quote(rel_path.as_posix())
            quoted_env_dir = urllib.parse.quote(envelope_dir.as_posix())

            if status == "QUARANTINED":
                status_badge = '<span class="badge badge-danger">⚠️ QUARANTINED</span>'
                report_name = f"{Path(rel_path).stem}.report.md"
                report_file = self.root_dir / "quarantine" / report_name
                report_link = f'<a class="btn btn-danger" href="./quarantine/{urllib.parse.quote(report_name)}">Threat Report</a> ' if report_file.exists() else ''
                actions = f'{report_link}<a class="btn btn-secondary" href="./{quoted_rel_path}">Raw File</a>'
                row_type = "QUARANTINED"
            else:
                status_badge = '<span class="badge badge-clean">✅ CLEAN</span>'
                context_link = f'<a class="btn btn-secondary" href="./{quoted_env_dir}/email_context.md">Context</a> ' if sidecar_file.exists() else ''
                actions = f'<a class="btn btn-primary" href="./{quoted_rel_path}">Download</a> {context_link}'
                row_type = "CLEAN"

            ver_badge = f' <span class="badge badge-version">v{version}</span>' if version > 1 else ''
            if version > 1:
                row_type += " REVISION"

            search_blob = f"{rec_date} {sender} {fname} {status}".lower()

            rows_html.append(
                f'<tr data-sender="{sender}" data-status="{row_type}" data-search="{html.escape(search_blob)}">'
                f'<td><code>{rec_date}</code></td>'
                f'<td><span class="sender-cell">{sender}</span></td>'
                f'<td><strong>{fname}</strong>{ver_badge}</td>'
                f'<td>{size_str}</td>'
                f'<td>{status_badge}</td>'
                f'<td class="actions-cell">{actions}</td>'
                f'</tr>'
            )

        table_rows_str = "\n".join(rows_html)

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Enterprise Email Ingestion Gateway - Master Catalog</title>
<style>
  :root {{
    --bg: #0f172a;
    --card-bg: #1e293b;
    --card-border: #334155;
    --text: #f8fafc;
    --text-muted: #94a3b8;
    --primary: #38bdf8;
    --primary-hover: #0284c7;
    --success: #34d399;
    --danger: #f87171;
    --warning: #fbbf24;
    --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }}
  @media (prefers-color-scheme: light) {{
    :root {{
      --bg: #f8fafc;
      --card-bg: #ffffff;
      --card-border: #e2e8f0;
      --text: #0f172a;
      --text-muted: #64748b;
      --primary: #0284c7;
      --primary-hover: #0369a1;
      --success: #059669;
      --danger: #dc2626;
      --warning: #d97706;
    }}
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: var(--font); background: var(--bg); color: var(--text); padding: 2rem; line-height: 1.5; }}
  .container {{ max-width: 1300px; margin: 0 auto; }}
  header {{ margin-bottom: 2rem; }}
  h1 {{ font-size: 1.875rem; font-weight: 700; margin-bottom: 0.5rem; display: flex; align-items: center; gap: 0.75rem; }}
  p.subtitle {{ color: var(--text-muted); font-size: 1rem; }}
  .metrics-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 2rem; }}
  .card {{ background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 0.75rem; padding: 1.25rem; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
  .card-label {{ font-size: 0.825rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); margin-bottom: 0.5rem; }}
  .card-val {{ font-size: 1.75rem; font-weight: 700; }}
  .val-clean {{ color: var(--success); }}
  .val-danger {{ color: var(--danger); }}
  .val-warning {{ color: var(--warning); }}
  .controls-bar {{ display: flex; flex-wrap: wrap; gap: 1rem; align-items: center; justify-content: space-between; margin-bottom: 1.5rem; }}
  .search-box {{ flex: 1; min-width: 280px; position: relative; }}
  .search-box input {{ width: 100%; padding: 0.75rem 1rem; border-radius: 0.5rem; border: 1px solid var(--card-border); background: var(--card-bg); color: var(--text); font-size: 0.95rem; outline: none; }}
  .search-box input:focus {{ border-color: var(--primary); }}
  .filter-tabs {{ display: flex; gap: 0.5rem; }}
  .tab-btn {{ padding: 0.6rem 1rem; border-radius: 0.5rem; border: 1px solid var(--card-border); background: var(--card-bg); color: var(--text); cursor: pointer; font-size: 0.875rem; font-weight: 500; transition: all 0.2s; }}
  .tab-btn.active {{ background: var(--primary); color: #fff; border-color: var(--primary); }}
  .sender-chips-container {{ display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 1.5rem; align-items: center; }}
  .sender-chips-label {{ font-size: 0.85rem; font-weight: 600; color: var(--text-muted); }}
  .sender-chip {{ display: inline-flex; align-items: center; gap: 0.5rem; padding: 0.35rem 0.75rem; border-radius: 9999px; border: 1px solid var(--card-border); background: var(--card-bg); color: var(--text); font-size: 0.825rem; cursor: pointer; }}
  .sender-chip:hover {{ border-color: var(--primary); }}
  .chip-count {{ font-size: 0.75rem; padding: 0.1rem 0.4rem; border-radius: 9999px; font-weight: 600; }}
  .badge {{ display: inline-block; padding: 0.2rem 0.55rem; border-radius: 0.375rem; font-size: 0.75rem; font-weight: 600; text-transform: uppercase; }}
  .badge-clean {{ background: rgba(52, 211, 153, 0.15); color: var(--success); border: 1px solid rgba(52, 211, 153, 0.3); }}
  .badge-danger {{ background: rgba(248, 113, 113, 0.15); color: var(--danger); border: 1px solid rgba(248, 113, 113, 0.3); }}
  .badge-version {{ background: rgba(251, 191, 36, 0.15); color: var(--warning); border: 1px solid rgba(251, 191, 36, 0.3); }}
  table {{ width: 100%; border-collapse: collapse; background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 0.75rem; overflow: hidden; }}
  th, td {{ padding: 1rem 1.25rem; text-align: left; border-bottom: 1px solid var(--card-border); font-size: 0.9rem; }}
  th {{ background: rgba(0,0,0,0.1); font-weight: 600; color: var(--text-muted); text-transform: uppercase; font-size: 0.75rem; letter-spacing: 0.05em; }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: rgba(255,255,255,0.02); }}
  .actions-cell {{ white-space: nowrap; }}
  .btn {{ display: inline-block; padding: 0.35rem 0.75rem; border-radius: 0.375rem; font-size: 0.8rem; font-weight: 600; text-decoration: none; margin-right: 0.35rem; transition: background 0.2s; }}
  .btn-primary {{ background: var(--primary); color: #fff; }}
  .btn-primary:hover {{ background: var(--primary-hover); }}
  .btn-secondary {{ background: transparent; color: var(--text); border: 1px solid var(--card-border); }}
  .btn-secondary:hover {{ border-color: var(--primary); color: var(--primary); }}
  .btn-danger {{ background: rgba(248, 113, 113, 0.2); color: var(--danger); border: 1px solid rgba(248, 113, 113, 0.4); }}
  .btn-danger:hover {{ background: var(--danger); color: #fff; }}
  code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 0.85em; opacity: 0.9; }}
  .footer {{ margin-top: 2rem; text-align: center; color: var(--text-muted); font-size: 0.825rem; }}
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>📥 Master Attachment Catalog</h1>
    <p class="subtitle">Orderly chronological ledger and security-verified archive of all ingested email attachments.</p>
  </header>

  <div class="metrics-grid">
    <div class="card">
      <div class="card-label">Total Files Tracked</div>
      <div class="card-val">{total_count}</div>
    </div>
    <div class="card">
      <div class="card-label">Clean Downloads</div>
      <div class="card-val val-clean">{clean_count}</div>
    </div>
    <div class="card">
      <div class="card-label">Quarantined Threats</div>
      <div class="card-val val-danger">{quarantine_count}</div>
    </div>
    <div class="card">
      <div class="card-label">Document Revisions</div>
      <div class="card-val val-warning">{revision_count}</div>
    </div>
    <div class="card">
      <div class="card-label">Storage Consumed</div>
      <div class="card-val">{total_size_str}</div>
    </div>
  </div>

  <div class="controls-bar">
    <div class="search-box">
      <input type="text" id="searchInput" placeholder="Live search by filename, sender, date, hash..." onkeyup="applyFilters()">
    </div>
    <div class="filter-tabs">
      <button class="tab-btn active" data-tab="ALL" onclick="setTab('ALL', this)">All ({total_count})</button>
      <button class="tab-btn" data-tab="CLEAN" onclick="setTab('CLEAN', this)">Clean ({clean_count})</button>
      <button class="tab-btn" data-tab="QUARANTINED" onclick="setTab('QUARANTINED', this)">Threats ({quarantine_count})</button>
      <button class="tab-btn" data-tab="REVISION" onclick="setTab('REVISION', this)">Revisions ({revision_count})</button>
    </div>
  </div>

  {f'<div class="sender-chips-container"><span class="sender-chips-label">Senders:</span><button class="sender-chip" onclick="clearSenderFilter()"><span>Show All</span></button>{sender_chips_str}</div>' if sender_chips_str else ''}

  <div style="overflow-x: auto; border-radius: 0.75rem;">
    <table id="attachmentsTable">
      <thead>
        <tr>
          <th>Received Date (UTC)</th>
          <th>Sender</th>
          <th>Filename & Version</th>
          <th>Size</th>
          <th>Status</th>
          <th>Direct Access</th>
        </tr>
      </thead>
      <tbody id="tableBody">
        {table_rows_str}
      </tbody>
    </table>
  </div>

  <div class="footer">
    Last Refreshed: {now_utc} · Enterprise Email Ingestion Gateway
  </div>
</div>

<script>
  let currentTab = 'ALL';
  let currentSender = '';

  function setTab(tab, btn) {{
    currentTab = tab;
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    applyFilters();
  }}

  function filterBySender(sender) {{
    currentSender = sender.toLowerCase();
    applyFilters();
  }}

  function clearSenderFilter() {{
    currentSender = '';
    applyFilters();
  }}

  function applyFilters() {{
    const query = document.getElementById('searchInput').value.toLowerCase().trim();
    const rows = document.querySelectorAll('#tableBody tr');

    rows.forEach(row => {{
      const searchBlob = (row.getAttribute('data-search') || '').toLowerCase();
      const rowStatus = row.getAttribute('data-status') || '';
      const rowSender = (row.getAttribute('data-sender') || '').toLowerCase();

      let matchesSearch = !query || searchBlob.includes(query);
      let matchesSender = !currentSender || rowSender.includes(currentSender);
      let matchesTab = true;

      if (currentTab === 'CLEAN') {{
        matchesTab = rowStatus.includes('CLEAN');
      }} else if (currentTab === 'QUARANTINED') {{
        matchesTab = rowStatus.includes('QUARANTINED');
      }} else if (currentTab === 'REVISION') {{
        matchesTab = rowStatus.includes('REVISION');
      }}

      if (matchesSearch && matchesSender && matchesTab) {{
        row.style.display = '';
      }} else {{
        row.style.display = 'none';
      }}
    }});
  }}
</script>
</body>
</html>
"""

