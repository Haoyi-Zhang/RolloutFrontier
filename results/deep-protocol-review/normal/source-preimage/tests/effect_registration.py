"""Owned registration failures cannot strand a newly committed protocol hold.

The suite uses real loopback TCP and SQLite. The two process cuts deliberately
SIGKILL an owned worker after a completed SQLite commit. They test process-loss
recovery on the same host, not physical power loss or independent storage faults.
"""
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import signal
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

from src.effect_ledger import DrainingClient, EffectLedger, MAX_LEASES, MAX_OPERATIONS, lease_id
from src.network import Client, Network

ROOT=Path(__file__).resolve().parents[1]
RECORDS=[]


@asynccontextmanager
async def environment(supports=None):
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory)
        net=Network(root/'net',supports or [['a','b'],['a','b']]);await net.start()
        state=dict(root=root,net=net,core=Client(net),ledger=EffectLedger(root/'effects.sqlite'))
        state['adapter']=DrainingClient(state['core'],state['ledger'])
        try:yield state
        finally:
            state['ledger'].disconnect();state['core'].disconnect();await net.stop()


def reopen(state):
    state['ledger'].disconnect();state['core'].disconnect()
    state['core']=Client(state['net']);state['ledger']=EffectLedger(state['root']/'effects.sqlite')
    state['adapter']=DrainingClient(state['core'],state['ledger'])


def inputs(mode,nodes=2):
    branch={str(n):['a'] for n in range(nodes)}
    return [branch],({n:[req] for n,req in branch.items()} if mode=='envelope' else None)


class PostCommitError:
    """One controlled error after a real SQLite context-manager commit."""
    def __init__(self,connection):self.connection=connection;self.armed=True
    def __getattr__(self,name):return getattr(self.connection,name)
    def __enter__(self):self.connection.__enter__();return self
    def __exit__(self,*args):
        result=self.connection.__exit__(*args)
        if args[0] is None and self.armed:
            self.armed=False
            raise sqlite3.OperationalError('owned registration postcommit uncertainty')
        return result


class EffectRegistrationTests(unittest.IsolatedAsyncioTestCase):
    def assert_clean(self,state):
        self.assertEqual(state['core'].state['attempts'],{})
        for endpoint in state['net'].nodes.values():self.assertEqual(endpoint.state['slots'],{})

    async def test_cumulative_lease_capacity_refuses_before_core_allocation(self):
        async with environment([['a','b']]) as state:
            core,ledger,adapter=state['core'],state['ledger'],state['adapter']
            for i in range(MAX_LEASES):
                admitted,lease=await adapter.acquire('complete-'+str(i),[{'0':['a']}])
                self.assertEqual(admitted['status'],'admitted')
                self.assertEqual(await lease.retire(),'retired')
            before=deepcopy(core.state);owner=deepcopy(state['net'].nodes[0].state)
            length=len(state['net'].trace)
            with self.assertRaisesRegex(ValueError,'effect lease bound'):
                await adapter.acquire('overflow',[{'0':['a']}])
            self.assertEqual(core.state,before);self.assertEqual(state['net'].nodes[0].state,owner)
            self.assertEqual(len(state['net'].trace),length);self.assert_clean(state)
            self.assertEqual(ledger.db.execute("SELECT COUNT(*) FROM leases WHERE phase='closed'").fetchone()[0],MAX_LEASES)
            RECORDS.append(dict(case='lease capacity',completed=MAX_LEASES,refused_before_allocation=True,
                                retained_closed_leases=MAX_LEASES,live_holds=0))

    async def test_full_ledger_can_reuse_its_existing_open_admission(self):
        async with environment([['a']]) as state:
            adapter=state['adapter'];ledger=state['ledger']
            for i in range(MAX_LEASES-1):
                _,lease=await adapter.acquire('past-'+str(i),[{'0':['a']}])
                self.assertEqual(await lease.retire(),'retired')
            admitted,lease=await adapter.acquire('live',[{'0':['a']}])
            before=deepcopy(state['core'].state)
            again,second=await adapter.acquire('live',[{'0':['a']}])
            self.assertEqual(again,admitted);self.assertEqual(second.token,lease.token)
            self.assertEqual(state['core'].state,before)
            number=await second.begin_write('key','value')
            self.assertEqual(await second.finish_write(number),'done')
            self.assertEqual(await second.retire(),'retired')
            self.assertEqual(ledger.db.execute('SELECT COUNT(*) FROM leases').fetchone()[0],MAX_LEASES)
            RECORDS.append(dict(case='capacity with existing authority',leases=MAX_LEASES,
                                existing_reused=True,new_sequence_allocated=False))

    async def test_cumulative_operation_capacity_does_not_allocate_another_admission(self):
        async with environment([['a']]) as state:
            adapter,ledger=state['adapter'],state['ledger']
            _,lease=await adapter.acquire('operations',[{'0':['a']}])
            # The capacity fixture executes actual owned ledger transactions
            # while the admission stays held; it is not a timing measurement.
            for i in range(MAX_OPERATIONS):
                number=ledger.begin(lease.token,'key',str(i));ledger.finish(lease.token,number)
                if i%128==0:await asyncio.sleep(0)
            with self.assertRaisesRegex(ValueError,'effect operation bound'):
                await lease.begin_write('key','overflow')
            self.assertEqual(await lease.retire(),'retired');before=deepcopy(state['core'].state)
            length=len(state['net'].trace)
            with self.assertRaisesRegex(ValueError,'effect operation bound'):
                await adapter.acquire('after-exhaustion',[{'0':['a']}])
            self.assertEqual(state['core'].state,before);self.assertEqual(len(state['net'].trace),length)
            self.assert_clean(state)
            RECORDS.append(dict(case='operation capacity',completed=MAX_OPERATIONS,
                                refused_before_next_admission=True,retirement_succeeded=True))

    async def test_sqlite_registration_abort_is_cleanable_and_retryable(self):
        for mode in ('fixed','envelope'):
            with self.subTest(mode=mode):
                async with environment() as state:
                    ledger=state['ledger'];branches,box=inputs(mode)
                    ledger.db.execute("CREATE TRIGGER registration_abort BEFORE INSERT ON leases BEGIN SELECT RAISE(ABORT, 'owned registration abort'); END")
                    ledger.db.commit()
                    with self.assertRaises(sqlite3.DatabaseError):
                        await state['adapter'].acquire('abort',branches,box)
                    self.assertTrue(ledger.failed);self.assert_clean(state)
                    self.assertEqual(ledger.db.execute('SELECT COUNT(*) FROM leases').fetchone()[0],0)
                    ledger.db.execute('DROP TRIGGER registration_abort');ledger.db.commit();reopen(state)
                    self.assertEqual(await state['adapter'].recover(),dict(fenced_registrations=0,pending_protocol_attempts=0))
                    admitted,lease=await state['adapter'].acquire('abort',branches,box)
                    self.assertEqual(admitted['status'],'admitted');self.assertEqual(await lease.retire(),'retired')
                    RECORDS.append(dict(case='actual registration abort',mode=mode,guard_cleanup=True,
                                        reopened_retry=True,first_lease_rows=0))

    async def test_uncertain_registration_commit_is_fenced_after_reopen(self):
        for mode in ('fixed','envelope'):
            with self.subTest(mode=mode):
                async with environment() as state:
                    ledger=state['ledger'];ledger.db=PostCommitError(ledger.db)
                    branches,box=inputs(mode)
                    with self.assertRaises(sqlite3.DatabaseError):
                        await state['adapter'].acquire('uncertain-registration',branches,box)
                    self.assertTrue(ledger.failed);self.assert_clean(state)
                    self.assertEqual(ledger.db.execute('SELECT phase FROM leases').fetchall(),[('open',)])
                    reopen(state)
                    result=await state['adapter'].recover()
                    self.assertEqual(result,dict(fenced_registrations=1,pending_protocol_attempts=0))
                    self.assertEqual(state['ledger'].db.execute('SELECT phase FROM leases').fetchall(),[('closed',)])
                    token=state['ledger'].db.execute('SELECT token FROM leases').fetchone()[0]
                    with self.assertRaisesRegex(ValueError,'no longer admits'):
                        state['ledger'].begin(token,'late','forbidden')
                    admitted,lease=await state['adapter'].acquire('retry',branches,box)
                    self.assertEqual(admitted['status'],'admitted');self.assertEqual(await lease.retire(),'retired')
                    RECORDS.append(dict(case='registration committed then reported error',mode=mode,
                                        guard_cleanup=True,orphan_fenced=True,closed_row_retained=True,retry=True))

    async def test_origin_commit_uncertainty_uses_reopened_commitment(self):
        for mode in ('fixed','envelope'):
            for after_commit in (False,True):
                with self.subTest(mode=mode,after_commit=after_commit):
                    async with environment() as state:
                        core,ledger=state['core'],state['ledger'];branches,box=inputs(mode)
                        actual=core.persist
                        def controlled_persist():
                            image=core.state if core._pending_state is None else core._pending_state
                            if image['attempts'].get('1',{}).get('status')=='committed':
                                if not after_commit:
                                    core.db.execute("CREATE TRIGGER origin_abort BEFORE INSERT ON state BEGIN SELECT RAISE(ABORT, 'owned origin abort'); END")
                                    core.db.commit()
                                actual()
                                raise sqlite3.OperationalError('owned origin postcommit uncertainty')
                            actual()
                        with mock.patch.object(core,'persist',side_effect=controlled_persist):
                            with self.assertRaises(sqlite3.DatabaseError):
                                await state['adapter'].acquire('origin-uncertain',branches,box)
                        self.assertTrue(core._persistence_failed)
                        self.assertEqual(ledger.db.execute('SELECT phase FROM leases').fetchall(),[('open',)])
                        self.assertTrue(all(endpoint.state['slots']['0:1']['status']=='held' for endpoint in state['net'].nodes.values()))
                        disk=json.loads(core.db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
                        self.assertEqual(disk['attempts']['1']['status'],'committed' if after_commit else 'acquiring')
                        if not after_commit:
                            core.db.execute('DROP TRIGGER origin_abort');core.db.commit()
                        reopen(state);result=await state['adapter'].recover()
                        self.assertEqual(result['fenced_registrations'],0 if after_commit else 1)
                        phases=state['ledger'].db.execute('SELECT phase FROM leases').fetchall()
                        self.assertEqual(phases,[('open',)] if after_commit else [('closed',)])
                        if after_commit:
                            cert=state['core'].state['attempts']['1']['certificate']
                            lease=await state['adapter'].resume(cert)
                            number=await lease.begin_write('key','committed')
                            self.assertEqual(await lease.finish_write(number),'done')
                            self.assertEqual(await lease.retire(),'retired')
                        else:self.assert_clean(state)
                        RECORDS.append(dict(case='origin commit reported error',mode=mode,
                                            durable_commit=after_commit,ledger_phase_after_reopen=phases[0][0],
                                            fenced=result['fenced_registrations']))

    async def test_registration_failure_with_lost_close_has_explicit_recovery(self):
        for mode in ('fixed','envelope'):
            with self.subTest(mode=mode):
                async with environment() as state:
                    net,ledger=state['net'],state['ledger'];branches,box=inputs(mode)
                    actual=ledger.register
                    def registered_then_error(token):
                        actual(token);net.blocked.add((0,1));raise RuntimeError('controlled registration failure')
                    with mock.patch.object(ledger,'register',side_effect=registered_then_error):
                        with self.assertRaisesRegex(RuntimeError,'controlled registration'):
                            await state['adapter'].acquire('partitioned-registration',branches,box)
                    self.assertEqual(state['core'].state['attempts']['1']['status'],'retiring')
                    self.assertEqual(ledger.db.execute('SELECT phase FROM leases').fetchall(),[('closed',)])
                    self.assertEqual((await net.rpc(1,1,{'op':'install','support':['b']}))['status'],'blocked')
                    self.assertEqual((await state['adapter'].recover())['pending_protocol_attempts'],1)
                    net.blocked.clear();self.assertEqual((await state['adapter'].recover())['pending_protocol_attempts'],0)
                    self.assert_clean(state)
                    self.assertEqual((await net.rpc(0,1,dict(op='prepare',origin=0,sequence=1,
                        manifest='partitioned-registration',requires=['a'])))['status'],'closed')
                    RECORDS.append(dict(case='registration failure and lost close',mode=mode,
                                        partial_hold_retained=True,healed_recovery=True,delayed_prepare='closed'))

    async def test_cancelled_precommit_acquisition_remains_recoverable(self):
        for mode in ('fixed','envelope'):
            with self.subTest(mode=mode):
                async with environment() as state:
                    net=state['net'];branches,box=inputs(mode)
                    actual=net.rpc;held=asyncio.Event();release=asyncio.Event()
                    async def delayed_reply(source,target,request,*args,**kwargs):
                        response=await actual(source,target,request,*args,**kwargs)
                        if target==1 and request['op']=='prepare':
                            held.set();await release.wait()
                        return response
                    with mock.patch.object(net,'rpc',side_effect=delayed_reply):
                        task=asyncio.create_task(state['adapter'].acquire('cancelled-registration',branches,box))
                        await asyncio.wait_for(held.wait(),2);task.cancel()
                        with self.assertRaises(asyncio.CancelledError):await task
                    self.assertEqual(state['core'].state['attempts']['1']['status'],'acquiring')
                    self.assertEqual(state['ledger'].db.execute('SELECT COUNT(*) FROM leases').fetchone()[0],0)
                    self.assertEqual((await state['adapter'].recover())['pending_protocol_attempts'],0)
                    self.assert_clean(state)
                    RECORDS.append(dict(case='cancelled before registration',mode=mode,
                                        acquiring_journal_retained=True,explicit_recovery=True))

    async def test_recovery_preserves_committed_active_and_draining_leases(self):
        async with environment() as state:
            _,lease=await state['adapter'].acquire('active',*inputs('fixed'))
            number=await lease.begin_write('key','value')
            self.assertEqual((await state['adapter'].recover())['fenced_registrations'],0)
            self.assertEqual(state['ledger'].phase(lease.token),'open')
            self.assertEqual(await lease.retire(),'draining')
            self.assertEqual((await state['adapter'].recover())['fenced_registrations'],0)
            self.assertEqual(state['ledger'].phase(lease.token),'closing')
            self.assertEqual(await lease.finish_write(number),'done')
            self.assertEqual(await lease.retire(),'retired');self.assert_clean(state)
            RECORDS.append(dict(case='committed work during adapter recovery',open_preserved=True,
                                closing_preserved=True,write_completed=True))

    async def test_active_orphan_is_not_silently_reclaimed(self):
        async with environment() as state:
            ledger=state['ledger'];token='f'*64;ledger.register(token)
            number=ledger.begin(token,'unknown','not-written')
            with self.assertRaisesRegex(ValueError,'active effect has no committed'):
                await state['adapter'].recover()
            self.assertEqual(ledger.phase(token),'open')
            self.assertEqual(ledger.db.execute('SELECT phase FROM operations WHERE id=?',(number,)).fetchone(),('active',))
            self.assertIsNone(ledger.read('unknown'))
            RECORDS.append(dict(case='inconsistent active orphan negative control',recovery_rejected=True,
                                reservation_preserved=True,write_absent=True))

    async def test_unregistered_bare_admission_is_not_implicitly_attached(self):
        async with environment() as state:
            branches,box=inputs('fixed')
            good=(await state['core'].acquire('bare',branches))['certificate']
            before=deepcopy(state['core'].state);length=len(state['net'].trace)
            with self.assertRaisesRegex(ValueError,'unknown effect lease'):
                await state['adapter'].acquire('bare',branches,box)
            self.assertEqual(state['core'].state,before);self.assertEqual(len(state['net'].trace),length)
            self.assertTrue(all(r['status']=='used' for r in await state['core'].use(good)))
            self.assertTrue(await state['core'].retire(good))
            admitted,lease=await state['adapter'].acquire('bare',branches,box)
            self.assertEqual(admitted['status'],'admitted');self.assertEqual(await lease.retire(),'retired')
            RECORDS.append(dict(case='bare admission attachment',refused_without_mutation=True,
                                original_authority_preserved=True,new_adapter_admission=True))

    @unittest.skipUnless(os.name=='posix','owned SIGKILL control requires POSIX')
    async def test_real_process_cuts_before_and_after_origin_commit(self):
        for mode in ('fixed','envelope'):
            for cut in ('registered','committed'):
                with self.subTest(mode=mode,cut=cut),tempfile.TemporaryDirectory() as directory:
                    root=Path(directory)
                    flags=['-'+'O'*sys.flags.optimize] if sys.flags.optimize else []
                    process=await asyncio.create_subprocess_exec(sys.executable,*flags,'-B','-m',
                        'tests.effect_registration','--crash-worker',str(root),mode,cut,cwd=ROOT,
                        stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
                    try:output,errors=await asyncio.wait_for(process.communicate(),15)
                    except BaseException:
                        if process.returncode is None:process.kill()
                        await process.wait();raise
                    self.assertEqual(process.returncode,-signal.SIGKILL,errors.decode())
                    checkpoint=json.loads(output)
                    self.assertEqual(checkpoint,dict(checkpoint=cut,mode=mode))
                    net=Network(root/'net',[['a','b'],['a','b']]);await net.start()
                    core=Client(net);ledger=EffectLedger(root/'effects.sqlite');adapter=DrainingClient(core,ledger)
                    try:
                        self.assertEqual(core.state['attempts']['1']['status'],
                                         'committed' if cut=='committed' else 'acquiring')
                        self.assertEqual(ledger.db.execute('SELECT phase FROM leases').fetchall(),[('open',)])
                        recovered=await adapter.recover()
                        self.assertEqual(recovered['fenced_registrations'],0 if cut=='committed' else 1)
                        if cut=='committed':
                            cert=core.state['attempts']['1']['certificate'];lease=await adapter.resume(cert)
                            number=await lease.begin_write('key','after-restart')
                            self.assertEqual(await lease.finish_write(number),'done')
                            self.assertEqual(await lease.retire(),'retired')
                        else:
                            self.assertEqual(core.state['attempts'],{})
                            self.assertEqual(ledger.db.execute('SELECT phase FROM leases').fetchall(),[('closed',)])
                            for endpoint in net.nodes.values():self.assertEqual(endpoint.state['slots'],{})
                        RECORDS.append(dict(case='actual owned SIGKILL',mode=mode,cut=cut,
                                            process_returncode=process.returncode,fenced=recovered['fenced_registrations'],
                                            committed_work_resumable=cut=='committed'))
                    finally:ledger.disconnect();core.disconnect();await net.stop()


async def crash_worker(root,mode,cut):
    net=Network(root/'net',[['a','b'],['a','b']]);await net.start()
    core=Client(net);ledger=EffectLedger(root/'effects.sqlite');adapter=DrainingClient(core,ledger)
    def kill():
        print(json.dumps(dict(checkpoint=cut,mode=mode)),flush=True)
        os.kill(os.getpid(),signal.SIGKILL)
        raise RuntimeError('SIGKILL returned')
    if cut=='registered':
        actual=ledger.register
        def registered(token):
            value=actual(token);kill();return value
        ledger.register=registered
    elif cut=='committed':
        actual=core.persist
        def committed():
            actual()
            if core._pending_state is not None and core._pending_state['attempts'].get('1',{}).get('status')=='committed':kill()
        core.persist=committed
    else:raise ValueError('unknown process cut')
    await adapter.acquire('crash-registration',*inputs(mode))
    raise RuntimeError('crash cut not reached')


if __name__=='__main__':
    if len(sys.argv)==5 and sys.argv[1]=='--crash-worker':
        asyncio.run(crash_worker(Path(sys.argv[2]),sys.argv[3],sys.argv[4]))
    else:unittest.main(verbosity=2)
