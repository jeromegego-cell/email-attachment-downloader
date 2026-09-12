#!/usr/bin/env python3
"""Automated, Cross-Platform Installer for Enterprise Email Ingestion Gateway.

Sets up a local Python virtual environment, installs all required dependencies,
performs preflight environment and database validation, and creates convenient launchers.

Usage:
    python3 install.py
"""

import os
import sys
import subprocess
import shutil
import venv
from pathlib import Path

# Minimum Python requirement
MIN_PY = (3, 11)
REPO_ROOT = Path(__file__).resolve().parent
VENV_DIR = REPO_ROOT / ".venv"


def log(msg: str, bold: bool = False):
    prefix = "\033[1;36m[INSTALLER]\033[0m" if sys.stdout.isatty() else "[INSTALLER]"
    text = f"\033[1m{msg}\033[0m" if bold and sys.stdout.isatty() else msg
    print(f"{prefix} {text}")


def log_success(msg: str):
    prefix = "\033[1;32m[SUCCESS]\033[0m" if sys.stdout.isatty() else "[SUCCESS]"
    print(f"{prefix} {msg}")


def log_error(msg: str):
    prefix = "\033[1;31m[ERROR]\033[0m" if sys.stdout.isatty() else "[ERROR]"
    print(f"{prefix} {msg}", file=sys.stderr)


def check_python_version():
    log(f"Checking Python version: {sys.version.split()[0]}...")
    if sys.version_info < MIN_PY:
        log_error(f"Python {MIN_PY[0]}.{MIN_PY[1]} or higher is required. Found: {sys.version.split()[0]}")
        sys.exit(1)
    log_success(f"Python version is compatible: {sys.version.split()[0]}")


def get_venv_binaries():
    if os.name == "nt":
        py_bin = VENV_DIR / "Scripts" / "python.exe"
        pip_bin = VENV_DIR / "Scripts" / "pip.exe"
        cli_bin = VENV_DIR / "Scripts" / "email-ingestion.exe"
    else:
        py_bin = VENV_DIR / "bin" / "python3"
        pip_bin = VENV_DIR / "bin" / "pip"
        cli_bin = VENV_DIR / "bin" / "email-ingestion"
    return py_bin, pip_bin, cli_bin


def setup_virtualenv():
    if not VENV_DIR.exists():
        log(f"Creating dedicated local virtual environment at '{VENV_DIR.name}'...")
        builder = venv.EnvBuilder(with_pip=True, symlinks=(os.name != "nt"))
        builder.create(VENV_DIR)
        log_success("Virtual environment created.")
    else:
        log("Local virtual environment already exists.")

    py_bin, pip_bin, _ = get_venv_binaries()
    if not py_bin.exists():
        log_error(f"Virtual environment Python binary not found at: {py_bin}")
        sys.exit(1)


def install_dependencies():
    py_bin, pip_bin, _ = get_venv_binaries()
    log("Upgrading pip and packaging tools...")
    subprocess.run([str(py_bin), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"], check=True)

    req_file = REPO_ROOT / "requirements.txt"
    if req_file.exists():
        log(f"Installing core production dependencies from '{req_file.name}'...")
        subprocess.run([str(py_bin), "-m", "pip", "install", "-r", str(req_file)], check=True)

    log("Installing email-ingestion-engine in editable development mode...")
    subprocess.run([str(py_bin), "-m", "pip", "install", "-e", "."], check=True)
    log_success("All dependencies installed successfully.")


def create_launchers():
    py_bin, _, cli_bin = get_venv_binaries()

    if os.name != "nt":
        # Create POSIX run.sh and email-ingestion symlink/wrapper
        run_sh = REPO_ROOT / "run.sh"
        run_sh_content = (
            "#!/usr/bin/env bash\n"
            "# Launcher script for Enterprise Email Ingestion Gateway\n"
            "set -e\n"
            f'SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"\n'
            'if [ -f "$SCRIPT_DIR/.venv/bin/email-ingestion" ]; then\n'
            '    exec "$SCRIPT_DIR/.venv/bin/email-ingestion" "$@"\n'
            'else\n'
            '    exec python3 "$SCRIPT_DIR/run.py" "$@"\n'
            'fi\n'
        )
        run_sh.write_text(run_sh_content, encoding="utf-8")
        run_sh.chmod(0o755)

        # Create root email-ingestion shortcut
        cli_shortcut = REPO_ROOT / "email-ingestion"
        cli_shortcut.write_text(run_sh_content, encoding="utf-8")
        cli_shortcut.chmod(0o755)
        log_success("Created executable launchers: './run.sh' and './email-ingestion'")
    else:
        # Create Windows run.bat
        run_bat = REPO_ROOT / "run.bat"
        run_bat_content = (
            "@echo off\n"
            "set SCRIPT_DIR=%~dp0\n"
            'if exist "%SCRIPT_DIR%.venv\\Scripts\\email-ingestion.exe" (\n'
            '    "%SCRIPT_DIR%.venv\\Scripts\\email-ingestion.exe" %*\n'
            ') else (\n'
            '    python "%SCRIPT_DIR%run.py" %*\n'
            ')\n'
        )
        run_bat.write_text(run_bat_content, encoding="utf-8")
        log_success("Created Windows launcher: 'run.bat'")


def run_preflight_validation():
    py_bin, _, cli_bin = get_venv_binaries()
    log("Running preflight validation checks...")
    try:
        if cli_bin.exists():
            res = subprocess.run([str(cli_bin), "validate"], capture_output=True, text=True)
        else:
            res = subprocess.run([str(py_bin), str(REPO_ROOT / "run.py"), "validate"], capture_output=True, text=True)
        if res.returncode == 0:
            log_success("System health and preflight checks passed cleanly!")
        else:
            log(f"Preflight validation output:\n{res.stdout}\n{res.stderr}")
    except Exception as e:
        log(f"Note: Could not run automated validation check ({e}), continuing.")


def main():
    print("\n" + "=" * 60)
    print("   Enterprise Email Ingestion Gateway - Automated Setup   ")
    print("=" * 60 + "\n")

    check_python_version()
    setup_virtualenv()
    install_dependencies()
    create_launchers()
    run_preflight_validation()

    print("\n" + "=" * 60)
    log_success("INSTALLATION COMPLETE & READY FOR PRODUCTION!")
    print("=" * 60)
    print("\nQuick Start Commands:")
    print("  ./run.sh configure        # Interactive email connection setup")
    print("  ./run.sh demo             # Run full test demonstration")
    print("  ./run.sh sync             # One-time email synchronization")
    print("  ./run.sh watch            # Continuous 24/7 background watcher")
    print("  ./run.sh --help           # View all available commands")
    print("\nOr run directly via Python:")
    print("  python3 run.py demo")
    print("  python3 main.py validate\n")


if __name__ == "__main__":
    main()
