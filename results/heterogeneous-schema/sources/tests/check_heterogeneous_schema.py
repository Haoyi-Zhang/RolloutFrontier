"""Standard-library-only independent checker for heterogeneous event chains.

No production or producer module is imported. Longest weighted constraints are
solved by repeated relaxation; fixed-path phase minima use a serial event
recurrence, independently of the producer's interval dynamic program.
"""
from __future__ import annotations

import argparse
from collections import Counter, deque
from copy import deepcopy
import csv
import gzip
from itertools import combinations, permutations, product
import json
import math
from pathlib import Path


CONFIGS = {
    'two_owner': [('ab0', 0, 1), ('ab1', 0, 1), ('ba0', 1, 0), ('ba1', 1, 0)],
    'three_owner': [('ab0', 0, 1), ('ab1', 0, 1), ('ba0', 1, 0), ('ba1', 1, 0),
                    ('bc0', 1, 2), ('cb0', 2, 1)],
    'three_owner_complete': [('ab0', 0, 1), ('ba0', 1, 0), ('bc0', 1, 2),
                             ('cb0', 2, 1), ('ca0', 2, 0), ('ac0', 0, 2)],
    'three_owner_complete_extra': [('ab0', 0, 1), ('ba0', 1, 0), ('bc0', 1, 2),
                                   ('cb0', 2, 1), ('ca0', 2, 0), ('ac0', 0, 2), ('ab1', 0, 1)],
}
STRATEGIES = ('owner', 'stage', 'prepare_first', 'prepare_first_stage')
SAMPLES = (('alpha', 'present'), ('κλειδί', 'migrated-δ'), ('中文', '扩展字段'),
           ('quoted"key', 'line\nbreak\\path'), ('emoji-λ', 'field-🙂'))
ROOT = Path(__file__).resolve().parents[1]
SOURCES = ('src/heterogeneous_contracts.py', 'src/factored_planner.py',
           'src/envelope.py', 'src/controller.py',
           'tests/heterogeneous_schema_study.py', 'tests/check_heterogeneous_schema.py')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(path.read_text())


def canonical(value):
    return json.loads(json.dumps(value))


def subsets(fields):
    return [tuple(s) for size in range(len(fields) + 1) for s in combinations(fields, size)]


def channel_inventory(config):
    groups = {}
    for field, sender, receiver in CONFIGS[config]:
        groups.setdefault((sender, receiver), []).append(field)
    return [(s, r, tuple(sorted(fields))) for (s, r), fields in sorted(groups.items())]


def protobuf_fields(data):
    """Decode only standard protobuf wire types needed by descriptor records."""
    cursor, result = 0, []
    def varint():
        nonlocal cursor
        value, shift = 0, 0
        while True:
            require(cursor < len(data) and shift <= 63, 'invalid descriptor varint')
            byte = data[cursor]; cursor += 1
            value |= (byte & 127) << shift
            if byte < 128: return value
            shift += 7
    while cursor < len(data):
        tag = varint(); number, wire_type = tag >> 3, tag & 7
        if wire_type == 0: value = varint()
        elif wire_type == 2:
            length = varint(); value = data[cursor:cursor + length]; cursor += length
            require(len(value) == length, 'truncated descriptor field')
        else: raise ValueError('unsupported descriptor wire type')
        result.append((number, value))
    return result


def verify_descriptor(hexadecimal, fields, prepared):
    decoded = protobuf_fields(bytes.fromhex(hexadecimal))
    require([v for n, v in decoded if n == 1] == [b'event_channel.proto'], 'descriptor filename')
    require([v for n, v in decoded if n == 2] == [b'events'], 'descriptor package')
    require([v for n, v in decoded if n == 12] == [b'proto3'], 'descriptor syntax')
    messages = [protobuf_fields(v) for n, v in decoded if n == 4]
    require(len(messages) == 1 and [v for n, v in messages[0] if n == 1] == [b'Record'],
            'descriptor message inventory')
    observed = []
    for number, value in messages[0]:
        if number != 2: continue
        field = dict(protobuf_fields(value))
        require(set(field) == {1, 3, 4, 5}, 'unexpected descriptor field attributes')
        observed.append((field[1].decode(), field[3], field[4], field[5]))
    expected = [('key', 1, 1, 9)] + [('tag_' + f, index + 2, 1, 9)
                                      for index, f in enumerate(fields) if f in prepared]
    require(observed == expected, 'descriptor field set differs from actual preparation')


def expected_wire(fields, active, sample):
    key, value = SAMPLES[sample]
    wire = {'key': key, **{'tag' + f[0].upper() + f[1:]: f + ':' + value for f in active}}
    semantic = {'key': key, **{f: f + ':' + value if f in active else '' for f in fields}}
    return wire, semantic


def verify_channels(channels):
    inventory = sorted({spec for config in CONFIGS for spec in channel_inventory(config)})
    require([(c['sender'], c['receiver'], tuple(c['fields'])) for c in channels] == inventory,
            'channel catalog inventory changed')
    counts = Counter(channel_catalogs=len(channels))
    for channel in channels:
        fields = tuple(channel['fields']); choices = subsets(fields)
        require(channel['subsets'] == [list(s) for s in choices], 'channel subset order')
        require(channel['matrix_axes'] == ['prepared_subset', 'emitted_subset'], 'matrix axes')
        require(len(channel['descriptors']) == len(choices), 'descriptor count')
        for prepared, descriptor in zip(choices, channel['descriptors']):
            require(descriptor['prepared_fields'] == list(prepared), 'descriptor subset binding')
            verify_descriptor(descriptor['serialized_hex'], fields, prepared)
        counts['descriptors'] += len(channel['descriptors'])
        require(len(channel['wires']) == len(choices) * len(SAMPLES), 'wire count')
        for index, wire in enumerate(channel['wires']):
            active = choices[index // len(SAMPLES)]; sample = index % len(SAMPLES)
            require(wire['id'] == str(index) and wire['emitted_fields'] == list(active)
                    and wire['sample'] == sample, 'wire context binding')
            expected, semantic = expected_wire(fields, active, sample)
            require(json.loads(wire['wire']) == expected and wire['semantic'] == semantic,
                    'wire payload or semantic record differs')
        counts['wires'] += len(channel['wires'])
        require(len(channel['parses']) == len(choices) * len(channel['wires']), 'parse count')
        matrix = []
        for prepared_index, prepared in enumerate(choices):
            matrix.append([int(set(active) <= set(prepared)) for active in choices])
            for wire_index, wire in enumerate(channel['wires']):
                observation = channel['parses'][prepared_index * len(channel['wires']) + wire_index]
                accepted = set(wire['emitted_fields']) <= set(prepared)
                require(observation['prepared_fields'] == list(prepared)
                        and observation['wire_id'] == wire['id'], 'parse context binding')
                require(observation['accepted'] is accepted, 'parse acceptance differs')
                if accepted:
                    require(observation['semantic_equal'] is True and observation['decoded'] == wire['semantic'],
                            'accepted parser output changed semantic values')
                    counts['accepted'] += 1
                else:
                    require(observation['error_type'] == 'ParseError' and isinstance(observation['error'], str),
                            'rejected parser evidence missing')
                    counts['rejected'] += 1
                counts['matrix_parser_invocations'] += 1
        require(channel['matrix'] == matrix, 'measured compatibility matrix changed')
        effects = [(field, before) for field in fields for before in choices if field not in before]
        require(len(channel['event_effect_witnesses']) == len(effects), 'event effect count')
        for witness, (field, before) in zip(channel['event_effect_witnesses'], effects):
            after = tuple(f for f in fields if f in before or f == field)
            require(witness['feature'] == field and witness['before_subset'] == list(before)
                    and witness['after_subset'] == list(after), 'event effect identity')
            require(json.loads(witness['before_emit_wire']) == expected_wire(fields, before, 0)[0]
                    and json.loads(witness['after_emit_wire']) == expected_wire(fields, after, 0)[0]
                    and witness['before_emit_wire'] != witness['after_emit_wire'], 'emitter event has no actual effect')
            require(json.loads(witness['prepare_witness_wire']) == expected_wire(fields, (field,), 0)[0]
                    and witness['reader_before_rejects'] is True
                    and witness['reader_after_preserves_semantics'] is True, 'reader effect witness changed')
        counts['event_effect_witnesses'] += len(effects)
        counts['event_effect_parser_invocations'] += 2 * len(effects)
    return dict(counts)


def event_inventory(config):
    edges = CONFIGS[config]
    owners = max(max(s, r) for _, s, r in edges) + 1
    inventory = [[] for _ in range(owners)]
    for field, sender, receiver in edges:
        inventory[sender].append('e_' + field); inventory[receiver].append('p_' + field)
    return inventory


def order_at(choices, identifier):
    result = []
    for values in reversed(choices):
        result.append(values[identifier % len(values)]); identifier //= len(values)
    require(identifier == 0, 'context identifier out of range')
    return tuple(reversed(result))


def independent_exact(config, orders):
    events = [event for chain in orders for event in chain]
    constraints = [(a, b, 0) for chain in orders for a, b in zip(chain, chain[1:])]
    constraints.extend(('p_' + field, 'e_' + field, 1) for field, _, _ in CONFIGS[config])
    labels = {event: 1 for event in events}
    for iteration in range(len(events)):
        changed = False
        for before, after, delay in constraints:
            required = labels[before] + delay
            if labels[after] < required:
                labels[after] = required; changed = True
        if not changed:
            maximum = max(labels.values())
            endpoints = [[0] * len(orders)] + [[sum(labels[event] <= phase for event in chain)
                                              for chain in orders] for phase in range(1, maximum + 1)]
            return maximum, endpoints
    return None, None


def path_cost(orders, priority, strategy):
    """Build a serial order; solve its phase constraints in one forward pass."""
    ranks, event_phases, path = [0] * len(orders), {}, [[0] * len(orders)]
    current_phase = 1
    phases = []
    while any(rank < len(chain) for rank, chain in zip(ranks, orders)):
        options = []
        for preference, owner in enumerate(priority):
            if ranks[owner] == len(orders[owner]): continue
            event = orders[owner][ranks[owner]]; emitted = event.startswith('e_')
            if emitted and 'p_' + event[2:] not in event_phases: continue
            if strategy == 'owner': key = (preference,)
            elif strategy == 'stage': key = (ranks[owner], preference)
            elif strategy == 'prepare_first': key = (emitted, preference)
            elif strategy == 'prepare_first_stage': key = (emitted, ranks[owner], preference)
            else: raise ValueError('unknown strategy')
            options.append((key, owner, event))
        require(options, 'serial baseline deadlocked on reachable release DAG')
        _, owner, event = min(options)
        if event.startswith('e_'):
            current_phase = max(current_phase, event_phases['p_' + event[2:]] + 1)
        event_phases[event] = current_phase
        ranks[owner] += 1; path.append(list(ranks)); phases.append(current_phase)
    return current_phase, path


def thresholds_for(config, orders):
    return [(sender, orders[sender].index('e_' + field) + 1,
             receiver, orders[receiver].index('p_' + field) + 1)
            for field, sender, receiver in CONFIGS[config]]


def literal_phase_graph(config, orders):
    thresholds = thresholds_for(config, orders)
    points = list(product(*(range(len(chain) + 1) for chain in orders)))
    relation = [p for p in points if all(p[s] < e or p[r] >= prep for s, e, r, prep in thresholds)]
    membership = set(relation)
    graph = {}
    for source in relation:
        graph[source] = []
        for target in relation:
            if source == target or any(s > t for s, t in zip(source, target)): continue
            if all(p in membership for p in product(*(range(s, t + 1) for s, t in zip(source, target)))):
                graph[source].append(target)
    initial = tuple(0 for _ in orders); target = tuple(map(len, orders))
    queue, distance = deque([initial]), {initial: 0}
    while queue:
        source = queue.popleft()
        for following in graph[source]:
            if following not in distance:
                distance[following] = distance[source] + 1; queue.append(following)
    return {'compatible_cells': len(relation), 'catalog_cells': len(points),
            'safe_phase_edges': sum(map(len, graph.values())), 'optimal_phases': distance.get(target),
            'relation': [list(p) for p in relation],
            'phase_graph': [{'source': list(s), 'targets': [list(t) for t in targets]}
                            for s, targets in graph.items()]}


def physical_model(config, orders, channels):
    lookup = {(c['sender'], c['receiver'], tuple(c['fields'])): c for c in channels}
    specs = channel_inventory(config)
    profiles = {str(owner): [] for owner in range(len(orders))}
    factors = []
    for owner, chain in enumerate(orders):
        for rank in range(len(chain) + 1):
            completed = set(chain[:rank]); support = set()
            for sender, receiver, fields in specs:
                channel = lookup[sender, receiver, fields]; name = str(sender) + '-' + str(receiver)
                if owner == sender:
                    emitted = [f for f in fields if 'e_' + f in completed]
                    support.add('emit:' + name + ':' + str(channel['subsets'].index(emitted)))
                if owner == receiver:
                    prepared = [f for f in fields if 'p_' + f in completed]
                    row = channel['matrix'][channel['subsets'].index(prepared)]
                    support.update('accept:' + name + ':' + str(i) for i, accepted in enumerate(row) if accepted)
            profiles[str(owner)].append(support)
        require(len({tuple(sorted(p)) for p in profiles[str(owner)]}) == len(chain) + 1,
                'physical release is semantically redundant')
    for sender, receiver, fields in specs:
        name = str(sender) + '-' + str(receiver)
        factors.append({'id': 'channel-' + name,
                        'branches': [{str(sender): {'emit:' + name + ':' + str(i)},
                                      str(receiver): {'accept:' + name + ':' + str(i)}}
                                     for i in range(len(lookup[sender, receiver, fields]['subsets']))]})
    return profiles, factors


def minimal_terms(terms):
    unique = {frozenset(t) for t in terms}
    return [term for term in unique if not any(other < term for other in unique)]


def verify_production(record, config, orders, channels, exact, endpoints):
    profiles, factors = physical_model(config, orders, channels)
    target, zero = list(map(len, orders)), [0] * len(orders)
    if exact is None:
        require(record['status'] == 'unreachable' and record['cost'] is None and record['phases'] == [],
                'production unreachable result changed')
        require(record['reason'] == 'greatest safe endpoint is a fixed point before target',
                'production unreachable diagnostic changed')
        trace = [zero]; thresholds = thresholds_for(config, orders)
        while True:
            following = list(target)
            for sender, emit, receiver, prepare in thresholds:
                if trace[-1][receiver] < prepare: following[sender] = min(following[sender], emit - 1)
            trace.append(following)
            if trace[-1] == trace[-2]: break
            require(len(trace) <= sum(target) + 2, 'nonterminating unreachable trace')
        require(trace[-1] != target and record['rank_iterates'] == trace, 'production fixed-point trace differs')
        return
    require(record['status'] == 'planned' and record['rank_iterates'] == endpoints,
            'production phase endpoints differ from weighted event constraints')
    require(record['reason'] is None, 'unexpected production success diagnostic')
    require(record['cost'] == {'phases': exact, 'installations': sum(target), 'handoffs': exact - 1},
            'production objective value differs')
    require(len(record['phases']) == exact, 'production phase count')
    previous, installation_count = zero, 0
    for index, phase in enumerate(record['phases']):
        begin, end = phase['source'], phase['target']
        require(begin == previous and end == endpoints[index + 1], 'phase continuity')
        require(set(phase['box']) == set(profiles), 'guard owner placement')
        require(set(phase['local_paths']) == set(profiles), 'local path owner placement')
        for owner in profiles:
            i = int(owner)
            path = list(range(begin[i], end[i] + 1))
            require(phase['local_paths'][owner] == path, 'local path skips a release')
            terms = phase['box'][owner]
            require(isinstance(terms, list) and 1 <= len(terms) <= 8
                    and all(isinstance(term, list) and all(isinstance(atom, str) for atom in term)
                            for term in terms), 'guard term types or protocol bound')
            require(len(terms) == len(minimal_terms(terms)) and all(t == sorted(set(t)) for t in terms),
                    'guard is not an antichain')
            for rank in path:
                require(any(set(term) <= profiles[owner][rank] for term in terms), 'guard rejects its actual release')
        expected_checks = []
        for factor in factors:
            scope = sorted(factor['branches'][0])
            relevant = {owner: set().union(*(branch[owner] for branch in factor['branches'])) for owner in scope}
            projected = {owner: minimal_terms(set(term) & relevant[owner] for term in phase['box'][owner])
                         for owner in scope}
            corners = 0
            for values in product(*(projected[owner] for owner in scope)):
                corner = dict(zip(scope, values)); corners += 1
                require(any(all(required <= corner[owner] for owner, required in branch.items())
                            for branch in factor['branches']), 'unsafe production guard corner')
            expected_checks.append({'id': factor['id'], 'corners': corners})
        require(phase['factor_checks'] == expected_checks, 'factor corner evidence differs')
        current = list(begin)
        for owner, rank in phase['steps']:
            require(owner in profiles, 'unknown installation owner')
            i = int(owner)
            require(rank == current[i] + 1 and rank <= end[i], 'installation skips or exceeds its local chain')
            current[i] = rank; installation_count += 1
        require(current == end, 'phase installation sequence ends early')
        previous = list(end)
    require(previous == target and installation_count == sum(target), 'production final installation count')


def verify_example(example, config, choices, channels):
    orders = order_at(choices, example['context'])
    require(example['orders'] == canonical(orders), 'example order binding')
    exact, endpoints = independent_exact(config, orders)
    require(example['exact'] == exact and example['thresholds'] == canonical(thresholds_for(config, orders)),
            'example event semantics changed')
    literal = literal_phase_graph(config, orders)
    require(example['literal_verification'] == literal and literal['optimal_phases'] == exact,
            'literal phase graph differs')
    if exact is None:
        cycle = example['dependency_cycle']
        edges = {(a, b) for chain in orders for a, b in zip(chain, chain[1:])}
        edges.update(('p_' + field, 'e_' + field) for field, _, _ in CONFIGS[config])
        require(len(cycle) >= 3 and cycle[0] == cycle[-1]
                and all((a, b) in edges for a, b in zip(cycle, cycle[1:])), 'dependency cycle witness invalid')
    else:
        require(example['endpoints'] == endpoints, 'example exact endpoint trace')
        priorities = list(permutations(range(len(orders))))
        require(len(example['paths']) == len(STRATEGIES) * len(priorities), 'example baseline inventory')
        relation = {tuple(p) for p in literal['relation']}
        for observed, (strategy, priority) in zip(example['paths'], product(STRATEGIES, priorities)):
            cost, path = path_cost(orders, priority, strategy)
            require(observed['strategy'] == strategy and observed['priority'] == list(priority)
                    and observed['phases'] == cost and observed['path'] == path, 'baseline path witness differs')
            cuts = observed['endpoints']
            require(len(cuts) == cost + 1 and cuts[0] == path[0] and cuts[-1] == path[-1]
                    and all(point in path for point in cuts), 'baseline partition endpoints')
            for begin, end in zip(cuts, cuts[1:]):
                require(all(a <= b for a, b in zip(begin, end)) and begin != end
                        and all(p in relation for p in product(*(range(a, b + 1) for a, b in zip(begin, end)))),
                        'baseline partition contains unsafe rectangle')
    verify_production(example['production'], config, orders, channels, exact, endpoints)


def verify_domain(directory, config, channels):
    summary = read(directory / 'summary.json')
    inventory = event_inventory(config)
    choices = [list(permutations(sorted(events))) for events in inventory]
    total = math.prod(map(len, choices)); priorities = list(permutations(range(len(inventory))))
    whole = config != 'three_owner_complete_extra'
    require(summary['scope'] == ('declared_finite_domain' if whole else 'discovery_extension'),
            'declared-versus-discovery scope changed')
    require(summary['domain'] == config and summary['field_edges'] == canonical(CONFIGS[config])
            and summary['events_by_owner'] == inventory, 'domain specification changed')
    require(summary['state_shape'] == [len(events) + 1 for events in inventory]
            and summary['context_count_formula'] == list(map(len, choices))
            and summary['installations'] == sum(map(len, inventory)), 'context denominator changed')
    require(summary['priorities'] == canonical(priorities) and summary['strategies'] == list(STRATEGIES),
            'baseline portfolio inventory changed')
    fixed = sorted({round(i * (total - 1) / 15) for i in range(16)})
    require(summary['production_fixed_grid'] == fixed
            and summary['production_scope'] == ('every_context' if whole else 'fixed_grid_and_outcome_witnesses'),
            'production validation coverage changed')
    counts, histogram, vectors, production_counts = Counter(), Counter(), Counter(), Counter()
    first_examples = {}
    with gzip.open(directory / 'contexts.csv.gz', 'rt', encoding='utf-8') as csv_stream, \
            gzip.open(directory / 'production.jsonl.gz', 'rt', encoding='utf-8') as plan_stream:
        production_rows = iter(plan_stream); next_plan = next(production_rows, None)
        for identifier, row in enumerate(csv.DictReader(csv_stream)):
            require(int(row['context']) == identifier and identifier < total, 'missing or repeated context')
            orders = order_at(choices, identifier)
            require(all(row['order_' + str(i)] == ' '.join(chain) for i, chain in enumerate(orders)),
                    'event permutation inventory changed')
            exact, endpoints = independent_exact(config, orders)
            counts['attempted'] += 1
            labels = []
            if exact is None:
                counts['unreachable'] += 1
                require(row['status'] == 'unreachable' and row['exact'] == '', 'deadlock result changed')
                require(all(row[s + suffix] == '' for s in STRATEGIES for suffix in ('_portfolio', '_costs'))
                        and row['owner_stage_portfolio'] == row['all_portfolio'] == '', 'cost assigned to deadlock')
                if 'first_unreachable' not in first_examples: labels.append('first_unreachable')
            else:
                counts['reachable'] += 1; histogram[exact] += 1
                require(row['status'] == 'reachable' and int(row['exact']) == exact, 'event-DAG optimum changed')
                portfolios = []
                for strategy in STRATEGIES:
                    costs = [path_cost(orders, priority, strategy)[0] for priority in priorities]
                    require(row[strategy + '_costs'] == ' '.join(map(str, costs)), 'baseline per-priority costs changed')
                    best = min(costs); portfolios.append(best)
                    require(int(row[strategy + '_portfolio']) == best and best >= exact, 'baseline portfolio changed')
                    counts[strategy + ('_tie' if best == exact else '_gap')] += 1
                union = min(portfolios); owner_stage = min(portfolios[:2])
                require(int(row['all_portfolio']) == union and int(row['owner_stage_portfolio']) == owner_stage,
                        'combined portfolio changed')
                counts['all' + ('_tie' if union == exact else '_gap')] += 1
                counts['owner_stage' + ('_tie' if owner_stage == exact else '_gap')] += 1
                vectors[(exact, *portfolios)] += 1
                if 'first_reachable' not in first_examples: labels.append('first_reachable')
                for name, value in [*zip(STRATEGIES, portfolios), ('owner_stage', owner_stage), ('all', union)]:
                    if value > exact and 'first_' + name + '_gap' not in first_examples:
                        labels.append('first_' + name + '_gap')
            if whole or identifier in fixed or labels:
                require(next_plan is not None, 'missing production witness')
                produced = json.loads(next_plan)
                selection = 'all_contexts' if whole else 'fixed_even_grid' if identifier in fixed else 'discovery_first_outcome'
                require(produced['context'] == identifier and produced['selection'] == selection,
                        'production selection changed')
                verify_production(produced, config, orders, channels, exact, endpoints)
                production_counts['checked'] += 1; production_counts[produced['status']] += 1
                production_counts[selection] += 1
                next_plan = next(production_rows, None)
            for label in labels: first_examples[label] = identifier
        require(counts['attempted'] == total and next_plan is None, 'context or production denominator incomplete')
    require(summary['counts'] == dict(sorted(counts.items())), 'domain outcome totals changed')
    require(summary['production_counts'] == dict(sorted(production_counts.items())), 'production totals changed')
    require(summary['optimal_phase_counts'] == {str(k): v for k, v in sorted(histogram.items())}, 'phase histogram changed')
    require(summary['cost_vectors'] == [{'exact_owner_stage_prepare_preparestage': list(k), 'contexts': v}
                                        for k, v in sorted(vectors.items())], 'cost vector totals changed')
    require(summary['retained_examples'] == list(first_examples), 'retained outcome witnesses changed')
    for name, identifier in first_examples.items():
        example = read(directory / (name + '.json'))
        require(example['context'] == identifier, 'outcome witness is not the declared first context')
        verify_example(example, config, choices, channels)
    return {'domain': config, 'contexts': total, 'reachable': counts['reachable'],
            'unreachable': counts['unreachable'], 'production_checked': production_counts['checked'],
            'examples': len(first_examples)}


def corruption_controls(directory, channels):
    results = []
    def rejects(name, operation):
        try: operation()
        except (ValueError, KeyError, TypeError, IndexError): results.append({'name': name, 'rejected': True})
        else: raise ValueError('corruption control accepted: ' + name)
    changed = deepcopy(channels); changed[0]['matrix'][0][0] ^= 1
    rejects('compatibility matrix cell', lambda: verify_channels(changed))
    changed_wire = deepcopy(channels); changed_wire[0]['wires'][0]['wire'] = '{"key":"changed"}'
    rejects('emitted wire semantic value', lambda: verify_channels(changed_wire))
    domain = 'two_owner'
    example = read(directory / domain / 'first_reachable.json')
    choices = [list(permutations(sorted(events))) for events in event_inventory(domain)]
    orders = order_at(choices, example['context']); exact, endpoints = independent_exact(domain, orders)
    altered_cost = deepcopy(example['production']); altered_cost['cost']['phases'] += 1
    rejects('production phase cost', lambda: verify_production(altered_cost, domain, orders, channels, exact, endpoints))
    altered_guard = deepcopy(example['production'])
    altered_guard['phases'][0]['box'] = {str(i): [[]] for i in range(len(orders))}
    rejects('unsafe positive phase guard', lambda: verify_production(altered_guard, domain, orders, channels, exact, endpoints))
    altered_step = deepcopy(example['production']); altered_step['phases'][0]['steps'][0][1] += 1
    rejects('skipped physical release', lambda: verify_production(altered_step, domain, orders, channels, exact, endpoints))
    altered_order = deepcopy(example); altered_order['orders'][0][0] = altered_order['orders'][0][1]
    rejects('duplicated prepare or emit event', lambda: verify_example(altered_order, domain, choices, channels))
    return results


def check(directory, controls=False):
    metadata = read(directory / 'metadata.json')
    require(metadata['domains'] and len(metadata['domains']) == len(set(metadata['domains']))
            and set(metadata['domains']) <= set(CONFIGS), 'domain selection changed')
    require(metadata['sources'] == list(SOURCES), 'captured source inventory changed')
    require(metadata['declared_finite_domains'] == ['two_owner', 'three_owner', 'three_owner_complete']
            and metadata['discovery_extension'] == 'three_owner_complete_extra'
            and metadata['queries_per_context'] == 1, 'study scope or query denominator changed')
    for name in metadata['sources']:
        require((directory / 'sources' / name).read_bytes() == (ROOT / name).read_bytes(),
                'captured executed source changed: ' + name)
    channels = read(directory / 'channel-observations.json')
    probe_summary = verify_channels(channels)
    require(probe_summary == read(directory / 'probe-summary.json'), 'probe denominator changed')
    rows = [verify_domain(directory / config, config, channels) for config in metadata['domains']]
    summary = read(directory / 'summary.json')
    require(summary['status'] == 'PASS' and summary['probe_summary'] == probe_summary,
            'overall probe summary changed')
    require(summary['domains'] == [read(directory / config / 'summary.json') for config in metadata['domains']],
            'overall domain summary differs')
    for field in ('attempted', 'reachable', 'unreachable', 'production_checked'):
        key = 'contexts' if field == 'attempted' else field
        require(summary[field] == sum(row[key] for row in rows), 'overall denominator changed: ' + field)
    result = {'status': 'PASS', 'scope': 'all retained event contexts; exact production coverage reported per domain',
              'probes': probe_summary, 'domains': rows,
              'contexts': sum(row['contexts'] for row in rows),
              'production_checked': sum(row['production_checked'] for row in rows),
              'independent_optimality': 'weighted-constraint relaxation and serial-event phase recurrence',
              'imports_production_or_producer': False}
    if controls: result['corruption_controls'] = corruption_controls(directory, channels)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    parser.add_argument('--corruption-controls', action='store_true')
    args = parser.parse_args()
    print(json.dumps(check(args.directory, args.corruption_controls), indent=2, sort_keys=True))
