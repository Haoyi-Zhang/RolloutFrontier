"""Trace-only deterministic checker; imports no implementation or generator.

Checks the campaign's abstract state and every successful reply against the
recorded requests. This is not independent authorship or a proof that an
unrecorded real machine obeyed its declared support set.
"""
from __future__ import annotations
import csv
import json
from pathlib import Path
import resource
import time
from tests.oracle import relation_truth


def canonical(x):
    return json.dumps(x, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def local(hold, support):
    for option in hold.get('options', [hold['requires']]):
        if all(atom in support for atom in option):
            return True
    return False


def check(path: Path, table: Path) -> dict:
    expected = {}
    with table.open(newline='') as f:
        for row in csv.DictReader(f):
            expected[(row['family'], int(row['seed']), row['policy'])] = row
    nodes = key = config = counts = None
    cases, checked, bytes_, controls = 0, 0, 0, {}
    def finish():
        nonlocal cases
        if key is None: return
        row = expected.pop(key)
        for name in ('delivered', 'serialized_bytes', 'installed', 'blocked', 'unchanged', 'incompatible_snapshots'):
            assert int(row[name]) == counts[name], (key, name, row[name], counts[name])
        assert all(n['catalog'] == nodes[0]['catalog'] for n in nodes.values())
        assert not any(n['holds'] for n in nodes.values())
        controls[key[2]] = controls.get(key[2], 0) + counts['incompatible_snapshots']
        cases += 1
    with path.open() as f:
        for line in f:
            event = json.loads(line)
            if event['event'] == 'case-start':
                finish(); config = event
                key = (event['case']['family'], event['case']['seed'], event['case']['policy'])
                nodes = {int(n): dict(support=sorted(s), generation=0, floor=[0]*6,
                    holds={}, closed=set(), catalog={str(n):dict(node=int(n),generation=0,support=sorted(s))})
                    for n,s in event['initial_support'].items()}
                assert relation_truth(config['branches'], {str(n):x['support'] for n,x in nodes.items()})
                counts = {k:0 for k in ('delivered','serialized_bytes','installed','blocked','unchanged','incompatible_snapshots')}
                continue
            assert config is not None
            assert key == (event['case']['family'], event['case']['seed'], event['case']['policy'])
            kind = event['event']
            if kind == 'oracle':
                snapshot = {str(n):s['support'] for n,s in nodes.items()}
                assert event['physical'] == snapshot
                truth = relation_truth(config['branches'], snapshot)
                assert event['compatible'] == truth
                counts['incompatible_snapshots'] += not truth
                if key[2] not in ('marginal','unguarded'): assert truth
                continue
            if kind in ('lost','unreachable','crash','recover'): continue
            assert kind == 'rpc'
            req, reply = event['request'], event['response']
            n = event['target']; node = nodes[n]
            wire = len((canonical(req)+'\n').encode()) + len((canonical(reply)+'\n').encode())
            assert wire == event['bytes'] and 0 <= event['wall_ns']
            counts['delivered'] += 1; counts['serialized_bytes'] += wire
            checked += 1; bytes_ += wire
            op, status = req['op'], reply['status']
            if op == 'prepare':
                origin, sequence = req['origin'], req['sequence']; token = (origin, sequence)
                if sequence <= node['floor'][origin] or token in node['closed']:
                    assert status == 'closed'; continue
                if sequence > node['floor'][origin] + config['window']:
                    assert status == 'window'; continue
                h = dict(status='held', node=n, origin=origin, sequence=sequence,
                         manifest=req['manifest'], requires=sorted(set(req['requires'])),
                         observed_generation=node['generation'])
                if 'options' in req:
                    h['options'] = [list(x) for x in sorted({tuple(sorted(set(o))) for o in req['options']})]
                if token in node['holds']:
                    old = node['holds'][token]
                    same = all(old.get(k) == h.get(k) for k in ('manifest','requires','options'))
                    assert status == ('held' if same else 'binding-conflict')
                    if same: assert reply['receipt'] == old
                elif local(h, node['support']):
                    assert status == 'held' and reply['receipt'] == h
                    node['holds'][token] = h
                else:
                    assert status == 'missing'
            elif op == 'close':
                origin, sequence = req['origin'], req['sequence']; token=(origin,sequence)
                if sequence > node['floor'][origin] + config['window']:
                    assert status == 'window'; continue
                assert status == 'closed'
                if sequence > node['floor'][origin]:
                    node['holds'].pop(token, None); node['closed'].add(token)
                    while (origin, node['floor'][origin]+1) in node['closed']:
                        node['closed'].remove((origin,node['floor'][origin]+1)); node['floor'][origin] += 1
                    assert reply['floor'] == node['floor'][origin]
            elif op == 'install':
                target = sorted(set(req['support']))
                blockers = [h for h in node['holds'].values() if config['endpoint_policy'] == 'epoch'
                            or (config['endpoint_policy'] == 'predicate' and not local(h,target))]
                if target == node['support']: assert status == 'unchanged'
                elif blockers: assert status == 'blocked'
                else:
                    assert status == 'installed'; node['generation'] += 1; node['support'] = target
                    node['catalog'][str(n)] = dict(node=n,generation=node['generation'],support=target)
                counts[status] += 1
                if status in ('installed','unchanged'):
                    assert reply['observed'] == dict(node=n,generation=node['generation'],support=node['support'])
            elif op == 'read':
                assert status == 'observed'
                assert reply['observed'] == dict(node=n,generation=node['generation'],support=node['support'])
            elif op == 'use':
                token=(req['origin'],req['sequence']); h=node['holds'].get(token)
                if h is None or h['manifest'] != req['manifest']: assert status == 'not-authorized'
                else:
                    assert status == ('used' if local(h,node['support']) else 'incompatible')
                    assert reply['generation'] == node['generation']
            elif op == 'merge':
                p=req['profile']; owner=p['node']; old=node['catalog'].get(str(owner))
                if owner == n:
                    own=dict(node=n,generation=node['generation'],support=node['support'])
                    assert status == ('unchanged' if p == own else 'self-authority-rejected')
                elif old and p['generation'] == old['generation'] and p != old:
                    assert status == 'equivocation-rejected'
                elif old is None or p['generation'] > old['generation']:
                    assert status == 'merged'; node['catalog'][str(owner)] = p
                else: assert status == 'unchanged'
            else:
                raise AssertionError('unsupported trace operation '+op)
            if config['endpoint_policy'] != 'unguarded':
                assert all(local(h,node['support']) for h in node['holds'].values())
    finish(); assert not expected
    assert all(controls[p] == 0 for p in ('epoch','branch','envelope','frontier'))
    assert controls['marginal'] > 0 and controls['unguarded'] > 0
    return dict(cases=cases, checked_rpc=checked, serialized_bytes=bytes_,
                incompatible_snapshots=controls, scope='full network campaign trace, separate state reconstruction')

if __name__ == '__main__':
    import sys
    root=Path(sys.argv[1] if len(sys.argv)>1 else 'results')
    cpu, wall = time.process_time(), time.perf_counter()
    result=check(root/'network-trace.jsonl',root/'network.csv')
    result.update(cpu_seconds=time.process_time()-cpu,wall_seconds=time.perf_counter()-wall,
                  peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    print(json.dumps(result,indent=2,sort_keys=True))
