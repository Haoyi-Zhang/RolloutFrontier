"""Owned SQLite write-failure conformance; no remote or power-loss experiment."""
from copy import deepcopy
from contextlib import ExitStack
import argparse
import asyncio
import hashlib
from pathlib import Path
import json
import os
import platform
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

from src.controller import Endpoint
from src.network import Network

TRANSITIONS = ('prepare', 'close', 'install', 'merge')
RECORDS = []


def transition(endpoint, name):
    if name == 'prepare':
        return endpoint.prepare(0, 2, 'owned-next', ['a'])
    if name == 'close':
        return endpoint.close(0, 1)
    if name == 'install':
        return endpoint.install(['a', 'b'])
    return endpoint.merge(dict(node=1, generation=1, support=['b']))


class PersistenceFailureTests(unittest.TestCase):
    def test_write_abort_preserves_live_and_durable_state_and_stops_replies(self):
        for name in TRANSITIONS:
            with self.subTest(transition=name), ExitStack() as stack:
                tmp = stack.enter_context(tempfile.TemporaryDirectory(dir=os.environ.get('P011_TEST_TMP')))
                path = Path(tmp) / 'owned.sqlite'
                endpoint = Endpoint(0, ['a'], path)
                stack.callback(endpoint.disconnect)
                endpoint.prepare(0, 1, 'owned-held', ['a'])
                before = deepcopy(endpoint.state)
                endpoint.db.execute("CREATE TRIGGER owned_abort BEFORE INSERT ON state BEGIN SELECT RAISE(ABORT, 'owned write abort'); END")
                endpoint.db.commit()
                with self.assertRaises(sqlite3.DatabaseError):
                    transition(endpoint, name)
                self.assertEqual(endpoint.state, before)
                disk = json.loads(endpoint.db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
                self.assertEqual(disk, before)
                for operation in (lambda: transition(endpoint,name), lambda: endpoint.profile(), lambda: endpoint.handle({'op':'inspect'}),
                                  lambda: endpoint.prepare(0,1,'owned-held',['a']), lambda: endpoint.use(0,1,'owned-held')):
                    with self.assertRaisesRegex(sqlite3.DatabaseError, 'reopen'):
                        operation()
                endpoint.disconnect()
                recovered = Endpoint(0, ['a'], path)
                stack.callback(recovered.disconnect)
                self.assertEqual(recovered.state, before)
                self.assertEqual(recovered.use(0,1,'owned-held')['status'], 'used')
                RECORDS.append(dict(kind='actual SQLite trigger abort', transition=name,
                                    before=before, live=deepcopy(endpoint.state), disk=disk,
                                    recovered=deepcopy(recovered.state), acknowledged=False))

    def test_uncertain_post_commit_failure_requires_reopen_and_recovers_committed_state(self):
        for name in TRANSITIONS:
            with self.subTest(transition=name), ExitStack() as stack:
                tmp = stack.enter_context(tempfile.TemporaryDirectory(dir=os.environ.get('P011_TEST_TMP')))
                path = Path(tmp) / 'owned.sqlite'
                endpoint = Endpoint(0,['a'],path)
                stack.callback(endpoint.disconnect)
                endpoint.prepare(0,1,'owned-held',['a'])
                before = deepcopy(endpoint.state)
                actual = endpoint.persist

                def completed_then_error():
                    actual()
                    raise sqlite3.OperationalError('owned uncertain completion control')

                with mock.patch.object(endpoint, 'persist', side_effect=completed_then_error):
                    with self.assertRaises(sqlite3.DatabaseError):
                        transition(endpoint, name)
                self.assertEqual(endpoint.state, before)
                with self.assertRaisesRegex(sqlite3.DatabaseError, 'reopen'):
                    endpoint.profile()
                disk = json.loads(endpoint.db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
                self.assertNotEqual(disk,before)
                endpoint.disconnect()
                recovered = Endpoint(0,['a'],path)
                stack.callback(recovered.disconnect)
                self.assertEqual(recovered.state,disk)
                RECORDS.append(dict(kind='simulated exception after actual commit', transition=name,
                                    before=before, live=deepcopy(endpoint.state), disk=disk,
                                    recovered=deepcopy(recovered.state), acknowledged=False))

    def test_owned_tcp_failure_response_and_durable_reopen(self):
        async def scenario():
            with tempfile.TemporaryDirectory(dir=os.environ.get('P011_TEST_TMP')) as tmp:
                network = Network(Path(tmp), [['a']], policy='predicate')
                await network.start()
                try:
                    endpoint = network.nodes[0]
                    endpoint.db.execute("CREATE TRIGGER owned_abort BEFORE INSERT ON state BEGIN SELECT RAISE(ABORT, 'owned write abort'); END")
                    endpoint.db.commit()
                    request = dict(op='prepare',origin=0,sequence=1,manifest='owned-tcp',requires=['a'])
                    failed = await network.rpc(0,0,request)
                    self.assertEqual(failed,dict(status='unavailable',reason='durable-state-reopen-required'))
                    retry = await network.rpc(0,0,request)
                    self.assertEqual(retry,failed)
                    endpoint.db.execute('DROP TRIGGER owned_abort')
                    endpoint.db.commit()
                    await network.crash(0)
                    recovered = await network.rpc(0,0,request)
                    self.assertEqual(recovered['status'],'held')
                    RECORDS.append(dict(kind='actual owned loopback TCP with SQLite abort',
                                        request=request, first_reply=failed, retry_reply=retry,
                                        recovered_reply=recovered, trace=deepcopy(network.trace)))
                finally:
                    await network.stop()
        asyncio.run(scenario())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path)
    args = parser.parse_args()
    if args.report is not None and args.report.exists():
        parser.error('report must not exist')
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(PersistenceFailureTests))
    root = Path(__file__).resolve().parents[1]
    paths = ('src/controller.py','src/network.py','tests/cost_endpoint.py','tests/persistence_failures.py')
    report = dict(outcome='PASS' if result.wasSuccessful() else 'FAIL',tests=result.testsRun,
                  failure_count=len(result.failures),error_count=len(result.errors),records=RECORDS,
                  environment=dict(python=sys.version,sqlite=sqlite3.sqlite_version,platform=platform.platform(),argv=sys.argv),
                  source_bindings=[dict(path=name,sha256=hashlib.sha256((root/name).read_bytes()).hexdigest()) for name in paths],
                  scope='Owned local SQLite transactions and loopback TCP; post-commit uncertainty is a control exception, not actual power loss, disk hardware failure or a remote vulnerability')
    if args.report is not None:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:report[key] for key in ('outcome','tests','failure_count','error_count','scope')}))
    raise SystemExit(0 if result.wasSuccessful() else 1)
