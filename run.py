#!/usr/bin/env python3
"""Standalone Source Runner for Enterprise Email Ingestion Gateway.

Enables running all email-ingestion CLI commands directly from the source repository
without requiring system-wide package installation or manual PYTHONPATH configuration.

Usage:
    python3 run.py sync
    python3 run.py watch
    python3 run.py demo
    python3 run.py configure
    python3 run.py validate
    python3 run.py --help
"""

import sys
from pathlib import Path

# Resolve repository root and add src/ directory to Python module search path
REPO_ROOT = Path(__file__).resolve().parent
SRC_DIR = REPO_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# If executed with system Python and a local .venv exists with installed packages,
# ensure virtualenv interpreter and site-packages are used seamlessly.
VENV_DIR = REPO_ROOT / ".venv"
if VENV_DIR.exists():
    import os
    py_bin = VENV_DIR / "bin" / "python3"
    if not py_bin.exists():
        py_bin = VENV_DIR / "Scripts" / "python.exe"
    if py_bin.exists() and Path(sys.executable).resolve() != py_bin.resolve():
        clean_env = os.environ.copy()
        clean_env.pop("PYTHONPATH", None)
        os.execve(str(py_bin), [str(py_bin), str(Path(__file__).resolve())] + sys.argv[1:], clean_env)

    import site
    for lib_dir in VENV_DIR.glob("lib/python*/site-packages"):
        sys.path.insert(1, str(lib_dir))
        site.addsitedir(str(lib_dir))
    for win_lib in VENV_DIR.glob("Lib/site-packages"):
        sys.path.insert(1, str(win_lib))
        site.addsitedir(str(win_lib))

try:
    from email_ingestion.cli import cli
except ImportError as e:
    sys.stderr.write(
        f"\n[ERROR] Required dependencies are missing: {e}\n"
        f"Please run the automated installer first:\n"
        f"    python3 install.py\n"
        f"or:\n"
        f"    ./install.sh\n\n"
    )
    sys.exit(1)

if __name__ == "__main__":
    cli()
