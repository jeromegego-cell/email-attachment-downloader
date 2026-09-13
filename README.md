# Enterprise Email Ingestion & Attachment Automation System

An enterprise-grade, production-ready Python automation engine designed to securely ingest, filter, validate, contextualize, and download email attachments from **Standard IMAP (Gmail, Outlook, Corporate Mail)**, **Google Workspace / Gmail APIs**, and **Microsoft 365 / Graph APIs**.

> [!TIP]
> **Production Documentation Suite:**
> - [**Documentation Suite Overview & Index**](./docs/README.md)
> - [**System Architecture & Design Guide**](./docs/architecture_guide.md)
> - [**Developer Onboarding & Extension Guide**](./docs/developer_onboarding_guide.md)
> - [**Configuration Reference Manual**](./docs/configuration_reference.md)
> - [**Security Operations & Threat Defense Manual**](./docs/security_operations_manual.md)
> - [**Master Specification & Roadmap**](./docs/Enterprise_Email_Ingestion_Gateway_Master_Plan.md)

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
├── run.py                             # Direct source runner (Pure Python)
├── main.py                            # Application entrypoint (Pure Python)
├── install.py                         # Automated installer (Pure Python)
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
├── tests/                             # Automated test suite (39 test cases, 100% passing)
│   ├── test_open_source_libraries.py  # Tenacity, Pathvalidate, RapidFuzz, ReplyParser, Executive Summary
│   ├── test_security_filters.py       # Traversal, Bidi, Unicode, Zip Slip
│   ├── test_security_edge_cases.py    # Macro detection, LNK, active SVG, streaming tar
│   ├── test_imap_rfc822_ingestion.py  # Multipart RFC 822 MIME parsing
│   ├── test_duplicate_and_similarity.py # Intra-message duplicates & fuzzy diffing
│   └── test_plugins_and_engine.py     # End-to-end sync & AI summarizer
│
├── .github/workflows/                 # CI/CD Workflows
│   └── ci.yml                         # Automated GitHub Actions test & validation matrix
│
└── docs/                              # Production Documentation Suite
    ├── README.md                      # Documentation catalog & index
    ├── architecture_guide.md          # Architecture & data flow
    ├── developer_onboarding_guide.md  # Developer setup & extension guide
    ├── configuration_reference.md     # Configuration manual
    ├── security_operations_manual.md  # Quarantine vault triage guide
    └── Enterprise_Email_Ingestion_Gateway_Master_Plan.md # Master Specification
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

## Quick Start & Execution

### 1. Direct Execution from Source (Zero Installation Required)
Run commands directly with Python from the repository root:
```bash
# Run preflight validation
python3 run.py validate

# Run offline demo
python3 run.py demo

# Interactive configuration wizard
python3 run.py configure

# Live email synchronization
python3 run.py sync
```
*(Or use `python3 main.py <command>`)*

### 2. Automated Installer Script (`install.py`)
For users setting up a local dedicated environment automatically:
```bash
# Cross-platform automated setup (creates virtualenv & configures dependencies)
python3 install.py
```

### 3. Verification & Preflight Health Check
Verify configuration syntax, database connectivity, and folder write permissions:
```bash
python3 run.py validate
```

### 4. Run the Live Offline Demonstration
Execute the end-to-end synthetic scenario generator to verify folder creation, quarantine, and index generation:
```bash
python3 run.py demo
```

### 5. Synchronizing Live Mailboxes
```bash
# Standard one-time synchronization
python3 run.py sync

# Autonomous continuous watcher mode (polls every 60 seconds)
python3 run.py watch --interval 60

# Simulation mode (dry run without writing to disk or database)
python3 run.py sync --dry-run

# Verbose informational logging
python3 run.py sync --verbose

# Detailed debug trace logging
python3 run.py sync --debug
```

### 6. Inspecting State & Audit Ledger
```bash
# View summary statistics of accounts, messages, and attachments
python3 run.py status

# Inspect the tamper-evident audit ledger
python3 run.py audit --limit 20
```

### 7. Rebuilding the Master Index
Rebuild `Auto_download_email/INDEX.md` from the database records at any time:
```bash
python3 run.py reindex
```

> [!NOTE]
> If you have run `install.py` to set up the local virtual environment, all commands above can also be executed using the `email-ingestion` CLI shortcut (e.g. `email-ingestion sync`).



