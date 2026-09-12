# Architecture & System Design Guide

The **Enterprise Email Ingestion Gateway** is a production-grade daemon engineered to autonomously ingest, sanitize, deduplicate, and catalog email attachments from heterogeneous corporate mailboxes into a structured, easily browsable repository (`Auto_download_email/`).

---

## 1. Core Architectural Tenet

The gateway adheres to a strict single-responsibility design: **All incoming corporate documents must land in an orderly, sender-organized, collision-proof directory structure accompanied by an auto-updating master catalog (`INDEX.md`) and contextual intelligence sidecars.**

```
Auto_download_email/
├── INDEX.md                             <- Clickable master catalog (sorted by received date)
├── .blobs/                              <- Content Addressable Storage (CAS deduplication)
├── .staging/                            <- Two-phase staging buffer (mode 0700)
├── quarantine/                          <- Secure sandbox for quarantined malicious files
└── <sanitized_sender>/                  <- e.g., acme_supplier_com/
    └── <delivery_envelope>/             <- e.g., 2026-09-11_14-30-00_a3b8c9d1/
        ├── email_context.md             <- Human-readable markdown sidecar
        ├── context.json                 <- Machine-readable metadata (SIEM/ERP integration)
        ├── Invoice_Q3.pdf               <- Downloaded attachment (mode 0600)
        └── Quote_diff_v1_to_v2.diff     <- Automatic visual diff (if revision detected)
```

---

## 2. Ingestion Pipeline & Execution Flow

Every synchronization cycle follows a deterministic 8-step pipeline:

```
[ Email Provider ] -> (IMAP / Gmail API / MS Graph API / Mock)
         │
         ▼
[ 1. Stale Cleanup ] -> Purge orphaned .staging/tmp_*.part files (>1hr)
         │
         ▼
[ 2. Message Deduplication ] -> Message-ID lookup against SQLite WAL State Ledger
         │
         ▼
[ 3. Chunked Ingestion ] -> 64KB atomic disk streaming into .staging/ buffer
         │
         ▼
[ 4. Defensive Security ]
    ├── Path Sanitizer   (pathvalidate: universal OS rules, Windows ADS, reserved devices, POSIX byte cap)
    ├── Magic Sniffer    (puremagic + binary headers: PE, ELF, Mach-O, Windows LNK, Office VBA macro)
    ├── Archive Guard    (Tar Slip, streaming tar members, nested zip bombs, 10:1 ratio ceiling)
    └── Sig Filter       (CID matching, 15KB threshold, HTML references)
         │
         ├── [THREAT] ───────► Move to quarantine/ (0600) + emit security audit event
         │
         ▼ [CLEAN]
[ 5. Intelligence Engine ]
    ├── Intra-Email Duplicate Detector (mistaken twins in same email)
    └── Fuzzy Revision Engine (rapidfuzz SIMD similarity >= 80%, versioning v1->v2 + difflib .diff)
         │
         ▼
[ 6. Atomic Commit ] -> Two-phase rename to delivery folder (with EXDEV fallback)
         │
         ▼
[ 7. Sidecar Generation ] -> ContextSidecarGenerator (email-reply-parser + email_context.md + context.json)
         │
         ▼
[ 8. ACID Persistence ] -> SQLAlchemy Session commit (Accounts, Messages, Attachments, AuditLogs)
         │
         ▼
[ 9. Master Index Update ] -> Atomic update of Auto_download_email/INDEX.md
```

---

## 3. Storage Subsystem & Atomic Commits

### Two-Phase Commit (`AtomicFileWriter`)
To avoid leaving partial or corrupt files on disk during unexpected process termination or network drops:
1. Data is written to `Auto_download_email/.staging/tmp_<uuid>.part` in 64KB buffers.
2. File permissions are restricted immediately via `os.chmod(temp_path, 0o600)`.
3. If writing completes successfully, `os.replace` atomically renames the staging file to the final destination.
4. **Cross-Device Fallback (`EXDEV`):** If the staging directory and download destination reside across different disk partitions or mount points, `AtomicFileWriter` catches `errno.EXDEV` and seamlessly transitions to `shutil.move` with explicit `0o600` permission enforcement.
5. **Rollback Guarantee:** If an unhandled exception occurs before database transaction completion, the ingestion orchestrator sweeps and deletes any uncommitted files written during that envelope cycle.

---

## 4. State Ledger & Concurrency Architecture

### SQLite Write-Ahead Logging (WAL)
Concurrency bottlenecks and database locked errors are mitigated through custom SQLite pragmas configured at connection initialization:
- `PRAGMA journal_mode=WAL;` — Enables non-blocking concurrent reads while writes are occurring.
- `PRAGMA synchronous=NORMAL;` — Balances ACID reliability with high write throughput.
- `PRAGMA busy_timeout=30000;` — Implements an automatic 30-second backoff when write contention occurs.
- `pool_pre_ping=True` — Verifies database connection liveness before executing queries.

### Explicit WAL Checkpointing
On clean shutdown or via the `DatabaseManager.checkpoint(mode="PASSIVE")` interface, dirty WAL frames are cleanly synced to disk, and `DatabaseManager.close()` issues a `TRUNCATE` checkpoint to minimize disk footprint.

---

## 5. Extensible Plugin Architecture

The engine implements an observer-style plugin pipeline (`PluginManager`). Plugins hook into standard event dispatch points:
- `notify_email_received(envelope)`
- `notify_quarantine(envelope, filename, reason)`
- `notify_duplicate_detected(anomaly_details)`
- `enrich_context(base_context) -> enriched_dict`
- `notify_ingestion_complete(summary)`

Built-in plugins include:
- `DesktopNotifierPlugin`: System notification tray alerts for received or quarantined items.
- `AISummarizerPlugin`: Heuristic or LLM-driven email summarization and actionable task extraction for markdown sidecars.
