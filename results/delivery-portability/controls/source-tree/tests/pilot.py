"""Discriminating owned-loopback pilot; run as python -m tests.pilot."""
import asyncio, json, resource, tempfile, time
from pathlib import Path
from src.controller import Endpoint, minimum_obstruction
from src.envelope import verify_box, synthesize
from src.checker import safe_envelope, certificate, endpoint_invariant
from src.network import Network, Client

async def main():
    started, cpu = time.perf_counter(), time.process_time()
    diagonal=[{'0':['wire.old'],'1':['wire.old']},{'0':['wire.new'],'1':['wire.new']}]
    marginal={n:[['wire.old'],['wire.new']] for n in ('0','1')}
    bad=verify_box(diagonal,marginal)
    assert bad['safe'] is False and safe_envelope(diagonal,marginal) is False
    # Complete compatibility at endpoint 1 permits endpoint 0 to change mode.
    safe={ '0':[['wire.new'],['wire.old']], '1':[['wire.new','wire.old']] }
    assert safe_envelope(diagonal,safe)
    policy_results={}
    for policy in ('predicate','epoch','unguarded'):
        with tempfile.TemporaryDirectory() as tmp:
            net=Network(Path(tmp),[['wire.old'],['wire.old','wire.new'],[],[],[]],policy=policy)
            await net.start(); c=Client(net)
            reply=await c.acquire_box('pilot',diagonal,safe)
            assert reply['status']=='admitted' and certificate(reply['certificate'],diagonal)
            cert=reply['certificate']
            net.blocked.add((0,1))
            changed=await net.rpc(0,0,dict(op='install',support=['wire.new']))
            breaking=await net.rpc(1,1,dict(op='install',support=[]))
            await net.crash(0)
            observed=await net.rpc(0,0,dict(op='use',origin=0,sequence=cert['sequences']['0'],manifest='pilot'))
            net.blocked.clear(); await net.gossip()
            use=await c.use(cert)
            catalog=[n.state['catalog'] for n in net.nodes.values()]
            assert all(x==catalog[0] for x in catalog)
            if policy=='predicate':
                assert changed['status']=='installed' and breaking['status']=='blocked'
                assert all(x['status']=='used' for x in use)
            elif policy=='epoch':
                assert changed['status']=='blocked' and breaking['status']=='blocked'
            else:
                assert breaking['status']=='installed' and any(x['status']=='incompatible' for x in use)
            policy_results[policy]=dict(change=changed['status'],breaking=breaking['status'],
                use=[x['status'] for x in use],delivered=net.delivered,serialized_bytes=net.bytes,
                converged=all(x==catalog[0] for x in catalog))
            assert await c.retire(cert)
            c.disconnect(); await net.stop()
    # A stale observation remains identical at the observer while the owner changes.
    e=Endpoint(0,['api']); observed=e.profile(); e.install([])
    assert 'api' in observed['support'] and 'api' not in e.profile()['support']
    result=dict(pilot='completed',marginal_counterexample=bad,policies=policy_results,
        wall_seconds=time.perf_counter()-started,cpu_seconds=time.process_time()-cpu,
        peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        scope='five TCP endpoints, one OS process, controlled close/reopen recovery')
    print(json.dumps(result,indent=2,sort_keys=True))

if __name__=='__main__': asyncio.run(main())
