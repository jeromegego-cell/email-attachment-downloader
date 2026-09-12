# Developer Onboarding & Extension Guide

Welcome to the **Enterprise Email Ingestion Gateway** project. This guide covers repository setup, coding standards, how to extend connectors, write custom plugins, and run comprehensive verification suites.

---

## 1. Quickstart Environment Setup

### Prerequisites
- Python 3.10+ (tested through Python 3.14)
- Linux / macOS / POSIX environment

### Local Installation
```bash
# Clone the repository
git clone https://github.com/jeromegego-cell/email-attachment-downloader.git
cd email-attachment-downloader

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install development dependencies
pip install -e ".[dev]"
```

### Preflight Health Check
Verify your local environment and directories:
```bash
python -m email_ingestion.cli validate
```
Expected output:
```
=== Running System Health & Configuration Validation ===
  [PASS] Configuration syntax and Pydantic schema validation
  [PASS] Database connectivity (sqlite:///email_ingestion_state.db) and WAL mode
  [PASS] Download root is writable: Auto_download_email
  [PASS] Staging directory is writable: Auto_download_email/.staging
  [PASS] Quarantine directory is writable: Auto_download_email/quarantine

[SUCCESS] All preflight configuration and environment checks passed!
```

---

## 2. Running Verification & Tests

Run the complete test suite:
```bash
# Run all 35 unit and integration tests
pytest -v

# Run open source library integration tests
pytest tests/test_open_source_libraries.py -v

# Run only security edge case tests
pytest tests/test_security_edge_cases.py -v

# Run IMAP RFC 822 ingestion tests
pytest tests/test_imap_rfc822_ingestion.py -v
```

---

## 3. Writing a Custom Email Provider Connector

All email connectors inherit from `BaseEmailConnector` in `src/email_ingestion/connectors/base.py`.

### Skeleton Implementation
```python
from typing import List, BinaryIO
import io
from email_ingestion.connectors.base import BaseEmailConnector, EmailEnvelope, AttachmentStub
from email_ingestion.connectors.resilience import retry_with_backoff

class CustomProviderConnector(BaseEmailConnector):
    def __init__(self, api_key: str):
        self.api_key = api_key
        self._client = None

    @property
    def provider_name(self) -> str:
        return "CUSTOM_PROVIDER"

    def connect(self) -> bool:
        # Authenticate with remote service
        self._client = True
        return True

    def fetch_new_messages(self, max_messages: int = 50) -> List[EmailEnvelope]:
        # Return list of unread EmailEnvelope objects with AttachmentStub metadata
        return []

    @retry_with_backoff(retries=3, base_delay=1.0)
    def download_attachment_stream(self, message_id: str, attachment_id: str) -> BinaryIO:
        # Stream attachment bytes in chunks
        return io.BytesIO(b"data...")

    def acknowledge_processed(self, message_id: str) -> None:
        # Mark email as read or apply remote label
        pass

    def disconnect(self) -> None:
        # Clean up sockets or session tokens
        self._client = None
```

---

## 4. Writing a Custom Plugin

Plugins extend `BasePlugin` in `src/email_ingestion/plugins/base.py`.

```python
from email_ingestion.plugins.base import BasePlugin
from email_ingestion.connectors.base import EmailEnvelope

class SlackAlertPlugin(BasePlugin):
    @property
    def name(self) -> str:
        return "slack_alert"

    def on_quarantine(self, envelope: EmailEnvelope, filename: str, reason: str) -> None:
        # Post incident payload to webhook
        print(f"ALERT: Malicious payload intercepted: {filename} ({reason})")
```

Register plugins in `src/email_ingestion/engine.py` or through the plugin registry.

---

## 5. Security & Style Standards
- **Defensive File Permissions:** Always enforce `0o700` on directories and `0o600` on files.
- **Fail-Closed Security:** File sniffers must reject untrusted files if parser exceptions occur.
- **Atomic Operations:** Never write partially downloaded files directly into delivery envelope folders. Always route through `AtomicFileWriter`.
