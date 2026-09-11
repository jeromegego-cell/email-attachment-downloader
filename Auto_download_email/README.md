# Auto_download_email Storage Gateway

This directory is the centralized, organized repository for all downloaded email attachments, context sidecars, and the master index.

## Directory Layout
* **Master Index:** `INDEX.md` — Automatically updated chronological catalog with direct links to every downloaded attachment and context sidecar.
* **Sender Subdirectories:** `<sender_domain>/<timestamp>_<hash>/` — Cleanly partitioned delivery envelopes containing:
  * Safe attachments
  * `email_context.md` (Human-readable metadata and DLP-sanitized email body)
  * `context.json` (Machine-readable envelope metadata for downstream pipelines)
  * `*.diff` (Visual diff files when document revisions are detected)
* **Quarantine:** `quarantine/` — Isolated storage for files that failed magic byte sniffing, executable header checks, or archive bomb defenses.

## Quick Demo
To populate this directory with synthetic enterprise scenarios demonstrating all features, run:
```bash
email-ingestion demo
```
