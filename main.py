#!/usr/bin/env python3
"""Standard application entrypoint pointing to run.py.

Usage:
    python3 main.py --help
    python3 main.py sync
"""

from run import cli

if __name__ == "__main__":
    cli()
