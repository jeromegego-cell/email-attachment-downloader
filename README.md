# Enterprise Email Ingestion & Attachment Automation System

An enterprise-grade, production-ready Python automation engine designed to securely ingest, filter, validate, contextualize, and download email attachments from **Standard IMAP (Gmail, Outlook, Corporate Mail)**, **Google Workspace / Gmail APIs**, and **Microsoft 365 / Graph APIs**.

---

## Core Architecture & Supervisor Fulfillment

The system strictly fulfills the supervisor's primary requirement: **"Download whatever is sent to this email in an orderly, sorted manner to one folder where it is easy to access, inspect, and verify."**

### 1. Orderly Storage & Browsable Master Index
All attachments are downloaded into a standardized root directory: `Auto_download_email/`.
- **Sender Hierarchy:** Attachments are cleanly partitioned by sender and chronological delivery envelopes:
  `Auto_download_email/<sanitized_sender>/<timestamp>_<hash_prefix>/`
- **Master Index (`INDEX.md`):** Automatically generated and maintained in the root `Auto_download_email/` folder. Anyone opening the folder sees a clean, chronological Markdown table with direct links to every downloaded file, file sizes, sender details, security status, and accompanying context sidecars.

### 2. Zero Data Loss & Multi-Provider Ingestion
- **Standard IMAP / SSL:** Universal compatibility with any standard email provider (Gmail App Passwords, Outlook, corporate Dovecot/Exchange).
- **Google Workspace (Gmail API):** High-throughput cursor-paginated retrieval via official Google client libraries.
- **Microsoft 365 (MS Graph API):** Azure Identity and Delta Sync support.
- **Mock Provider:** Built-in offline testing provider simulating synthetic real-world email scenarios.

### 3. Context Sidecars (`email_context.md` & `context.json`)
- Each delivery envelope contains human-readable Markdown and machine-readable JSON sidecars preserving email headers, sender intent, conversation thread ID, and sanitized body snippets.
- Built-in DLP filters redact credit cards, SSNs, and passwords before writing sidecars.
- Sidecars are committed atomically with restricted POSIX `0600` permissions.

### 4. Duplicate & Anomaly Intelligence
- **Intra-Email Duplicates:** Flags when a sender accidentally attaches the same file twice to the same email.
- **Cross-Email Resends:** Identifies repeated resends with interactive or automated resolution strategies (`KEEP_FIRST`, `KEEP_BOTH`, `SKIP`).
- **Fuzzy Document Similarity:** Detects revisions of same-name files (e.g., `Quote_v1.txt` vs `Quote_v2.txt`), tracks parent-child versioning, and produces visual `.diff` patch files.

### 5. Defensive Security Hardening
- **Signature & Logo Filtering:** Drops decorative inline logos, tracking pixels, and social media icons (`image001.png`, CID matching).
- **PureMagic Header Sniffing:** Verifies true binary file headers (using `puremagic`) to detect extension spoofing (e.g., `.exe` or ELF binaries disguised as `.pdf`) and quarantines threats.
- **Zip Bomb & Archive Guard:** Defends against Zip Slip (path traversal & malicious symlinks) and decompression bombs (Fifield attacks with >10:1 ratio limits against physical on-disk size).
- **POSIX Path Sanitizer:** Defends against directory traversal (`../`), null bytes, Windows reserved words (`CON`, `PRN`), Unicode NFKC spoofing, and Bidi override characters (`\u202e`).
- **Atomic Two-Phase Streaming:** Writes streams directly to disk in 64KB chunks to prevent RAM exhaustion (OOM), followed by atomic rename (`os.replace`).

---

## Directory Structure

```
email_attachment_downloader/
├── config.yaml                        # Configuration (folders, thresholds, credentials)
├── pyproject.toml                     # Modern package build configuration
├── requirements.txt                   # Dependency specifications
├── README.md                          # Documentation & Quickstart
│
├── Auto_download_email/               # Root downloads folder
│   ├── INDEX.md                       # Master chronological table with clickable links
│   ├── quarantine/                    # Isolated suspicious files
│   └── <sender_email>/                # Organized sender directories
│       └── <delivery_envelope>/       # Envelope folder (attachments + sidecars + diffs)
│
├── src/email_ingestion/
│   ├── config.py                      # Strongly-typed Pydantic settings
│   ├── engine.py                      # Main Ingestion Orchestrator
│   ├── cli.py                         # Command-Line Interface (sync, status, audit, demo, reindex)
│   │
│   ├── connectors/                    # Email provider connectors
│   │   ├── base.py                    # BaseEmailConnector abstract interface
│   │   ├── imap_connector.py          # Universal IMAP/IMAP-SSL connector
│   │   ├── gmail_connector.py         # Google Workspace API connector
│   │   ├── ms_graph_connector.py      # Microsoft 365 Graph connector
│   │   └── mock_connector.py          # Synthetic scenario generator
│   │
│   ├── database/                      # ACID state & audit ledger
│   │   ├── models.py                  # SQLAlchemy models (Account, Message, Attachment, AuditLog)
│   │   └── session.py                 # SQLite WAL mode & connection manager
│   │
│   ├── intelligence/                  # Context and similarity analysis
│   │   ├── context_sidecar.py         # DLP-sanitized email_context.md & context.json
│   │   ├── duplicate_detector.py      # Duplicate anomaly detection
│   │   └── fuzzy_similarity.py        # Versioning & diff generator
│   │
│   ├── security/                      # Defensive security modules
│   │   ├── archive_guard.py           # Zip Slip & archive bomb defense
│   │   ├── magic_verifier.py          # Header sniffing & executable quarantine
│   │   ├── path_sanitizer.py          # Path traversal, NFKC, & Bidi sanitization
│   │   └── signature_filter.py        # Inline signature/icon filter
│   │
│   ├── storage/                       # Atomic file persistence
│   │   ├── atomic_writer.py           # Two-phase streaming atomic writer
│   │   └── layout_manager.py          # Directory layout & INDEX.md generator
│   │
│   └── plugins/                       # Extensible plugin system
│       ├── base_plugin.py             # Plugin lifecycle hook interface
│       ├── manager.py                 # Hook dispatcher
│       └── builtin/
│           ├── ai_summarizer.py       # AI context summarizer
│           └── desktop_notifier.py    # Desktop notification plugin
│
├── tests/                             # Automated test suite (15 test suites)
│   ├── test_security_filters.py
│   ├── test_duplicate_and_similarity.py
│   └── test_plugins_and_engine.py
│
└── docs/                              # Architecture reports & master plan
    └── Enterprise_Email_Ingestion_Gateway_Master_Plan.md
```

---

## Quick Start Guide

### 1. Activate Environment & Run Verification Tests
```bash
cd /home/jerome/email_attachment_downloader
source .venv/bin/activate
pytest -v
```

### 2. Run the Live Offline Demonstration
```bash
email-ingestion demo
```
This demonstrates:
- Downloading legitimate invoices while discarding signature banners.
- Detecting an accidental duplicate twin attachment and logging an anomaly alert.
- Tracking document revisions (`Quote_2026.txt` v1 -> v2) with automatic `.diff` generation.
- Intercepting and quarantining a disguised PE executable.
- Generating the root `Auto_download_email/INDEX.md` catalog.

### 3. Check System Status & Audit Logs
```bash
email-ingestion status
email-ingestion audit
```

### 4. Rebuilding the Master Index
To rebuild the master `Auto_download_email/INDEX.md` from the database ledger at any time:
```bash
email-ingestion reindex
```

### 5. Connecting a Real Mailbox
To connect to a live email account (Gmail, Microsoft 365, or standard IMAP), edit `config.yaml` and run:
```bash
email-ingestion sync
```

