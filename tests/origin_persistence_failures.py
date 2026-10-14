"""Owned origin transaction controls with actual loopback owners and SQLite."""
import asyncio
import argparse
from copy import deepcopy
import json
import hashlib
from pathlib import Path
import sqlite3
import platform
import sys
import tempfile
import unittest
from unittest import mock

from src.network import Client, Network
RECORDS = []


def target(image, phase):
    state = image['attempts'].get('1', {}).get('status')
    return state == {'allocation':'acquiring','commit':'committed','retire':'retiring','cleanup':None}[phase]


class OriginPersistenceFailureTests(unittest.TestCase):
    def test_origin_write_abort_and_uncertain_completion_stop_authorization(self):
        async def scenario(mode,phase,post_commit):
            with tempfile.TemporaryDirectory() as tmp:
                net = Network(Path(tmp),[['a']],policy='predicate')
                await net.start()
                client = Client(net)
                branches = [{'0':['a']}]
                async def acquire():
                    if mode == 'fixed':
                        return await client.acquire('owned-origin',branches)
                    return await client.acquire_box('owned-origin',branches,{'0':[['a']]})
                try:
                    certificate = None
                    if phase in ('retire','cleanup'):
                        certificate = (await acquire())['certificate']
                    actual = client.persist
                    pre_commit = []
                    def controlled_write():
                        pending = getattr(client,'_pending_state',None)
                        image = client.state if pending is None else pending
                        if target(image,phase):
                            pre_commit.append(json.loads(client.db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0]))
                            if not post_commit:
                                client.db.execute("CREATE TRIGGER owned_abort BEFORE INSERT ON state BEGIN SELECT RAISE(ABORT, 'owned origin abort'); END")
                                client.db.commit()
                            actual()
                            raise sqlite3.OperationalError('owned exception after actual origin commit')
                        actual()
                    with mock.patch.object(client,'persist',side_effect=controlled_write):
                        with self.assertRaises(sqlite3.DatabaseError):
                            if phase in ('retire','cleanup'):
                                await client.retire(certificate)
                            else:
                                await acquire()
                    self.assertEqual(len(pre_commit),1)
                    self.assertEqual(client.state,pre_commit[0])
                    disk = json.loads(client.db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
                    if post_commit:
                        self.assertNotEqual(disk,pre_commit[0])
                    else:
                        self.assertEqual(disk,pre_commit[0])
                        client.db.execute('DROP TRIGGER owned_abort')
                        client.db.commit()
                    trace_length = len(net.trace)
                    for operation in (acquire,client.recover,lambda:client.use(certificate or {})):
                        with self.assertRaisesRegex(sqlite3.DatabaseError,'reopen'):
                            await operation()
                    self.assertEqual(len(net.trace),trace_length)
                    client.disconnect()
                    recovered = Client(net)
                    try:
                        self.assertEqual(recovered.state,disk)
                        await recovered.recover()
                        if disk['attempts'].get('1',{}).get('status') != 'committed':
                            self.assertEqual(recovered.state['attempts'],{})
                        RECORDS.append(dict(mode=mode,phase=phase,
                                            control='simulated error after actual commit' if post_commit else 'actual SQLite trigger abort',
                                            before_write=pre_commit[0],live_after_error=deepcopy(client.state),
                                            disk_after_error=disk,recovered=deepcopy(recovered.state),
                                            trace=deepcopy(net.trace),later_authorization_stopped=True))
                    finally:
                        recovered.disconnect()
                finally:
                    client.disconnect()
                    await net.stop()
        for mode in ('fixed','envelope'):
            for phase in ('allocation','commit','retire','cleanup'):
                for post_commit in (False,True):
                    with self.subTest(mode=mode,phase=phase,post_commit=post_commit):
                        asyncio.run(scenario(mode,phase,post_commit))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path)
    args=parser.parse_args()
    if args.report is not None and args.report.exists():
        parser.error('report must not exist')
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(OriginPersistenceFailureTests))
    root=Path(__file__).resolve().parents[1]
    report=dict(outcome='PASS' if result.wasSuccessful() else 'FAIL',tests=result.testsRun,
                failure_count=len(result.failures),error_count=len(result.errors),records=RECORDS,
                environment=dict(python=sys.version,platform=platform.platform(),sqlite=sqlite3.sqlite_version,argv=sys.argv),
                source_bindings=[dict(path=name,sha256=hashlib.sha256((root/name).read_bytes()).hexdigest())
                                 for name in ('src/controller.py','src/network.py','tests/origin_persistence_failures.py')],
                scope='16 owned local origin controls with SQLite and loopback owners; postcommit uncertainty is simulated, not physical power loss')
    if args.report is not None:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:report[key] for key in ('outcome','tests','failure_count','error_count','scope')}))
    raise SystemExit(0 if result.wasSuccessful() else 1)
