"""Independently reconstruct the registered numerical-policy goal study.

Only Python standard-library modules are imported. The integer state/interval
graphs, literal positive corners, complete task inventory and SQLite evidence
are checked without importing the planner, synthesizer or durable coordinator.
"""
from __future__ import annotations

import argparse
from collections import Counter, deque
from copy import deepcopy
import gzip
import hashlib
import itertools
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def equal(value, expected, message):
    require(canonical(value) == canonical(expected), message)


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe(vector, server_count):
    servers, clients = vector[:server_count], vector[server_count:]
    return (all(type(v) is int for v in vector)
            and max(servers) - min(servers) <= 1
            and all(max(servers) - 3 <= v <= min(servers) for v in clients))


def phase_safe(source, target, server_count):
    """All points in the directed interval hull obey the numerical rules."""
    if any(a > b for a, b in zip(source, target)):
        return False
    servers = range(server_count)
    return (all(target[i] - source[j] <= 1 for i in servers for j in servers if i != j)
            and all(target[i] <= min(source[:server_count])
                    and source[i] >= max(target[:server_count]) - 3
                    for i in range(server_count, len(source))))


def specifications(fixture):
    equal(fixture['schema'], 1, 'Unknown goal-study schema')
    equal(fixture['design_id'], 'kubernetes-goal-phases-v1', 'Goal design differs')
    equal(fixture['policy'], {'server_minor_gap': 1, 'kubelet_max_older_minor_gap': 3,
          'kubelet_not_newer_than_any_server': True, 'minimum_client_minor': 25},
          'Transcribed numerical policy differs')
    equal(fixture['transitions'], {'changed_owners_per_installation': 1,
          'minor_increment': 1, 'downgrades': False, 'self_updates': False},
          'Registered directed transition relation differs')
    primary = fixture['primary_domain']
    equal([primary['server_owners'], primary['client_owners'], primary['server_versions'], primary['client_versions']],
          [2, 1, [35, 36, 37], [33, 34, 35, 36, 37]], 'Primary domain differs')
    specs = [dict(primary)]
    scale = fixture['scaling_domains']
    equal([scale['server_owners'], scale['client_owner_counts'], scale['server_versions'], scale['client_versions']],
          [2, [2, 3, 4], [35, 36, 37], [35, 36, 37]], 'Active-owner scaling domain differs')
    for count in scale['client_owner_counts']:
        specs.append({'name': f'active-{count + 2}-owner', 'server_owners': 2,
                      'client_owners': count, 'server_versions': scale['server_versions'],
                      'client_versions': scale['client_versions'], 'tasks': scale['tasks']})
    return specs


def expected_domain(spec):
    """Reconstruct interval products and declarations from integer policy."""
    ns, nc = spec['server_owners'], spec['client_owners']
    servers, clients = spec['server_versions'], spec['client_versions']
    windows = []
    for low in servers:
        for high in servers:
            if 0 <= high - low <= 1:
                ss = tuple(v for v in servers if low <= v <= high)
                cs = tuple(v for v in clients if high - 3 <= v <= low)
                if cs:
                    windows.append((ss, cs))
    maximal = sorted((ss, cs) for ss, cs in windows if not any(
        (ss, cs) != other and set(ss) <= set(other[0]) and set(cs) <= set(other[1]) for other in windows))
    regions = [{'servers': list(ss), 'clients': list(cs), 'tag': f'{ss[0]}_{ss[-1]}'} for ss, cs in maximal]
    profiles = {}
    for node in range(ns + nc):
        role = 'server' if node < ns else 'client'
        versions = servers if node < ns else clients
        profiles[str(node)] = {str(v): sorted([f'version.{role}.{v}'] +
             [f'{role}.interval.{r["tag"]}' for r in regions if v in r['servers' if node < ns else 'clients']])
                              for v in versions}
    branches = [{str(node): [f'{"server" if node < ns else "client"}.interval.{r["tag"]}']
                 for node in range(ns + nc)} for r in regions]
    domains = [servers] * ns + [clients] * nc
    vertices = [list(v) for v in itertools.product(*domains) if safe(v, ns)]
    candidates = {node: sorted(values.values()) for node, values in profiles.items()}
    transitions = {node: sorted([{'source': values[str(v)], 'target': values[str(v + 1)]}
                                 for v in map(int, values) if str(v + 1) in values],
                                key=lambda e: (e['source'], e['target']))
                   for node, values in profiles.items()}
    return {'name': spec['name'], 'specification': spec, 'regions': regions,
            'profiles': profiles, 'branches': branches, 'candidates': candidates,
            'transitions': transitions, 'compatible_placements': vertices,
            'catalog_placements': __import__('math').prod(map(len, domains))}


def support_vector(domain, vector):
    return {str(i): domain['profiles'][str(i)][str(v)] for i, v in enumerate(vector)}


def version_vector(domain, support):
    require(isinstance(support, dict) and set(support) == set(domain['profiles']), 'Support owner coverage differs')
    vector = []
    for node, values in domain['profiles'].items():
        matching = [int(v) for v, atoms in values.items() if atoms == support[node]]
        require(len(matching) == 1, 'Full-profile identity differs from registered versions')
        vector.append(matching[0])
    return tuple(vector)


def encoded(branches, support):
    return any(all(set(required) <= set(support[node]) for node, required in branch.items()) for branch in branches)


def guard_check(domain, box, source):
    nodes = list(domain['profiles'])
    require(isinstance(box, dict) and set(box) == set(nodes), 'Guard owner coverage differs')
    count = 1
    for node in nodes:
        terms = box[node]
        require(isinstance(terms, list) and 1 <= len(terms) <= 8, 'Guard term-count bound')
        require(all(isinstance(t, list) and t == sorted(set(t)) and all(isinstance(a, str) for a in t)
                    for t in terms), 'Noncanonical guard atoms')
        require(terms == sorted(terms) and len({tuple(t) for t in terms}) == len(terms), 'Repeated or unsorted guard term')
        require(not any(set(a) < set(b) for a in terms for b in terms), 'Non-antichain guard')
        require(any(set(t) <= set(source[node]) for t in terms), 'Guard excludes phase source')
        count *= len(terms)
    require(count <= 4096, 'Guard corner bound')
    for corner in itertools.product(*(box[node] for node in nodes)):
        require(encoded(domain['branches'], dict(zip(nodes, corner))), 'Unsafe positive guard corner')


class IntegerOracle:
    def __init__(self, domain):
        self.domain = domain
        self.ns = domain['specification']['server_owners']
        self.vertices = [tuple(v) for v in domain['compatible_placements']]
        self.edges = {s: [t for t in self.vertices if s != t and phase_safe(s, t, self.ns)] for s in self.vertices}
        self.steps = {s: [t for t in self.edges[s] if sum(b - a for a, b in zip(s, t)) == 1] for s in self.vertices}
        self.cache = {}
        # Check the interval-hull shortcut literally over the complete primary domain.
        if domain['name'] == 'boundary-three-owner':
            for source in self.vertices:
                for target in self.vertices:
                    literal = all(a <= b for a, b in zip(source, target)) and all(
                        safe(v, self.ns) for v in itertools.product(*(range(a, b + 1) for a, b in zip(source, target))))
                    equal(phase_safe(source, target, self.ns), literal, 'Interval oracle differs from literal hull')

    @staticmethod
    def distances(source, edges):
        distances, queue = {source: 0}, deque([source])
        while queue:
            current = queue.popleft()
            for following in edges[current]:
                if following not in distances:
                    distances[following] = distances[current] + 1
                    queue.append(following)
        return distances

    def query(self, source, target):
        source, target = tuple(source), tuple(target)
        if source not in self.cache:
            self.cache[source] = (self.distances(source, self.edges), self.distances(source, self.steps))
        phases, steps = self.cache[source]
        equal(target in phases, target in steps, 'Phase and one-step reachability differ')
        reachable = target in phases
        return {'reachable': reachable, 'minimum_phases': phases.get(target),
                'coordinate_every_proposal': steps.get(target),
                'minimum_installations': steps.get(target),
                'single_static_reaches_target': reachable and phases[target] <= 1,
                'direction_infeasible': any(a > b for a, b in zip(source, target)),
                'already_target': source == target}


def tasks(domain):
    spec = domain['specification']
    if domain['name'] == 'boundary-three-owner':
        return [(f'{i:03d}-{j:03d}', s, t) for i, s in enumerate(domain['compatible_placements'])
                for j, t in enumerate(domain['compatible_placements'])]
    ns, nc = spec['server_owners'], spec['client_owners']
    return [(item['name'], [item['initial_servers']] * ns + [item['initial_clients']] * nc,
             [item['target_servers']] * ns + [item['target_clients']] * nc) for item in spec['tasks']]


def verify_plan(domain, row, oracle):
    result = oracle.query(row['initial_versions'], row['target_versions'])
    comparators = row['comparators']
    static = result['single_static_reaches_target']
    equal(comparators['single_static_product'],
          {'status': 'reachable' if static else 'unreachable',
           'guard_admissions': int(not result['already_target']) if static else None,
           'installations': result['minimum_installations'] if static else None},
          'Static-product comparator differs from the complete interval oracle')
    stepwise = comparators['coordinate_every_proposal']
    equal([stepwise['status'], stepwise['global_checks'], stepwise['installations']],
          ['reachable' if result['reachable'] else 'unreachable', result['coordinate_every_proposal'],
           result['minimum_installations']], 'Per-proposal comparator cost or status differs')
    path = stepwise['version_path']
    if not result['reachable']:
        equal(path, [], 'Unreachable proposal comparator contains a route')
    else:
        equal([path[0], path[-1], len(path) - 1],
              [row['initial_versions'], row['target_versions'], result['minimum_installations']],
              'Proposal comparator route does not match its endpoints or optimum')
        for source, target in zip(path, path[1:]):
            require(all(a <= b for a, b in zip(source, target)) and
                    sum(b - a for a, b in zip(source, target)) == 1,
                    'Proposal comparator did not perform exactly one legal minor installation')
            require(target in domain['compatible_placements'], 'Proposal comparator leaves the registered catalog or policy')
    if row['status'] == 'refused':
        require(isinstance(row.get('reason'), str) and row['reason'] in {
            'goal placement bound', 'goal phase-edge bound', 'exact frontier local-library bound',
            'exact frontier search-state bound', 'exact frontier result bound'}, 'Unknown refusal classification')
        require('plan' not in row, 'Refused task contains an apparent optimum')
        return result
    plan = row['plan']
    equal(plan['schema'], 'rollout-goal-plan-v1', 'Unknown planner schema')
    equal(plan['initial'], support_vector(domain, row['initial_versions']), 'Plan initial profile differs')
    equal(plan['target'], support_vector(domain, row['target_versions']), 'Plan target profile differs')
    equal(plan['branches'], domain['branches'], 'Plan policy encoding differs')
    equal(plan['catalog'], domain['candidates'], 'Plan catalog differs')
    equal(plan['transitions'], domain['transitions'], 'Plan allowed transitions differ')
    if not result['reachable']:
        equal(plan['status'], 'unreachable', 'Unreachable task reported planned')
        equal([plan['cost'], plan['phases']], [None, []], 'Unreachable task has a partial route')
        equal(row['status'], 'unreachable', 'Outer task status differs')
        return result
    equal([row['status'], plan['status']], ['planned', 'planned'], 'Reachable task did not return a plan')
    expected_cost = {'phases': result['minimum_phases'], 'installations': result['minimum_installations'],
                     'handoffs': max(result['minimum_phases'] - 1, 0)}
    require(all(type(v) is int for v in plan['cost'].values()), 'Noninteger goal cost')
    equal(plan['cost'], expected_cost, 'Goal optimum differs from integer interval graph')
    equal(len(plan['phases']), expected_cost['phases'], 'Phase count differs from plan')
    current = deepcopy(plan['initial'])
    writes = 0
    for phase in plan['phases']:
        equal(phase['source'], current, 'Phase source breaks route continuity')
        guard_check(domain, phase['box'], current)
        local = {node: [list(profile)] for node, profile in current.items()}
        require(phase['steps'], 'Empty nonzero phase')
        for step in phase['steps']:
            equal(sorted(step), ['node', 'support'], 'Step schema differs')
            node = step['node']
            require(type(node) is str and node in current, 'Step owner differs')
            before = version_vector(domain, current)
            proposed = deepcopy(current)
            proposed[node] = step['support']
            after = version_vector(domain, proposed)
            require(after[int(node)] == before[int(node)] + 1, 'Illegal skipped/reversed minor transition')
            require(any(set(term) <= set(step['support']) for term in phase['box'][node]), 'Planned step leaves its guard')
            require(safe(after, domain['specification']['server_owners']), 'Planned step violates numerical policy')
            current = proposed
            local[node].append(list(step['support']))
            writes += 1
        equal(phase['target'], current, 'Phase target differs from actual steps')
        equal(phase['local_paths'], local, 'Local paths differ from interleaved steps')
    equal(current, plan['target'], 'Plan does not reach registered target')
    equal(writes, expected_cost['installations'], 'Installation path length differs')
    return result


def database(path):
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
        require(db.execute('PRAGMA quick_check').fetchone()[0] == 'ok', 'SQLite integrity failure')
        rows = db.execute('SELECT id,payload FROM state ORDER BY id').fetchall()
        require(len(rows) == 1 and rows[0][0] == 1, 'SQLite singleton row differs')
        return json.loads(rows[0][1])


def read_rows(path):
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        return [json.loads(line) for line in stream]


def check(directory, source_checks=True, execution_checks=True, verify_summary=True):
    directory = Path(directory).resolve()
    manifest = read(directory / 'manifest.json')
    equal(manifest['schema'], 'goal-policy-evidence-v1', 'Evidence manifest schema differs')
    listed = [item['path'] for item in manifest['files']]
    actual = [str(path.relative_to(directory)) for path in sorted(directory.rglob('*'))
              if path.is_file() and path.name != 'manifest.json']
    equal(listed, actual, 'Evidence manifest omits, duplicates or reorders files')
    for item in manifest['files']:
        path = (directory / item['path']).resolve()
        require(path.is_relative_to(directory) and path.is_file(), 'Evidence path escape or missing file')
        equal(digest(path), item['sha256'], 'Evidence checksum differs: ' + item['path'])
    if source_checks:
        for name, sha in manifest['source_sha256'].items():
            live = ROOT / name
            preimage = directory / 'source-preimage' / name
            source = live if live.exists() and digest(live) == sha else preimage
            require(source.is_file() and digest(source) == sha, 'Missing exact tested source: ' + name)
    fixture = read(directory / 'fixture.json')
    equal(fixture, read(directory / 'source-preimage/data/goal-policy.json'),
          'Executed fixture differs from its bound source preimage')
    domains = read(directory / 'domains.json')
    expected = [expected_domain(spec) for spec in specifications(fixture)]
    equal(domains, expected, 'Saved domain/profile declarations differ from numerical reconstruction')
    for domain in domains:
        raw_domains = [list(map(int, domain['profiles'][node])) for node in domain['profiles']]
        for vector in itertools.product(*raw_domains):
            equal(encoded(domain['branches'], support_vector(domain, vector)),
                  safe(vector, domain['specification']['server_owners']), 'Positive encoding disagrees with numerical policy')
    rows = read_rows(directory / 'plans.jsonl.gz')
    inventory = [(d['name'], name, source, target) for d in domains for name, source, target in tasks(d)]
    equal([(r['domain'], r['task'], r['initial_versions'], r['target_versions']) for r in rows],
          inventory, 'Registered goal-task inventory differs')
    oracles = {d['name']: IntegerOracle(d) for d in domains}
    by_name = {d['name']: d for d in domains}
    totals = []
    for domain in domains:
        counts, phases = Counter(), Counter()
        coordination = static = writes = 0
        for row in (r for r in rows if r['domain'] == domain['name']):
            oracle = verify_plan(domain, row, oracles[domain['name']])
            counts[row['status']] += 1
            counts['already_target'] += oracle['already_target']
            counts['direction_infeasible'] += oracle['direction_infeasible']
            if row['status'] == 'planned':
                phases[str(row['plan']['cost']['phases'])] += 1
                coordination += oracle['coordinate_every_proposal']
                writes += row['plan']['cost']['installations']
                static += int(oracle['single_static_reaches_target'])
        totals.append({'domain': domain['name'], 'catalog_placements': domain['catalog_placements'],
                       'compatible_placements': len(domain['compatible_placements']),
                       'tasks': len(tasks(domain)), 'statuses': dict(sorted(counts.items())),
                       'planned_phase_histogram': dict(sorted(phases.items())),
                       'single_static_reachable_planned_tasks': static,
                       'planned_installations_total': writes, 'per_proposal_coordination_total': coordination})
    controls = read(directory / 'budget-controls.json')
    equal([c['kind'] for c in controls], [c['kind'] for c in fixture['budget_controls']], 'Budget-control inventory differs')
    for control, design in zip(controls, fixture['budget_controls']):
        equal(control['status'], 'refused', 'Insufficient budget returned an answer')
        equal(control['arguments'], {**fixture['planner_bounds'], **{k: v for k, v in design.items() if k != 'kind'}},
              'Budget-control arguments differ from the frozen design')
        equal(control['reason'], {'placement': 'goal placement bound', 'phase-edge': 'goal phase-edge bound'}[design['kind']],
              'Budget control used wrong failure classification')
    execution = {'status': 'not-requested'}
    if execution_checks:
        execution = check_executions(directory, fixture, domains, rows)
    result = {'status': 'PASS', 'domains': totals, 'tasks': len(rows),
              'default_refusals': sum(r['status'] == 'refused' for r in rows),
              'budget_controls': len(controls), 'execution': execution,
              'scope': 'Independent integer-policy and interval-graph oracle, literal positive corners, registered task inventory and durable-state replay; no planner/runtime imports.'}
    if verify_summary:
        equal(read(directory / 'summary.json'), result, 'Saved summary differs from reconstructed counts')
    return result


def check_executions(directory, fixture, domains, rows):
    return _check_executions(directory, fixture, domains, rows)


def owner_initial(domain, versions):
    result = {}
    for node, profile in support_vector(domain, versions).items():
        observed = {'node': int(node), 'generation': 0, 'support': profile}
        result[node] = {'node': int(node), 'generation': 0, 'support': profile,
                        'window': 8, 'policy': 'predicate', 'floor': [0] * 6,
                        'slots': {}, 'catalog': {node: deepcopy(observed)}}
    return result


def profile(state):
    return {key: deepcopy(state[key]) for key in ('node', 'generation', 'support')}


def apply_rpc(states, row, domain):
    """Literal owner transition reconstruction from delivered request/reply rows."""
    if row['event'] in ('lost', 'unreachable'):
        return
    require(row['event'] == 'rpc', 'Unregistered network event')
    node = str(row['target'])
    state, request = states[node], row['request']
    op = request['op']
    if op == 'read':
        expected = {'status': 'observed', 'observed': profile(state)}
    elif op in ('prepare', 'close'):
        origin, sequence = request['origin'], request['sequence']
        require(type(origin) is int and origin in (0, 1) and type(sequence) is int and sequence >= 1,
                'Invalid phase RPC authority')
        key = f'{origin}:{sequence}'
        floor = state['floor'][origin]
        if sequence <= floor:
            expected = {'status': 'closed'}
        elif sequence > floor + state['window']:
            expected = {'status': 'window'}
        elif op == 'close':
            state['slots'][key] = {'status': 'closed'}
            while state['slots'].get(f'{origin}:{floor + 1}') == {'status': 'closed'}:
                del state['slots'][f'{origin}:{floor + 1}']
                floor += 1
            state['floor'][origin] = floor
            expected = {'status': 'closed', 'floor': floor}
        elif key in state['slots']:
            hold = state['slots'][key]
            if hold['status'] == 'closed':
                expected = {'status': 'closed'}
            elif any(hold.get(k) != request.get(k) for k in ('manifest', 'requires', 'options')):
                expected = {'status': 'binding-conflict'}
            else:
                expected = {'status': 'held', 'receipt': deepcopy(hold)}
        else:
            require(request['requires'] == [] and isinstance(request['options'], list), 'Expected envelope preparation')
            allowed = any(set(t) <= set(state['support']) for t in request['options'])
            if not allowed:
                expected = {'status': 'missing', 'missing': [], 'observed': profile(state)}
            else:
                hold = {'status': 'held', 'node': int(node), 'origin': origin, 'sequence': sequence,
                        'manifest': request['manifest'], 'requires': [], 'options': deepcopy(request['options']),
                        'observed_generation': state['generation']}
                state['slots'][key] = hold
                expected = {'status': 'held', 'receipt': deepcopy(hold)}
    elif op == 'install_if_current':
        if request['expected_generation'] != state['generation'] or request['expected_support'] != state['support']:
            expected = {'status': 'stale', 'observed': profile(state)}
        elif request['support'] == state['support']:
            expected = {'status': 'unchanged', 'observed': profile(state)}
        else:
            blocking = [key for key, hold in sorted(state['slots'].items()) if hold['status'] == 'held'
                        and not any(set(t) <= set(request['support']) for t in hold['options'])]
            if blocking:
                expected = {'status': 'blocked', 'holds': blocking}
            else:
                before = version_vector(domain, {n: s['support'] for n, s in states.items()})
                trial = {n: deepcopy(s['support']) for n, s in states.items()}
                trial[node] = request['support']
                after = version_vector(domain, trial)
                require(after[int(node)] == before[int(node)] + 1, 'Runtime skipped/reversed a minor version')
                require(safe(after, domain['specification']['server_owners']), 'Runtime violates numerical policy')
                state['support'] = deepcopy(request['support'])
                state['generation'] += 1
                state['catalog'][node] = profile(state)
                expected = {'status': 'installed', 'observed': profile(state)}
    else:
        raise ValueError('Unregistered owner RPC: ' + op)
    equal(row['response'], expected, 'Runtime response differs from literal state replay')
    equal(row['bytes'], len((canonical(request) + '\n').encode()) + len((canonical(expected) + '\n').encode()),
          'Runtime RPC byte count differs')
    require(type(row['wall_ns']) is int and row['wall_ns'] >= 0, 'Invalid RPC elapsed observation')


def check_job_snapshot(snapshot, run, states, domain):
    job = snapshot['job_state']
    equal(job['schema'], 'durable-rollout-v1', 'Unknown durable job schema')
    equal(job['plan'], run['plan'], 'Durable goal plan differs')
    equal(job['plan_sha256'], hashlib.sha256(canonical(run['plan']).encode()).hexdigest(), 'Durable plan digest differs')
    equal(job['manifest'], 'goal-policy-' + run['name'], 'Durable manifest identity differs')
    equal(job['origins'], [0, 1], 'Durable phase origins differ')
    i, k, stage = job['phase_index'], job['step_index'], job['stage']
    require(type(i) is int and type(k) is int and i >= 0 and k >= 0, 'Invalid durable position')
    phases = run['plan']['phases']
    if stage == 'complete':
        equal([i, k, job['certificates']], [len(phases), 0, {}], 'Completed job retains phase authority')
        completed = run['plan']['cost']['installations']
        expected_support = run['plan']['target']
    else:
        require(i < len(phases) and k <= len(phases[i]['steps']), 'Durable position outside plan')
        wanted = ({str(i - 1)} if i else set()) if stage == 'acquire' else (
                 {str(i - 1), str(i)} if stage == 'release-old' else {str(i)})
        require(stage in {'acquire', 'release-old', 'install', 'release-final'}, 'Unknown durable stage')
        equal(sorted(job['certificates']), sorted(wanted), 'Durable phase-role map differs')
        if stage in {'acquire', 'release-old'}:
            equal(k, 0, 'New phase contains premature completed steps')
        completed = sum(len(p['steps']) for p in phases[:i]) + k
        expected_support = deepcopy(phases[i]['source'])
        for step in phases[i]['steps'][:k]:
            expected_support[step['node']] = step['support']
    equal({n: s['support'] for n, s in states.items()}, expected_support, 'Durable position and owner support differ')
    equal(job['acknowledged_installs'] + job['reconciled_steps'], completed, 'Durable completed-step counters differ')
    require(all(type(job[field]) is int and job[field] >= 0
                for field in ('acknowledged_installs', 'reconciled_steps', 'journal_revision')), 'Noncanonical durable counter')
    known = {}
    for phase_index, phase in enumerate(phases):
        manifest = f'{job["manifest"]}:r:{job["plan_sha256"]}:p:{phase_index}'
        known[manifest] = (phase_index, phase)
    committed = {}
    for origin, origin_state in snapshot['origin_states'].items():
        equal(origin_state['origin'], int(origin), 'Stored origin identity differs')
        for attempt in origin_state['attempts'].values():
            require(attempt['manifest'] in known, 'Origin has an unregistered phase admission')
            phase_index, phase = known[attempt['manifest']]
            equal(phase_index % 2, int(origin), 'Origin owns wrong phase')
            if attempt['status'] == 'committed':
                token = attempt['certificate']
                equal(token['box'], phase['box'], 'Committed certificate guard differs')
                equal(token['manifest'], attempt['manifest'], 'Committed certificate manifest differs')
                equal(token['origin'], int(origin), 'Committed certificate origin differs')
                for node, sequence in token['sequences'].items():
                    hold = states[node]['slots'].get(f'{origin}:{sequence}')
                    require(hold is not None and hold['status'] == 'held', 'Committed authority lacks a live owner hold')
                    equal(hold['options'], phase['box'][node], 'Committed owner guard differs')
                    equal(hold['manifest'], token['manifest'], 'Committed owner manifest differs')
                committed[phase_index] = token
            else:
                require(attempt['status'] in {'acquiring', 'retiring'}, 'Unknown origin attempt state')
    if stage == 'acquire' and i:
        require(i - 1 in committed, 'Next-phase acquisition lost preceding committed authority')
    elif stage in {'install', 'release-old'}:
        require(i in committed, 'Active phase has no committed authority')
    elif stage == 'complete':
        require(not committed and all(not s['slots'] for s in states.values()), 'Completed rollout retained owner holds')
        require(all(not s['attempts'] for s in snapshot['origin_states'].values()), 'Completed rollout retained origin attempts')
    for key, token in job['certificates'].items():
        phase_index = int(key)
        equal(token['box'], phases[phase_index]['box'], 'Journal certificate differs from phase')
        equal(token['manifest'], f'{job["manifest"]}:r:{job["plan_sha256"]}:p:{phase_index}', 'Journal certificate binding differs')


def _check_executions(directory, fixture, domains, rows):
    runs = read(directory / 'executions.json')
    require(fixture.get('original_design_frozen_before_initial_execution') is True and
            fixture.get('execution_coverage_amended_after_initial_cohort') is True,
            'Runtime-coverage amendment history omitted')
    amendment = fixture['execution_amendment']
    equal([amendment['id'], amendment['added_after'], amendment['fault']],
          ['all-existing-scaling-goals', 'initial three-case execution cohort', 'none'],
          'Runtime-coverage amendment differs')
    designs = [{**deepcopy(c), 'domain': domains[0]['name']} for c in fixture['execution_cases']]
    for domain in domains[1:]:
        for name, source, target in tasks(domain):
            designs.append({'name': domain['name'] + '--' + name, 'domain': domain['name'],
                            'initial': source, 'target': target, 'fault': 'none',
                            'amendment': amendment['id']})
    equal([r['name'] for r in runs], [c['name'] for c in designs], 'Runtime-case inventory differs')
    by_name = {d['name']: d for d in domains}
    counts = Counter()
    cases = []
    for run, design in zip(runs, designs):
        domain = by_name[design['domain']]
        equal(run['design'], design, 'Runtime design differs')
        matching = [r for r in rows if r['domain'] == domain['name'] and r['initial_versions'] == design['initial']
                    and r['target_versions'] == design['target']]
        require(len(matching) == 1, 'Runtime goal absent from registered tasks')
        if matching[0]['status'] == 'refused':
            equal(run['status'], 'not-run', 'Refused plan was executed')
            counts['not_run'] += 1
            continue
        equal(run['plan'], matching[0]['plan'], 'Runtime did not execute the automatically generated plan')
        equal(run['status'], 'complete', 'Runtime did not complete after recovery')
        states = owner_initial(domain, design['initial'])
        cursor = 0
        for snapshot in run['snapshots']:
            require(type(snapshot['trace_length']) is int and cursor <= snapshot['trace_length'] <= len(run['logical_rpc_trace']),
                    'Snapshot trace position differs')
            for event in run['logical_rpc_trace'][cursor:snapshot['trace_length']]:
                apply_rpc(states, event, domain)
            cursor = snapshot['trace_length']
            equal(snapshot['owner_states'], states, 'Saved owner state differs from literal RPC execution')
            check_job_snapshot(snapshot, run, states, domain)
            expected_db = {f'node-{n}.sqlite': state for n, state in states.items()}
            expected_db.update({f'origin-{n}.sqlite': state for n, state in snapshot['origin_states'].items()})
            expected_db['rollout.sqlite'] = snapshot['job_state']
            equal(sorted(Path(item['path']).name for item in snapshot['databases']), sorted(expected_db), 'Snapshot DB inventory differs')
            for item in snapshot['databases']:
                path = (directory / item['path']).resolve()
                require(path.is_relative_to(directory) and path.is_file(), 'Snapshot path escape or missing DB')
                equal(digest(path), item['sha256'], 'Snapshot DB checksum differs')
                equal(database(path), expected_db[path.name], 'SQLite state differs from reconstructed snapshot')
                counts['database_snapshots'] += 1
        equal(cursor, len(run['logical_rpc_trace']), 'Final snapshot omits owner transitions')
        equal(version_vector(domain, {n: s['support'] for n, s in states.items()}), design['target'], 'Final runtime target differs')
        equal(run['final_state'], run['snapshots'][-1]['job_state'], 'Final runtime summary differs')
        final_result = run['action_results'][-1]
        equal([final_result['status'], final_result.get('goal_reached')], ['complete', True],
              'Final runtime action lacks a completed goal observation')
        observation = final_result.get('target_observation')
        require(isinstance(observation, dict) and set(observation) == {'first', 'second'},
                'Goal completion lacks two complete authoritative collects')
        equal(observation['first'], observation['second'], 'Goal completion accepted changing owner generations')
        equal(observation['first'], {node: profile(state) for node, state in states.items()},
              'Goal completion observation differs from the replayed target state')
        nodes = sorted(states, key=int)
        tail = run['logical_rpc_trace'][-2 * len(nodes):]
        equal(len(tail), 2 * len(nodes), 'Missing final complete-collect RPCs')
        for index, event in enumerate(tail):
            node = nodes[index % len(nodes)]
            require(event['event'] == 'rpc' and event['target'] == int(node) and event['request'] == {'op': 'read'},
                    'Completion observation is not backed by the final two full collects')
            equal(event['response'], {'status': 'observed', 'observed': observation['first'][node]},
                  'Complete-collect reply differs from the reported target observation')
        installed = sum(e.get('event') == 'rpc' and e['request']['op'] == 'install_if_current'
                        and e['response']['status'] == 'installed' for e in run['logical_rpc_trace'])
        equal(installed, run['plan']['cost']['installations'], 'Actual installation count differs from plan')
        admitted = sum(action.get('event') == 'phase-admitted' for action in run['action_results'])
        equal(admitted, run['plan']['cost']['phases'], 'Committed runtime phase admissions differ from plan')
        equal(len(run['snapshots']), len(run['action_results']) + 1 + int(run['reopened_after_pending']),
              'Runtime action is missing its durable evidence checkpoint')
        if design['name'] == 'new-phase-unavailable':
            require(any(r['status'] == 'pending' and r.get('reason') == 'phase-not-admitted' for r in run['action_results']),
                    'Unavailable next-phase control was not observed')
            require(any(e['event'] == 'lost' and e['request']['op'] == 'prepare' for e in run['logical_rpc_trace']),
                    'Unavailable next-phase control did not lose a prepare')
        if design['name'] == 'close-reply-lost':
            equal(len(run['suppressed_close_replies']), 1, 'Lost-close reply control missing')
            lost = run['suppressed_close_replies'][0]
            event = run['logical_rpc_trace'][lost['trace_index']]
            require(event['event'] == 'rpc' and event['request']['op'] == 'close' and event['response']['status'] == 'closed',
                    'Suppressed close was not actually delivered and acknowledged by owner')
            require(any(r['status'] == 'pending' and r.get('reason') == 'old-phase-release-pending' for r in run['action_results']),
                    'Lost-close reply did not preserve pending retirement')
        if design['fault'] != 'none':
            require(run['reopened_after_pending'], 'Recovery case did not reopen durable coordinator')
        counts['completed'] += 1
        counts['installations'] += installed
        counts['guard_phases'] += run['plan']['cost']['phases']
        counts['handoffs'] += run['plan']['cost']['handoffs']
        counts['snapshots'] += len(run['snapshots'])
        rpc_counts = Counter(f'{event["event"]}:{event["request"]["op"]}' for event in run['logical_rpc_trace'])
        cases.append({'name': run['name'], 'domain': domain['name'], 'committed_guard_phases': admitted,
                      'installations': installed, 'handoffs': run['plan']['cost']['handoffs'],
                      'pending_returns': sum(action['status'] == 'pending' for action in run['action_results']),
                      'reopened': run['reopened_after_pending'], 'rpc_counts': dict(sorted(rpc_counts.items())),
                      'suppressed_close_replies': len(run['suppressed_close_replies'])})
    return {'status': 'PASS', **dict(sorted(counts.items())), 'cases': cases,
            'scope': 'Three original cases and all eighteen already-fixed scaling goals executed over TCP/SQLite; phase admissions and per-proposal global checks are distinct operations, not measured equal-cost units.'}


def corruption_controls(directory):
    directory = Path(directory).resolve()
    check(directory)
    results = []
    with tempfile.TemporaryDirectory(prefix='goal-data-controls-') as temporary:
        target = Path(temporary) / 'evidence'
        for kind in ('missing_task', 'wrong_cost', 'skipped_minor', 'profile_identity', 'unsafe_guard', 'rehashed_owner_state'):
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(directory, target)
            rows = read_rows(target / 'plans.jsonl.gz')
            selected = next(r for r in rows if r['status'] == 'planned' and r['plan']['cost']['installations'] >= 2)
            if kind == 'missing_task':
                rows.pop()
            elif kind == 'wrong_cost':
                selected['plan']['cost']['phases'] += 1
            elif kind == 'skipped_minor':
                domain = read(target / 'domains.json')[0]
                selected = next(r for r in rows if r['domain'] == domain['name'] and
                                r['initial_versions'] == [35, 35, 35] and r['target_versions'] == [37, 37, 37])
                step = selected['plan']['phases'][0]['steps'][0]
                step['support'] = domain['profiles'][step['node']]['37']
            elif kind == 'profile_identity':
                selected['plan']['target']['0'] = selected['plan']['target']['0'] + ['version.server.999']
            elif kind == 'unsafe_guard':
                selected['plan']['phases'][0]['box']['0'] = [[]]
            else:
                runs = read(target / 'executions.json')
                snap = runs[0]['snapshots'][-1]
                item = next(x for x in snap['databases'] if Path(x['path']).name == 'node-0.sqlite')
                path = target / item['path']
                with sqlite3.connect(path) as db:
                    value = json.loads(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
                    value['floor'][0] += 1
                    db.execute('UPDATE state SET payload=? WHERE id=1', (canonical(value),))
                    db.commit()
                item['sha256'] = digest(path)
                snap['owner_states']['0']['floor'][0] += 1
                (target / 'executions.json').write_text(json.dumps(runs, sort_keys=True) + '\n')
            if kind != 'rehashed_owner_state':
                with (target / 'plans.jsonl.gz').open('wb') as raw:
                    with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as stream:
                        for row in rows:
                            stream.write((canonical(row) + '\n').encode())
            manifest = read(target / 'manifest.json')
            for item in manifest['files']:
                item['sha256'] = digest(target / item['path'])
            (target / 'manifest.json').write_text(json.dumps(manifest, sort_keys=True) + '\n')
            try:
                check(target)
            except ValueError as exc:
                results.append({'case': kind, 'rejected': True, 'reason': str(exc)})
            else:
                raise ValueError('Corrupted goal evidence accepted: ' + kind)
    return {'status': 'PASS', 'controls': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT / 'results/goal-policy')
    parser.add_argument('--corruption-controls', action='store_true')
    args = parser.parse_args()
    value = corruption_controls(args.root) if args.corruption_controls else check(args.root)
    print(json.dumps(value, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
