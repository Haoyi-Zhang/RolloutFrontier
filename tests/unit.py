"""Run every ``test_*.py`` module in an isolated standard-library process.

Process-heavy runtime tests and verifier-interruption tests must not share
interpreter state. The parent binds the exact discovered test IDs and test-module
bytes, executes each module in a fresh child, and fails closed on nonzero exit,
malformed output, timeout, duplicate IDs, or a surviving descendant process.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import io
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE_WALL_TIMEOUT_SECONDS = 180


def iter_cases(suite: unittest.TestSuite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from iter_cases(item)
        else:
            yield item


def run_module(module: str) -> dict:
    begin = time.perf_counter()
    cpu = time.process_time()
    suite = unittest.defaultTestLoader.loadTestsFromName(module)
    test_ids = sorted(case.id() for case in iter_cases(suite))
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    if not result.wasSuccessful():
        sys.stderr.write(stream.getvalue())
        raise AssertionError(f"unit module failed: {module}")
    if result.testsRun != len(test_ids):
        raise AssertionError(f"discovered and executed counts differ: {module}")
    return {
        "module": module,
        "test_ids": test_ids,
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "cpu_seconds": time.process_time() - cpu,
        "wall_seconds": time.perf_counter() - begin,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }


def enable_child_subreaper() -> bool:
    """Keep abandoned grandchildren visible to this runner on Linux."""
    if not sys.platform.startswith("linux"):
        return False
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    return True


def process_table() -> dict[int, tuple[int, str]]:
    table: dict[int, tuple[int, str]] = {}
    for entry in Path("/proc").iterdir() if Path("/proc").is_dir() else ():
        if not entry.name.isdigit():
            continue
        try:
            parent = None
            state = "?"
            for line in (entry / "status").read_text().splitlines():
                if line.startswith("PPid:"):
                    parent = int(line.split()[1])
                elif line.startswith("State:"):
                    state = line.split()[1]
            if parent is not None:
                table[int(entry.name)] = (parent, state)
        except (FileNotFoundError, PermissionError, ProcessLookupError, ValueError):
            pass
    return table


def descendants(root: int, table: dict[int, tuple[int, str]] | None = None) -> list[int]:
    table = process_table() if table is None else table
    answer: list[int] = []
    frontier = [root]
    while frontier:
        parent = frontier.pop()
        children = sorted(pid for pid, (ppid, _) in table.items() if ppid == parent)
        answer.extend(children)
        frontier.extend(children)
    return answer


def live_descendants(root: int) -> list[int]:
    table = process_table()
    return [pid for pid in descendants(root, table) if table.get(pid, (0, "?"))[1] not in ("Z", "X")]


def kill_processes(pids: list[int]) -> None:
    for pid in reversed(pids):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def reap_children() -> None:
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if pid == 0:
            return


def run() -> dict:
    begin = time.perf_counter()
    parent_cpu = time.process_time()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    source_paths = sorted((ROOT / "tests").glob("test_*.py"))
    if not source_paths:
        raise AssertionError("no discoverable test modules")
    modules = [f"tests.{path.stem}" for path in source_paths]
    source_sha256 = {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source_paths
    }
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    subreaper_enabled = enable_child_subreaper()
    module_results = []
    test_ids = []
    for module in modules:
        command = [sys.executable, "-B", "-m", "tests.unit", "--module", module]
        with tempfile.TemporaryDirectory(prefix="rollout-unit-module-") as temporary:
            stdout_path = Path(temporary) / "stdout.json"
            stderr_path = Path(temporary) / "stderr.log"
            with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
                process = subprocess.Popen(
                    command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                    stdout=stdout, stderr=stderr, start_new_session=True,
                )
                try:
                    returncode = process.wait(timeout=MODULE_WALL_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired as error:
                    live = descendants(process.pid)
                    kill_processes(live)
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=5)
                    reap_children()
                    sys.stderr.write(stderr_path.read_text(errors="replace"))
                    raise AssertionError(
                        f"unit module exceeded {MODULE_WALL_TIMEOUT_SECONDS} seconds: {module}"
                    ) from error
            stdout_text = stdout_path.read_text(errors="replace")
            stderr_text = stderr_path.read_text(errors="replace")
        # With subreaping enabled, detached grandchildren from an exited module
        # become children of this process instead of disappearing under PID 1.
        # Reap terminated descendants first; only a process that remains live
        # after a bounded cleanup window is a module leak.
        live: list[int] = []
        if subreaper_enabled:
            deadline = time.monotonic() + 1.0
            while True:
                reap_children()
                live = live_descendants(os.getpid())
                if not live or time.monotonic() >= deadline:
                    break
                time.sleep(0.02)
        if live:
            kill_processes(live)
            time.sleep(0.05)
            reap_children()
            sys.stderr.write(stderr_text)
            raise AssertionError(
                f"unit module left live descendant processes {live}: {module}"
            )
        if returncode != 0:
            sys.stderr.write(stderr_text)
            raise AssertionError(f"unit module failed with exit {returncode}: {module}")
        try:
            answer = json.loads(stdout_text)
        except json.JSONDecodeError as error:
            sys.stderr.write(stdout_text + "\n" + stderr_text)
            raise AssertionError(f"unit module emitted invalid JSON: {module}") from error
        if answer.get("module") != module or any(
            answer.get(key) != 0 for key in ("failures", "errors")
        ):
            raise AssertionError(f"unit module result is inconsistent: {module}")
        module_results.append({
            key: answer[key]
            for key in ("module", "tests_run", "failures", "errors", "skipped")
        })
        test_ids.extend(answer["test_ids"])
    if len(test_ids) != len(set(test_ids)):
        raise AssertionError("duplicate discovered test ID")
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {
        "tests_run": len(test_ids),
        "test_ids": sorted(test_ids),
        "test_source_sha256": source_sha256,
        "module_results": module_results,
        "module_isolation": "fresh subprocess per test module",
        "linux_child_subreaper_enabled": subreaper_enabled,
        "module_wall_timeout_seconds": MODULE_WALL_TIMEOUT_SECONDS,
        "failures": sum(row["failures"] for row in module_results),
        "errors": sum(row["errors"] for row in module_results),
        "skipped": sum(row["skipped"] for row in module_results),
        "cpu_seconds": (time.process_time() - parent_cpu) +
                       (after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime),
        "wall_seconds": time.perf_counter() - begin,
        "peak_rss_kib": max(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                            after.ru_maxrss),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", help=argparse.SUPPRESS)
    args = parser.parse_args()
    answer = run_module(args.module) if args.module else run()
    print(json.dumps(answer, sort_keys=True))


if __name__ == "__main__":
    main()
