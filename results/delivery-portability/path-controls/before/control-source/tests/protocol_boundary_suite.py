"""Run and preserve the curated protocol/owned-effect boundary regression suite.

Use a fresh output directory. This records local conformance tests, including
controlled failures and same-host process loss; it is not a timing benchmark.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import platform
import shutil
import sqlite3
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
MODULES=('tests.cancellation_lifecycle','tests.recovery_type_aliases',
         'tests.origin_serialization','tests.effect_drain','tests.closed_objects',
         'tests.persistence_failures','tests.origin_persistence_failures',
         'tests.receipt_snapshots','tests.window_types',
         'tests.live_certificate_types','tests.effect_registration')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',required=True,type=Path)
    args=parser.parse_args();out=args.out.resolve()
    if out.exists() or out==ROOT or ROOT in out.parents and any(
            out.is_relative_to(ROOT/name) for name in ('src','tests','data')):
        parser.error('out must be a fresh directory outside protected inputs')
    out.mkdir(parents=True)
    paths=sorted(set(p.relative_to(ROOT).as_posix() for p in (ROOT/'src').glob('*.py')) |
                 {m.replace('.','/')+'.py' for m in MODULES} |
                 {'tests/memory_lifecycle.py','tests/optimizer_benchmark.py',
                  'tests/full_path_costs.py','tests/protocol_boundary_suite.py'})
    before={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in paths}
    for name in paths:
        target=out/'source-preimage'/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/name,target)
    modules=[importlib.import_module(name) for name in MODULES]
    suites=[unittest.defaultTestLoader.loadTestsFromModule(module) for module in modules]
    counts={name:suite.countTestCases() for name,suite in zip(MODULES,suites)}
    with (out/'unittest.log').open('w',encoding='utf-8') as log:
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(unittest.TestSuite(suites))
    after={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in paths}
    unchanged=before==after
    report=dict(status='PASS' if result.wasSuccessful() and unchanged else 'FAIL',
                tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),
                skipped=len(result.skipped),tests_by_module=counts,
                source_sha256=before,source_bytes_unchanged_during_run=unchanged,
                environment=dict(python=sys.version,optimized=sys.flags.optimize,
                                 platform=platform.platform(),sqlite=sqlite3.sqlite_version),
                observations={module.__name__:module.RECORDS for module in modules
                              if hasattr(module,'RECORDS')},
                scope='Actual local SQLite and TCP; deterministic schema, lifetime and failure controls. '
                      'SIGKILL cuts are same-host process loss. No physical power-loss or production claim.')
    (out/'verification.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({key:report[key] for key in ('status','tests','failures','errors','skipped',
                                                 'source_bytes_unchanged_during_run')}))
    raise SystemExit(0 if report['status']=='PASS' else 1)


if __name__=='__main__':main()
