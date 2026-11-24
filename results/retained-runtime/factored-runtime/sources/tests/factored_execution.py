"""Audited real-process dataflows and recovery controls for factored rollouts.

The large cohorts use 32 separate owner processes on one host. A separate owned
TCP relay forwards their actual requests. The retained overlap probes use an
explicit application pause to exercise long-lived obligations; their durations
are not included in the steady-target request latency summaries. Fault runs are
stored separately and never enter those latency aggregates.
"""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import statistics
import sys
import time

import google.protobuf
from src.controller import canonical
from src.factored_runtime import FactoredCoordinator, FactoredExecutionError
from src.factored_session import FactoredSession, SchemaRequestPending
from src.schema_contracts import payloads
from tests.factored_cases import graph_case, probe_for
from tests.factored_network import PhysicalNetwork, RegisteredTransport
from tests.check_factored_execution import check_directory


def save(path,value):
    path = Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(canonical(value)+'\n')


def append(path,value):
    with open(path,'a',encoding='utf-8') as stream:
        stream.write(canonical(value)+'\n'); stream.flush(); os.fsync(stream.fileno())


async def snapshot(net):
    result = {}
    for owner in sorted(net.registry['owners']):
        answer = await net.rpc(owner,{'op':'inspect'})
        if answer is None or answer['status'] != 'state': raise RuntimeError('snapshot incomplete')
        result[owner] = answer['state']
    return result


def prepare(directory,case):
    directory = Path(directory)
    if directory.exists() and any(directory.iterdir()): raise ValueError('evidence directory must be empty')
    directory.mkdir(parents=True,exist_ok=True)
    save(directory/'case.json',case); save(directory/'plan.json',case['plan'])
    save(directory/'schema-probe.json',probe_for(case['family']))
    (directory/'requests.jsonl').touch()
    return directory


async def measured_request(net,directory,session,session_name,request_id,value,category,after_step=None):
    start = time.perf_counter_ns()
    output = await session.request(request_id,value,after_step=after_step)
    end = time.perf_counter_ns()
    entry = {'session':session_name,'request_id':request_id,'input':deepcopy(value),'output':output,
             'category':category,'start_ns':start,'end_ns':end,'elapsed_ns':end-start}
    append(directory/'requests.jsonl',entry)
    net.record('request-complete',session=session_name,request_id=request_id,category=category)
    return entry


async def paused_batch(net,directory,case,session,session_name,label,concurrency):
    reached,release = asyncio.Event(),asyncio.Event()
    seen = 0
    first = case['workflow'][0]['id']
    async def pause(step,response):
        nonlocal seen
        if step['id'] == first:
            seen += 1
            if seen == concurrency: reached.set()
            await release.wait()
    values = payloads(case['family'],0)
    tasks = [asyncio.create_task(measured_request(net,directory,session,session_name,
        label+'-'+str(i),values[i%len(values)],label,after_step=pause)) for i in range(concurrency)]
    await asyncio.wait_for(reached.wait(),30)
    net.record('application-pause-reached',session=session_name,requests=concurrency,
               pending=session.db.execute("SELECT count(*) FROM requests WHERE status='pending'").fetchone()[0])
    return tasks,release


async def drain(session):
    if not await session.close(): raise RuntimeError('completed session did not retire')
    session.disconnect()


async def live_cohort(directory,case,*,concurrency=4,steady_requests=16):
    directory = prepare(directory,case)
    net = PhysicalNetwork(directory,case['registry']); net.start()
    manifest = 'physical-rollout'
    coordinator = FactoredCoordinator(net,directory/'rollout.sqlite',plan=case['plan'],manifest=manifest,
        observer=lambda event:net.record('coordinator-event',detail=event))
    sessions = []
    outstanding,release = [],None
    try:
        start = time.perf_counter_ns()
        old_name = 'session-old.sqlite'
        old = await FactoredSession.begin(net,directory/old_name,case['workflow'],'retained-old-traffic')
        sessions.append(old)
        if old.state['stage'] != 'open': raise RuntimeError('old traffic admission failed')
        outstanding,release = await paused_batch(net,directory,case,old,old_name,'old-overlap',concurrency)
        blocked = await coordinator.run()
        if blocked.get('reason') != 'blocked': raise RuntimeError('retained old serializer did not block its incompatible replacement')
        protected = await snapshot(net)
        save(directory/'old-overlap-state.json',protected)
        advanced = sum(s['generation'] for s in protected.values())
        if advanced == 0: raise RuntimeError('compatible owner updates made no progress')
        release.set(); await asyncio.gather(*outstanding); outstanding=[]; release=None
        await drain(old)
        cleanup_overlap = 0
        if len(case['plan']['phases']) >= 3:
            while coordinator.state['phase_index'] < len(case['plan']['phases'])-1:
                step = await coordinator.advance()
                if step['status'] != 'progress': raise RuntimeError('rollout stalled after old request drain')
            current_name = 'session-current.sqlite'
            current = await FactoredSession.begin(net,directory/current_name,case['workflow'],'retained-current-traffic')
            sessions.append(current)
            outstanding,release = await paused_batch(net,directory,case,current,current_name,'current-overlap',concurrency)
            before = await snapshot(net)
            rollout = await coordinator.run()
            if rollout['status'] != 'complete': raise RuntimeError('compatible final cleanup stalled')
            after = await snapshot(net)
            cleanup_overlap = sum(after[n]['generation']-before[n]['generation'] for n in after)
            save(directory/'current-overlap-state.json',{'before':before,'after':after})
            if cleanup_overlap == 0: raise RuntimeError('no final owner replacement overlapped retained current traffic')
            release.set(); await asyncio.gather(*outstanding); outstanding=[]; release=None
            await drain(current)
        else:
            rollout = await coordinator.run()
        if rollout['status'] != 'complete': raise RuntimeError('rollout incomplete')
        rollout_elapsed = time.perf_counter_ns()-start
        steady_name = 'session-steady.sqlite'
        steady = await FactoredSession.begin(net,directory/steady_name,case['workflow'],'steady-target-traffic')
        sessions.append(steady)
        if steady.state['stage'] != 'open': raise RuntimeError('steady traffic admission failed')
        semaphore = asyncio.Semaphore(concurrency)
        values = payloads(case['family'],len(probe_for(case['family'])['profiles'])-1)
        async def one(index):
            async with semaphore:
                return await measured_request(net,directory,steady,steady_name,'steady-'+str(index),
                    values[index%len(values)],'steady-target')
        steady_start = time.perf_counter_ns()
        rows = await asyncio.gather(*(one(i) for i in range(steady_requests)))
        steady_elapsed = time.perf_counter_ns()-steady_start
        await drain(steady)
        final = await snapshot(net); save(directory/'final-owner-state.json',final)
        rss = {}
        for owner,process in net.processes.items():
            text = Path('/proc/'+str(process.pid)+'/status').read_text().splitlines()
            rss[owner] = int(next(v for v in text if v.startswith('VmHWM:')).split()[1])
        result = {'kind':'live-cohort','family':case['family'],'topology':case['topology'],
            'manifest':manifest,'owners':len(case['owners']),'factors':len(case['plan']['factors']),
            'finite_dataflow_hops':len(case['workflow']),'concurrency':concurrency,
            'rollout':rollout,'old_overlap_block':blocked,'compatible_installs_during_old_pause':advanced,
            'cleanup_installs_during_current_pause':cleanup_overlap,'rollout_probe_elapsed_ns':rollout_elapsed,
            'steady_target_requests':steady_requests,'steady_target_batch_elapsed_ns':steady_elapsed,
            'steady_target_request_elapsed_ns':[r['elapsed_ns'] for r in rows],
            'owner_peak_rss_kib':rss,
            'timing_scope':'fully audited loopback TCP with durable trace writes; excludes startup; paused overlap requests excluded from steady latency',
            'placement':'separate OS owner processes and one TCP relay process on one host'}
        save(directory/'result.json',result)
    finally:
        if release is not None: release.set()
        if outstanding: await asyncio.gather(*outstanding,return_exceptions=True)
        for session in sessions: session.disconnect()
        coordinator.disconnect(); net.close()
    assurance = check_directory(directory); save(directory/'check.json',assurance)
    return {**result,'verification':assurance,'directory':str(directory)}


async def coordinator_cut(net,directory,event,phase,owner):
    args = [sys.executable,'-B','-m','tests.factored_coordinator_worker',
        '--directory',str(directory),'--registry',str(directory/'registry.json'),
        '--routes',str(directory/'relay-routes.json'),'--journal',str(directory/'rollout.sqlite'),
        '--plan',str(directory/'plan.json'),'--manifest','fault-rollout','--cut-event',event,
        '--cut-phase',str(phase),'--cut-owner',owner]
    process = await asyncio.create_subprocess_exec(*args,stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,start_new_session=True)
    net.record('coordinator-start',pid=process.pid,command=args)
    try: output,error = await asyncio.wait_for(process.communicate(),45)
    except BaseException:
        if process.returncode is None: process.kill(); await process.wait()
        raise
    net.record('coordinator-stop',pid=process.pid,returncode=process.returncode)
    if process.returncode != -signal.SIGKILL:
        raise RuntimeError('coordinator cut did not occur: '+error.decode()+output.decode())


async def fault_cohort(directory):
    case = graph_case('enum-alias',3,'cycle',deployment='recovery-controls')
    directory = prepare(directory,case)
    net = PhysicalNetwork(directory,case['registry']); net.start()
    coordinator,session,altered = None,None,None
    controls = []
    try:
        await coordinator_cut(net,directory,'acquire-returned',0,'owner-000')
        first = await snapshot(net); save(directory/'partial-acquisition.json',first)
        if sum(len(s['slots']) for s in first.values()) != 1: raise RuntimeError('partial admission cut')
        controls.append({'control':'coordinator killed after partial acquisition','held_owners':1})
        await coordinator_cut(net,directory,'retire-returned',1,'owner-000')
        second = await snapshot(net); save(directory/'partial-retirement.json',second)
        if [len(second[n]['slots']) for n in sorted(second)] != [1,2,2]: raise RuntimeError('partial retirement cut')
        controls.append({'control':'coordinator killed after partial old-guard retirement','new_phase_owners':3})
        coordinator = FactoredCoordinator(net,directory/'rollout.sqlite',observer=lambda e:net.record('coordinator-event',detail=e))
        await net.control('drop-reply','owner-001',operation='close')
        uncertain = await coordinator.advance()
        if uncertain.get('reason') != 'old-phase-release-pending': raise RuntimeError('retirement reply was not lost')
        save(directory/'uncertain-retirement.json',{'journal':coordinator.state,'owners':await snapshot(net)})
        coordinator.disconnect()
        coordinator = FactoredCoordinator(net,directory/'rollout.sqlite',observer=lambda e:net.record('coordinator-event',detail=e))
        if (await coordinator.advance())['status'] != 'progress': raise RuntimeError('retirement recovery failed')
        controls.append({'control':'old-guard retirement reply lost after owner close','new_phase_preserved':True})
        index = coordinator.state['phase_index']; step = coordinator.state['step_index']
        owner = case['plan']['phases'][index]['steps'][step]['node']
        await net.control('drop-reply',owner,operation='install_if_current')
        unknown = await coordinator.advance()
        if unknown.get('reason') != 'installation-outcome-unknown': raise RuntimeError('install reply was not lost')
        save(directory/'lost-install-journal.json',coordinator.state)
        coordinator.disconnect()
        coordinator = FactoredCoordinator(net,directory/'rollout.sqlite',observer=lambda e:net.record('coordinator-event',detail=e))
        reconciled = await coordinator.advance()
        if reconciled.get('event') != 'already-target' or reconciled['reconciled_steps'] != 1:
            raise RuntimeError('lost installation double credited')
        controls.append({'control':'installed reply lost after owner commit','reconciled_steps':1})
        next_step = case['plan']['phases'][coordinator.state['phase_index']]['steps'][coordinator.state['step_index']]
        owner = next_step['node']; before = await snapshot(net); pid = net.processes[owner].pid
        await net.control('cut',owner)
        unreachable = await coordinator.advance()
        if unreachable.get('reason') != 'owner-unreachable' or net.processes[owner].poll() is not None:
            raise RuntimeError('TCP interruption did not isolate a live owner')
        await net.control('restore',owner)
        after = await snapshot(net)
        if after != before or net.processes[owner].pid != pid: raise RuntimeError('link cut changed physical state')
        save(directory/'tcp-interruption.json',{'before':before,'after':after,'owner':owner,'live_pid':pid})
        controls.append({'control':'controlled TCP interruption','owner_alive':True,'same_pid_after_restore':True})
        rollout = await coordinator.run()
        if rollout['status'] != 'complete' or rollout['acknowledged_installs']+rollout['reconciled_steps'] != 9:
            raise RuntimeError('fault rollout incomplete')
        # Every read uses the physical response identity, even after completion.
        port = net.ports['owner-000']; net.ports['owner-000'] = net.ports['owner-001']
        try:
            try: await coordinator.advance()
            except FactoredExecutionError: controls.append({'control':'wrong-owner target receipt','rejected':True})
            else: raise RuntimeError('wrong physical receipt accepted')
        finally: net.ports['owner-000'] = port
        binding = deepcopy(net.registry); binding['owners']['owner-000']['catalog'][0].append('foreign')
        altered = RegisteredTransport(directory,binding,net.ports,trace_name='altered-identity.jsonl')
        try: FactoredCoordinator(altered,directory/'rollout.sqlite')
        except FactoredExecutionError: controls.append({'control':'registered catalog substitution','rejected':True})
        else: raise RuntimeError('catalog substitution accepted')
        altered.disconnect(); altered=None
        session_name = 'session-recovery.sqlite'
        session = await FactoredSession.begin(net,directory/session_name,case['workflow'],'durable-request')
        await net.restart_owner('owner-001',kill_after_request='retry:h0001')
        value = {'key':'lost-reply-κ','value':2147483647,'status':1}
        try: await session.request('retry',value)
        except SchemaRequestPending: pass
        else: raise RuntimeError('owner death did not interrupt its reply')
        if await session.close(): raise RuntimeError('unresolved request released its holds')
        save(directory/'pending-request-session.json',session.state)
        try: await session.request('new-while-closing',value)
        except ValueError: pass
        else: raise RuntimeError('draining gate accepted new work')
        net.processes['owner-001'].wait(timeout=5)
        if net.processes['owner-001'].returncode != -signal.SIGKILL: raise RuntimeError('owner was not killed')
        session.disconnect()
        await net.restart_owner('owner-001',kill=False)
        session = FactoredSession(net,directory/session_name)
        row = await measured_request(net,directory,session,session_name,'retry',value,'failure-recovery')
        if not row['output']['steps']['h0001']['duplicate']: raise RuntimeError('durable effect retry was not deduplicated')
        await drain(session)
        controls.append({'control':'owner killed after committed schema effect','exact_retry_duplicate':True,
                         'pending_holds_retained':True,'new_work_rejected_while_closing':True})
        save(directory/'final-owner-state.json',await snapshot(net))
        result = {'kind':'fault-cohort','family':case['family'],'topology':case['topology'],
                  'owners':3,'manifest':'fault-rollout','rollout':rollout,'controls':controls,
                  'timing_scope':'fault control; excluded from latency summaries',
                  'placement':'separate OS owner processes and one TCP relay process on one host'}
        save(directory/'result.json',result)
    finally:
        if altered: altered.disconnect()
        if session: session.disconnect()
        if coordinator: coordinator.disconnect()
        net.close()
    assurance = check_directory(directory); save(directory/'check.json',assurance)
    return {**result,'verification':assurance,'directory':str(directory)}


async def campaign(args):
    root = args.output
    if root.exists() and any(root.iterdir()): raise ValueError('campaign output must be empty')
    root.mkdir(parents=True,exist_ok=True)
    artifact = Path(__file__).resolve().parents[1]
    names = [str(path.relative_to(artifact)) for path in sorted((artifact/'src').rglob('*.py'))]
    names += ['tests/'+name for name in (
        '__init__.py','factored_execution.py','factored_cases.py','factored_network.py',
        'factored_tcp_relay.py','factored_coordinator_worker.py','check_factored_execution.py',
        'factored_planning_oracle.py','factored_checker_controls.py','test_factored_runtime.py',
        'factored_followon_regression.py')]
    frozen = {}
    for name in names:
        original,target = artifact/name,root/'sources'/name
        frozen[name] = original.read_bytes()
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(frozen[name])
    save(root/'source-files.json',{'files':names,'capture':'byte copies before campaign; compared after campaign'})
    save(root/'environment.json',{'system':platform.system(),'release':platform.release(),
        'machine':platform.machine(),'python':platform.python_version(),'protobuf':google.protobuf.__version__,
        'logical_cpus':os.cpu_count(),'cpu_affinity':sorted(os.sched_getaffinity(0)),
        'deployment':'one host; independent owner processes; actual loopback TCP relay',
        'concurrency':args.concurrency,'steady_requests':args.steady_requests,
        'large_cohort_repetitions':args.repetitions})
    result = []
    if args.smoke:
        case = graph_case('enum-alias',3,'cycle',deployment='execution-smoke')
        result.append(await live_cohort(root/'smoke',case,concurrency=2,steady_requests=4))
        result.append(await fault_cohort(root/'recovery'))
    else:
        for family,topology in [('enum-alias','cycle'),('field-key','fanout-join')]:
            for repeat in range(args.repetitions):
                case = graph_case(family,32,topology,deployment=f'{family}-{topology}-trial-{repeat+1}')
                result.append(await live_cohort(root/(family+'-'+topology)/f'trial-{repeat+1:02d}',case,
                    concurrency=args.concurrency,steady_requests=args.steady_requests))
                print(canonical({'completed':result[-1]['directory'],'verification':result[-1]['verification']}),flush=True)
        for family in ('field-addition','integer-widening'):
            case = graph_case(family,5,'fanout-join',deployment=family+'-application-control')
            result.append(await live_cohort(root/(family+'-control'),case,
                concurrency=args.concurrency,steady_requests=args.steady_requests))
            print(canonical({'completed':result[-1]['directory'],'verification':result[-1]['verification']}),flush=True)
        result.append(await fault_cohort(root/'recovery-controls'))
    summary = {'cases':[{'directory':str(Path(row['directory']).relative_to(root)),
                        'kind':row['kind'],'family':row['family'],'topology':row['topology'],
                        'verification':row['verification'],
                        'steady_target_request_elapsed_ns':row.get('steady_target_request_elapsed_ns',[])} for row in result],
        'total_requests':sum(row['verification']['complete_requests'] for row in result),
        'total_effects':sum(row['verification']['durable_effects'] for row in result),
        'total_conditional_installations':sum(row['verification']['installations'] for row in result),
        'all_independent_checks_passed':all(row['verification']['checked'] for row in result)}
    save(root/'summary.json',summary)
    changed = [name for name,data in frozen.items() if (artifact/name).read_bytes()!=data or
               (root/'sources'/name).read_bytes()!=data]
    if changed: raise RuntimeError('execution source changed during campaign: '+str(changed))
    save(root/'source-check.json',{'same_before_and_after':True,'captured_files':len(frozen)})
    print(canonical(summary),flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--repetitions',type=int,default=3)
    parser.add_argument('--concurrency',type=int,default=4)
    parser.add_argument('--steady-requests',type=int,default=16)
    parser.add_argument('--smoke',action='store_true')
    args = parser.parse_args()
    if not 1 <= args.repetitions <= 5 or not 1 <= args.concurrency <= 16 or not 1 <= args.steady_requests <= 256:
        parser.error('bounded repetitions, concurrency, or steady request count')
    asyncio.run(campaign(args))
