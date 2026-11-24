"""Independent saved-data checker for alternative-reader planning evidence.

No producer, planner, codec helper, or runtime module is imported. Serialized
descriptor fields and actual JSON records are decoded with the standard
library. The existing independent phase oracle checks every execution witness;
synchronous OR relaxation and selected-edge relaxation reconstruct the exact
event comparisons from the registered local orders.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import csv
import gzip
import hashlib
from itertools import product
import json
from pathlib import Path

from tests.factored_planning_oracle import Oracle, require


ROOT = Path(__file__).resolve().parents[1]
SOURCES = {'src/factored_planner.py', 'src/heterogeneous_contracts.py',
           'src/controller.py', 'src/envelope.py',
           'tests/alternate_reader_study.py', 'tests/alternate_reader_check.py',
           'tests/factored_planning_oracle.py'}
SAMPLES = (('alpha', 'present'), ('κλειδί', 'migrated-δ'), ('中文', '扩展字段'),
           ('quoted"key', 'line\nbreak\\path'), ('emoji-λ', 'field-🙂'))


def read(path):
    return json.loads(path.read_text())


def wire_fields(data):
    cursor = 0

    def varint():
        nonlocal cursor
        value, shift = 0, 0
        while cursor < len(data) and shift <= 63:
            byte = data[cursor]
            cursor += 1
            value |= (byte & 127) << shift
            if byte < 128:
                return value
            shift += 7
        raise ValueError('invalid descriptor varint')

    fields = []
    while cursor < len(data):
        tag = varint()
        number, kind = tag >> 3, tag & 7
        if kind == 0:
            value = varint()
        elif kind == 2:
            size = varint()
            value = data[cursor:cursor + size]
            require(len(value) == size, 'truncated descriptor field')
            cursor += size
        else:
            raise ValueError('unexpected descriptor wire type')
        fields.append((number, value))
    return fields


def check_probe(probe):
    require(probe['sender'] == 0 and probe['receiver'] == 1 and probe['fields'] == ['choice'],
            'single-field codec identity differs')
    require(probe['subsets'] == [[], ['choice']] and
            probe['matrix_axes'] == ['prepared_subset', 'emitted_subset'], 'codec axes differ')
    require(len(probe['descriptors']) == 2, 'descriptor inventory differs')
    for ready, item in enumerate(probe['descriptors']):
        require(item['prepared_fields'] == (['choice'] if ready else []), 'descriptor identity')
        top = wire_fields(bytes.fromhex(item['serialized_hex']))
        require([n for n, _ in top] == [1, 2, 4, 12], 'descriptor top-level fields')
        require(dict(top)[1] == b'event_channel.proto' and dict(top)[2] == b'events'
                and dict(top)[12] == b'proto3', 'descriptor schema identity')
        message = wire_fields(dict(top)[4])
        require(message[0] == (1, b'Record') and all(n == 2 for n, _ in message[1:]),
                'descriptor message inventory')
        expected = [('key', 1)] + ([('tag_choice', 2)] if ready else [])
        observed = []
        for _, data in message[1:]:
            field = wire_fields(data)
            require([n for n, _ in field] == [1, 3, 4, 5], 'descriptor field attributes')
            values = dict(field)
            require(values[4] == 1 and values[5] == 9, 'descriptor string field type')
            observed.append((values[1].decode('utf-8'), values[3]))
        require(observed == expected, 'descriptor field preparation differs')
    require(len(probe['wires']) == 10 and len(probe['parses']) == 20, 'codec observation inventory')
    for i, wire in enumerate(probe['wires']):
        emitted, sample = divmod(i, 5)
        key, value = SAMPLES[sample]
        semantic = {'key': key, 'choice': 'choice:' + value if emitted else ''}
        payload = {'key': key}
        if emitted:
            payload['tagChoice'] = semantic['choice']
        require(wire['id'] == str(i) and wire['sample'] == sample and
                wire['emitted_fields'] == (['choice'] if emitted else []), 'wire identity')
        require(json.loads(wire['wire']) == payload and wire['semantic'] == semantic,
                'wire payload or semantic values differ')
    matrix = []
    for ready in range(2):
        row = []
        for emitted in range(2):
            observations = []
            for sample in range(5):
                wire_id = emitted * 5 + sample
                wire = probe['wires'][wire_id]
                item = probe['parses'][ready * 10 + wire_id]
                success = bool(ready or not emitted)
                require(item['prepared_fields'] == (['choice'] if ready else []) and
                        item['wire_id'] == str(wire_id), 'parse identity')
                require(item['accepted'] is success, 'parse acceptance differs')
                if success:
                    require(item['semantic_equal'] is True and item['decoded'] == wire['semantic'],
                            'accepted record lost application values')
                else:
                    require(item['error_type'] == 'ParseError' and isinstance(item['error'], str)
                            and item['error'], 'missing strict-parser rejection')
                observations.append(success)
            row.append(int(all(observations)))
        matrix.append(row)
    require(probe['matrix'] == matrix == [[1, 0], [1, 1]], 'measured relation differs')
    require(len(probe['event_effect_witnesses']) == 1, 'event witness inventory')
    witness = probe['event_effect_witnesses'][0]
    require(witness['feature'] == 'choice' and witness['before_subset'] == [] and
            witness['after_subset'] == ['choice'], 'event identity')
    require(json.loads(witness['before_emit_wire']) == json.loads(probe['wires'][0]['wire']) and
            json.loads(witness['after_emit_wire']) == json.loads(probe['wires'][5]['wire']) and
            json.loads(witness['prepare_witness_wire']) == json.loads(probe['wires'][5]['wire']),
            'event witness payload differs')
    require(witness['before_emit_wire'] != witness['after_emit_wire'] and
            witness['reader_before_rejects'] is True and
            witness['reader_after_preserves_semantics'] is True, 'event has no observed effect')
    return matrix


def expected_specs():
    return [(f'{mask}-' + '-'.join(''.join(o) for o in orders), mask, orders)
            for mask in range(1, 8) for orders in product((('p', 'e'), ('e', 'p')), repeat=3)]


def check_context(context, spec, matrix):
    identity, mask, orders = spec
    require(context['id'] == identity and context['mask'] == mask and
            context['orders'] == [list(o) for o in orders], 'context identity differs')
    producers = [i for i in range(3) if mask & (1 << i)]
    require(context['producers'] == producers, 'producer set differs')
    catalog = {}
    for owner, order in enumerate(orders):
        profiles = []
        for rank in range(3):
            emitted = int('e' in order[:rank])
            prepared = int('p' in order[:rank])
            support = [f'program:e{emitted}p{prepared}', 'accept:old',
                       'emit:new' if emitted else 'emit:old']
            if prepared:
                support.append('accept:new')
            profiles.append(sorted(support))
        catalog[str(owner)] = profiles
    transitions = {owner: [{'source': profiles[i], 'target': profiles[i + 1]} for i in range(2)]
                   for owner, profiles in catalog.items()}
    factors = []
    for producer in producers:
        branches = []
        for receiver in range(3):
            if receiver == producer:
                continue
            for message in ('old', 'new'):
                branch = {str(i): [] for i in range(3)}
                branch[str(producer)] = ['emit:' + message]
                branch[str(receiver)] = ['accept:' + message]
                branches.append(branch)
        factors.append({'id': 'choice-' + str(producer), 'branches': branches})
    require(context['catalog'] == catalog and context['transitions'] == transitions and
            context['factors'] == factors, 'physical model or reader choices differ')
    relation = set()
    for state in product(range(3), repeat=3):
        emitted = ['e' in orders[i][:state[i]] for i in range(3)]
        prepared = ['p' in orders[i][:state[i]] for i in range(3)]
        if all(any(matrix[int(prepared[r])][int(emitted[p])] for r in range(3) if r != p)
               for p in producers):
            relation.add(state)
    require(context['allowed'] == [list(s) for s in sorted(relation)], 'codec-derived relation differs')
    require(context['checked_ordered_joins'] == len(relation) ** 2, 'closure denominator')
    witness = None
    for a, b in product(sorted(relation), repeat=2):
        require(tuple(max(x, y) for x, y in zip(a, b)) in relation, 'relation is not max closed')
        minimum = tuple(min(x, y) for x, y in zip(a, b))
        if witness is None and minimum not in relation:
            witness = {'first': list(a), 'second': list(b), 'minimum': list(minimum)}
    require(witness is not None and context['not_min_closed_witness'] == witness,
            'missing or incorrect non-min-closure witness')
    oracle = Oracle(factors, catalog, transitions)
    require(set(oracle.graph()) == relation, 'independent factor relation differs')
    oracle.check_recognition(context['recognition'])
    return oracle


def event_constraints(context, source, target):
    if any(a > b for a, b in zip(source, target)):
        return None
    events = [(owner, rank) for owner in range(3)
              for rank in range(source[owner] + 1, target[owner] + 1)]
    index = {event: i for i, event in enumerate(events)}
    local = [(index[(owner, rank - 1)], i) for i, (owner, rank) in enumerate(events)
             if (owner, rank - 1) in index]
    clauses = []
    for i, (owner, rank) in enumerate(events):
        if owner not in context['producers'] or context['orders'][owner][rank - 1] != 'e':
            continue
        options = []
        for reader in range(3):
            if reader == owner:
                continue
            ready = context['orders'][reader].index('p') + 1
            options.append(-1 if source[reader] >= ready else index.get((reader, ready), -2))
        clauses.append((i, options))
    return events, local, clauses


def exact_events(context, source, target):
    constraints = event_constraints(context, source, target)
    if constraints is None:
        return None, None, 0
    events, local, clauses = constraints
    size = len(events)
    if not size:
        return 0, [], 1
    infinity = size + 1
    labels = [1] * size
    for _ in range(size * size + 1):
        following = [1] * size
        for before, after in local:
            following[after] = max(following[after], labels[before])
        for after, options in clauses:
            earliest = min(0 if p == -1 else infinity if p == -2 else labels[p] for p in options)
            following[after] = max(following[after], min(infinity, earliest + 1))
        require(all(a <= b for a, b in zip(labels, following)), 'nonmonotone event recurrence')
        if following == labels:
            break
        labels = following
    else:
        raise ValueError('event recurrence exceeded its finite-height bound')
    optimum = None if infinity in labels else max(labels)
    selected_best = None
    choices_checked = 0
    for selected in product(*(options for _, options in clauses)):
        choices_checked += 1
        if -2 in selected:
            continue
        edges = [(a, b, 0) for a, b in local]
        edges.extend((p, after, 1) for (after, _), p in zip(clauses, selected) if p != -1)
        rounds = [1] * size
        for _ in range(size):
            following = list(rounds)
            for before, after, weight in edges:
                following[after] = max(following[after], rounds[before] + weight)
            if following == rounds:
                cost = max(rounds)
                selected_best = cost if selected_best is None else min(selected_best, cost)
                break
            rounds = following
    require(selected_best == optimum, 'OR and selected-reader event optima differ')
    return optimum, [[owner, rank, labels[i]] for i, (owner, rank) in enumerate(events)], choices_checked


def check_row(row, context, oracle):
    source, target = tuple(row['source']), tuple(row['target'])
    oracle.check_plan(row['answer'], source, target)
    optimum, labels, choices = exact_events(context, source, target)
    cost = oracle.cost(source, target)
    require(optimum == (None if cost is None else cost['phases']),
            'event result differs from literal safe-rectangle graph')
    expected = {'literal_phases': optimum, 'or_fixed_point_phases': optimum,
                'or_event_rounds': labels, 'best_chosen_dag_phases': optimum,
                'chosen_graphs_checked': choices}
    require(row['comparisons'] == expected, 'captured exact comparison or event witness differs')
    return optimum, choices


def check_inventory(contexts, rows, oracles):
    expected = {(c['id'], a, b) for c in contexts
                for a, b in product(oracles[c['id']].graph(), repeat=2)}
    actual = [(row['context'], tuple(row['source']), tuple(row['target'])) for row in rows]
    require(len(actual) == len(set(actual)) and set(actual) == expected,
            'complete compatible endpoint inventory differs')


def reconstruct(contexts, rows, matrix):
    specs = expected_specs()
    require(len(contexts) == len(specs), 'complete context count differs')
    oracles = {context['id']: check_context(context, spec, matrix)
               for context, spec in zip(contexts, specs)}
    check_inventory(contexts, rows, oracles)
    by_id = {c['id']: c for c in contexts}
    counts = {c['id']: Counter() for c in contexts}
    full, phase_counts = {}, Counter()
    for row in rows:
        identity = row['context']
        optimum, choices = check_row(row, by_id[identity], oracles[identity])
        current = counts[identity]
        current['queries'] += 1
        current['chosen_graphs'] += choices
        current['unreachable' if optimum is None else 'noops' if optimum == 0 else 'reachable_changes'] += 1
        forward = all(a <= b for a, b in zip(row['source'], row['target']))
        current['forward_queries' if forward else 'direction_refusals'] += 1
        if forward:
            phase_counts['unreachable' if optimum is None else str(optimum)] += 1
            if optimum is None:
                current['forward_obstructions'] += 1
        if row['source'] == [0, 0, 0] and row['target'] == [2, 2, 2]:
            full[identity] = {key: row['answer'][key] for key in ('status', 'cost')}
            full[identity]['rank_iterates'] = row['answer']['search']['rank_iterates']
    totals = sum(counts.values(), Counter())
    catalogs = [{'id': c['id'], 'compatible_states': len(oracles[c['id']].graph()),
                 'phase_edges': sum(map(len, oracles[c['id']].graph().values())),
                 'not_min_closed_witness': c['not_min_closed_witness'],
                 'full_migration': full[c['id']], **dict(counts[c['id']])} for c in contexts]
    summary = {'status': 'PASS', 'contexts': len(contexts), 'every_context_max_closed': True,
               'contexts_not_min_closed': len(contexts), 'actual_parser_matrix_calls': 20,
               'actual_emitted_wire_records': 10, 'additional_parser_event_witness_calls': 2,
               'actual_emitter_calls': 13, 'all_compatible_source_target_pairs_covered': True,
               'planning_compared_to_actual_codec_derived_relations': True,
               'production_planner_queries': len(rows),
               'or_fixed_point_equals_literal_and_best_selected_dag': True,
               'forward_phase_counts': dict(phase_counts),
               'full_migrations': dict(Counter('unreachable' if v['cost'] is None else
                                               str(v['cost']['phases']) + ' phases' for v in full.values())),
               'counts': dict(totals), 'catalogs': catalogs}
    return summary, oracles


def check_csv(path, rows):
    with path.open(newline='') as handle:
        actual = list(csv.DictReader(handle))
    expected = []
    for row in rows:
        phases = row['comparisons']['literal_phases']
        cost = row['answer']['cost']
        text = '' if phases is None else str(phases)
        expected.append({'context': row['context'], 'source': ''.join(map(str, row['source'])),
                         'target': ''.join(map(str, row['target'])), 'literal_phases': text,
                         'or_fixed_point_phases': text, 'best_chosen_dag_phases': text,
                         'production_status': row['answer']['status'], 'production_phases': text,
                         'production_installations': '' if cost is None else str(cost['installations']),
                         'chosen_graphs_checked': str(row['comparisons']['chosen_graphs_checked']),
                         'forward': str(int(all(a <= b for a, b in zip(row['source'], row['target']))))})
    require(actual == expected, 'CSV and complete plan records differ')


def corruption_controls(probe, contexts, rows, oracles):
    result = []

    def rejects(name, function):
        try:
            function()
        except (ValueError, KeyError, IndexError, TypeError):
            result.append({'name': name, 'rejected': True})
        else:
            raise ValueError('corruption control was accepted: ' + name)

    bad = deepcopy(probe)
    bad['parses'][5]['accepted'] = True
    rejects('old parser falsely accepts new field', lambda: check_probe(bad))
    bad = deepcopy(probe)
    bad['wires'][5]['semantic']['choice'] = ''
    rejects('new field loses application value', lambda: check_probe(bad))
    bad = deepcopy(probe)
    bad['descriptors'][1]['serialized_hex'] = bad['descriptors'][0]['serialized_hex']
    rejects('prepared descriptor is unchanged', lambda: check_probe(bad))
    bad = deepcopy(contexts[0])
    bad['factors'][0]['branches'].pop()
    rejects('removed alternative reader', lambda: check_context(bad, expected_specs()[0], probe['matrix']))
    bad = deepcopy(contexts[0])
    bad['not_min_closed_witness']['minimum'] = bad['not_min_closed_witness']['first']
    rejects('false non-min-closure witness', lambda: check_context(bad, expected_specs()[0], probe['matrix']))
    by_id = {c['id']: c for c in contexts}
    base = next(r for r in rows if r['answer']['phases'])

    def row_control(name, change):
        altered = deepcopy(base)
        change(altered)
        rejects(name, lambda: check_row(altered, by_id[altered['context']], oracles[altered['context']]))

    row_control('changed exact optimum', lambda r: r['answer']['cost'].__setitem__('phases', 99))
    row_control('missing physical installation', lambda r: r['answer']['phases'][0]['steps'].pop())
    row_control('unsafe positive guard', lambda r: r['answer']['phases'][0].__setitem__(
        'box', {str(i): [[]] for i in range(3)}))
    row_control('changed OR-round witness', lambda r: r['comparisons']['or_event_rounds'][0].__setitem__(2, 99))
    row_control('changed selected-reader optimum', lambda r: r['comparisons'].__setitem__('best_chosen_dag_phases', 99))
    obstruction = next(r for r in rows if r['answer']['status'] == 'unreachable' and
                       all(a <= b for a, b in zip(r['source'], r['target'])))
    bad = deepcopy(obstruction)
    bad['answer']['status'] = 'planned'
    rejects('forward deadlock marked reachable', lambda: check_row(
        bad, by_id[bad['context']], oracles[bad['context']]))
    rejects('missing endpoint query', lambda: check_inventory(contexts, rows[1:], oracles))
    rejects('duplicated endpoint query', lambda: check_inventory(contexts, rows + rows[:1], oracles))
    return result


def check(directory, controls=False):
    metadata = read(directory / 'metadata.json')
    require(set(metadata['sources']) == SOURCES and metadata['sources_unchanged'] is True,
            'source inventory differs')
    require(metadata['inventory'] == {'physical_owners': 3, 'events_per_owner': 2,
                                      'producer_sets': 7, 'local_event_orders': 8,
                                      'all_compatible_ordered_endpoints': True}, 'registered study inventory')
    for name, digest in metadata['sources'].items():
        for path in (ROOT / name, directory / 'sources' / name):
            require(hashlib.sha256(path.read_bytes()).hexdigest() == digest, 'source binding differs: ' + name)
    probe = read(directory / 'actual-channel-probe.json')
    matrix = check_probe(probe)
    contexts = read(directory / 'contexts.json')
    with gzip.open(directory / 'plans.jsonl.gz', 'rt', encoding='utf-8') as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    summary, oracles = reconstruct(contexts, rows, matrix)
    require(summary == read(directory / 'summary.json'), 'saved summary differs from reconstruction')
    check_csv(directory / 'queries.csv', rows)
    if controls:
        summary['corruption_controls'] = corruption_controls(probe, contexts, rows, oracles)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--corruption-controls', action='store_true')
    args = parser.parse_args()
    report = check(args.results, args.corruption_controls)
    print(json.dumps({k: v for k, v in report.items() if k != 'catalogs'}, sort_keys=True, indent=2))
