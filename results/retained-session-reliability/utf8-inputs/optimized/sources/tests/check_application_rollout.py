"""Independently replay ProtoJSON study records using only Python's standard library.

This checker imports neither the application handler nor the planner/runtime.
It reconstructs schema support, safe interval products, per-owner guards and
application effects from JSON observations and retained SQLite databases.
"""
from __future__ import annotations
import argparse
from collections import deque, Counter
from copy import deepcopy
import gzip
import itertools
import json
import math
from pathlib import Path
import shutil
import sqlite3
import statistics
import tempfile

NAMES = ('legacy', 'accepting', 'emitting', 'current')
ALIASES = (('ACTIVE',), ('ACTIVE', 'ENABLED'), ('ENABLED', 'ACTIVE'), ('ENABLED',))
PROFILES = [sorted(['emit:' + aliases[0], 'program:' + name] + ['parse:' + a for a in aliases])
            for name, aliases in zip(NAMES, ALIASES)]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(path.read_text())


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def program(support):
    require(support in PROFILES, 'unregistered physical program profile')
    return PROFILES.index(support)


def safe(state):
    return ALIASES[state[0]][0] in ALIASES[state[1]] and ALIASES[state[1]][0] in ALIASES[state[2]]


def phase(source, target):
    return (source != target and all(a <= b for a, b in zip(source, target)) and
            all(safe(state) for state in itertools.product(*(range(a, b + 1) for a, b in zip(source, target)))))


def graph_checks(output):
    states = [s for s in itertools.product(range(4), repeat=3) if safe(s)]
    edges = {s: [t for t in states if phase(s, t)] for s in states}
    single = {s: [t for t in edges[s] if sum(t[i] - s[i] for i in range(3)) == 1] for s in states}
    outcomes = {'queries': len(states)**2, 'compatible_configurations': len(states),
                'no_op': 0, 'reachable_nontrivial': 0, 'unreachable': 0,
                'frontier_phases': 0, 'one_step_phases': 0, 'segmented_phases': 0,
                'segmentation_gaps': 0, 'plan_disagreements': 0}
    with gzip.open(output / 'catalog-plans.jsonl.gz', 'rt') as stream:
        rows = [json.loads(line) for line in stream]
    require(len(rows) == len(states)**2, 'catalog goal inventory')
    lookup = {(tuple(row['source']), tuple(row['target'])): row for row in rows}
    require(len(lookup) == len(rows), 'duplicated catalog goal')
    for source in states:
        distance, todo = {source: 0}, deque([source])
        while todo:
            state = todo.popleft()
            for target in edges[state]:
                if target not in distance:
                    distance[target] = distance[state] + 1
                    todo.append(target)
        paths, todo = {source: [source]}, deque([source])
        while todo:
            state = todo.popleft()
            for target in single[state]:
                if target not in paths:
                    paths[target] = paths[state] + [target]
                    todo.append(target)
        for target in states:
            row = lookup[(source, target)]
            result = row['plan']
            if target not in distance:
                outcomes['unreachable'] += 1
                require(result['status'] == 'unreachable' and result.get('cost') is None and result.get('phases') == [], 'incorrect unreachable goal')
                continue
            require(result['status'] == 'planned', 'reachable catalog goal missing plan')
            expected = {'phases': distance[target], 'installations': sum(b - a for a, b in zip(source, target)),
                        'handoffs': max(distance[target] - 1, 0)}
            require(result['cost'] == expected, 'frontier differs from independent phase graph')
            validate_plan(result, source, target)
            if source == target:
                outcomes['no_op'] += 1
                continue
            outcomes['reachable_nontrivial'] += 1
            path = paths[target]
            best = [0] + [10**9] * (len(path) - 1)
            for end in range(1, len(path)):
                for start in range(end):
                    if phase(path[start], path[end]):
                        best[end] = min(best[end], best[start] + 1)
            outcomes['frontier_phases'] += distance[target]
            outcomes['one_step_phases'] += len(path) - 1
            outcomes['segmented_phases'] += best[-1]
            outcomes['segmentation_gaps'] += best[-1] > distance[target]
    return outcomes


def validate_plan(plan, source, target):
    expected_branches = [{str(i):sorted(needed(i,list(pair))) for i in range(3)}
                         for pair in itertools.product(('ACTIVE','ENABLED'),repeat=2)]
    require({canonical(b) for b in plan['branches']} == {canonical(b) for b in expected_branches}, 'application compatibility manifest differs')
    expected_catalog={str(i):PROFILES for i in range(3)}
    require(set(plan['catalog'])==set(expected_catalog) and all({tuple(p) for p in plan['catalog'][n]}=={tuple(p) for p in PROFILES} and len(plan['catalog'][n])==4 for n in expected_catalog), 'application catalog differs')
    expected_edges={(tuple(PROFILES[i]),tuple(PROFILES[i+1])) for i in range(3)}
    require(set(plan['transitions'])==set(expected_catalog) and all(len(plan['transitions'][n])==3 and {(tuple(e['source']),tuple(e['target'])) for e in plan['transitions'][n]}==expected_edges for n in expected_catalog), 'application transitions differ')
    require(plan['cost']['phases']==len(plan['phases']) and plan['cost']['handoffs']==max(len(plan['phases'])-1,0), 'reported phase count differs')
    require({str(i): PROFILES[source[i]] for i in range(3)} == plan['initial'], 'plan source')
    require({str(i): PROFILES[target[i]] for i in range(3)} == plan['target'], 'plan target')
    current, writes = source, 0
    for item in plan['phases']:
        beginning = tuple(program(item['source'][str(i)]) for i in range(3))
        ending = tuple(program(item['target'][str(i)]) for i in range(3))
        require(beginning == current and phase(beginning, ending), 'unsafe or disconnected application phase')
        for corner in itertools.product(*(item['box'][str(i)] for i in range(3))):
            require(any(all(set(branch[str(i)]) <= set(corner[i]) for i in range(3))
                        for branch in plan['branches']), 'unsafe guard corner')
        require(all(any(set(term)<=set(PROFILES[beginning[i]]) for term in item['box'][str(i)]) for i in range(3)), 'phase guard excludes its source')
        local_paths={str(i):[PROFILES[beginning[i]]] for i in range(3)}
        for step in item['steps']:
            node = int(step['node']); following = program(step['support'])
            require(following == current[node] + 1, 'undeclared application edge')
            require(any(set(term) <= set(step['support']) for term in item['box'][str(node)]), 'step outside guard')
            local_paths[str(node)].append(PROFILES[following])
            current = tuple(following if i == node else current[i] for i in range(3)); writes += 1
            require(safe(current), 'incompatible application state')
        require(current == ending and item['local_paths']==local_paths, 'phase path witness differs')
    require(current == target and writes == plan['cost']['installations'], 'application plan outcome')


def needed(node, codec):
    require(isinstance(codec, list) and len(codec) == 2 and all(x in ('ACTIVE', 'ENABLED') for x in codec), 'wire contracts')
    return ({'emit:' + codec[0]} if node == 0 else
            {'parse:' + codec[0], 'emit:' + codec[1]} if node == 1 else {'parse:' + codec[1]})


def semantic(value):
    require(isinstance(value, dict) and set(value) == {'key', 'amount'} and isinstance(value['key'], str)
            and bool(value['key']) and type(value['amount']) is int, 'invalid semantic data')
    return value


def application_output(node, index, codec, value):
    require(needed(node, codec) <= set(PROFILES[index]), 'handler lacks application contracts')
    if node == 0:
        record = semantic(value)
    else:
        raw = json.loads(value)
        require(set(raw) == {'key', 'amount', 'state'} and raw['state'] == codec[node - 1]
                and raw['state'] in ALIASES[index] and isinstance(raw['amount'], str), 'ProtoJSON wire mismatch')
        record = semantic({'key': raw['key'], 'amount': int(raw['amount'])})
    if node == 1:
        record = {**record, 'amount': 3 * record['amount'] + 7}
    if node == 2:
        return {'record': record}
    return {'wire': canonical({'key': record['key'], 'amount': str(record['amount']), 'state': ALIASES[index][0]})}


def owner_database(output, record, node):
    path = output / 'databases' / record['name'] / f'process-node-{node}.sqlite'
    require(path.is_file(), 'missing application owner database')
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
        state_rows = db.execute('SELECT id,payload FROM state').fetchall()
        require(len(state_rows) == 1 and state_rows[0][0] == 1, 'owner state row')
        final = json.loads(state_rows[0][1])
        effects = {r[0]: {'codec': json.loads(r[1]), 'input': json.loads(r[2]), 'output': json.loads(r[3]),
                         'generation': r[4], 'program': r[5]} for r in db.execute('SELECT * FROM application_results')}
        audit = [(r[0], json.loads(r[1]), json.loads(r[2]), json.loads(r[3]))
                 for r in db.execute('SELECT * FROM application_audit ORDER BY ordinal')]
    profile = {'node': node, 'generation': 0, 'support': record['initial'][node]}
    holds, floors, seen = {}, [0] * 6, set()
    stats = Counter()
    audit_lookup = {ordinal: (request, response) for ordinal, request, response, _ in audit}
    for ordinal, req, response, observed in audit:
        op, status = req.get('op'), response.get('status')
        if op == 'prepare' and status == 'held':
            terms = req.get('options', [req['requires']])
            require(any(set(t) <= set(profile['support']) for t in terms), 'admitted unsupported hold')
            key = (req['origin'], req['sequence'])
            require(req['sequence'] > floors[req['origin']], 'revived retired sequence')
            holds[key] = {'terms': terms, 'manifest': req['manifest']}
        elif op == 'close' and status in ('closed',):
            key = (req['origin'], req['sequence']); holds.pop(key, None)
            floors[req['origin']] = max(floors[req['origin']], response.get('floor', 0))
        elif op in ('install', 'install_if_current'):
            if status == 'installed':
                next_support = req['support']; program(next_support)
                require(next_support != profile['support'], 'spurious installed response')
                require(all(any(set(t) <= set(next_support) for t in h['terms']) for h in holds.values()),
                        'installation violated a retained guard')
                if op == 'install_if_current':
                    require(req['expected_generation'] == profile['generation'] and req['expected_support'] == profile['support'], 'stale installation applied')
                profile = {'node': node, 'generation': profile['generation'] + 1, 'support': next_support}
                require(response['observed'] == profile, 'installed generation/code selector mismatch')
                stats['installs'] += 1
            elif status == 'blocked':
                require(any(not any(set(t) <= set(req['support']) for t in h['terms']) for h in holds.values()), 'unexplained blocked install')
                stats['blocked_installs'] += 1
        elif op == 'application':
            key = (req['origin'], req['sequence']); hold = holds.get(key)
            if status == 'applied':
                require(hold is not None and hold['manifest'] == req['manifest'], 'application has no live authority')
                require(all(needed(node, req['codec']) <= set(t) for t in hold['terms']), 'application codec not retained')
                effect = effects.get(req['request_id']); require(effect is not None, 'application reply lacks durable effect')
                require(effect['input'] == req['input'] and effect['codec'] == req['codec'], 'durable application request binding')
                index = NAMES.index(effect['program'])
                expected = application_output(node, index, req['codec'], req['input'])
                require(response['output'] == expected == effect['output'], 'incorrect application output')
                require(response['applied_generation'] == effect['generation'] and response['applied_program'] == effect['program'], 'application generation evidence differs')
                require(effect['generation'] <= profile['generation'], 'application effect from future program')
                if not response['duplicate']:
                    require(req['request_id'] not in seen and effect['generation'] == profile['generation']
                            and effect['program'] == NAMES[program(profile['support'])], 'effect not tied to active program')
                seen.add(req['request_id']); stats['applied_calls'] += 1
            elif status == 'not-authorized':
                require(hold is None or hold['manifest'] != req['manifest'], 'unexplained authority rejection')
                stats['authority_rejections'] += 1
            elif status == 'codec-not-retained':
                require(hold is not None and any(not needed(node, req['codec']) <= set(t) for t in hold['terms']), 'unexplained codec rejection')
                stats['codec_rejections'] += 1
        require(observed == profile, 'audit state differs from replayed activation')
    require(final['support'] == profile['support'] and final['generation'] == profile['generation'], 'final owner state differs from replay')
    for request_id, effect in effects.items():
        require(request_id in seen, 'unobserved application effect')
        require(effect['output'] == application_output(node, NAMES.index(effect['program']), effect['codec'], effect['input']), 'retained effect semantic mismatch')
    for event in record['trace']:
        if event['event'] == 'rpc' and event['target'] == node:
            require(event.get('owner_order') in audit_lookup, 'network response missing owner audit')
            require(audit_lookup[event['owner_order']] == (event['request'], event['response']), 'network/owner audit mismatch')
            require(event['end_ns'] >= event['start_ns'] and event['wall_ns'] == event['end_ns'] - event['start_ns'], 'RPC clock interval')
    stats['effects'] = len(effects)
    return effects, dict(stats)


def origin_database(output, record, *, expected_pending=0):
    path = output / 'databases' / record['name'] / 'origin-2.sqlite'
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
        sessions = db.execute('SELECT manifest,codec,closing FROM application_sessions').fetchall()
        requests = db.execute('SELECT manifest,request_id,input,codec,status,output FROM application_requests').fetchall()
    indexed = {row[0]: row for row in sessions}
    require(len(indexed) == len(sessions) and all(row[2] == 1 for row in sessions), 'origin session drain gate')
    pending = 0
    completed = {}
    for manifest, request_id, raw_input, raw_codec, status, raw_output in requests:
        require(manifest in indexed and raw_codec == indexed[manifest][1], 'origin request/session binding')
        original = semantic(json.loads(raw_input))
        if status == 'pending':
            pending += 1
            require(raw_output is None, 'pending origin request has output')
        else:
            require(status == 'complete', 'origin request status')
            result = json.loads(raw_output)
            require(result['record'] == {'key':original['key'], 'amount':3*original['amount']+7}, 'origin durable output differs')
            completed[request_id] = result['record']
    require(pending == expected_pending, 'unexpected unresolved application requests')
    if 'requests' in record:
        require(completed == {r['request_id']:r['output'] for r in record['requests']}, 'origin durable traffic inventory')
    return len(requests)


def quantile(values, fraction):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def check(output, verify_summary=True):
    output = output.resolve()
    plan = read(output / 'plan.json'); validate_plan(plan, (0, 0, 0), (3, 3, 3))
    require(plan['cost'] == {'phases': 3, 'installations': 9, 'handoffs': 2}, 'documented migration goal')
    probes = read(output / 'schema-probes.json')
    require(len(probes) == 8, 'schema probe inventory')
    require({(p['program'], p['input_name']) for p in probes} == set(itertools.product(NAMES, ('ACTIVE','ENABLED'))), 'probe coverage')
    for row in probes:
        index = NAMES.index(row['program'])
        accepted = row['input_name'] in ALIASES[index]
        require(row['accepted'] == accepted and row['emitted_name'] == ALIASES[index][0], 'actual protobuf probe differs from schema')
        require(row['output'] == ({'key': 'probe', 'amount': 23} if accepted else None), 'probe semantic result')
    inventory = read(output / 'runs.json')
    require(len(inventory) == 18, 'traffic trial inventory')
    expected_design = set(itertools.product(('fixed','rollout'), (1,4,16), range(3)))
    observed_design, summaries, overall = set(), [], Counter()
    for item in inventory:
        record = read(output / item['path']); require(record['name'] == item['name'], 'traffic path binding')
        observed_design.add((record['condition'], record['concurrency'], record['repetition']))
        require(record['request_count'] == len(record['requests']) == 96, 'traffic request denominator')
        effects = []
        for node in range(3):
            data, counts = owner_database(output, record, node); effects.append(data); overall.update(counts)
        origin_database(output, record)
        ids = {request['request_id'] for request in record['requests']}
        require(len(ids) == 96 and all(set(data) == ids for data in effects), 'traffic durable request inventory')
        latencies = []
        for request in record['requests']:
            original = semantic(request['input']); expected = {'key': original['key'], 'amount': 3*original['amount'] + 7}
            require(request['output'] == expected == effects[2][request['request_id']]['output']['record'], 'end-to-end application output')
            require(request['end_ns'] >= request['start_ns'] and request['latency_ns'] == request['end_ns'] - request['start_ns'], 'request latency interval')
            payload = original
            for node in range(3):
                effect = effects[node][request['request_id']]
                require(effect['input'] == payload and effect['codec'] == request['codec'], 'pipeline input chain')
                payload = effect['output'].get('wire') if node < 2 else effect['output']['record']
            latencies.append(request['latency_ns'] / 1e6)
        events = []
        for req in record['requests']:
            events += [(req['start_ns'], 1), (req['end_ns'], -1)]
        active = maximum = 0
        for _, delta in sorted(events, key=lambda x: (x[0], x[1])):
            active += delta; maximum = max(maximum, active)
        require(maximum <= record['concurrency'] and active == 0, 'observed concurrency exceeds design')
        installs = [event for event in record['trace'] if event['event'] == 'rpc' and
                    event['request']['op'] == 'install_if_current' and event['response']['status'] == 'installed']
        overlap = sum(any(request['start_ns'] < event['end_ns'] and request['end_ns'] > event['start_ns'] for event in installs)
                      for request in record['requests'])
        target = 3 if record['condition'] == 'rollout' else 0
        require(all(p['support'] == PROFILES[target] for p in record['final_profiles']), 'traffic final program')
        if record['condition'] == 'rollout':
            require(len(installs) == 9 and overlap > 0, 'rollout did not overlap active application requests')
            require(record['job_state']['stage'] == 'complete', 'application rollout incomplete')
        else:
            require(not installs and record['job_state'] is None, 'fixed condition changed handler')
        summaries.append({'name': record['name'], 'condition': record['condition'], 'concurrency': record['concurrency'],
            'repetition': record['repetition'], 'requests': 96, 'observed_max_concurrency': maximum,
            'median_latency_ms': statistics.median(latencies), 'p95_latency_ms': quantile(latencies,.95),
            'requests_overlapping_install_rpc': overlap, 'installed_program_changes': len(installs),
            'blocked_install_attempts': sum(event['event']=='rpc' and event['request']['op']=='install_if_current' and event['response']['status']=='blocked'
                                          for event in record['trace'])})
    require(observed_design == expected_design, 'traffic design differs')
    controls = read(output / 'controls.json'); require(len(controls)==3 and {x['name'] for x in controls} == {'drain','guard-controls','crash-recovery'}, 'control inventory')
    for record in controls:
        origin_database(output, record, expected_pending=1 if record['name']=='guard-controls' else 0)
        for node in range(3):
            _, counts = owner_database(output, record, node); overall.update(counts)
    mapped = {x['name']:x for x in controls}
    drain = mapped['drain']
    require(drain['premature_install']['status']=='blocked' and drain['new_request_rejected'] and drain['retired']
            and drain['after_drain_install']['status']=='installed' and drain['late_request']['status']=='not-authorized'
            and drain['result']['record']=={'key':'drain','amount':40}, 'drain control failed')
    guard = mapped['guard-controls']
    require(guard['pipeline_rejected'] and guard['weak_authority']['status']=='codec-not-retained'
            and guard['unknown_program']['status']=='invalid', 'guard controls failed')
    crash = mapped['crash-recovery']
    require(crash['pending_retirement'] is False, 'uncertain output incorrectly retired')
    with sqlite3.connect((output / 'databases/crash-pending/origin-2.sqlite').as_uri() + '?mode=ro', uri=True) as db:
        pending = db.execute('SELECT request_id,status,output FROM application_requests').fetchall()
        closing = db.execute('SELECT closing FROM application_sessions').fetchall()
        require(pending == [('uncertain-request','pending',None)] and closing == [(1,)], 'pending origin state not retained')
    for node in range(3):
        path = output / 'databases/crash-pending' / f'process-node-{node}.sqlite'
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
            state = json.loads(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
        require(any(hold.get('status')=='held' and hold.get('origin')==2 for hold in state['slots'].values()), 'pending request lost owner authority')
    require(crash['sink_exit_code']==-9 and len(crash['committed_before_retry'])==1
            and all(x['duplicate'] for x in crash['retry']['owner_replies'])
            and crash['retry']['record']=={'key':'recovered','amount':-14}
            and crash['reopened']['observed']['support']==PROFILES[2]
            and crash['after_reopen']['record']=={'key':'active','amount':16}, 'actual crash recovery evidence failed')
    summary = {'status':'pass', 'catalog':graph_checks(output), 'traffic_trials':18,
        'completed_pipeline_requests':18*96, 'owner_effects_in_traffic':18*96*3,
        'migration_cost':plan['cost'], 'controls':3, 'schema_probes':8,
        'observed_owner_counts':dict(overall), 'trials':summaries}
    if verify_summary:
        require(read(output / 'summary.json') == summary, 'stored summary differs from raw evidence')
    return summary


def corruption_controls(output):
    result = []
    for kind in ('changed-output', 'missing-durable-effect', 'removed-owner-audit',
                 'changed-phase-count', 'source-excluding-guard', 'changed-local-path', 'missing-catalog-edge'):
        with tempfile.TemporaryDirectory(prefix='application-corruption-') as temporary:
            copied = Path(temporary) / 'records'; shutil.copytree(output, copied)
            item = read(copied / 'runs.json')[0]
            if kind == 'changed-output':
                path = copied / item['path']; record = read(path); record['requests'][0]['output']['amount'] += 1
                path.write_text(json.dumps(record))
            elif kind in ('changed-phase-count','source-excluding-guard','changed-local-path','missing-catalog-edge'):
                path=copied/'plan.json';plan=read(path)
                if kind=='changed-phase-count':
                    old=plan['phases'][0];first,second=deepcopy(old),deepcopy(old)
                    first['steps']=old['steps'][:1];second['steps']=old['steps'][1:]
                    state=deepcopy(old['source']);step=first['steps'][0];state[step['node']]=step['support']
                    first['target']=deepcopy(state);second['source']=deepcopy(state)
                    for item in (first,second):
                        local={n:[p] for n,p in item['source'].items()}
                        for step in item['steps']:local[step['node']].append(step['support'])
                        item['local_paths']=local
                    plan['phases'][:1]=[first,second]
                elif kind=='source-excluding-guard':
                    item=plan['phases'][0];node=item['steps'][0]['node']
                    item['box'][node]=[item['target'][node]]
                elif kind=='changed-local-path':
                    item=plan['phases'][0];node=item['steps'][0]['node'];item['local_paths'][node]=[item['source'][node]]
                else:
                    plan['transitions']['0'].pop()
                path.write_text(json.dumps(plan))
            else:
                path = copied / 'databases' / item['name'] / 'process-node-2.sqlite'
                with sqlite3.connect(path) as db:
                    if kind == 'missing-durable-effect':
                        db.execute('DELETE FROM application_results WHERE request_id=(SELECT request_id FROM application_results LIMIT 1)')
                    else:
                        db.execute('DELETE FROM application_audit WHERE ordinal=(SELECT MAX(ordinal) FROM application_audit)')
            try:
                check(copied, verify_summary=False)
            except ValueError as error:
                result.append({'mutation':kind, 'rejected':True, 'reason':str(error)})
            else:
                raise ValueError('semantic corruption survived: ' + kind)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', required=True, type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--corruption-controls', action='store_true')
    args = parser.parse_args(); value = check(args.results)
    if args.corruption_controls: value['corruption_controls'] = corruption_controls(args.results)
    encoded = json.dumps(value, sort_keys=True, indent=2) + '\n'
    if args.out: args.out.write_text(encoded)
    print(encoded)
