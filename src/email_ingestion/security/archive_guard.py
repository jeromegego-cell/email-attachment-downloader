"""Archive and zip bomb defense guard.

Validates compressed archives to ensure they do not exploit Zip Slip,
contain symlinks to sensitive system paths, or execute decompression bombs.
"""

import os
import re
import stat
import tarfile
import zipfile
from pathlib import Path
from typing import Tuple, Optional


class ArchiveGuard:
    """Guards against archive traversal exploits, symlinks, and zip bombs."""

    def __init__(self, max_ratio: float = 10.0, max_uncompressed_bytes: int = 524288000):
        self.max_ratio = max_ratio
        self.max_uncompressed_bytes = max_uncompressed_bytes  # 500 MB default ceiling

    def inspect_archive(self, file_path: Path) -> Tuple[bool, Optional[str]]:
        """Unified inspection for ZIP and TAR archives."""
        if zipfile.is_zipfile(file_path):
            return self._inspect_zip(file_path)
        elif tarfile.is_tarfile(file_path):
            return self._inspect_tar(file_path)
        return True, None

    # Alias for compatibility with tests
    inspect_zip_archive = inspect_archive

    def _inspect_zip(self, file_path: Path) -> Tuple[bool, Optional[str]]:
        physical_size = file_path.stat().st_size
        if physical_size == 0:
            return True, None

        try:
            with zipfile.ZipFile(file_path, "r") as zf:
                total_uncompressed = 0

                for info in zf.infolist():
                    filename = info.filename.replace("\\", "/")

                    # 1. Zip Slip check (traversal tokens, root slashes, Windows drive letters)
                    if ".." in filename or filename.startswith("/") or re.match(r"^[a-zA-Z]:", filename):
                        return False, f"Zip Slip path traversal detected: {info.filename}"

                    # 2. Symlink check via POSIX external_attr (prevents symlink-based traversal)
                    mode = info.external_attr >> 16
                    if mode != 0 and stat.S_ISLNK(mode):
                        return False, f"Zip Slip symlink entry detected: {info.filename}"

                    total_uncompressed += info.file_size

                # 3. Maximum uncompressed limit
                if total_uncompressed > self.max_uncompressed_bytes:
                    return False, f"Archive uncompressed size ({total_uncompressed} bytes) exceeds limit ({self.max_uncompressed_bytes} bytes)"

                # 4. Overlapping header bomb defense: compute ratio against physical file size
                ratio = total_uncompressed / physical_size
                if ratio > self.max_ratio:
                    return False, f"Zip bomb pattern detected! Physical ratio {ratio:.1f}:1 exceeds safe threshold {self.max_ratio}:1"

            return True, None
        except Exception as err:
            return False, f"Failed to inspect zip archive: {str(err)}"

    def _inspect_tar(self, file_path: Path) -> Tuple[bool, Optional[str]]:
        physical_size = file_path.stat().st_size
        if physical_size == 0:
            return True, None

        try:
            with tarfile.open(file_path, "r:*") as tf:
                total_uncompressed = 0

                for member in tf.getmembers():
                    filename = member.name.replace("\\", "/")

                    # Tar Slip check
                    if ".." in filename or filename.startswith("/") or re.match(r"^[a-zA-Z]:", filename):
                        return False, f"Tar Slip path traversal detected: {member.name}"

                    # Symlink / Hardlink / Device Node check
                    if member.issym() or member.islnk():
                        return False, f"Tar symlink/hardlink detected: {member.name}"
                    if member.isdev() or member.ischr() or member.isfifo():
                        return False, f"Dangerous device or FIFO member in tar: {member.name}"

                    total_uncompressed += member.size

                if total_uncompressed > self.max_uncompressed_bytes:
                    return False, f"Tar uncompressed size exceeds limit"

                ratio = total_uncompressed / max(physical_size, 1)
                if ratio > self.max_ratio:
                    return False, f"Tar bomb pattern detected! Ratio {ratio:.1f}:1 exceeds limit"

            return True, None
        except Exception as err:
            return False, f"Failed to inspect tar archive: {str(err)}"
