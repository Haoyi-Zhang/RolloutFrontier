"""Data-only verification of the separate Kubernetes policy-boundary cohort.

No production module or experiment driver is imported. Numerical constraints,
version subsets, positive guard corners, RPC outcomes and actual SQLite rows are
checked directly from retained data. --corruption-controls also checks that six
deliberately falsified records fail validation.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import itertools
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile

ROOT = Path(__file__).resolve().parents[1]
RULES = ('ha_gap', 'not_newer', 'max_lag')
NODES = ('0', '1', '2')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def equal(actual, expected, message):
    require(canonical(actual) == canonical(expected), message)


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def flags(vector):
    a, b, c = vector
    require(all(type(v) is int for v in vector), 'Noninteger version vector')
    return {'ha_gap': max(a, b) - min(a, b) <= 1,
            'not_newer': c <= min(a, b), 'max_lag': c >= max(a, b) - 3}


def safe(vector, omitted=None):
    return all(value for key, value in flags(vector).items() if key != omitted)


def fixture_inputs(facts):
    equal(facts['server_minor_catalog'], [35, 36, 37], 'Server domain changed')
    equal(facts['client_minor_catalog'], [33, 34, 35, 36, 37], 'Client domain changed')
    equal(facts['rules'], {'ha_gap': {'max_minor_distance': 1},
          'not_newer': {'client_not_newer_than_each_contacted_server': True},
          'max_lag': {'max_older_minor_distance': 3, 'applies_at_or_above_minor': 25}},
          'Transcribed policy constants changed')
    equal(facts['ha_windows'], {'35_36': [35, 36], '36_37': [36, 37]}, 'HA windows changed')
    domains = [facts['server_minor_catalog'], facts['server_minor_catalog'], facts['client_minor_catalog']]
    profiles = {}
    for node in NODES:
        profiles[node] = {}
        for version in domains[int(node)]:
            if node == '2':
                atoms = [f'client.{version}']
            else:
                atoms = sorted([f'allows.{c}' for c in domains[2] if version - 3 <= c <= version]
                               + [f'ha.{name}' for name, window in facts['ha_windows'].items() if version in window])
                equal(facts['server_profiles'][str(version)], atoms, 'Server declarations differ from numerical rules')
            profiles[node][str(version)] = atoms
    expected_windows = {}
    for c in domains[2]:
        accepted = {name: {server for server in window if server - 3 <= c <= server}
                    for name, window in facts['ha_windows'].items()}
        expected_windows[str(c)] = [name for name, values in accepted.items()
                                   if values and not any(values < other for other in accepted.values())]
    equal(facts['alternative_windows'], expected_windows, 'Alternative window coverage differs')
    branches = [{node: ([f'client.{c}'] if node == '2' else [f'allows.{c}', f'ha.{window}'])
                 for node in NODES}
                for c in domains[2] for window in expected_windows[str(c)]]
    require(len(branches) == 7, 'Seven-alternative boundary language changed')
    return domains, profiles, branches


def encoded(branches, support):
    return any(all(set(branch[node]) <= set(support[node]) for node in NODES) for branch in branches)


def subsets(domain, initial):
    return [tuple(values) for size in range(1, len(domain) + 1)
            for values in itertools.combinations(domain, size) if initial in values]


def all_products(domains, vector):
    products = [box for box in itertools.product(*(subsets(d, v) for d, v in zip(domains, vector)))
                if all(safe(point) for point in itertools.product(*box))]
    frontier = sorted(box for box in products if not any(
        box != other and all(set(a).issubset(b) for a, b in zip(box, other)) for other in products))
    return products, frontier


def guard_vector(box, profiles, branches, initial):
    require(isinstance(box, dict) and set(box) == set(NODES), 'Guard owner coverage differs')
    corner_count = 1
    for node in NODES:
        options = box[node]
        require(isinstance(options, list) and 1 <= len(options) <= 8, 'Guard term bound')
        terms = []
        for option in options:
            require(isinstance(option, list) and all(isinstance(a, str) for a in option), 'Guard term type')
            require(option == sorted(set(option)) and len(option) <= 12000, 'Noncanonical guard atoms')
            terms.append(frozenset(option))
        require(len(terms) == len(set(terms)) and not any(a < b for a in terms for b in terms),
                'Redundant or repeated guard term')
        corner_count *= len(options)
    require(corner_count <= 4096, 'Guard corner language bound')
    for corner in itertools.product(*(box[node] for node in NODES)):
        require(encoded(branches, dict(zip(NODES, corner))), 'Unsafe off-catalog positive corner')
    accepted = tuple(tuple(int(v) for v, atoms in profiles[node].items()
                           if any(set(term).issubset(atoms) for term in box[node])) for node in NODES)
    require(all(value in domain for value, domain in zip(initial, accepted)), 'Guard excludes initial version')
    return accepted


def verify_member(member, profiles, branches, initial):
    rectangle = guard_vector(member['box'], profiles, branches, initial)
    local = {node: len(rectangle[int(node)]) for node in NODES}
    product = local['0'] * local['1'] * local['2']
    accepted_profiles = {node: sorted(profiles[node][str(v)] for v in rectangle[int(node)]) for node in NODES}
    equal(member['local_masses'], local, 'Local mass differs')
    equal(member['accepted_unique_profiles'], local, 'Accepted profile count differs')
    equal(member['product_mass'], product, 'Product mass differs')
    equal(member['accepted_profiles'], accepted_profiles, 'Accepted profile inventory differs')
    equal(member['guard_terms'], sum(len(member['box'][node]) for node in NODES), 'Guard term count differs')
    return rectangle


def check_trace(run, profiles, expected_events, generations):
    certificate = run['certificate']
    equal(certificate['origin'], 0, 'Unexpected origin')
    equal(certificate['sequences'], {node: 1 for node in NODES}, 'Unexpected first-admission sequences')
    equal(certificate['box'], run['box'], 'Certificate guard differs')
    require(certificate['mode'] == 'envelope' and certificate['manifest'] == 'policy-boundary-' + run['rule'],
            'Certificate binding differs')
    manifest = certificate['manifest']
    expected = []
    for node in NODES:
        expected.append((int(node), {'op': 'prepare', 'origin': 0, 'sequence': 1, 'manifest': manifest,
                                     'requires': [], 'options': run['box'][node]}, 'held'))
    for event in expected_events:
        expected.append((event['owner'], {'op': 'install',
                        'support': profiles[str(event['owner'])][str(event['proposed_minor'])]}, event['status']))
    for node in NODES:
        expected.append((int(node), {'op': 'use', 'origin': 0, 'sequence': 1, 'manifest': manifest}, 'used'))
    for node in NODES:
        expected.append((int(node), {'op': 'close', 'origin': 0, 'sequence': 1}, 'closed'))
    expected.append((1, {'op': 'prepare', 'origin': 0, 'sequence': 1, 'manifest': manifest,
                        'requires': [], 'options': run['box']['1']}, 'closed'))
    trace = run['logical_rpc_trace']
    rpcs = [row for row in trace if row.get('event') == 'rpc']
    controls = [row for row in trace if row.get('event') != 'rpc']
    equal(controls, [{'event': 'crash', 'node': 1, 'tick': 15},
                     {'event': 'recover', 'node': 1, 'tick': 15}], 'Owner reopen trace differs')
    require(len(rpcs) == len(expected) == 22, 'RPC count differs')
    require(trace[15:17] == controls, 'Reopen occurs at an unexpected point')
    for tick, (observed, (target, request, status)) in enumerate(zip(rpcs, expected), 1):
        equal(observed['tick'], tick, 'RPC tick differs')
        equal(observed['source'], 0, 'RPC origin differs')
        equal(observed['target'], target, 'RPC target differs')
        equal(observed['request'], request, 'RPC request differs')
        require(observed['response']['status'] == status, 'RPC outcome differs')
        expected_bytes = len((canonical(request) + '\n').encode()) + len((canonical(observed['response']) + '\n').encode())
        equal(observed['bytes'], expected_bytes, 'Logical RPC byte count differs')
        require(type(observed['wall_ns']) is int and observed['wall_ns'] >= 0, 'Invalid elapsed RPC observation')
        if tick <= 3:
            receipt = observed['response']['receipt']
            equal(receipt, certificate['receipts'][target], 'Prepare receipt does not match certificate')
            equal(receipt, {'status': 'held', 'origin': 0, 'sequence': 1, 'manifest': manifest, 'node': target,
                            'observed_generation': 0, 'requires': [], 'options': run['box'][str(target)]},
                  'Prepare receipt binding differs')
        elif request['op'] == 'use':
            equal(observed['response']['generation'], generations[target], 'Reopened generation differs')


def check_databases(directory, run, profiles, state, generations):
    expected_owners = {}
    for node in NODES:
        index = int(node)
        support = profiles[node][str(state[index])]
        profile = {'node': index, 'generation': generations[index], 'support': support}
        expected_owners[node] = {'node': index, 'generation': generations[index], 'support': support,
                                'window': 8, 'policy': 'predicate', 'floor': [1, 0, 0, 0, 0, 0],
                                'slots': {}, 'catalog': {node: profile}}
    expected_origin = {'origin': 0, 'node_count': 3, 'window': 8, 'policy': 'predicate',
                       'next': [1, 1, 1], 'serial': 1, 'attempts': {}}
    equal(run['owner_states'], expected_owners, 'Final owner states differ from literal execution')
    equal(run['origin_state'], expected_origin, 'Final origin state differs')
    expected_names = [f'databases/{run["rule"]}/{name}.sqlite'
                      for name in ('node-0', 'node-1', 'node-2', 'origin-0')]
    equal([item['path'] for item in run['databases']], expected_names, 'Database inventory differs')
    for item in run['databases']:
        path = (directory / item['path']).resolve()
        require(path.is_relative_to(directory.resolve()) and path.is_file(), 'Database path escape or missing file')
        require(digest(path) == item['sha256'], 'Database checksum differs')
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
            require(db.execute('PRAGMA quick_check').fetchone()[0] == 'ok', 'Database integrity failure')
            rows = db.execute('SELECT id,payload FROM state ORDER BY id').fetchall()
            require(len(rows) == 1 and rows[0][0] == 1, 'Invalid stored row set')
            saved = json.loads(rows[0][1])
        wanted = expected_origin if path.name == 'origin-0.sqlite' else expected_owners[path.stem.split('-')[1]]
        equal(saved, wanted, 'Stored database state differs from literal execution')


def check_handoff(directory, facts, result, profiles, branches, domains):
    design = facts['handoff']
    equal({key: design[key] for key in ('manifest', 'old_origin', 'new_origin', 'initial', 'target',
          'goal_proposals', 'remaining_goal_proposals', 'handoff_planning_state')},
          {'manifest': 'kubernetes-policy-handoff', 'old_origin': 0, 'new_origin': 1,
           'initial': [36, 36, 36], 'target': [37, 37, 37],
           'goal_proposals': [{'owner': 0, 'minor': 37}, {'owner': 1, 'minor': 37}, {'owner': 2, 'minor': 37}],
           'remaining_goal_proposals': [{'owner': 2, 'minor': 37}], 'handoff_planning_state': [37, 37, 36]},
          'Registered handoff goal differs')
    run = result['handoff']
    first = next(row for row in result['exhaustive'] if row['versions'] == design['initial'])
    second = next(row for row in result['exhaustive'] if row['versions'] == design['handoff_planning_state'])
    for row in (first, second):
        if row['status'] == 'refused':
            equal(run, {'status': 'not-run', 'reason': row['reason'], 'refused_seed': row['versions']},
                  'Handoff refusal handling differs')
            return {'status': 'not-run', 'reason': row['reason']}
    require(run['status'] == 'completed', 'Handoff did not complete')
    equal(run['design'], design, 'Saved handoff design differs')
    equal(run['first_box'], first['plan']['box'], 'First handoff guard differs')

    def replay(vector, rectangle, proposals):
        state = list(vector)
        counts = {'installed': 0, 'blocked': 0, 'unchanged': 0}
        for proposal in proposals:
            owner, value = proposal['owner'], proposal['minor']
            status = 'unchanged' if state[owner] == value else 'installed' if value in rectangle[owner] else 'blocked'
            counts[status] += 1
            if status == 'installed':
                state[owner] = value
            require(safe(state), 'Handoff literal static replay violates policy')
        return {**counts, 'final': state}

    products, _ = all_products(domains, design['initial'])
    static_best = max(replay(design['initial'], product, design['goal_proposals'])['installed'] for product in products)
    equal(static_best, 2, 'Full-path static optimum changed')
    equal(run['single_static_optimum'], static_best, 'Saved static optimum differs')
    equal(run['static_products_considered'], len(products), 'Static product denominator differs')
    first_rect = guard_vector(run['first_box'], profiles, branches, design['initial'])
    first_replay = replay(design['initial'], first_rect, design['goal_proposals'])
    equal(first_replay['final'], design['handoff_planning_state'], 'First phase does not reach the planning state')
    require(first_replay['installed'] == 2, 'First phase does not attain the static optimum')
    choice = run['second_choice']
    equal(choice['frontier_plan'], second['plan'], 'Second handoff frontier differs')
    batch = [{'node': str(proposal['owner']), 'support': profiles[str(proposal['owner'])][str(proposal['minor'])]}
             for proposal in design['remaining_goal_proposals']]
    equal(run['remaining_batch'], batch, 'Second phase has information beyond the remaining goal')

    def forecast(box):
        rectangle = guard_vector(box, profiles, branches, design['handoff_planning_state'])
        outcome = replay(design['handoff_planning_state'], rectangle, design['remaining_goal_proposals'])
        return {**{name: outcome[name] for name in ('installed', 'blocked', 'unchanged')},
                'proposals': len(batch), 'final': {node: profiles[node][str(outcome['final'][int(node)])] for node in NODES}}

    default = forecast(second['plan']['box'])
    selected_box, selected = second['plan']['box'], default
    scores = []
    for index, member in enumerate(second['plan']['frontier']):
        score = forecast(member['box'])
        scores.append({'member_index': index, **score})
        if score['installed'] > selected['installed']:
            selected_box, selected = member['box'], score
    equal(choice['box'], selected_box, 'Remaining-target selector chose a different guard')
    equal(choice['forecast'], selected, 'Remaining-target forecast differs')
    equal(choice['max_mass_forecast'], default, 'Mass forecast differs')
    equal(choice['batch_scores'], scores, 'Frontier batch score inventory differs')
    equal(choice['kept_max_mass'], False, 'Remaining target incorrectly retains the mass guard')
    require(selected['installed'] == 1 and default['installed'] == 0, 'Remaining target does not distinguish guard choices')
    second_rect = guard_vector(selected_box, profiles, branches, design['handoff_planning_state'])

    def expected_certificate(origin, box, observed_generations):
        return {'mode': 'envelope', 'manifest': design['manifest'], 'origin': origin, 'box': box,
                'sequences': {node: 1 for node in NODES},
                'receipts': [{'status': 'held', 'node': int(node), 'origin': origin, 'sequence': 1,
                              'manifest': design['manifest'], 'requires': [],
                              'observed_generation': observed_generations[int(node)], 'options': box[node]}
                             for node in NODES]}

    certificates = {0: expected_certificate(0, run['first_box'], [0, 0, 0]),
                    1: expected_certificate(1, selected_box, [1, 1, 0])}
    equal(run['old_certificate'], certificates[0], 'Old handoff certificate differs')
    equal(run['new_certificate'], certificates[1], 'New handoff certificate differs')
    state = list(design['initial'])
    generations = [0, 0, 0]
    expected_events = []
    install_responses = []
    specifications = [(proposal, 'first-static-phase', [0]) for proposal in design['goal_proposals']]
    specifications += [(design['remaining_goal_proposals'][0], 'both-guards-probe', [0, 1]),
                       (design['remaining_goal_proposals'][0], 'second-static-phase', [1])]
    rectangles = {0: first_rect, 1: second_rect}
    for proposal, stage, origins in specifications:
        owner, value = proposal['owner'], proposal['minor']
        blocking = [f'{origin}:1' for origin in origins if value not in rectangles[origin][owner]]
        status = 'unchanged' if state[owner] == value else 'blocked' if blocking else 'installed'
        if status == 'installed':
            state[owner] = value
            generations[owner] += 1
        require(safe(state), 'Handoff literal live-guard intersection violates policy')
        expected_events.append({'stage': stage, 'owner': owner, 'proposed_minor': value,
                                'active_origins': origins, 'status': status, 'versions_after': list(state),
                                'rules_after': flags(state)})
        response = {'status': status}
        if status == 'blocked':
            response['holds'] = blocking
        else:
            response['observed'] = {'node': owner, 'generation': generations[owner],
                                    'support': profiles[str(owner)][str(state[owner])]}
        install_responses.append(response)
    equal(run['events'], expected_events, 'Handoff event differs from live-guard replay')
    require(expected_events[3]['status'] == 'blocked' and install_responses[3]['holds'] == ['0:1'],
            'Both-guards probe is not blocked solely by the old phase')
    require(state == design['target'], 'Handoff final target differs')

    snapshots = run['snapshots']
    require(set(snapshots) == {'both-held', 'old-retired', 'both-closed'}, 'Handoff checkpoint inventory differs')
    for stage, retired in [('both-held', set()), ('old-retired', {0}), ('both-closed', {0, 1})]:
        expected_state = design['target'] if stage == 'both-closed' else design['handoff_planning_state']
        expected_generations = [1, 1, 1] if stage == 'both-closed' else [1, 1, 0]
        owners = {}
        for node in NODES:
            index = int(node)
            support = profiles[node][str(expected_state[index])]
            owners[node] = {'node': index, 'generation': expected_generations[index], 'support': support,
                            'window': 8, 'policy': 'predicate',
                            'floor': [int(0 in retired), int(1 in retired), 0, 0, 0, 0],
                            'slots': {f'{origin}:1': certificates[origin]['receipts'][index]
                                      for origin in (0, 1) if origin not in retired},
                            'catalog': {node: {'node': index, 'generation': expected_generations[index], 'support': support}}}
        origins = {}
        for origin in (0, 1):
            attempts = {} if origin in retired else {'1': {'status': 'committed', 'manifest': design['manifest'],
                        'sequences': {node: 1 for node in NODES}, 'certificate': certificates[origin]}}
            origins[str(origin)] = {'origin': origin, 'node_count': 3, 'window': 8, 'policy': 'predicate',
                                    'next': [1, 1, 1], 'serial': 1, 'attempts': attempts}
        snapshot = snapshots[stage]
        equal(snapshot['owner_states'], owners, 'Handoff checkpoint owner guards/floors differ: ' + stage)
        equal(snapshot['origin_states'], origins, 'Handoff checkpoint origin authorization differs: ' + stage)
        names = [f'databases/handoff/{stage}/{name}.sqlite' for name in ('node-0', 'node-1', 'node-2', 'origin-0', 'origin-1')]
        equal([item['path'] for item in snapshot['databases']], names, 'Handoff database inventory differs')
        for item in snapshot['databases']:
            path = (directory / item['path']).resolve()
            require(path.is_relative_to(directory.resolve()) and path.is_file(), 'Handoff database path escape')
            require(digest(path) == item['sha256'], 'Handoff database checksum differs')
            with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
                require(db.execute('PRAGMA quick_check').fetchone()[0] == 'ok', 'Handoff database integrity failure')
                rows = db.execute('SELECT id,payload FROM state ORDER BY id').fetchall()
                require(len(rows) == 1 and rows[0][0] == 1, 'Handoff database row set differs')
                saved = json.loads(rows[0][1])
            kind, identity = path.stem.split('-')
            equal(saved, owners[identity] if kind == 'node' else origins[identity], 'Stored handoff checkpoint differs: ' + stage)

    expected_rpcs = []
    def prepare(origin, box, target, status='held'):
        request = {'op': 'prepare', 'origin': origin, 'sequence': 1, 'manifest': design['manifest'],
                   'requires': [], 'options': box[str(target)]}
        response = {'status': status}
        if status == 'held':
            response['receipt'] = certificates[origin]['receipts'][target]
        return (origin, target, request, response)

    def update(event_index, source):
        event = expected_events[event_index]
        return (source, event['owner'], {'op': 'install', 'support': profiles[str(event['owner'])][str(event['proposed_minor'])]},
                install_responses[event_index])

    expected_rpcs += [prepare(0, run['first_box'], target) for target in range(3)]
    expected_rpcs += [update(index, 0) for index in range(3)]
    expected_rpcs += [prepare(1, selected_box, target) for target in range(3)]
    expected_rpcs += [update(3, 1)]
    expected_rpcs += [(0, target, {'op': 'close', 'origin': 0, 'sequence': 1}, {'status': 'closed', 'floor': 1}) for target in range(3)]
    expected_rpcs += [update(4, 1)]
    expected_use = [{'status': 'used', 'node': target, 'manifest': design['manifest'], 'generation': 1}
                    for target in range(3)]
    expected_rpcs += [(1, target, {'op': 'use', 'origin': 1, 'sequence': 1, 'manifest': design['manifest']}, expected_use[target])
                     for target in range(3)]
    expected_rpcs += [(1, target, {'op': 'close', 'origin': 1, 'sequence': 1}, {'status': 'closed', 'floor': 1}) for target in range(3)]
    expected_rpcs += [prepare(0, run['first_box'], 1, 'closed')]
    trace = run['logical_rpc_trace']
    rpcs = [row for row in trace if row.get('event') == 'rpc']
    controls = [row for row in trace if row.get('event') != 'rpc']
    equal(controls, [{'event': 'crash', 'node': 1, 'tick': 14}, {'event': 'recover', 'node': 1, 'tick': 14}],
          'Handoff owner reopen trace differs')
    require(trace[14:16] == controls and len(rpcs) == len(expected_rpcs) == 21, 'Handoff RPC ordering/count differs')
    for tick, (observed, (source, target, request, response)) in enumerate(zip(rpcs, expected_rpcs), 1):
        equal({key: observed[key] for key in ('tick', 'source', 'target', 'request', 'response')},
              {'tick': tick, 'source': source, 'target': target, 'request': request, 'response': response},
              'Handoff RPC differs from literal protocol trace')
        equal(observed['bytes'], len((canonical(request) + '\n').encode()) + len((canonical(response) + '\n').encode()),
              'Handoff logical byte count differs')
        require(type(observed['wall_ns']) is int and observed['wall_ns'] >= 0, 'Invalid handoff elapsed time')
    equal(run['old_use_after_retirement'], [{'status': 'not-authorized'}], 'Retired old token still authorizes')
    equal(run['old_use_after_reopen'], [{'status': 'not-authorized'}], 'Reopen revives old token')
    equal(run['new_use_after_reopen'], expected_use, 'New token did not survive reopen')
    equal(run['late_old_prepare'], {'status': 'closed'}, 'Old prepare resurrected')
    totals = {'goal_steps': len(design['goal_proposals']), 'single_static_optimum': static_best,
              'first_phase_targets_completed': sum(a == b for a, b in zip(first_replay['final'], design['target'])),
              'final_targets_completed': sum(a == b for a, b in zip(state, design['target'])),
              'target_reached': state == design['target'], 'installation_requests': len(expected_events),
              **{name: sum(event['status'] == name for event in expected_events) for name in ('installed', 'blocked', 'unchanged')},
              'database_snapshots': sum(len(snapshot['databases']) for snapshot in snapshots.values())}
    equal(run['totals'], totals, 'Handoff goal/outcome totals differ')
    return {'status': 'PASS', **totals}


def check(directory=ROOT / 'results/policy-boundaries'):
    directory = Path(directory).resolve()
    result = read(directory / 'results.json')
    facts = read(ROOT / 'data/kubernetes-policy-boundaries.json')
    equal(result['source'], facts, 'Fixture differs from saved source')
    require(result['status'] == 'PASS' and result['source_bytes_unchanged_during_run'] is True,
            'Unsuccessful or source-changing execution')
    registration = read(directory / 'registration.json')
    execution = read(directory / 'execution.json')
    equal(registration['source_sha256'], result['source_sha256'], 'Registration differs from result sources')
    equal(execution['source_sha256'], result['source_sha256'], 'Execution differs from result sources')
    require(execution['status'] == 'PASS' and type(execution['returncode']) is int and execution['returncode'] == 0
            and execution['source_bytes_unchanged_during_run'] is True, 'Failed execution record')
    required_sources = {'data/kubernetes-policy-boundaries.json', 'docs/POLICY-BOUNDARY-DESIGN.md',
                        'tests/kubernetes_policy_boundaries.py', 'tests/check_policy_boundaries.py'}
    # The recorded campaign snapshots its source directory. Later, unrelated
    # modules do not become retrospective inputs to that campaign. Require all
    # of its original core modules and every actually retained source snapshot.
    core_sources = {'src/' + name for name in (
        '__init__.py', 'android_contracts.py', 'batch.py', 'checker.py',
        'controller.py', 'direct_batch.py', 'effect_ledger.py', 'envelope.py',
        'goal_planner.py', 'network.py', 'rollout.py')}
    retained_sources = {str(path.relative_to(directory / 'source-preimage'))
                        for path in (directory / 'source-preimage' / 'src').glob('*.py')}
    require(core_sources <= retained_sources, 'Missing recorded core source')
    required_sources.update(retained_sources)
    require(set(result['source_sha256']) == required_sources, 'Incomplete source inventory')
    for name, expected in result['source_sha256'].items():
        source = (ROOT / name).resolve()
        preimage = (directory / 'source-preimage' / name).resolve()
        require(source.is_relative_to(ROOT.resolve()) and preimage.is_relative_to((directory / 'source-preimage').resolve()),
                'Source path escape')
        require(digest(preimage) == expected, 'Recorded source snapshot differs: ' + name)
        if name != 'tests/check_policy_boundaries.py':
            require(digest(source) == expected, 'Current measured source differs: ' + name)
        # This acceptance checker can evolve after measurement; its original
        # bytes remain verified above. It was not part of the measured runtime.
    equal(registration['default_bounds'], True, 'Nondefault synthesis bounds')
    equal(registration['planned_vectors'], 45, 'Planned vector count differs')
    equal(registration['planned_rule_controls'], 3, 'Planned rule count differs')
    equal(registration['planned_lifecycles'], 3, 'Planned lifecycle count differs')
    equal(registration['planned_handoffs'], 1, 'Planned handoff count differs')
    equal(registration['handoff_goal_steps'], 3, 'Handoff goal denominator differs')
    domains, profiles, branches = fixture_inputs(facts)
    equal(result['profiles'], profiles, 'Saved profile encoding differs')
    equal(result['branches'], branches, 'Saved manifest differs')
    vectors = list(itertools.product(*domains))
    rows = result['exhaustive']
    equal([row['versions'] for row in rows], list(map(list, vectors)), 'Missing or reordered policy vector')
    completed = refused = members = compatible_count = 0
    for vector, row in zip(vectors, rows):
        compatible = safe(vector)
        equal(row['rules'], flags(vector), 'Rule arithmetic differs')
        equal(row['compatible'], compatible, 'Compatibility differs')
        support = {node: profiles[node][str(vector[int(node)])] for node in NODES}
        equal(row['encoded_compatible'], encoded(branches, support), 'Saved encoded compatibility differs')
        require(row['encoded_compatible'] is compatible, 'Positive encoding differs from numerical policy')
        if not compatible:
            require('plan' not in row and 'status' not in row, 'Incompatible seed was planned')
            continue
        compatible_count += 1
        products, frontier = all_products(domains, vector)
        equal(row['safe_products'], len(products), 'Safe product count differs')
        equal(row['literal_frontier'], [list(map(list, box)) for box in frontier], 'Literal frontier differs')
        if row['status'] == 'refused':
            require(row['reason'] in {'exact frontier local-library bound',
                    'exact frontier search-state bound', 'exact frontier result bound'}
                    and 'plan' not in row, 'Malformed or non-resource refusal')
            refused += 1
            continue
        require(row['status'] == 'completed', 'Unexpected seed status')
        completed += 1
        plan = row['plan']
        returned = [verify_member(member, profiles, branches, vector) for member in plan['frontier']]
        require(len(returned) == len(set(returned)), 'Duplicate acceptance vector')
        equal(sorted(returned), frontier, 'Synthesized frontier differs')
        equal(plan['frontier_size'], len(frontier), 'Frontier size differs')
        selected = verify_member(plan, profiles, branches, vector)
        require(selected in frontier, 'Selected vector is not on the frontier')
        equal(plan['product_mass'], max(len(a) * len(b) * len(c) for a, b, c in products), 'Selected mass is not optimal')
        equal(plan['exact'], True, 'Missing exactness declaration')
        require(any(canonical(member['box']) == canonical(plan['box']) for member in plan['frontier']),
                'Selected guard absent from frontier')
        members += len(frontier)
    expected_controls = []
    equal([case['omitted_rule'] for case in facts['boundary_cases']], list(RULES), 'Rule witness inventory differs')
    for witness in facts['boundary_cases']:
        rule = witness['omitted_rule']
        bad, good = witness['incompatible'], witness['compatible']
        values = flags(bad)
        require(values[rule] is False and all(flag for name, flag in values.items() if name != rule)
                and safe(good), 'Boundary witness does not isolate exactly one rule')
        equal([i for i in range(3) if bad[i] != good[i]], [witness['changed_owner']], 'Boundary changed-owner mismatch')
        false_positives = [list(vector) for vector in vectors if not safe(vector) and safe(vector, omitted=rule)]
        require(bad in false_positives, 'Rule deletion misses its witness')
        expected_controls.append({'omitted_rule': rule, 'newly_admitted': false_positives,
                                  'newly_admitted_count': len(false_positives),
                                  'witness': witness, 'witness_rules': values})
    equal(result['controls']['rule_deletions'], expected_controls, 'Rule-deletion controls differ')
    marginals = [sorted({vector[i] for vector in vectors if safe(vector)}) for i in range(3)]
    false_marginals = [list(vector) for vector in itertools.product(*marginals) if not safe(vector)]
    equal(result['controls']['marginals'], {'domains': marginals, 'newly_admitted': false_marginals,
          'newly_admitted_count': len(false_marginals)}, 'Marginal-only control differs')
    equal(result['refusals'], [{'versions': row['versions'], 'reason': row['reason']}
          for row in rows if row.get('status') == 'refused'], 'Refusal inventory differs')
    lifecycles = result['lifecycles']
    equal([run['rule'] for run in lifecycles], list(RULES), 'Lifecycle inventory differs')
    executed = proposals_count = database_count = blocked_witnesses = 0
    for witness, run in zip(facts['boundary_cases'], lifecycles):
        seed_row = next(row for row in rows if row['versions'] == witness['compatible'])
        if seed_row['status'] == 'refused':
            equal(run, {'rule': witness['omitted_rule'], 'status': 'not-run', 'reason': seed_row['reason']},
                  'Refused seed runtime handling differs')
            continue
        require(run['status'] == 'completed', 'Missing completed boundary lifecycle')
        equal(run['initial'], witness['compatible'], 'Lifecycle seed differs')
        equal(run['box'], seed_row['plan']['box'], 'Lifecycle guard differs from selected plan')
        state = list(run['initial'])
        generations = [0, 0, 0]
        changed = witness['changed_owner']
        proposals = [(changed, witness['incompatible'][changed], 'rule-witness')]
        proposals += [(i, value, 'catalog') for i, domain in enumerate(domains) for value in domain]
        expected_events = []
        for owner, value, kind in proposals:
            atoms = profiles[str(owner)][str(value)]
            allowed = any(set(term).issubset(atoms) for term in run['box'][str(owner)])
            status = 'unchanged' if state[owner] == value else 'installed' if allowed else 'blocked'
            if status == 'installed':
                state[owner] = value
                generations[owner] += 1
            require(safe(state), 'Reconstructed lifecycle violates policy')
            expected_events.append({'owner': owner, 'proposed_minor': value, 'kind': kind,
                                    'status': status, 'versions_after': list(state), 'rules_after': flags(state)})
        equal(run['events'], expected_events, 'Lifecycle event differs from literal replay')
        require(expected_events[0]['status'] == 'blocked', 'Boundary violation not blocked')
        equal(run['final_versions'], state, 'Lifecycle final versions differ')
        equal(run['outcomes'], {name: sum(e['status'] == name for e in expected_events)
                               for name in ('installed', 'blocked', 'unchanged')}, 'Lifecycle totals differ')
        require(run['owner_and_origin_reopen'] == 'authorized' and run['retirement'] == run['delayed_prepare'] == 'closed',
                'Lifecycle completion/recovery differs')
        check_trace(run, profiles, expected_events, generations)
        check_databases(directory, run, profiles, state, generations)
        executed += 1
        proposals_count += len(proposals)
        database_count += len(run['databases'])
        blocked_witnesses += 1
    totals = {'vectors': len(vectors), 'compatible_vectors': compatible_count, 'completed_seeds': completed,
              'refused_seeds': refused, 'frontier_members_across_completed_seeds': members,
              'rule_deletion_false_positives': {row['omitted_rule']: row['newly_admitted_count'] for row in expected_controls},
              'marginal_false_positives': len(false_marginals), 'completed_lifecycles': executed,
              'lifecycle_proposals': proposals_count, 'blocked_rule_witnesses': blocked_witnesses,
              'database_snapshots': database_count}
    equal(result['totals'], totals, 'Summary totals differ')
    handoff = check_handoff(directory, facts, result, profiles, branches, domains)
    return {'status': 'PASS', **totals, 'handoff': handoff, 'source_files': len(required_sources), 'data_only_checker': True}


def corruption_controls(directory):
    check(directory)
    controls = []
    for case in ('policy_flag', 'missing_frontier_member', 'event_status', 'rehashed_database_floor',
                 'handoff_overlap_event', 'rehashed_handoff_live_guard'):
        with tempfile.TemporaryDirectory(prefix='policy-boundary-corrupt-') as scratch:
            changed = Path(scratch) / 'cohort'
            shutil.copytree(directory, changed)
            result = read(changed / 'results.json')
            if case == 'policy_flag':
                result['exhaustive'][0]['compatible'] = not result['exhaustive'][0]['compatible']
            elif case == 'missing_frontier_member':
                row = next(row for row in result['exhaustive'] if row.get('status') == 'completed'
                           and row['plan']['frontier_size'] > 1)
                row['plan']['frontier'].pop()
                row['plan']['frontier_size'] -= 1
            elif case == 'event_status':
                result['lifecycles'][0]['events'][0]['status'] = 'installed'
            elif case == 'rehashed_database_floor':
                run = result['lifecycles'][0]
                item = next(item for item in run['databases'] if item['path'].endswith('node-1.sqlite'))
                path = changed / item['path']
                with sqlite3.connect(path) as db:
                    payload = json.loads(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
                    payload['floor'][0] = 0
                    db.execute('UPDATE state SET payload=? WHERE id=1', (canonical(payload),))
                item['sha256'] = digest(path)
                run['owner_states']['1'] = deepcopy(payload)
            elif case == 'handoff_overlap_event':
                result['handoff']['events'][3]['active_origins'] = [1]
            else:
                snapshot = result['handoff']['snapshots']['both-held']
                item = next(item for item in snapshot['databases'] if item['path'].endswith('node-2.sqlite'))
                path = changed / item['path']
                with sqlite3.connect(path) as db:
                    payload = json.loads(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
                    del payload['slots']['0:1']
                    db.execute('UPDATE state SET payload=? WHERE id=1', (canonical(payload),))
                item['sha256'] = digest(path)
                snapshot['owner_states']['2'] = deepcopy(payload)
            (changed / 'results.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
            try:
                check(changed)
            except (ValueError, KeyError, TypeError, IndexError, sqlite3.DatabaseError) as exc:
                controls.append({'case': case, 'rejected': True, 'reason': str(exc)})
            else:
                raise ValueError('Corruption control was accepted: ' + case)
    return {'status': 'PASS', 'corruption_controls': controls}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=ROOT / 'results/policy-boundaries')
    parser.add_argument('--corruption-controls', action='store_true')
    arguments = parser.parse_args()
    answer = corruption_controls(arguments.directory) if arguments.corruption_controls else check(arguments.directory)
    print(json.dumps(answer, indent=2, sort_keys=True))
