#!/usr/bin/env python3
"""Command-line wrapper for ZM Wall stream diagnostics."""

import os
import sys
from zmwall import __version__
from zmwall.core import detect_decode_hardware
from zmwall.diagnostics import diagnose_camera


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] in {"-h", "--help"}:
        raise SystemExit(
            "Verwendung: sudo -u zmwall /opt/zmwall/.venv/bin/python "
            "/opt/zmwall/diagnose-stream.py KAMERA-ID"
        )
    try:
        print(diagnose_camera(
            os.getenv("ZMWALL_DB", "/var/lib/zmwall/zmwall.db"),
            sys.argv[1], __version__, detect_decode_hardware(),
        ), end="")
    except ValueError as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
