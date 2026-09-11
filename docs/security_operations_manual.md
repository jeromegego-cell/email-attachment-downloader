# Security Operations & Threat Defense Manual

This document defines the security boundaries, threat mitigation matrix, sandbox policies, and incident response procedures for the **Enterprise Email Ingestion Gateway**.

---

## 1. Threat Model & Attack Surface

The email attachment ingestion path represents an untrusted, adversarial ingestion gateway. The engine addresses five primary threat categories:

```
┌─────────────────────────┬──────────────────────────────────┬───────────────────────────────────────────┐
│ Threat Category         │ Attack Vector Example            │ Defensive Mitigation                      │
├─────────────────────────┼──────────────────────────────────┼───────────────────────────────────────────┤
│ Path Traversal & Escapes│ `../../etc/passwd` or `%2e%2e/`  │ URL unquote + NFKC + strict basename split│
│ Null Byte Injection     │ `invoice.pdf\0.exe`              │ Replace `\x00` with `_` (no bypass)       │
│ Windows ADS / Reserved  │ `file.pdf:hidden.exe`, `CON.txt` │ Replace colons + sanitize reserved names  │
│ POSIX Length DoS        │ 300+ byte filenames              │ UTF-8 byte truncation preserving suffix   │
│ Spoofed Executables     │ PE header inside `.pdf`          │ Header sniffing via puremagic + MZ check  │
│ Linux / Mach-O Binaries │ Disguised ELF / Mach-O binaries  │ Explicit magic byte signatures check      │
│ Windows LNK Shortcuts   │ `.lnk` payload disguised as docs │ Magic signature + disallow extension      │
│ Office VBA Macros       │ `.docm` renamed to `.docx`       │ Deep ZIP entry scan for `vbaProject.bin`  │
│ Active Script Exploits  │ SVG / HTML with `<script>` tags  │ First 8KB regex scan for active tags      │
│ Decompression Bombs     │ 1000:1 zip bomb, Fifield bomb    │ 10:1 ratio ceiling + 100MB size ceiling   │
│ Tar Slip / Inode Exhaust│ Streaming tar traversal, symlink │ Stream `tf.next()`, 10k entry limit       │
│ Data Leakage (Local)    │ Multi-user file access           │ POSIX permissions: `0700` dirs, `0600` files│
└─────────────────────────┴──────────────────────────────────┴───────────────────────────────────────────┘
```

---

## 2. Deep-Dive Security Defenses

### A. Filename Sanitization (`PathSanitizer`)
1. **URL Percent-Decoding:** Decodes `%2e%2e`, `%2f`, `%5c`, `%00` before parsing.
2. **Null Byte Neutralization:** Converts `\x00` to `_` rather than deleting it. This ensures an attacker submitting `invoice.pdf\0.exe` cannot bypass filters into `invoice.pdf`.
3. **Unicode NFKC Normalization:** Neutralizes fullwidth slashes (`／`, `＼`) and colons (`：`).
4. **Bidi & Control Stripping:** Strips Unicode Right-to-Left Override (`\u202e`) and invisible zero-width characters.
5. **Windows Reserved Device Defense:** Case-insensitive prefixing of reserved device names: `CON`, `PRN`, `AUX`, `NUL`, `CLOCK$`, `CONIN$`, `CONOUT$`, `COM0`-`COM9`, `LPT0`-`LPT9`.
6. **POSIX Byte Length Ceiling:** Hard-caps filenames at 255 bytes while strictly preserving the file extension and stripping trailing periods or spaces.

### B. Header Sniffing & Binary Verification (`MagicVerifier`)
1. **Disallowed Extensions:** Rejects `.exe`, `.scr`, `.bat`, `.cmd`, `.ps1`, `.vbs`, `.hta`, `.msi`, `.lnk`, etc. immediately.
2. **Zero-Byte Disguise Defense:** Zero-byte files declaring structured document types (`.pdf`, `.docx`, `.xlsx`) are rejected as corrupted or truncated anomalies.
3. **Binary Header Verification:**
   - Windows PE executable header (`MZ`, `\x4d\x5a`)
   - Linux ELF header (`\x7fELF`)
   - Mach-O binary signatures (`\xfe\xed\xfa\xce`, `\xca\xfe\xba\xbe`, etc.)
   - Windows LNK shortcut header (`\x4c\x00\x00\x00\x01\x14\x02\x00`)
4. **Disguised Office Macro Verification:** Deeply inspects the inner ZIP directory of `.docx`, `.xlsx`, and `.pptx` documents. If any VBA macro storage (`vbaProject.bin`, `vbaData.xml`) is detected, the file is rejected.
5. **Active Script Detection:** Scans text, SVG, XML, and HTML files for `<script>`, `javascript:`, `vbscript:`, `<hta:application`, `onload=`, or `onerror=`.

### C. Archive Bomb & Traversal Defense (`ArchiveGuard`)
1. **Streaming Tar Evaluation:** Uses `tf.next()` iterator instead of buffering `tf.getmembers()` into RAM to prevent memory exhaustion on giant tar archives.
2. **Tar Slip & Symlink Blocking:** Rejects any tar member containing `..`, absolute paths, symlinks (`issym()`), hardlinks (`islnk()`), or FIFO devices.
3. **Sparse File Defense:** Validates `member.issparse()` to block sparse-file allocation attacks.
4. **Entry Limit:** Enforces a maximum threshold of 10,000 entries per archive to prevent inode exhaustion.
5. **Compression Ratio Defense:** Enforces a maximum expansion ratio of 10:1 against physical archive size.

---

## 3. Quarantine Procedures & Incident Handling

### File Isolation Protocol
When a suspicious file fails verification:
1. It is never committed to the recipient's delivery folder.
2. It is immediately moved to `Auto_download_email/quarantine/`.
3. File naming applies a collision-proof SHA-256 hash prefix:
   `Auto_download_email/quarantine/<sha256_prefix>_<original_stem>.quarantine`
4. Directory permissions are clamped to `0700` and file permissions to `0600`.
5. An immutable audit record with event type `QUARANTINE` is written to the SQLite WAL database.
6. A security notification event is dispatched via `PluginManager`.

### Viewing Security Audits
To inspect recent quarantine events via the CLI:
```bash
email-ingestion audit --limit 20
```
Example output:
```
=== Recent Audit Events (Last 20) ===
[2026-09-11 19:46:46] [QUARANTINE]
  Quarantined 'Urgent_Invoice.pdf': Windows/DOS executable header (MZ) detected
```
