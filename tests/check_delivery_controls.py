"""Run fresh, bounded portability controls and emit one verifier JSON result."""
from __future__ import annotations

from contextlib import redirect_stdout
import json
import sys
import unittest

from tests.test_sqlite_paths import NAMES


def check():
    modules = ('tests.test_sqlite_paths', 'tests.test_verify_interruption')
    suite = unittest.defaultTestLoader.loadTestsFromNames(modules)
    registered = suite.countTestCases()
    with redirect_stdout(sys.stderr):
        observed = unittest.TextTestRunner(stream=sys.stderr, verbosity=2).run(suite)
    complete = observed.wasSuccessful() and not observed.skipped and observed.testsRun == registered == 4
    result = {
        'status': 'PASS' if complete else ('FAIL' if not observed.wasSuccessful() else 'INCOMPLETE'),
        'assurance': 'Fresh SQLite path and verifier process controls; no research workload or performance measurement.',
        'optimization': sys.flags.optimize,
        'registered_test_methods': registered,
        'executed_test_methods': observed.testsRun,
        'test_failures': len(observed.failures),
        'test_errors': len(observed.errors),
        'skipped_test_methods': len(observed.skipped),
        'verified_counts': {
            'path_names': len(NAMES),
            'absolute_and_relative_forms_per_name': 2,
            'read_only_source_connections': len(NAMES) * 2 * 5,
            'missing_source_rejections_without_file_creation': len(NAMES) * 2 * 4,
            'sigint_process_group_controls': 1,
            'timeout_process_group_controls': 1,
            'processes_per_group': 2,
        } if complete else None,
    }
    return result


if __name__ == '__main__':
    result = check()
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result['status'] == 'PASS' else 1)
