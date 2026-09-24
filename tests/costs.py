"""Bounded in-memory costs, not network or production performance."""
from __future__ import annotations
import json
from pathlib import Path
import resource
import time
from src.controller import Endpoint, minimum_obstruction, canonical
from src.checker import safe_envelope, obstruction
from src.envelope import verify_box


def main():
    cpu, wall = time.process_time(), time.perf_counter()
    corners, witnesses, holds = [], [], []
    # Normalization reorders options; a last raw option need not be visited last.
    normalization_case = verify_box([{'0':['good']}],
        {'0':[['good','a'],['good','b'],['good','c'],['bad']]})
    assert not normalization_case['safe'] and normalization_case['corners'] == 3
    # Last-corner rejection and full acceptance. Counts are fixed before timing.
    for n in (1,2,3,4,5,6):
        branches = [{str(k):(['good'] if k==j else []) for k in range(n)} for j in range(n)]
        for safe in (False,True):
            options = [['good','z_a'], ['good','z_b'], ['good','z_c'],
                       (['good','z_d'] if safe else ['zz_bad'])]
            box = {str(k): options for k in range(n)}
            times=[]
            for _ in range(5):
                begin=time.perf_counter_ns(); got=safe_envelope(branches,box)
                times.append(time.perf_counter_ns()-begin); assert got == safe
            producer=verify_box(branches,box)
            assert producer['safe'] == safe and producer['corners'] == 4**n
            corners.append(dict(nodes=n,corners=4**n,accepted=safe,repetitions=5,
                                checker_median_ns=sorted(times)[2],checker_min_ns=min(times)))
    for width in (1,8,32,96):
        branches=[{(0,f'branch{j}.atom{k}') for k in range(width)} for j in range(8)]
        times=[]
        for _ in range(3):
            begin=time.perf_counter_ns(); witness=minimum_obstruction(branches,set())
            times.append(time.perf_counter_ns()-begin)
            assert len(witness)==8 and obstruction(branches,set(),witness)
        witnesses.append(dict(branches=8,atoms_per_branch=width,false_atoms=8*width,
            minimum=8,dp_median_ns=sorted(times)[1],repetitions=3,
            independent_check='coverage and deletion-minimality; minimum also follows disjoint branches'))
    for count in (128,1024,12000):
        support=[f'api.{k:05d}' for k in range(count)]
        for holders in (1,8,64,384):
            ep=Endpoint(0,support,window=64)
            for h in range(holders):
                assert ep.prepare(h//64,h%64+1,f'holder{h}',support[:32])['status']=='held'
            replacement=support[:-1]+['spare.contract']
            times=[]
            for k in range(6):
                begin=time.perf_counter_ns()
                reply=ep.install(replacement if k%2==0 else support)
                times.append(time.perf_counter_ns()-begin); assert reply['status']=='installed'
            assert ep.install([])['status']=='blocked'
            holds.append(dict(contracts=count,holders=holders,conjunction_atoms=32,
                repetitions=6,install_median_ns=sorted(times)[3],
                serialized_state_bytes=len(canonical(ep.state).encode()),
                storage='in-memory only, no SQLite or RPC'))
    return dict(normalization_order_case=normalization_case,corner_checks=corners,witness_costs=witnesses,hold_costs=holds,
        cpu_seconds=time.process_time()-cpu,wall_seconds=time.perf_counter()-wall,
        peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)

if __name__=='__main__':
    print(json.dumps(main(),indent=2,sort_keys=True))
