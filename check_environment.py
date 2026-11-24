#!/usr/bin/env python3
"""Report the current artifact environment and optionally require the retained one."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import platform
import signal
import sqlite3
import sys

ROOT = Path(__file__).resolve().parent
EXPECTED = json.loads((ROOT / "environment-retained.json").read_text())


def protobuf_version():
    try:
        import google.protobuf  # type: ignore
    except Exception as error:
        return None, f"{type(error).__name__}: {error}"
    return getattr(google.protobuf, "__version__", None), None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict-retained", action="store_true",
                        help="exit nonzero unless Python, protobuf and SQLite match the retained campaign")
    args = parser.parse_args()
    protobuf, protobuf_error = protobuf_version()
    current = {
        "python": platform.python_version(),
        "python_executable": sys.executable,
        "protobuf": protobuf,
        "protobuf_import_error": protobuf_error,
        "sqlite": sqlite3.sqlite_version,
        "platform": platform.platform(),
        "posix_signals": all(hasattr(signal, name) for name in ("SIGTERM", "SIGKILL", "SIGINT")),
    }
    matches = {
        "python": current["python"] == EXPECTED["python"],
        "protobuf": current["protobuf"] == EXPECTED["protobuf"],
        "sqlite": current["sqlite"] == EXPECTED["sqlite"],
    }
    report = {
        "status": "MATCH" if all(matches.values()) else "DIFFERENT",
        "strict_requested": args.strict_retained,
        "expected": EXPECTED,
        "current": current,
        "matches": matches,
        "interpretation": (
            "Exact retained environment." if all(matches.values()) else
            "Usable only as a separately labelled host-environment run; do not call it the retained fixed environment."
        ),
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if (not args.strict_retained or all(matches.values())) else 2


if __name__ == "__main__":
    raise SystemExit(main())
