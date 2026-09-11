# Configuration Reference Manual

The **Enterprise Email Ingestion Gateway** uses a strongly typed Pydantic configuration hierarchy loaded from YAML files (default: `config.yaml`) and optionally overridden by environment variables.

---

## 1. Configuration Hierarchy Overview

```yaml
# ==========================================
# ENTERPRISE EMAIL INGESTION GATEWAY CONFIG
# ==========================================

# 1. State Database Ledger
database:
  db_url: "sqlite:///email_ingestion_state.db"  # Supports PostgreSQL: postgresql+psycopg://user:pass@host/db

# 2. Storage Subsystem & Directory Layout
storage:
  download_dir: "Auto_download_email"          # Master directory for all downloads & INDEX.md
  staging_dir: "Auto_download_email/.staging"  # Temporary two-phase buffer
  quarantine_dir: "Auto_download_email/quarantine" # Sandboxed threat directory
  enable_cas: true                             # Content Addressable Storage hardlink deduplication

# 3. Defensive Security Settings
security:
  max_attachment_size_bytes: 104857600         # 100 MB per attachment ceiling
  max_zip_decompression_ratio: 10.0            # Zip bomb threshold (e.g. 10:1 ratio)
  signature_max_size_bytes: 15360              # 15 KB threshold for inline email signature filters
  filter_signatures: true                      # Automatic removal of decorative email signature images
  quarantine_on_mismatch: true                 # Automatically quarantine spoofed/dangerous payloads

# 4. Intelligence Engine
intelligence:
  fuzzy_similarity_threshold: 0.85             # 85% SequenceMatcher threshold to detect document revisions (v1 -> v2)
  generate_context_sidecars: true              # Create email_context.md and context.json in each envelope folder
  duplicate_detection_mode: "auto_dedupe"      # Options: auto_dedupe, warn_only, ignore

# 5. Email Providers
# 5A. IMAP / Corporate SSL
imap:
  enabled: false
  host: "imap.corporate-domain.com"
  port: 993
  username: "ingestion@corporate-domain.com"
  password: "YOUR_APP_PASSWORD"
  mailbox: "INBOX"
  use_ssl: true

# 5B. Google Workspace (Gmail API)
gmail:
  enabled: false
  credentials_json: "credentials/service_account.json"
  user_email: "me"

# 5C. Microsoft 365 (MS Graph API)
microsoft:
  enabled: false
  client_id: "AZURE_CLIENT_ID"
  client_secret: "AZURE_CLIENT_SECRET"
  tenant_id: "AZURE_TENANT_ID"
  user_email: "inbox@company.com"

# 5D. Offline Mock Provider (for demonstrations and offline testing)
mock_provider:
  enabled: true

# 6. Active Plugins
plugins:
  - "desktop_notifier"
  - "ai_summarizer"
```

---

## 2. Configuration Field Descriptions

### Database
| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `db_url` | `str` | `sqlite:///email_ingestion_state.db` | SQLAlchemy database connection string. Supports SQLite WAL or PostgreSQL. |

### Storage
| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `download_dir` | `Path` | `Auto_download_email` | Primary corporate directory where all organized downloads and `INDEX.md` live. |
| `staging_dir` | `Path` | `Auto_download_email/.staging` | Atomic two-phase write buffer (created with permissions `0700`). |
| `quarantine_dir` | `Path` | `Auto_download_email/quarantine` | Sandboxed isolation directory for malicious files. |
| `enable_cas` | `bool` | `true` | When true, uses Content Addressable Storage to link identical blobs without wasting disk space. |

### Security
| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `max_attachment_size_bytes` | `int` | `104857600` (100MB) | Hard ceiling on attachment size to prevent disk and memory exhaustion. |
| `max_zip_decompression_ratio`| `float`| `10.0` | Rejects archives if uncompressed:compressed byte ratio exceeds this threshold. |
| `signature_max_size_bytes` | `int` | `15360` (15KB) | Size threshold for detecting small decorative email signatures. |
| `filter_signatures` | `bool` | `true` | Drops decorative logo images referenced inline in HTML bodies. |
| `quarantine_on_mismatch` | `bool` | `true` | Moves spoofed or dangerous files directly into the quarantine sandbox. |

### Intelligence
| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `fuzzy_similarity_threshold` | `float`| `0.85` | Similarity ratio needed to classify a file as a new revision of an earlier document. |
| `generate_context_sidecars` | `bool` | `true` | Emits `email_context.md` and `context.json` into each envelope directory. |
| `duplicate_detection_mode` | `str` | `auto_dedupe` | Mode for handling intra-message duplicates: `auto_dedupe`, `warn_only`, or `ignore`. |

---

## 3. Environment Variable Overrides

Any setting can be overridden via environment variables using the `EMAIL_INGESTION_` prefix with nested double underscores (`__`):
- `EMAIL_INGESTION__DATABASE__DB_URL="postgresql+psycopg://user:pass@localhost:5432/ingestion"`
- `EMAIL_INGESTION__IMAP__ENABLED="true"`
- `EMAIL_INGESTION__IMAP__HOST="imap.gmail.com"`
- `EMAIL_INGESTION__IMAP__USERNAME="user@gmail.com"`
- `EMAIL_INGESTION__IMAP__PASSWORD="app_password"`
