"""Two-phase atomic file writer and Content Addressable Storage (CAS) manager.

Guarantees that files on disk are never partially written, enforce
strict maximum file size ceilings to prevent DoS, and apply secure POSIX permissions (0600).
"""

import hashlib
import os
import shutil
import uuid
from pathlib import Path
from typing import Tuple, BinaryIO


class AtomicFileWriter:
    """Safely writes files to disk using two-phase atomic commits."""

    def __init__(
        self,
        staging_dir: Path = Path("Auto_download_email/.staging"),
        cas_blob_dir: Path = Path("Auto_download_email/.blobs"),
        default_max_bytes: int = 104857600  # 100 MB default ceiling
    ):
        self.staging_dir = Path(staging_dir)
        self.cas_blob_dir = Path(cas_blob_dir)
        self.default_max_bytes = default_max_bytes
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self.cas_blob_dir.mkdir(parents=True, exist_ok=True)
        # Enforce secure directory permissions
        try:
            os.chmod(self.staging_dir, 0o700)
            os.chmod(self.cas_blob_dir, 0o700)
        except OSError:
            pass

    def write_bytes_atomically(
        self,
        data: bytes,
        destination_path: Path,
        max_bytes: int = None
    ) -> Tuple[str, int]:
        """Write raw in-memory bytes atomically to disk."""
        ceiling = max_bytes or self.default_max_bytes
        if len(data) > ceiling:
            raise ValueError(f"Attachment size ({len(data)} bytes) exceeds limit ({ceiling} bytes)")

        destination_path.parent.mkdir(parents=True, exist_ok=True)
        temp_filename = f"tmp_{uuid.uuid4().hex}.part"
        temp_path = self.staging_dir / temp_filename

        hasher = hashlib.sha256()
        try:
            with open(temp_path, "wb") as f:
                f.write(data)
                hasher.update(data)
            
            sha256_hash = hasher.hexdigest()
            file_size = len(data)

            # Restrict file permissions to 0600 (owner read/write only)
            try:
                os.chmod(temp_path, 0o600)
            except OSError:
                pass

            # Atomic rename from staging to target destination
            os.replace(temp_path, destination_path)
            return sha256_hash, file_size
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            raise

    def write_stream_atomically(
        self,
        stream: BinaryIO,
        destination_path: Path,
        chunk_size: int = 65536,
        max_bytes: int = None
    ) -> Tuple[str, int]:
        """Stream data in chunks to prevent high memory usage on large attachments."""
        ceiling = max_bytes or self.default_max_bytes
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        temp_filename = f"tmp_{uuid.uuid4().hex}.part"
        temp_path = self.staging_dir / temp_filename

        hasher = hashlib.sha256()
        total_bytes = 0

        try:
            with open(temp_path, "wb") as out_f:
                while True:
                    chunk = stream.read(chunk_size)
                    if not chunk:
                        break
                    total_bytes += len(chunk)
                    if total_bytes > ceiling:
                        raise ValueError(f"Stream size exceeded maximum allowed limit of {ceiling} bytes")
                    out_f.write(chunk)
                    hasher.update(chunk)

            sha256_hash = hasher.hexdigest()

            # Restrict file permissions to 0600
            try:
                os.chmod(temp_path, 0o600)
            except OSError:
                pass

            # Atomic replace into final destination
            os.replace(temp_path, destination_path)
            return sha256_hash, total_bytes
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            raise

    def link_cas_duplicate(
        self,
        existing_source_path: Path,
        destination_path: Path
    ) -> None:
        """Create a hardlink or copy to deduplicate disk usage while keeping files accessible."""
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(existing_source_path, destination_path)
        except (OSError, NotImplementedError):
            shutil.copy2(existing_source_path, destination_path)
