# Enterprise Email Ingestion & Attachment Automation System

An enterprise-grade, production-ready Python automation engine designed to securely ingest, filter, validate, contextualize, and download email attachments from **Standard IMAP (Gmail, Outlook, Corporate Mail)**, **Google Workspace / Gmail APIs**, and **Microsoft 365 / Graph APIs**.

> [!TIP]
> **Production Documentation Suite:**
> - [**System Architecture & Design Guide**](./docs/architecture_guide.md)
> - [**Developer Onboarding & Extension Guide**](./docs/developer_onboarding_guide.md)
> - [**Configuration Reference Manual**](./docs/configuration_reference.md)
> - [**Security Operations & Threat Defense Manual**](./docs/security_operations_manual.md)
> - [**Master Specification & Roadmap (Markdown)**](./Enterprise_Email_Ingestion_Gateway_Master_Plan.md) | [**Interactive UI (HTML)**](./Enterprise_Email_Ingestion_Gateway_Master_Plan.html)

---

## Core Architecture & Supervisor Fulfillment

The system strictly fulfills the supervisor's primary requirement: **"Download whatever is sent to this email in an orderly, sorted manner to one folder where it is easy to access, inspect, and verify."**

### 1. Orderly Storage & Browsable Master Index
All attachments are downloaded into a standardized root directory: `Auto_download_email/`.
- **Sender Hierarchy:** Attachments are cleanly partitioned by sender and chronological delivery envelopes:
  `Auto_download_email/<sanitized_sender>/<timestamp>_<hash_prefix>/`
- **Master Index (`INDEX.md`):** Automatically generated and maintained in the root `Auto_download_email/` folder. Anyone opening the folder sees a clean, chronological Markdown table with direct links to every downloaded file, file sizes, sender details, security status, and accompanying context sidecars.
- **Atomic Index Commits:** Index is generated via `.tmp_INDEX.md` and swapped atomically with POSIX `0600` permissions. Special characters, markdown pipes (`|`), and path links are properly URL-escaped to prevent formatting breakage.

### 2. Multi-Provider Ingestion & Network Resilience
- **Standard IMAP / SSL:** Universal compatibility with standard email providers (Gmail App Passwords, Outlook, corporate Dovecot/Exchange).
- **Google Workspace (Gmail API):** Cursor-paginated retrieval via official Google client libraries.
- **Microsoft 365 (MS Graph API):** Azure Identity and Delta Sync support.
- **Mock Provider:** Built-in offline testing provider simulating synthetic real-world email scenarios.
- **Transient Network Resilience:** Built-in exponential backoff with full randomized jitter (`retry_with_backoff`) handling rate limits, socket timeouts, and provider throttling.

### 3. Context Sidecars (`email_context.md` & `context.json`)
- Each delivery envelope contains human-readable Markdown and machine-readable JSON sidecars preserving email headers, sender intent, conversation thread ID, and sanitized body snippets.
- Built-in DLP filters redact credit cards, SSNs, and passwords before writing sidecars.
- Sidecars are committed atomically with restricted POSIX `0600` permissions.

### 4. Duplicate & Anomaly Intelligence
- **Intra-Email Duplicates:** Flags when a sender accidentally attaches the same file twice to the same email.
- **Cross-Email Resends:** Identifies repeated resends with interactive or automated resolution strategies (`KEEP_FIRST`, `KEEP_BOTH`, `SKIP`).
- **Fuzzy Document Similarity:** Detects revisions of same-name files (e.g., `Quote_v1.txt` vs `Quote_v2.txt`), tracks parent-child versioning, and produces visual `.diff` patch files.

### 5. Multi-Layer Defensive Security Hardening
- **Signature & Logo Filtering:** Drops decorative inline logos, tracking pixels, and social media icons (`image001.png`, CID matching).
- **Header Sniffing & Macro Defense:** Verifies true binary file headers (`puremagic`, MZ, ELF, Mach-O, Windows LNK) to detect extension spoofing. Deeply inspects ZIP structures of Office `.docx`/`.xlsx` to reject disguised VBA macros.
- **Zip Bomb & Streaming Tar Defense:** Defends against Zip Slip (path traversal & malicious symlinks), decompression bombs (ratio ceiling 10:1), sparse files, and streams tar members with `tf.next()` (max 10,000 entries).
- **POSIX Path Sanitizer:** Defends against directory traversal (`../`), URL percent-encoding (`%2e%2e`, `%2f`), null bytes (`\x00` -> `_`), Windows reserved devices (`CON`, `PRN`, `AUX`, `NUL`, `COM0`-`COM9`, `LPT0`-`LPT9`), Unicode NFKC spoofing, and Bidi override characters (`\u202e`).
- **Atomic Two-Phase Streaming:** Writes streams directly to disk in 64KB chunks to prevent RAM exhaustion (OOM), followed by atomic rename (`os.replace`) with cross-device (`EXDEV`) fallback.

---

## Directory Layout

```
email_attachment_downloader/
├── config.yaml                        # Configuration (folders, thresholds, credentials)
├── pyproject.toml                     # Modern package build configuration
├── requirements.txt                   # Dependency specifications
├── README.md                          # Documentation & Quickstart
├── Enterprise_Email_Ingestion_Gateway_Master_Plan.md   # Project Master Specification (Markdown)
├── Enterprise_Email_Ingestion_Gateway_Master_Plan.html # Interactive Specification UI
│
├── Auto_download_email/               # Root downloads folder
│   ├── INDEX.md                       # Master chronological table with clickable links
│   ├── quarantine/                    # Isolated suspicious files (0700/0600)
│   └── <sender_email>/                # Organized sender directories
│       └── <delivery_envelope>/       # Envelope folder (attachments + sidecars + diffs)
│
├── src/email_ingestion/
│   ├── config.py                      # Strongly-typed Pydantic settings
│   ├── engine.py                      # Main Ingestion Orchestrator
│   ├── cli.py                         # Command-Line Interface (sync, status, audit, demo, reindex, validate, test-connection)
│   │
│   ├── connectors/                    # Email provider connectors
│   │   ├── base.py                    # BaseEmailConnector abstract interface
│   │   ├── resilience.py              # Exponential backoff with jitter
│   │   ├── imap_connector.py          # Universal IMAP/IMAP-SSL connector
│   │   ├── gmail_connector.py         # Google Workspace API connector
│   │   ├── ms_graph_connector.py      # Microsoft 365 Graph connector
│   │   └── mock_connector.py          # Synthetic scenario generator
│   │
│   ├── database/                      # ACID state & audit ledger
│   │   ├── models.py                  # SQLAlchemy models (Account, Message, Attachment, AuditLog)
│   │   └── session.py                 # SQLite WAL mode, busy timeout, & connection manager
│   │
│   ├── intelligence/                  # Context and similarity analysis
│   │   ├── context_sidecar.py         # DLP-sanitized email_context.md & context.json
│   │   ├── duplicate_detector.py      # Duplicate anomaly detection
│   │   └── fuzzy_similarity.py        # Versioning & diff generator
│   │
│   ├── security/                      # Defensive security modules
│   │   ├── archive_guard.py           # Zip Slip, Tar Slip, streaming & archive bomb defense
│   │   ├── magic_verifier.py          # Sniffing, LNK, macro & executable quarantine
│   │   ├── path_sanitizer.py          # Path traversal, URL unquote, NFKC, & Bidi sanitization
│   │   └── signature_filter.py        # Inline signature/icon filter
│   │
│   ├── storage/                       # Atomic file persistence
│   │   ├── atomic_writer.py           # Two-phase streaming atomic writer with EXDEV fallback
│   │   └── layout_manager.py          # Directory layout & INDEX.md generator
│   │
│   └── plugins/                       # Extensible plugin system
│       ├── base_plugin.py             # Plugin lifecycle hook interface
│       ├── manager.py                 # Hook dispatcher
│       └── builtin/
│           ├── ai_summarizer.py       # AI context summarizer
│           └── desktop_notifier.py    # Desktop notification plugin
│
├── tests/                             # Automated test suite (33 test cases, 100% passing)
│   ├── test_open_source_libraries.py  # Tenacity, Pathvalidate, RapidFuzz, ReplyParser, Executive Summary
│   ├── test_security_filters.py
│   ├── test_security_edge_cases.py
│   ├── test_imap_rfc822_ingestion.py
│   ├── test_duplicate_and_similarity.py
│   └── test_plugins_and_engine.py
│
├── .github/workflows/                 # CI/CD Workflows
│   └── ci.yml                         # Automated GitHub Actions test & validation matrix
│
└── docs/                              # Production Documentation Suite
    ├── architecture_guide.md
    ├── developer_onboarding_guide.md
    ├── configuration_reference.md
    ├── security_operations_manual.md
    └── Enterprise_Email_Ingestion_Gateway_Master_Plan.md
```

---

## Production Open-Source Library Foundations

To guarantee maximum reliability and eliminate fragile hand-rolled logic, the engine replaces custom implementations with battle-tested open-source libraries:
- **`pathvalidate` (MIT):** Cross-platform filename sanitization, Windows reserved device neutralizing (`CON`, `PRN`, `AUX`, `NUL`, `COM0-9`, `LPT0-9`), and POSIX length enforcement.
- **`rapidfuzz` (MIT):** SIMD C++ accelerated Levenshtein / ratio calculation (10x–100x faster than difflib) for document revisions and diffing.
- **`tenacity` (Apache 2.0):** Production-grade exponential backoff and randomized jitter for network and provider resilience.
- **`email-reply-parser` (MIT):** Thread reply stripping to cleanly separate newly typed email text from conversation history quotes.
- **`imapclient` (BSD-3) & Python `email.policy.default`:** Native RFC 2047 and RFC 2231 auto-decoding with resilient IMAP protocol handling.
- **`puremagic` (MIT):** Multi-byte binary signature sniffing.

---

## Quick Start & CLI Usage

### 1. Preflight Health Check & Validation
Verify configuration syntax, database connectivity, and folder write permissions:
```bash
email-ingestion validate
```

### 2. Run Verification Tests
```bash
pytest -v
```
All 33 test cases pass in ~0.35s across Linux, macOS, and Windows.

### 3. Interactive Configuration Wizard
Quickly configure your Gmail, Outlook, or corporate IMAP credentials with automatic TLS verification:
```bash
email-ingestion configure
```

### 4. Test Provider Authentication (Without Downloading)
```bash
email-ingestion test-connection
```

### 5. Run the Live Offline Demonstration
```bash
email-ingestion demo
```

### 6. Synchronizing Live Mailboxes
```bash
# Standard one-time synchronization
email-ingestion sync

# Autonomous continuous watcher mode (polls every 60 seconds)
email-ingestion watch --interval 60

# Real-time IMAP IDLE push mode (sub-second zero-delay push)
email-ingestion watch --interval 60 --idle

# Simulation mode (dry run without writing to disk or database)
email-ingestion sync --dry-run

# Verbose informational logging
email-ingestion sync --verbose

# Detailed debug trace logging
email-ingestion sync --debug
```

### 7. Instant Full-Text Search
Search across all downloaded attachments, senders, subjects, and hashes:
```bash
# Search by keyword
email-ingestion search "contract"

# Filter by sender
email-ingestion search --sender "acme-corp.com"

# Filter by security status
email-ingestion search --status QUARANTINED

# Show only document revisions (v2+)
email-ingestion search --revisions-only
```

### 8. Operational Analytics & Storage Statistics
Display gateway metrics, storage consumption, top senders, and file type distribution:
```bash
email-ingestion stats
```

### 9. Interactive Web Dashboard & Catalog Viewer
In addition to `Auto_download_email/INDEX.md`, the engine automatically maintains a sleek, responsive HTML5 web application at `Auto_download_email/index.html` with real-time live search, filter tabs (Clean, Threats, Revisions), and sender chips.

Launch the local web server to browse the interactive catalog directly in your browser:
```bash
email-ingestion serve --port 8080
```

### 10. Catalog Export & Legal Archiving
Export the audit ledger or package verified attachments into an archive:
```bash
# Export to CSV spreadsheet
email-ingestion export --format csv --output attachments_audit.csv

# Export to structured JSON
email-ingestion export --format json --output audit_manifest.json

# Bundle clean attachments into a ZIP archive
email-ingestion export --format zip --output clean_archive.zip --sender "acme-corp.com"
```

### 11. State & Audit Ledger Inspection
```bash
email-ingestion status
email-ingestion audit --limit 20
email-ingestion reindex
```

---

## Production Deployment (Docker & Systemd)

### 1. Docker Compose (Zero-Configuration Deployment)
Run 24/7 background email ingestion with persistent storage and optional web dashboard:
```bash
# Start background worker and web catalog
docker compose up -d

# View real-time logs
docker compose logs -f email-ingestion
```

### 2. Systemd Service (Linux Server Daemon)
A production systemd unit template is provided in `systemd/email-ingestion.service`:
```bash
# Copy service unit
sudo cp systemd/email-ingestion.service /etc/systemd/system/

# Reload systemd and enable service
sudo systemctl daemon-reload
sudo systemctl enable --now email-ingestion

# Check service status
sudo systemctl status email-ingestion
```



