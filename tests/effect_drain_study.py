"""Registered owned application-lifetime study; no timing or deployment claim."""
from __future__ import annotations
import argparse
import asyncio
from copy import deepcopy
import hashlib
import itertools
import json
from pathlib import Path
import platform
import sqlite3
import sys
import time
from src.effect_ledger import EffectLedger,DrainingClient
from src.network import Network,Client

ROOT=Path(__file__).resolve().parents[1]
def save(path,value):path.write_text(json.dumps(value,sort_keys=True,indent=2)+'\n',encoding='utf-8')
def require(value,message):
    if not value:raise ValueError(message)

async def scenario(root,policy,completion,restart,partition):
    net=Network(root/'net',[['a','b'],['a','b']],policy=policy);await net.start()
    core=Client(net);path=root/'effects.sqlite';ledger=EffectLedger(path)
    try:
        owner=DrainingClient(core,ledger);result,lease=await owner.acquire('write',[{'0':['a'],'1':['a']}])
        require(result['status']=='admitted','admission failed')
        operation=await lease.begin_write('result','committed')
        initial=await lease.retire();require(initial=='draining','inflight effect was released')
        block=await net.rpc(0,0,dict(op='install',support=['b']));require(block['status']=='blocked','guard disappeared')
        try:await lease.begin_write('late','forbidden')
        except ValueError:new_work_rejected=True
        else:new_work_rejected=False
        require(new_work_rejected,'closing phase admitted new effect')
        if restart=='endpoint':await net.crash(0)
        if restart=='coordinator':
            ledger.disconnect();core.disconnect();core=Client(net);await core.recover();ledger=EffectLedger(path)
            lease=await DrainingClient(core,ledger).resume(result['certificate'])
        require(await lease.retire()=='draining','restart dropped durable active operation')
        require(await lease.finish_write(operation,cancel=completion=='cancel') in ('done','cancelled'),'completion failed')
        if partition:net.blocked.add((0,1))
        first=await lease.retire()
        require(first==('release-pending' if partition else 'retired'),'incorrect release status')
        net.blocked.clear();require(await lease.retire()=='retired','release did not finish')
        require((await net.rpc(0,0,dict(op='install',support=['b'])))['status']=='installed','drained update did not install')
        try:await lease.finish_write(operation)
        except ValueError:stale_rejected=True
        else:stale_rejected=False
        require(stale_rejected,'retired callback still has execution authority')
        expected='committed' if completion=='commit' else None
        require(ledger.read('result')==expected and ledger.read('late') is None,'owned effect differs')
        return dict(policy=policy,completion=completion,restart=restart,release_partition=partition,
            initial_retirement=initial,incompatible_install_while_active=block['status'],
            first_release=first,final_release='retired',new_work_rejected=new_work_rejected,
            stale_effect_rejected=stale_rejected,actual_stored_value=ledger.read('result'))
    finally:ledger.disconnect();core.disconnect();await net.stop()

async def bare_counterexample(root):
    net=Network(root/'net',[['a','b']]);await net.start();core=Client(net)
    db=sqlite3.connect(root/'unfenced-effect.sqlite')
    try:
        db.execute('CREATE TABLE effects(value TEXT)')
        result=await core.acquire('bare',[{'0':['a']}]);certificate=result['certificate']
        require((await core.use(certificate))[0]['status']=='used','bare use failed')
        require(await core.retire(certificate),'bare retirement failed')
        changed=await net.rpc(0,0,dict(op='install',support=['b']))
        require(changed['status']=='installed','bare update failed')
        # An application callback using an unfenced external DB can run later.
        # This intentionally violates the core model's caller drain premise.
        db.execute("INSERT INTO effects VALUES('late effect after retirement')");db.commit()
        return dict(use_before_retirement='used',installation_after_retirement=changed['status'],
            unfenced_late_effect=db.execute('SELECT value FROM effects').fetchone()[0],
            interpretation='Application composition negative control, not a violation of the protocol theorem')
    finally:db.close();core.disconnect();await net.stop()

async def run(out):
    out=out.resolve()
    if out.exists() or out.is_relative_to(ROOT.resolve()):raise ValueError('Fresh output outside artifact required')
    out.mkdir(parents=True)
    design=list(itertools.product(('predicate','epoch'),('commit','cancel'),('none','endpoint','coordinator'),(False,True)))
    bindings={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [ROOT/'src/effect_ledger.py',ROOT/'src/controller.py',ROOT/'src/network.py',Path(__file__)]}
    save(out/'registration.json',dict(cases=24,design=design,maximum_cases=24,wall_cap_seconds=120,
        source_bindings=bindings,no_new_timing_campaign=True,no_external_service=True,
        same_host_process_and_SQLite_scope=True,detached_callbacks_not_covered=True))
    start=time.monotonic();rows=[];status='FAILED_OR_PARTIAL'
    try:
        for index,case in enumerate(design):
            if time.monotonic()-start>120:raise TimeoutError('Registered lifetime study wall cap')
            root=out/('case-'+str(index));root.mkdir();rows.append(await scenario(root,*case))
        root=out/'composition-negative-control';root.mkdir();negative=await bare_counterexample(root)
        save(out/'rows.json',rows);save(out/'negative-control.json',negative);status='PASS'
    finally:
        save(out/'summary.json',dict(status=status,cases=len(rows),planned_cases=24,
            new_effects_during_drain_rejected=sum(r['new_work_rejected'] for r in rows),
            stale_effects_after_retirement_rejected=sum(r['stale_effect_rejected'] for r in rows),
            stored_commits=sum(r['actual_stored_value']=='committed' for r in rows),
            cancelled_without_write=sum(r['actual_stored_value'] is None for r in rows),
            independent_experimental_drain_comparator=False,
            wall_seconds=time.monotonic()-start,python=sys.version,platform=platform.platform(),
            scope='Owned SQLite application effect, not production deployment, remote arbitrary-effect fencing or performance comparison'))
    print(json.dumps(dict(status=status,cases=len(rows))))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True,type=Path)
    asyncio.run(run(p.parse_args().out))
