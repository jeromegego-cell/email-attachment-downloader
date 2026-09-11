"""Two-phase atomic file writer and Content Addressable Storage (CAS) manager.

Guarantees that files on disk are never partially written, enforce
strict maximum file size ceilings to prevent DoS, and apply secure POSIX permissions (0600).
"""

import errno
import hashlib
import os
import shutil
import time
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
        # Enforce secure directory permissions (0700)
        try:
            os.chmod(self.staging_dir, 0o700)
            os.chmod(self.cas_blob_dir, 0o700)
        except OSError:
            pass

    def _commit_staged_file(self, temp_path: Path, destination_path: Path) -> None:
        """Atomically commit staged temporary file to final destination with cross-device fallback."""
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(temp_path, 0o600)
        except OSError:
            pass

        try:
            os.replace(temp_path, destination_path)
        except OSError as err:
            if err.errno == errno.EXDEV:
                shutil.move(str(temp_path), str(destination_path))
                try:
                    os.chmod(destination_path, 0o600)
                except OSError:
                    pass
            else:
                raise

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

            self._commit_staged_file(temp_path, destination_path)
            return sha256_hash, file_size
        except Exception:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
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

            self._commit_staged_file(temp_path, destination_path)
            return sha256_hash, total_bytes
        except Exception:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            raise

    def cleanup_stale_staging(self, max_age_seconds: int = 3600) -> int:
        """Purge orphaned temporary staging files older than the specified age."""
        purged_count = 0
        now = time.time()
        try:
            for part_file in self.staging_dir.glob("tmp_*.part"):
                try:
                    if (now - part_file.stat().st_mtime) > max_age_seconds:
                        part_file.unlink()
                        purged_count += 1
                except OSError:
                    pass
        except OSError:
            pass
        return purged_count

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
        try:
            os.chmod(destination_path, 0o600)
        except OSError:
            pass
