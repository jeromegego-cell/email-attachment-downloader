"""Document similarity and revision detection engine.

Compares same-name files across emails from the same sender to distinguish
between minor revisions (v1 -> v2) and completely unrelated documents.
Guards against CPU exhaustion by capping text comparisons to 100 KB.
"""

import difflib
from pathlib import Path
from typing import Tuple, Optional


class DocumentSimilarityEngine:
    """Calculates similarity metrics and generates change diffs between file versions."""

    def __init__(self, threshold: float = 0.80):
        self.threshold = threshold

    @staticmethod
    def _read_sample_text(file_path: Path, max_bytes: int = 102400) -> Optional[str]:
        """Try reading a file as UTF-8 or Latin-1 text up to 100KB."""
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read(max_bytes)
        except Exception:
            return None

    def compare_files(
        self,
        original_file_path: Path,
        new_file_path: Path
    ) -> Tuple[bool, float, Optional[str]]:
        """Compare an existing file with a newly downloaded file sharing the same name.
        
        Returns:
            Tuple of (is_revision: bool, similarity_score: float, diff_content: Optional[str])
        """
        if not original_file_path.exists() or not new_file_path.exists():
            return False, 0.0, None

        # Attempt textual diff if both are readable as text
        orig_text = self._read_sample_text(original_file_path)
        new_text = self._read_sample_text(new_file_path)

        if orig_text is not None and new_text is not None and (orig_text or new_text):
            matcher = difflib.SequenceMatcher(None, orig_text, new_text)
            similarity_ratio = matcher.quick_ratio()
            if similarity_ratio < self.threshold:
                return False, similarity_ratio, None

            # Accurate ratio
            similarity_ratio = matcher.ratio()
            is_revision = similarity_ratio >= self.threshold

            # Generate unified diff text if they are similar revisions
            diff_text = None
            if is_revision and similarity_ratio < 1.0:
                diff_lines = list(difflib.unified_diff(
                    orig_text.splitlines(keepends=True),
                    new_text.splitlines(keepends=True),
                    fromfile=str(original_file_path.name),
                    tofile=str(new_file_path.name),
                    n=3
                ))
                diff_text = "".join(diff_lines)

            return is_revision, similarity_ratio, diff_text

        # For non-text / binary files, fast check to avoid O(N*M) CPU exhaustion
        try:
            with open(original_file_path, "rb") as f1, open(new_file_path, "rb") as f2:
                b1 = f1.read(8192)  # Read 8KB sample
                b2 = f2.read(8192)
            if b1 == b2:
                return True, 1.0, None
            return False, 0.0, None
        except Exception:
            return False, 0.0, None
