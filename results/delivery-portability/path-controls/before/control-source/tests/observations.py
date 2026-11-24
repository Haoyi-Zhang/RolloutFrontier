"""Paired admission checks on frozen live states with separately stale evidence.

Cached baselines return a proposed admission, never a durable guarantee. A fresh
read is measured at a quiescent snapshot here; a separate directed test exposes
its check-to-use race. The controller's internal state is used only by the oracle.
"""
from __future__ import annotations
import asyncio
import csv
import json
from pathlib import Path
import random
import resource
import tempfile
import time
from tests.oracle import relation_truth
from src.network import Network, Client

POLICIES = ['central-latest', 'local-only', 'last-observation', 'generation-cache',
            'intersection-only', 'fresh-read', 'guarded']
FAMILIES = ['independent', 'correlated', 'one-sided', 'bridge']
SEEDS = range(6)
STEPS = 24

def manifest(family):
    cells = [(0,0), (0,1), (1,0), (1,1)]
    if family in ('correlated', 'bridge'): cells = [(0,0), (1,1)]
    elif family == 'one-sided': cells = [(0,0), (0,1), (1,0)]
    names = ['wire.old', 'wire.new']
    return [{str(n): [names[x]] for n,x in enumerate(cell)} for cell in cells]

async def case(directory, family, seed):
    rng = random.Random(seed)
    branches = manifest(family)
    initial = [['wire.old'], ['wire.old'], ['api.base'], ['api.base'], ['api.base']]
    if family == 'bridge': initial[1] = ['wire.old', 'wire.new']
    net = Network(directory, initial, seed=seed)
    await net.start(); client = Client(net)
    last = {n: net.nodes[n].profile() for n in (0,1)}
    generation = dict(last)
    held_old = dict(last[1])
    rows = []
    # The complete proposed schedule is generated before decisions.
    options = [[], ['wire.old'], ['wire.new'], ['wire.old', 'wire.new']]
    updates = [(rng.randrange(2), list(options[rng.randrange(4)])) for _ in range(STEPS)]
    try:
        for step, (node, support) in enumerate(updates):
            if step == 3: net.blocked.add((0,1))
            if step == 14: net.blocked.clear()
            result = await net.rpc(node, node, dict(op='install', support=support))
            assert result['status'] in ('installed','unchanged')
            # New advertisements at fixed steps; later an older one is replayed.
            if step % 3 == 0:
                p = net.nodes[1].profile()
                r = await net.rpc(1, 0, dict(op='merge', profile=p))
                if r is not None:
                    last[1] = p
                    if p['generation'] > generation[1]['generation']: generation[1] = p
                if step == 0: held_old = p
            if step in (2, 15, 20):
                r = await net.rpc(1, 0, dict(op='merge', profile=held_old))
                if r is not None:
                    last[1] = held_old
                    if held_old['generation'] > generation[1]['generation']: generation[1] = held_old
            last[0] = generation[0] = net.nodes[0].profile()
            actual = {str(n): set(net.nodes[n].state['support']) for n in (0,1)}
            truth = relation_truth(branches, actual)
            target = {'wire.old'} if step < 3 else {'wire.new'}
            central = {str(n): target for n in (0,1)}
            local = {str(n): set(last[0]['support']) for n in (0,1)}
            arrival = {str(n): set(last[n]['support']) for n in (0,1)}
            recent = {str(n): set(generation[n]['support']) for n in (0,1)}
            common = set.intersection(*recent.values())
            intersect = {str(n): common for n in (0,1)}
            decisions = {p: relation_truth(branches, s) for p,s in zip(POLICIES[:5],
                         [central, local, arrival, recent, intersect])}
            reads = [await net.rpc(0, n, dict(op='read')) for n in (0,1)]
            known = all(r is not None and r['status'] == 'observed' for r in reads)
            decisions['fresh-read'] = known and relation_truth(branches,
                {str(n): set(r['observed']['support']) for n,r in enumerate(reads)})
            granted = await client.acquire(f'query-{family}-{seed}-{step}', branches)
            decisions['guarded'] = granted['status'] == 'admitted'
            if decisions['guarded']:
                assert truth
                assert await client.retire(granted['certificate'])
            for policy, admitted in decisions.items():
                rows.append(dict(family=family, seed=seed, step=step, policy=policy,
                    feasible=int(truth), admitted=int(admitted),
                    unsafe_admission=int(admitted and not truth),
                    withheld_feasible=int(truth and not admitted),
                    partitioned=int((0,1) in net.blocked),
                    live_support={n:sorted(v) for n,v in actual.items()},
                    arrival_generations={str(n):last[n]['generation'] for n in (0,1)},
                    max_generations={str(n):generation[n]['generation'] for n in (0,1)}))
        net.blocked.clear(); await client.recover(); await net.gossip()
        assert all(x.state['catalog'] == net.nodes[0].state['catalog'] for x in net.nodes.values())
        assert net.opened_connections <= 5
        return rows, net.trace, net.delivered, net.bytes, net.opened_connections
    finally:
        client.disconnect(); await net.stop()

async def read_race(directory):
    net = Network(directory, [['a']] * 5)
    await net.start()
    try:
        before = await net.rpc(0,1,dict(op='read'))
        changed = await net.rpc(1,1,dict(op='install', support=[]))
        observation_would_admit = 'a' in before['observed']['support']
        actual_incompatible = 'a' not in net.nodes[1].state['support']
        assert observation_would_admit and actual_incompatible
        assert net.opened_connections <= 2
        return dict(observed_admission=True, incompatible_before_use=True,
                    update=changed['status'], trace=net.trace,
                    tcp_connections_opened=net.opened_connections)
    finally:
        await net.stop()

def main(destination):
    destination.mkdir(parents=True, exist_ok=True)
    start, cpu = time.perf_counter(), time.process_time()
    counts = {p: dict(queries=0, feasible=0, admitted=0, unsafe_admission=0,
                     withheld_feasible=0, partition_queries=0) for p in POLICIES}
    events = bytes_ = connections = 0
    with (destination/'observations.csv').open('w', newline='') as f, \
         (destination/'observation-trace.jsonl').open('w') as log, \
         tempfile.TemporaryDirectory(prefix='compat-observations-') as d:
        fields = ['family','seed','step','policy','feasible','admitted','unsafe_admission',
                  'withheld_feasible','partitioned']
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore'); writer.writeheader()
        for family in FAMILIES:
            for seed in SEEDS:
                rows, trace, delivered, wire, opened = asyncio.run(
                    case(Path(d)/f'{family}-{seed}', family, seed))
                writer.writerows(rows); events += delivered; bytes_ += wire; connections += opened
                for row in rows:
                    c = counts[row['policy']]; c['queries'] += 1
                    for k in ('feasible','admitted','unsafe_admission','withheld_feasible'): c[k] += row[k]
                    c['partition_queries'] += row['partitioned']
                    log.write(json.dumps(dict(event='decision', **row), sort_keys=True)+'\n')
                for event in trace:
                    log.write(json.dumps(dict(case=f'{family}-{seed}', **event), sort_keys=True)+'\n')
        race = asyncio.run(read_race(Path(d)/'race'))
        connections += race.pop('tcp_connections_opened')
    assert counts['guarded']['unsafe_admission'] == counts['fresh-read']['unsafe_admission'] == 0
    assert all(counts[p]['unsafe_admission'] > 0 for p in ('central-latest','local-only','last-observation','generation-cache'))
    answer = dict(policies=counts, paired_states=len(FAMILIES)*len(SEEDS)*STEPS,
                  delivered=events, serialized_bytes=bytes_,
                  tcp_connections_opened=connections, read_race=race,
                  cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-start,
                  peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    (destination/'observations.json').write_text(json.dumps(answer, indent=2, sort_keys=True)+'\n')
    return answer

if __name__ == '__main__':
    import sys
    print(json.dumps(main(Path(sys.argv[1] if len(sys.argv)>1 else 'results')), indent=2, sort_keys=True))
