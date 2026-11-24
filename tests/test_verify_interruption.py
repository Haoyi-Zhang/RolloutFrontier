"""Bounded process controls for verifier interruption and timeout cleanup.

The fixture driver imports the actual verifier and registers two small control
tasks. It never runs research workloads or invokes the verifier recursively.
Set ROLLOUTFRONTIER_VERIFY_CONTROL_OUTPUT to a new directory to retain the
fixture scripts, process markers, reports, and both checker log streams.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKER = '''from pathlib import Path
import json, os, subprocess, sys, time
root = Path(sys.argv[1])
descendant = subprocess.Popen([sys.executable, '-B', '-u', '-c',
    "from pathlib import Path; import json,os,sys,time; "
    "Path(sys.argv[1]).write_text(json.dumps({'pid':os.getpid(),'group':os.getpgrp()})); "
    "print('control-descendant-ready',flush=True); time.sleep(60)",
    str(root / 'descendant.json')])
print('control-worker-ready', flush=True)
print('control-diagnostic', file=sys.stderr, flush=True)
(root / 'worker.json').write_text(json.dumps(
    {'pid':os.getpid(), 'group':os.getpgrp(), 'descendant':descendant.pid}))
time.sleep(60)
'''
REMAINING = '''from pathlib import Path
import json, sys
Path(sys.argv[1]).write_text('remaining control executed\\n')
print(json.dumps({'status':'PASS','scope':'verifier process control'}))
'''
DRIVER = '''from pathlib import Path
import signal, sys
import verify
# Background shells may start children with SIGINT ignored. Reset the fixture
# driver explicitly so this control measures the verifier's interruption path
# rather than the launcher's inherited signal disposition.
signal.signal(signal.SIGINT, signal.default_int_handler)
root, mode, limit = Path(sys.argv[1]), sys.argv[2], float(sys.argv[3])
verify.tasks = lambda: [
    {'name':'blocking-control', 'arguments':[str(root/'worker.py'),str(root)],
     'anchors':[], 'assurance':'bounded verifier process control', 'timeout_seconds':limit},
    {'name':'remaining-control', 'arguments':[str(root/'remaining.py'),str(root/'remaining.txt')],
     'anchors':[], 'assurance':'bounded verifier process control', 'timeout_seconds':5},
]
sys.argv = [str(verify.__file__), '--out', str(root/'report'), '--mode', mode]
raise SystemExit(verify.main())
'''


@unittest.skipUnless(os.name == 'posix' and shutil.which('ps'),
                     'Process-group controls require POSIX and ps')
class VerificationInterruptionTests(unittest.TestCase):
    def setUp(self):
        retained = os.environ.get('ROLLOUTFRONTIER_VERIFY_CONTROL_OUTPUT')
        if retained:
            self.path = Path(retained).resolve() / self._testMethodName
            self.path.mkdir(parents=True)
        else:
            temporary = tempfile.TemporaryDirectory(prefix='verifier-process-control-')
            self.addCleanup(temporary.cleanup)
            self.path = Path(temporary.name).resolve()
        (self.path / 'worker.py').write_text(WORKER)
        (self.path / 'remaining.py').write_text(REMAINING)
        (self.path / 'driver.py').write_text(DRIVER)
        self.mode = 'optimized' if sys.flags.optimize else 'normal'
        self.process = None
        self.addCleanup(self.cleanup_processes)

    @staticmethod
    def running(pid):
        observed = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)],
                                  capture_output=True, text=True, timeout=3)
        if observed.returncode not in (0, 1):
            raise RuntimeError(observed.stderr)
        state = observed.stdout.strip()
        return bool(state and state[0] not in ('Z', 'X'))

    def cleanup_processes(self):
        marker = self.path / 'worker.json'
        if marker.exists():
            worker = json.loads(marker.read_text())
            try:
                os.killpg(worker['group'], signal.SIGKILL)
            except ProcessLookupError:
                pass
        if self.process is not None and self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGKILL)
            self.process.wait(timeout=5)

    def launch(self, timeout):
        flags = ['-O', '-B'] if sys.flags.optimize else ['-B']
        command = [sys.executable, *flags, '-c', DRIVER, str(self.path), self.mode, str(timeout)]
        env = dict(os.environ)
        env.pop('PYTHONPATH', None)
        env['PYTHONNOUSERSITE'] = '1'
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        with (self.path / 'driver.stdout.log').open('wb') as stdout, \
                (self.path / 'driver.stderr.log').open('wb') as stderr:
            self.process = subprocess.Popen(command, cwd=ROOT, env=env,
                                            stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                            start_new_session=True)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            markers = (self.path / 'worker.json', self.path / 'descendant.json')
            if all(marker.is_file() for marker in markers):
                try:
                    worker, descendant = [json.loads(marker.read_text()) for marker in markers]
                except json.JSONDecodeError:
                    pass
                else:
                    self.assertEqual(worker['pid'], worker['group'])
                    self.assertEqual(worker['descendant'], descendant['pid'])
                    self.assertEqual(worker['group'], descendant['group'])
                    self.assertNotEqual(worker['group'], self.process.pid)
                    self.assertTrue(self.running(worker['pid']))
                    self.assertTrue(self.running(descendant['pid']))
                    report = json.loads((self.path / 'report/report.json').read_text())
                    self.assertEqual(report['status'], 'RUNNING')
                    self.assertEqual(report['checks'], [])
                    return worker, descendant
            if self.process.poll() is not None:
                self.fail('Verifier exited before both control processes started: ' +
                          (self.path / 'driver.stderr.log').read_text())
            time.sleep(0.02)
        self.fail('Verifier control processes did not start within five seconds')

    def check_stopped(self, worker, descendant):
        pids = (worker['pid'], descendant['pid'])
        deadline = time.monotonic() + 3
        while any(self.running(pid) for pid in pids) and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertFalse(any(self.running(pid) for pid in pids), 'Checker group remains active')

    def read_report(self):
        report = json.loads((self.path / 'report/report.json').read_text())
        self.assertEqual(report['status'], 'INCOMPLETE')
        self.assertIn('finished_utc', report)
        self.assertTrue(report['code_unchanged'])
        self.assertEqual(report['artifact_root'], str(ROOT))
        self.assertFalse((self.path / 'report/report.json.tmp').exists())
        first = report['checks'][0]
        self.assertIsNone(first['result'])
        self.assertIn('control-worker-ready',
                      (self.path / 'report' / first['stdout_path']).read_text())
        self.assertIn('control-descendant-ready',
                      (self.path / 'report' / first['stdout_path']).read_text())
        self.assertIn('control-diagnostic',
                      (self.path / 'report' / first['stderr_path']).read_text())
        return report

    def test_sigint_stops_group_and_finalizes_report(self):
        worker, descendant = self.launch(timeout=30)
        os.kill(self.process.pid, signal.SIGINT)
        self.assertEqual(self.process.wait(timeout=8), 130)
        self.check_stopped(worker, descendant)
        report = self.read_report()
        self.assertEqual(report['exit_code'], 130)
        self.assertEqual([row['status'] for row in report['checks']], ['INTERRUPTED', 'NOT_RUN'])
        self.assertEqual(report['counts'], {'INTERRUPTED': 1, 'NOT_RUN': 1})
        self.assertEqual(report['checks'][1]['reason'], 'Verification interrupted')
        self.assertFalse((self.path / 'remaining.txt').exists())

    def test_timeout_stops_group_and_preserves_remaining_check(self):
        worker, descendant = self.launch(timeout=3)
        self.assertEqual(self.process.wait(timeout=8), 2)
        self.check_stopped(worker, descendant)
        report = self.read_report()
        self.assertEqual(report['exit_code'], 2)
        self.assertEqual([row['status'] for row in report['checks']], ['TIMEOUT', 'PASS'])
        self.assertEqual(report['counts'], {'TIMEOUT': 1, 'PASS': 1})
        self.assertEqual((self.path / 'remaining.txt').read_text(), 'remaining control executed\n')


if __name__ == '__main__':
    unittest.main()
