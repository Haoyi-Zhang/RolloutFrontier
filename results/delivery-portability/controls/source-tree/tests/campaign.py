"""Frozen generated API-mode campaign. No external services or workload execution."""
from __future__ import annotations
import asyncio, csv, json, random, resource, tempfile, time
from pathlib import Path
from src.network import Network, Client
from src.envelope import synthesize, frontier_synthesize
from tests.oracle import relation_truth
from src.checker import endpoint_invariant

FAMILIES=('independent','correlated','one-sided','bridge')
POLICIES=('epoch','branch','envelope','frontier','unguarded','marginal')
SEEDS=tuple(range(6))
STEPS=24


def fixture(family):
    pairs={'independent':[(0,0),(0,1),(1,0),(1,1)],'correlated':[(0,0),(1,1)],
           'one-sided':[(0,0),(0,1),(1,0)],'bridge':[(0,0),(1,1)]}[family]
    names=('wire.old','wire.new')
    branches=[{'0':[names[a]],'1':[names[b]],'2':['api.base'],
               '3':['api.base'],'4':['api.base']} for a,b in pairs]
    current={str(n):(['wire.old'] if n<2 else ['api.base']) for n in range(5)}
    if family=='bridge': current['1']=['wire.old','wire.new']
    candidates={str(n):([['wire.old'],['wire.new'],['wire.old','wire.new']]
                        if n<2 else [['api.base']]) for n in range(5)}
    return branches,current,candidates


async def one(family,seed,policy,trace_file):
    branches,current,candidates=fixture(family)
    rng=random.Random(seed)
    # Freeze the proposed transitions before any policy response is observed.
    transitions=[]
    for step in range(STEPS):
        node=rng.randrange(5)
        choices=[['wire.old'],['wire.new'],['wire.old','wire.new'],[]] if node<2 else [['api.base'],[]]
        support=list(choices[rng.randrange(len(choices))])
        if step%4==0: support.append('unrelated.extension')
        transitions.append((node,support))
    epolicy='epoch' if policy=='epoch' else 'unguarded' if policy=='unguarded' else 'predicate'
    begin=time.perf_counter(); cpu=time.process_time()
    with tempfile.TemporaryDirectory() as tmp:
        net=Network(Path(tmp),[current[str(i)] for i in range(5)],policy=epolicy,seed=seed)
        await net.start(); client=Client(net)
        if policy in ('epoch','branch','unguarded'):
            result=await client.acquire('live',branches); cert=result['certificate']
        elif policy in ('envelope','frontier'):
            planned=(synthesize(branches,current,candidates) if policy=='envelope'
                     else frontier_synthesize(branches,current,candidates))
            assert planned['certificate']['safe']
            if policy=='envelope': assert not planned['bounded']
            result=await client.acquire_box('live',branches,planned['box']); cert=result['certificate']
        else:
            # Negative control: deliberately bypass the global envelope checker.
            # Local marginals can all be true while no single global alternative is.
            receipts=[]; sequences={str(i):1 for i in range(5)}
            for i in range(5):
                options=sorted({tuple(b[str(i)]) for b in branches})
                reply=await net.rpc(0,i,dict(op='prepare',origin=0,sequence=1,manifest='live',
                                           requires=[],options=[list(o) for o in options]))
                assert reply['status']=='held'; receipts.append(reply['receipt'])
            cert=dict(manifest='live',origin=0,sequences=sequences,receipts=receipts)
            result={'status':'admitted'}
        assert result['status']=='admitted'
        installs=blocked=unchanged=global_violations=local_violations=0
        for step,(node,support) in enumerate(transitions):
            if step==3: net.blocked.update({(0,1),(0,3),(0,4)})
            if step==14: net.blocked.clear()
            if step in (5,15): await net.crash((seed+step)%5)
            if step==10 and policy!='marginal':
                client.disconnect(); client=Client(net); await client.recover()
            reply=await net.rpc(node,node,dict(op='install',support=support))
            installs+=reply['status']=='installed'; blocked+=reply['status']=='blocked'
            unchanged+=reply['status']=='unchanged'
            # Read the simulator's authoritative snapshot only for the oracle,
            # never for admission. This separates decision input from labels.
            physical={str(n):set(ep.state['support']) for n,ep in net.nodes.items()}
            violation=not relation_truth(branches,physical); global_violations+=violation
            local=[]
            for n in range(5):
                answer=await net.rpc(n,n,dict(op='use',origin=0,sequence=cert['sequences'][str(n)],manifest='live'))
                local.append(answer['status'])
            local_violations+=any(x=='incompatible' for x in local)
            net.trace.append(dict(event='oracle',step=step,compatible=not violation,
                                  physical={n:sorted(x) for n,x in physical.items()}))
            if policy not in ('unguarded','marginal'):
                assert not violation and all(endpoint_invariant(x.state) for x in net.nodes.values())
            if step in (6,16):
                # Drops and independently delayed duplicate observations.
                for source in range(5):
                    profile=net.nodes[source].profile()
                    for target in range(5):
                        if (source+target+seed)%7==0:
                            await net.rpc(source,target,dict(op='merge',profile=profile),drop=True)
                        else:
                            net.enqueue(source,target,dict(op='merge',profile=profile),rng.randrange(6))
                            net.enqueue(source,target,dict(op='merge',profile=profile),rng.randrange(6))
                await net.drain()
        net.blocked.clear(); before=net.delivered; await net.gossip()
        catalogs=[ep.state['catalog'] for ep in net.nodes.values()]
        converged=all(c==catalogs[0] for c in catalogs)
        assert converged
        reconcile_rpcs=net.delivered-before
        if policy=='marginal':
            for i in range(5): await net.rpc(0,i,dict(op='close',origin=0,sequence=1))
        else: assert await client.retire(cert)
        # A delayed prepare cannot resurrect the explicitly retired acquisition.
        replay=await net.rpc(0,0,dict(op='prepare',origin=0,sequence=cert['sequences']['0'],
                                     manifest='live',requires=['wire.old']))
        assert replay['status']=='closed'
        lat=sorted(x['wall_ns']/1e6 for x in net.trace if x['event']=='rpc')
        assert net.opened_connections <= 7  # five targets plus at most two crash reconnects
        row=dict(family=family,seed=seed,policy=policy,workloads=1,proposed=STEPS,
                 installed=installs,blocked=blocked,unchanged=unchanged,
                 incompatible_snapshots=global_violations,local_incompatible_steps=local_violations,
                 converged=int(converged),reconcile_rpcs=reconcile_rpcs,delivered=net.delivered,
                 serialized_bytes=net.bytes,tcp_connections_opened=net.opened_connections,
                 rpc_median_ms=lat[len(lat)//2],
                 rpc_p95_ms=lat[min(len(lat)-1,int(.95*len(lat)))],
                 wall_seconds=time.perf_counter()-begin,cpu_seconds=time.process_time()-cpu)
        trace_file.write(json.dumps(dict(event="case-start", case=dict(family=family,seed=seed,policy=policy),
            initial_support=current, branches=branches, endpoint_policy=epolicy, window=8),
            sort_keys=True,separators=(",",":"))+"\n")
        for event in net.trace:
            event.update(case=dict(family=family,seed=seed,policy=policy))
            trace_file.write(json.dumps(event,sort_keys=True,separators=(',',':'))+'\n')
        client.disconnect(); await net.stop()
        return row


async def run(out: Path):
    out.mkdir(parents=True,exist_ok=True)
    begin=time.perf_counter(); cpu=time.process_time(); rows=[]
    with (out/'network-trace.jsonl').open('w') as f:
        for family in FAMILIES:
            for seed in SEEDS:
                for policy in POLICIES:
                    rows.append(await one(family,seed,policy,f))
    with (out/'network.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    summary={}
    for policy in POLICIES:
        selected=[r for r in rows if r['policy']==policy]
        summary[policy]={k:sum(r[k] for r in selected) for k in
                        ('workloads','proposed','installed','blocked','unchanged','incompatible_snapshots',
                         'local_incompatible_steps','converged','delivered','serialized_bytes',
                         'tcp_connections_opened')}
    assert summary['unguarded']['incompatible_snapshots']>0
    assert summary['marginal']['incompatible_snapshots']>0
    assert summary['marginal']['local_incompatible_steps']==0
    result=dict(cases=len(rows),families=list(FAMILIES),seeds=list(SEEDS),steps=STEPS,
                policies=summary,
                tcp_connections_opened=sum(r['tcp_connections_opened'] for r in rows),
                cpu_seconds=time.process_time()-cpu,
                wall_seconds=time.perf_counter()-begin,
                peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    (out/'network.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    return result

if __name__=='__main__':
    import sys
    print(json.dumps(asyncio.run(run(Path(sys.argv[1] if len(sys.argv)>1 else 'results'))),indent=2))
