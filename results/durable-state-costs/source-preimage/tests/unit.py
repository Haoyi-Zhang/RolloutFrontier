"""Run the discoverable standard-library unit suite and emit bounded JSON."""
from __future__ import annotations

import io
import json
import resource
import sys
import time
import unittest


def run() -> dict:
    begin = time.perf_counter()
    cpu = time.process_time()
    suite = unittest.defaultTestLoader.discover("tests", pattern="test_*.py")
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    if not result.wasSuccessful():
        sys.stderr.write(stream.getvalue())
        raise AssertionError("discoverable unit suite failed")
    return {
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "cpu_seconds": time.process_time() - cpu,
        "wall_seconds": time.perf_counter() - begin,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True))
