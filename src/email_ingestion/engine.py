"""Main ingestion orchestrator engine.

Coordinates connectors, security checks, duplicate anomaly detection,
document similarity versioning, context sidecars, atomic writes, and
ACID state ledger persistence.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any

from email_ingestion.config import EngineSettings, get_settings
from email_ingestion.database.session import DatabaseManager
from email_ingestion.database.models import Message, Attachment, Account
from email_ingestion.storage.layout_manager import StorageLayoutManager
from email_ingestion.storage.atomic_writer import AtomicFileWriter
from email_ingestion.security.path_sanitizer import PathSanitizer
from email_ingestion.security.signature_filter import SignatureFilter
from email_ingestion.security.magic_verifier import MagicVerifier
from email_ingestion.security.archive_guard import ArchiveGuard
from email_ingestion.intelligence.context_sidecar import ContextSidecarGenerator
from email_ingestion.intelligence.fuzzy_similarity import DocumentSimilarityEngine
from email_ingestion.intelligence.duplicate_detector import DuplicateAnomalyDetector
from email_ingestion.connectors.base import BaseEmailConnector, EmailEnvelope
from email_ingestion.connectors.mock_connector import MockEmailConnector
from email_ingestion.connectors.gmail_connector import GmailConnector
from email_ingestion.connectors.ms_graph_connector import MSGraphConnector
from email_ingestion.connectors.imap_connector import IMAPConnector
from email_ingestion.plugins.manager import PluginManager
from email_ingestion.plugins.builtin.desktop_notifier import DesktopNotifierPlugin
from email_ingestion.plugins.builtin.ai_summarizer import AISummarizerPlugin

logger = logging.getLogger(__name__)


class EmailIngestionEngine:
    """Master orchestrator for corporate email and attachment ingestion."""

    def __init__(self, settings: Optional[EngineSettings] = None):
        self.settings = settings or get_settings()

        # 1. State Database (WAL Mode)
        self.db = DatabaseManager(self.settings.database.db_url)

        # 2. Storage & Atomic Writes
        self.layout_mgr = StorageLayoutManager(self.settings.storage.download_dir)
        self.writer = AtomicFileWriter(
            staging_dir=self.settings.storage.staging_dir,
            cas_blob_dir=self.settings.storage.download_dir / ".blobs",
            default_max_bytes=self.settings.security.max_attachment_size_bytes
        )

        # 3. Security Modules
        self.signature_filter = SignatureFilter(self.settings.security.signature_max_size_bytes)
        self.magic_verifier = MagicVerifier()
        self.archive_guard = ArchiveGuard(
            max_ratio=self.settings.security.max_zip_decompression_ratio,
            max_uncompressed_bytes=self.settings.security.max_attachment_size_bytes
        )

        # 4. Intelligence Modules
        self.similarity_engine = DocumentSimilarityEngine(self.settings.intelligence.fuzzy_similarity_threshold)
        self.duplicate_detector = DuplicateAnomalyDetector(self.settings.intelligence.duplicate_detection_mode)

        # 5. Plugin Engine
        self.plugin_mgr = PluginManager()
        self._init_plugins()

        # 6. Active Connectors
        self.connectors: List[BaseEmailConnector] = []
        self._init_connectors()

    def _init_plugins(self) -> None:
        """Register active plugins based on settings."""
        if "desktop_notifier" in self.settings.plugins:
            self.plugin_mgr.register_plugin(DesktopNotifierPlugin())
        if "ai_summarizer" in self.settings.plugins:
            self.plugin_mgr.register_plugin(AISummarizerPlugin())

    def _init_connectors(self) -> None:
        """Initialize enabled email provider connectors."""
        if self.settings.mock_provider.enabled:
            mock = MockEmailConnector()
            if mock.connect():
                self.connectors.append(mock)

        if self.settings.gmail.enabled:
            gmail = GmailConnector(
                credentials_json=self.settings.gmail.credentials_json,
                user_email=self.settings.gmail.user_email or "me"
            )
            if gmail.connect():
                self.connectors.append(gmail)

        if self.settings.microsoft.enabled:
            m365 = MSGraphConnector(
                client_id=self.settings.microsoft.client_id,
                client_secret=self.settings.microsoft.client_secret,
                tenant_id=self.settings.microsoft.tenant_id,
                user_email=self.settings.microsoft.user_email
            )
            if m365.connect():
                self.connectors.append(m365)

        if self.settings.imap.enabled:
            imap = IMAPConnector(
                host=self.settings.imap.host,
                port=self.settings.imap.port,
                username=self.settings.imap.username,
                password=self.settings.imap.password,
                mailbox=self.settings.imap.mailbox,
                use_ssl=self.settings.imap.use_ssl
            )
            if imap.connect():
                self.connectors.append(imap)

    def run_sync(self, dry_run: bool = False) -> Dict[str, int]:
        """Execute a full synchronization cycle across all configured connectors."""
        metrics = {"messages_processed": 0, "attachments_downloaded": 0, "quarantined": 0}

        # Step 0: Sweep stale temporary files from previous aborted runs
        if not dry_run:
            purged = self.writer.cleanup_stale_staging(max_age_seconds=3600)
            if purged > 0:
                logger.info(f"Purged {purged} stale staging files from previous runs.")

        for connector in self.connectors:
            logger.info(f"Checking for messages via provider: {connector.provider_name}")
            try:
                envelopes = connector.fetch_new_messages()
            except Exception as conn_err:
                logger.error(f"Failed fetching messages from provider {connector.provider_name}: {conn_err}")
                continue

            for envelope in envelopes:
                # Deduplication Check 1: Has this message already been processed?
                if self.db.message_exists(envelope.id):
                    logger.info(f"Skipping already-processed message: {envelope.id}")
                    continue

                try:
                    if not dry_run:
                        self.plugin_mgr.notify_email_received(envelope)
                    
                    msg_metrics = self._process_envelope(connector, envelope, dry_run=dry_run)
                    
                    metrics["messages_processed"] += 1
                    metrics["attachments_downloaded"] += msg_metrics["downloaded"]
                    metrics["quarantined"] += msg_metrics["quarantined"]

                    if not dry_run:
                        connector.acknowledge_processed(envelope.id)

                except Exception as env_err:
                    # Isolated per-envelope failure: does not crash the entire sync run
                    logger.error(f"Error processing envelope {envelope.id} from {envelope.sender_email}: {env_err}", exc_info=True)
                    try:
                        self.db.log_audit_event(
                            event_type="ENVELOPE_PROCESSING_ERROR",
                            message_text=f"Failed processing envelope: {str(env_err)}",
                            message_id=envelope.id
                        )
                    except Exception:
                        pass

        # Step 7: Update master index table in root download directory
        if not dry_run:
            self._refresh_master_index()

        return metrics

    def _refresh_master_index(self) -> Optional[Path]:
        """Update Auto_download_email/INDEX.md with all indexed attachments."""
        try:
            entries = self.db.get_all_attachments_for_index()
            if entries:
                return self.layout_mgr.update_master_index(entries)
        except Exception as e:
            logger.warning(f"Could not refresh master index: {e}")
        return None

    def _process_envelope(
        self,
        connector: BaseEmailConnector,
        envelope: EmailEnvelope,
        dry_run: bool = False
    ) -> Dict[str, int]:
        """Process a single email envelope through the security and intelligence pipeline."""
        downloaded_count = 0
        quarantined_count = 0
        envelope_dir = self.layout_mgr.get_envelope_directory(
            sender_email=envelope.sender_email,
            received_at=envelope.received_at,
            message_id=envelope.id
        )

        attachments_meta_for_sidecar: List[Dict[str, Any]] = []
        anomaly_warnings: List[str] = []
        downloaded_attachment_records: List[Attachment] = []
        revision_info_sidecar: Optional[Dict[str, Any]] = None
        created_disk_files: List[Path] = []

        try:
            # Step 1: Pre-download inspection and chunked staging
            staged_items: List[Dict[str, Any]] = []

            for att_stub in envelope.attachments:
                # Check for signature icons
                if self.settings.security.filter_signatures:
                    is_sig = self.signature_filter.is_signature_attachment(
                        filename=att_stub.filename,
                        content_disposition=att_stub.content_disposition,
                        content_id=att_stub.content_id,
                        file_size_bytes=att_stub.size_bytes,
                        html_body=envelope.body_html
                    )
                    if is_sig:
                        logger.info(f"Filtered signature image: {att_stub.filename}")
                        continue

                safe_filename = PathSanitizer.sanitize_filename(att_stub.filename)
                target_path = envelope_dir / safe_filename

                if dry_run:
                    downloaded_count += 1
                    continue

                # True Streaming: Stream directly to staging disk buffer in 64KB chunks
                stream = connector.download_attachment_stream(envelope.id, att_stub.id)
                sha256, actual_size = self.writer.write_stream_atomically(
                    stream=stream,
                    destination_path=target_path,
                    max_bytes=self.settings.security.max_attachment_size_bytes
                )
                created_disk_files.append(target_path)

                staged_items.append({
                    "stub": att_stub,
                    "filename": safe_filename,
                    "target_path": target_path,
                    "sha256": sha256,
                    "size_bytes": actual_size
                })

            if dry_run:
                return {"downloaded": downloaded_count, "quarantined": quarantined_count}

            # Step 2: Intra-email duplicate check (accidental twin attachments in same email)
            intra_dups = self.duplicate_detector.detect_intra_message_duplicates(staged_items)
            if intra_dups:
                for dup in intra_dups:
                    warning_msg = (
                        f"Sender mistakenly attached duplicate file twice: "
                        f"'{dup['original_slot']}' and '{dup['duplicate_slot']}'"
                    )
                    anomaly_warnings.append(warning_msg)
                    
                    self.plugin_mgr.notify_duplicate_detected(dup)
                    self.db.log_audit_event(
                        event_type="DUPLICATE_ANOMALY",
                        message_text=warning_msg,
                        message_id=envelope.id
                    )

            # Step 3: Security inspections (MagicVerifier & ArchiveGuard)
            for item in staged_items:
                target_path: Path = item["target_path"]
                safe_filename: str = item["filename"]
                sha256: str = item["sha256"]
                actual_size: int = item["size_bytes"]

                # Check 3A: Magic Byte Sniffing (puremagic + header checks)
                is_safe, detected_mime, quarantine_reason = self.magic_verifier.inspect_file(target_path)

                # Check 3B: Archive Guard (Zip Slip, Symlinks & Tar Bombs)
                if is_safe:
                    is_archive_safe, archive_reason = self.archive_guard.inspect_archive(target_path)
                    if not is_archive_safe:
                        is_safe = False
                        quarantine_reason = archive_reason

                # Quarantine if failed checks
                if not is_safe and self.settings.security.quarantine_on_mismatch:
                    quarantine_dir = self.settings.storage.quarantine_dir
                    quarantine_dir.mkdir(parents=True, exist_ok=True)
                    try:
                        import os
                        os.chmod(quarantine_dir, 0o700)
                    except OSError:
                        pass

                    quarantine_filename = f"{sha256[:12]}_{target_path.stem}.quarantine"
                    quarantine_path = quarantine_dir / quarantine_filename
                    import shutil
                    shutil.move(str(target_path), str(quarantine_path))
                    try:
                        import os
                        os.chmod(quarantine_path, 0o600)
                    except OSError:
                        pass

                    if target_path in created_disk_files:
                        created_disk_files.remove(target_path)
                    created_disk_files.append(quarantine_path)

                    # Generate companion threat report in quarantine directory
                    report_filename = f"{sha256[:12]}_{target_path.stem}.report.md"
                    report_path = quarantine_dir / report_filename
                    report_md = (
                        f"# Threat Quarantine Report\n\n"
                        f"> [!CAUTION]\n"
                        f"> **Quarantined Suspicious / Malicious File**\n"
                        f"> This attachment was blocked by security policy and isolated in the quarantine vault.\n\n"
                        f"## Quarantine Metadata\n"
                        f"- **Threat Assessment:** `{quarantine_reason or 'Security check failed'}`\n"
                        f"- **Original Filename:** `{item['stub'].filename}`\n"
                        f"- **Detected MIME Type:** `{detected_mime}`\n"
                        f"- **Sender:** `{envelope.sender_email}`\n"
                        f"- **Subject:** {envelope.subject or '(No Subject)'}\n"
                        f"- **Received (UTC):** {envelope.received_at.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                        f"- **SHA-256 Hash:** `{sha256}`\n"
                        f"- **File Size:** {actual_size:,} bytes\n"
                        f"- **Vault Binary Path:** `{quarantine_filename}`\n"
                    )
                    report_path.write_text(report_md, encoding="utf-8")
                    try:
                        import os
                        os.chmod(report_path, 0o600)
                    except OSError:
                        pass
                    created_disk_files.append(report_path)

                    quarantined_count += 1
                    anomaly_warnings.append(f"Quarantined '{safe_filename}': {quarantine_reason}")
                    self.plugin_mgr.notify_quarantine(envelope, safe_filename, quarantine_reason or "Security check failed")
                    
                    att_record = Attachment(
                        id=f"{envelope.id}_{item['stub'].id}",
                        message_id=envelope.id,
                        original_filename=item["stub"].filename,
                        sanitized_filename=safe_filename,
                        file_hash_sha256=sha256,
                        file_size_bytes=actual_size,
                        detected_mime_type=detected_mime,
                        local_storage_path=str(quarantine_path),
                        quarantine_status="QUARANTINED",
                        quarantine_reason=quarantine_reason
                    )
                    downloaded_attachment_records.append(att_record)
                    attachments_meta_for_sidecar.append({
                        "filename": safe_filename,
                        "size_bytes": actual_size,
                        "sha256": sha256,
                        "status": "QUARANTINED",
                        "quarantine_reason": quarantine_reason
                    })
                    continue

                # Step 4: Document Similarity & Thread-Scoped Revision Versioning (v1 vs v2)
                version_num = 1
                parent_id = None
                sim_score = None

                prior_attachment = self.db.find_latest_attachment_by_name(
                    sender_email=envelope.sender_email,
                    filename=safe_filename,
                    thread_id=envelope.thread_id  # Thread-scoped!
                )

                if prior_attachment and Path(prior_attachment.local_storage_path).exists():
                    is_rev, sim_ratio, diff_content = self.similarity_engine.compare_files(
                        original_file_path=Path(prior_attachment.local_storage_path),
                        new_file_path=target_path
                    )
                    if is_rev:
                        version_num = prior_attachment.version_number + 1
                        parent_id = prior_attachment.id
                        sim_score = sim_ratio

                        # Save visual diff file
                        if diff_content:
                            diff_path = envelope_dir / f"{target_path.stem}_diff_v{prior_attachment.version_number}_to_v{version_num}.diff"
                            with open(diff_path, "w", encoding="utf-8") as df:
                                df.write(diff_content)
                            try:
                                import os
                                os.chmod(diff_path, 0o600)
                            except OSError:
                                pass
                            created_disk_files.append(diff_path)

                        revision_info_sidecar = {
                            "is_revision": True,
                            "version_number": version_num,
                            "parent_version": prior_attachment.version_number,
                            "similarity_score": sim_ratio
                        }

                downloaded_count += 1
                att_record = Attachment(
                    id=f"{envelope.id}_{item['stub'].id}",
                    message_id=envelope.id,
                    original_filename=item["stub"].filename,
                    sanitized_filename=safe_filename,
                    file_hash_sha256=sha256,
                    file_size_bytes=actual_size,
                    detected_mime_type=detected_mime,
                    version_number=version_num,
                    parent_attachment_id=parent_id,
                    similarity_score=sim_score,
                    local_storage_path=str(target_path),
                    quarantine_status="CLEAN"
                )
                downloaded_attachment_records.append(att_record)

                attachments_meta_for_sidecar.append({
                    "filename": safe_filename,
                    "size_bytes": actual_size,
                    "sha256": sha256,
                    "status": "CLEAN",
                    "version": version_num
                })

            # Step 5: Generate Context Sidecars (email_context.md & context.json)
            if self.settings.intelligence.generate_context_sidecars:
                base_context = {
                    "subject": envelope.subject,
                    "body_snippet": envelope.body_text or "",
                    "attachments": attachments_meta_for_sidecar
                }
                enriched_context = self.plugin_mgr.enrich_context(base_context)

                ContextSidecarGenerator.generate_sidecars(
                    envelope_dir=envelope_dir,
                    sender_email=envelope.sender_email,
                    sender_name=envelope.sender_name,
                    subject=envelope.subject,
                    received_at=envelope.received_at,
                    message_id=envelope.id,
                    thread_id=envelope.thread_id,
                    body_text=envelope.body_text,
                    attachments_meta=attachments_meta_for_sidecar,
                    anomaly_warnings=anomaly_warnings,
                    revision_info=revision_info_sidecar,
                    ai_summary=enriched_context.get("ai_summary")
                )

            # Step 6: Commit ACID transaction to SQLite/Postgres
            with self.db.session() as session:
                acc = session.query(Account).filter(Account.id == envelope.account_id).first()
                if not acc:
                    acc = Account(
                        id=envelope.account_id,
                        provider=connector.provider_name,
                        email_address=envelope.sender_email
                    )
                    session.add(acc)

                db_msg = Message(
                    id=envelope.id,
                    account_id=envelope.account_id,
                    thread_id=envelope.thread_id,
                    sender_email=envelope.sender_email,
                    sender_name=envelope.sender_name,
                    subject=envelope.subject,
                    received_at=envelope.received_at,
                    status="PROCESSED",
                    has_attachments=bool(envelope.attachments),
                    raw_body_snippet=envelope.body_text[:200] if envelope.body_text else None
                )
                session.add(db_msg)

                for rec in downloaded_attachment_records:
                    session.add(rec)

            self.plugin_mgr.notify_ingestion_complete({
                "message_id": envelope.id,
                "sender": envelope.sender_email,
                "downloaded": downloaded_count,
                "quarantined": quarantined_count
            })

            return {"downloaded": downloaded_count, "quarantined": quarantined_count}

        except Exception:
            # Atomic rollback: Clean up any files written to disk for this envelope if an unhandled error occurred
            for orphan_path in created_disk_files:
                try:
                    if orphan_path.exists():
                        orphan_path.unlink()
                except OSError:
                    pass
            raise
