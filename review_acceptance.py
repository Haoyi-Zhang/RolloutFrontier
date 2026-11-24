#!/usr/bin/env python3
"""Run the bounded reviewer-facing acceptance checks as isolated invocations."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
DEFAULT_CHECKS = (
    "sources", "goal-planning", "priority-counterexample", "factored-planning",
    "factored-scale", "application-planning", "application-rollout",
    "phase-granularity", "direct", "recovery", "kubernetes-skew", "publication",
)


def run_one(check: str, mode: str, out: Path, timeout: int) -> dict:
    target = out / check
    target.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, "-B", str(ROOT / "verify.py"), "--mode", mode,
               "--checks", check, "--out", str(target / "report")]
    stdout_path, stderr_path = target / "stdout.log", target / "stderr.log"
    start = time.monotonic()
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                                   stdout=stdout, stderr=stderr, start_new_session=True,
                                   env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            return {"check": check, "status": "TIMEOUT", "seconds": time.monotonic()-start,
                    "command": command, "timeout_seconds": timeout}
    reports = sorted((target / "report").glob("report.json"))
    if not reports:
        return {"check": check, "status": "NO_REPORT", "exit_code": code,
                "seconds": time.monotonic()-start, "command": command}
    report = json.loads(reports[-1].read_text())
    expected_passes = 2 if mode == "both" else 1
    passed = report.get("counts", {}).get("PASS", 0)
    failed = report.get("counts", {}).get("FAIL", 0)
    status = "PASS" if passed == expected_passes and failed == 0 else "FAIL"
    return {"check": check, "status": status, "exit_code": code,
            "seconds": time.monotonic()-start, "passes": passed, "failures": failed,
            "report": str(reports[-1].relative_to(out)), "command": command}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="new output directory")
    parser.add_argument("--mode", choices=("normal", "optimized", "both"), default="both")
    parser.add_argument("--checks", help="comma-separated override")
    parser.add_argument("--timeout", type=int, default=300, help="per-check wall timeout")
    args = parser.parse_args()
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        parser.error("output directory must be new or empty")
    out.mkdir(parents=True, exist_ok=True)
    checks = tuple(x.strip() for x in args.checks.split(",") if x.strip()) if args.checks else DEFAULT_CHECKS
    results = []
    for index, check in enumerate(checks, 1):
        print(f"[{index:02d}/{len(checks):02d}] {check}", file=sys.stderr, flush=True)
        results.append(run_one(check, args.mode, out, args.timeout))
    summary = {"status": "PASS" if all(x["status"] == "PASS" for x in results) else "FAIL",
               "mode": args.mode, "checks": list(checks), "results": results}
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
