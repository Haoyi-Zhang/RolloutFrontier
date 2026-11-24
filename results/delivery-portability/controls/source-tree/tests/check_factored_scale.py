"""Independently verify immutable alias scale inputs, witnesses, and timings.

No planner or producer imports are used. Small graph costs come from the full
global phase graph. Large graphs are checked through their complete local
relations, literal phase rectangles, positive guard corners and installation
paths. Their three-phase optimum also has an independent single-edge lower
bound from the full two-owner phase graph.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
from itertools import product
import json
import math
from pathlib import Path
import statistics

from tests.factored_planning_oracle import Oracle, canonical_terms, require


ROOT = Path(__file__).resolve().parents[1]
SOURCES = {'src/factored_planner.py', 'src/controller.py', 'src/envelope.py',
           'src/schema_contracts.py', 'tests/factored_scale_study.py',
           'tests/check_factored_scale.py', 'tests/factored_planning_oracle.py'}
COMPONENTS = ('input_cpu_ns', 'model_cpu_ns', 'recognition_cpu_ns',
              'query_other_cpu_ns', 'phase_other_cpu_ns', 'positive_guard_cpu_ns',
              'serialization_cpu_ns')
LIMITS = {'owners': 1024, 'factors': 4096, 'factor_placements': 4096,
          'total_factor_placements': 262144, 'closure_pairs': 4000000, 'steps': 8192}


def read(path):
    return json.loads(path.read_bytes())


def digest(data):
    return hashlib.sha256(data).hexdigest()


def probe_contract(probes):
    rows = [p for p in probes if p['family'] == 'enum-alias']
    require(len(rows) == 1, 'alias probe inventory')
    p = rows[0]
    require(p['programs'] == ['legacy', 'accepting', 'emitting', 'current'], 'alias program order')
    require(p['classes'] == ['old-name', 'new-name'] and
            p['emitted_classes'] == ['old-name', 'old-name', 'new-name', 'new-name'], 'alias class contract')
    wires = {w['id']: w for w in p['wires']}
    require(len(wires) == len(p['wires']) and wires, 'wire inventory')
    parses = {(r['consumer_rank'], r['wire_id']): r for r in p['parses']}
    require(len(parses) == len(p['parses']) and set(parses) == set(product(range(4), wires)),
            'parser-pair inventory')
    for w in wires.values():
        require(w['class'] == p['emitted_classes'][w['rank']], 'wire class changed')
    accepts = [[cls for cls in p['classes']
                if all(parses[i, w['id']]['accepted'] and
                       parses[i, w['id']].get('output') == w['input']
                       for w in wires.values() if w['class'] == cls)] for i in range(4)]
    require(all(any(w['class'] == cls for w in wires.values()) for cls in p['classes']),
            'empty wire class')
    require(accepts == p['accepted_classes'], 'acceptance classes differ from actual parser records')
    profiles = [sorted(['program:enum-alias:' + p['programs'][i], 'emit:' + p['emitted_classes'][i],
                        *('accept:' + cls for cls in accepts[i])]) for i in range(4)]
    require(p['profiles'] == profiles, 'physical profiles differ from measured contract')
    relation = [[int(p['emitted_classes'][i] in accepts[j]) for j in range(4)] for i in range(4)]
    require(p['relation'] == relation, 'probe relation differs from measured classes')
    require(relation == [[1, 1, 1, 0], [1, 1, 1, 0], [0, 1, 1, 1], [0, 1, 1, 1]],
            'three-phase alias relation changed')
    return p


def expected_edges(n, topology):
    if topology == 'single-edge':
        require(n == 2, 'single edge owner count')
        return {(0, 1)}
    if topology == 'complete-digraph':
        require(n == 3, 'complete digraph owner count')
        return {(i, j) for i, j in product(range(n), repeat=2) if i != j}
    if topology == 'ring':
        return {(i, j) for i, j in product(range(n), repeat=2) if (j - i) % n == 1}
    require(topology == 'circulant-four', 'unknown graph topology')
    return {(i, j) for i in range(n) for j in ((i + 1) % n, (i + 2) % n,
                                             (i + 3) % n, (i + 4) % n) if i != j}


def branches(factor):
    return {tuple((n, tuple(sorted(required))) for n, required in sorted(b.items()))
            for b in factor['branches']}


def check_input(data, probe, topology, size):
    require(data['name'] == f'{topology}-{size}' and data['family'] == 'enum-alias' and
            data['topology'] == topology and data['owners'] == size, 'input condition identity')
    edges = expected_edges(size, topology)
    observed = [tuple(e) for e in data['edges']]
    require(len(observed) == len(edges) and set(observed) == edges, 'graph edges changed')
    nodes = {str(i) for i in range(size)}
    require(set(data['catalog']) == nodes and
            all(v == probe['profiles'] for v in data['catalog'].values()), 'physical catalog changed')
    expected_transitions = [{'source': probe['profiles'][i], 'target': probe['profiles'][i + 1]}
                            for i in range(3)]
    require(set(data['transitions']) == nodes and
            all(v == expected_transitions for v in data['transitions'].values()), 'chain edges changed')
    require(data['initial'] == {n: probe['profiles'][0] for n in nodes} and
            data['target'] == {n: probe['profiles'][3] for n in nodes}, 'full goal changed')
    factors = {f['id']: f for f in data['factors']}
    require(len(factors) == len(edges) == len(data['factors']) and
            set(factors) == {f'edge-{i}-{j}' for i, j in edges}, 'factor inventory changed')
    for i, j in edges:
        actual = factors[f'edge-{i}-{j}']
        expected = {'branches': [{str(i): ['emit:' + cls], str(j): ['accept:' + cls]}
                                 for cls in probe['classes']]}
        require(branches(actual) == branches(expected), 'factor differs from measured wire contract')
    return Oracle(data['factors'], data['catalog'], data['transitions'])


def check_large_plan(data, plan, oracle):
    n, m = data['owners'], len(data['factors'])
    require(plan['schema'] == 'factored-chain-plan' and plan['status'] == 'planned',
            'scale condition did not produce an executable plan')
    require(plan['initial'] == data['initial'] and plan['target'] == data['target'], 'plan endpoints')
    require(plan['catalog'] == data['catalog'] and plan['transitions'] == data['transitions'],
            'plan physical model differs from input')
    expected_factors = {f['id']: branches(f) for f in data['factors']}
    require(len(plan['factors']) == m and
            {f['id']: branches(f) for f in plan['factors']} == expected_factors, 'plan factor model changed')
    require(plan['budgets'] == LIMITS, 'default work contracts were changed')
    require(plan['objective'] == ['fewest guard phases', 'fewest installations'], 'plan objective')
    require(plan['cost'] == {'phases': 3, 'installations': 3 * n, 'handoffs': 2}, 'known optimal scale cost')
    require(plan['search']['rank_iterates'] == [[r] * n for r in range(4)], 'known synchronized endpoints')
    require(len(plan['phases']) == 3, 'phase inventory')
    oracle.check_recognition(plan['recognition'])
    corners_checked = 0
    for r, phase in enumerate(plan['phases']):
        source, target = (r,) * n, (r + 1,) * n
        require(phase['source'] == oracle.external(source) and phase['target'] == oracle.external(target),
                'phase full endpoints')
        box = phase['box']
        require(set(box) == set(oracle.nodes) and
                all(terms == canonical_terms(terms) for terms in box.values()), 'canonical global owner guards')
        expected_paths = {owner: [list(oracle.profiles[owner][r]), list(oracle.profiles[owner][r + 1])]
                          for owner in oracle.nodes}
        require(phase['local_paths'] == expected_paths, 'local physical path differs')
        for owner, path in expected_paths.items():
            require(all(any(set(term) <= set(profile) for term in box[owner]) for profile in path),
                    'guard does not authorize complete physical path')
        checks = []
        for factor in sorted(data['factors'], key=lambda f: f['id']):
            scope = oracle.shapes[factor['id']][0]
            require(all(oracle.factor_truth(factor, local)
                        for local in product(range(r, r + 2), repeat=len(scope))),
                    'literal phase rectangle contains incompatible catalog placement')
            terms = {}
            for owner in scope:
                relevant = {atom for branch in factor['branches'] for atom in branch[owner]}
                terms[owner] = canonical_terms([sorted(set(term) & relevant) for term in box[owner]])
            corners = list(product(*(terms[owner] for owner in scope)))
            for corner in corners:
                supports = dict(zip(scope, map(set, corner)))
                require(any(all(set(required) <= supports[owner] for owner, required in branch.items())
                            for branch in factor['branches']), 'positive guard corner is unsafe')
            checks.append({'id': factor['id'], 'corners': len(corners)})
            corners_checked += len(corners)
        require(phase['factor_checks'] == checks, 'positive guard evidence differs')
        steps = phase['steps']
        require(len(steps) == n and {step['node'] for step in steps} == set(oracle.nodes),
                'missing or repeated physical installation')
        require(all(set(step) == {'node', 'support'} and
                    step['support'] == list(oracle.profiles[step['node']][r + 1]) for step in steps),
                'installation differs from physical chain edge')
    return {'owners': n, 'factors': m, 'phases': 3, 'installations': 3 * n,
            'local_catalog_cells': 16 * m, 'join_pairs': 78 * m,
            'positive_guard_corners': corners_checked}


def prepared(directory):
    environment, inventory = read(directory / 'environment.json'), read(directory / 'inventory.json')
    require(set(environment['sources']) == SOURCES, 'source inventory differs')
    for name, expected in environment['sources'].items():
        require(digest((ROOT / name).read_bytes()) == expected and
                digest((directory / 'sources' / name).read_bytes()) == expected, 'source differs: ' + name)
    probe_bytes = (directory / 'probes.json').read_bytes()
    require(environment['probe_source'] == 'results/schema-census/probes.json' and
            probe_bytes == (ROOT / environment['probe_source']).read_bytes() and
            digest(probe_bytes) == environment['probe_sha256'], 'actual probe source binding changed')
    probe = probe_contract(json.loads(probe_bytes))
    specs = [(topology, n) for n in (8, 32, 128, 512, 1024) for topology in ('ring', 'circulant-four')]
    controls = [('single-edge', 2), ('ring', 3), ('complete-digraph', 3)]
    require([e['name'] for e in inventory['conditions']] == [f'{t}-{n}' for t, n in specs],
            'scale condition inventory')
    require([e['name'] for e in inventory['controls']] == [f'{t}-{n}' for t, n in controls],
            'small control inventory')
    names = [e['name'] for e in inventory['conditions']]
    require(inventory['rounds'] == 5 and inventory['order'] == [
        {'round': r, 'position': p, 'condition': names[(p + r) % 10]}
        for r in range(5) for p in range(10)], 'fresh worker rotation schedule')
    require(environment['target_cpu_ns'] == 100_000_000 and environment['max_cohorts'] == 256 and
            environment['cpu_budget_seconds'] == 30 and environment['components'] == list(COMPONENTS),
            'timing work contracts changed')
    evidence, examples = [], {}
    for prefix, entries, expected in [('controls', inventory['controls'], controls),
                                       ('conditions', inventory['conditions'], specs)]:
        for row, (topology, size) in zip(entries, expected):
            base = directory / prefix / row['name']
            raw, witness = (base / 'input.json').read_bytes(), (base / 'witness.json').read_bytes()
            require(digest(raw) == row['input_sha256'] and len(raw) == row['input_bytes'] and
                    digest(witness) == row['output_sha256'] and len(witness) == row['output_bytes'],
                    'immutable input or witness bytes changed')
            data, plan = json.loads(raw), json.loads(witness)
            require(row['topology'] == topology and row['owners'] == size and
                    row['factors'] == len(expected_edges(size, topology)) and row['status'] == plan['status'],
                    'condition metadata differs')
            oracle = check_input(data, probe, topology, size)
            if prefix == 'controls':
                oracle.check_recognition(plan['recognition'])
                oracle.check_plan(plan, (0,) * size, (3,) * size)
                require(plan['cost']['phases'] == 3, 'independent lower-bound control changed')
                evidence.append({'name': row['name'], 'global_catalog_cells': 4 ** size,
                                 'cost': plan['cost']})
            else:
                evidence.append(dict(name=row['name'], **check_large_plan(data, plan, oracle)))
                examples[row['name']] = (data, plan, oracle)
    return inventory, evidence, examples


def check_worker(summary, rows, item, entry):
    require(summary['condition'] == item['condition'] and summary['round'] == item['round'] and
            summary['position'] == item['position'], 'worker schedule identity')
    require(type(summary['pid']) is int and summary['pid'] > 0 and summary['python_hash_seed'] == '0',
            'fresh worker environment')
    require(type(summary['maximum_rss_kib']) is int and summary['maximum_rss_kib'] > 0,
            'worker peak RSS')
    require(1 <= len(rows) <= 256 and summary['cohorts'] == len(rows), 'cohort inventory')
    for row in rows:
        require(set(row['components']) == set(COMPONENTS) and
                all(type(v) is int and v >= 0 for v in row['components'].values()), 'component time values')
        require(type(row['total_cpu_ns']) is int and row['total_cpu_ns'] >= 0 and
                row['total_cpu_ns'] == sum(row['components'].values()), 'component times do not sum to total')
        require(type(row['wall_ns']) is int and row['wall_ns'] > 0, 'wall timer')
        require(row['model_calls'] == 1 and row['phase_calls'] == 3 and row['guard_calls'] == 3,
                'measured stage inventory differs')
        require(row['input_sha256'] == entry['input_sha256'] and row['output_sha256'] == entry['output_sha256'] and
                row['output_bytes'] == entry['output_bytes'] and row['status'] == 'planned', 'measured witness differs')
    total = sum(r['total_cpu_ns'] for r in rows)
    require(total >= 100_000_000 and total - rows[-1]['total_cpu_ns'] < 100_000_000,
            'cohort stop condition differs')
    require(summary['charged_cpu_ns'] == total and
            summary['zero_cpu_cohorts'] == sum(r['total_cpu_ns'] == 0 for r in rows) and
            summary['mean_total_cpu_ns'] == statistics.mean(r['total_cpu_ns'] for r in rows) and
            summary['mean_wall_ns'] == statistics.mean(r['wall_ns'] for r in rows), 'worker aggregate differs')
    require(summary['mean_components'] == {key: statistics.mean(r['components'][key] for r in rows)
                                          for key in COMPONENTS}, 'worker component aggregate differs')
    require(summary['status'] == 'planned' and summary['output_sha256'] == entry['output_sha256'],
            'worker output binding differs')


def aggregate(inventory, workers):
    result = []
    def spread(values):
        values = list(values)
        require(all(math.isfinite(x) and x >= 0 for x in values), 'invalid aggregate measurement')
        return {'median': statistics.median(values), 'min': min(values), 'max': max(values)}
    for entry in inventory['conditions']:
        selected = [w for w in workers if w['condition'] == entry['name']]
        require(len(selected) == 5, 'fresh worker count')
        result.append({'name': entry['name'], 'owners': entry['owners'], 'factors': entry['factors'],
            'status': entry['status'], 'workers': len(selected),
            'zero_cpu_cohorts': sum(w['zero_cpu_cohorts'] for w in selected),
            'cpu_ms': spread(w['mean_total_cpu_ns'] / 1e6 for w in selected),
            'wall_ms': spread(w['mean_wall_ns'] / 1e6 for w in selected),
            'component_cpu_ms': {key.removesuffix('_cpu_ns'): spread(w['mean_components'][key] / 1e6
                                   for w in selected) for key in COMPONENTS},
            'maximum_rss_kib': spread(w['maximum_rss_kib'] for w in selected),
            'input_bytes': entry['input_bytes'], 'output_bytes': entry['output_bytes']})
    return {'status': 'complete', 'conditions': result, 'workers': len(workers),
            'cohorts': sum(w['cohorts'] for w in workers),
            'zero_cpu_cohorts': sum(w['zero_cpu_cohorts'] for w in workers),
            'statistic': 'median and full range of five fresh-worker cohort means'}


def controls(examples, worker_example=None):
    results = []
    def reject(name, action):
        try:
            action()
        except (ValueError, KeyError, IndexError, TypeError):
            results.append({'name': name, 'rejected': True})
        else:
            raise ValueError('corruption escaped: ' + name)
    data, plan, oracle = examples['ring-8']
    bad = deepcopy(plan); bad['cost']['phases'] = 2
    reject('changed exact optimum', lambda: check_large_plan(data, bad, oracle))
    bad = deepcopy(plan); bad['search']['rank_iterates'][1][0] = 2
    reject('changed synchronized endpoint', lambda: check_large_plan(data, bad, oracle))
    bad = deepcopy(plan); bad['phases'][0]['steps'].pop()
    reject('missing owner installation', lambda: check_large_plan(data, bad, oracle))
    bad = deepcopy(plan); bad['phases'][0]['box']['0'] = [[]]
    reject('unsafe positive owner guard', lambda: check_large_plan(data, bad, oracle))
    bad = deepcopy(plan); bad['recognition']['factors'][0]['axis_limits'][0]['upper'][0] = 3
    reject('changed local axis certificate', lambda: check_large_plan(data, bad, oracle))
    if worker_example is not None:
        summary, rows, item, entry = worker_example
        bad = deepcopy(rows); bad[0]['components']['model_cpu_ns'] += 1
        reject('component time total mismatch', lambda: check_worker(summary, bad, item, entry))
        bad = deepcopy(rows); bad[0]['output_sha256'] = 'changed'
        reject('measured witness binding mismatch', lambda: check_worker(summary, bad, item, entry))
    return results


def check(directory, prepared_only=False, corruption_controls=False):
    inventory, evidence, examples = prepared(directory)
    result = {'status': 'prepared-pass' if prepared_only else 'pass', 'semantic_evidence': evidence,
              'optimality': 'three-phase literal witnesses plus full-graph single-edge lower bound'}
    worker_example = None
    if not prepared_only:
        entries = {e['name']: e for e in inventory['conditions']}
        workers = []
        for item in inventory['order']:
            base = directory / 'workers' / f"round-{item['round']}" / item['condition']
            summary = read(base / 'summary.json')
            rows = [json.loads(line) for line in (base / 'cohorts.jsonl').read_text().splitlines()]
            check_worker(summary, rows, item, entries[item['condition']])
            workers.append(summary)
            if worker_example is None:
                worker_example = (summary, rows, item, entries[item['condition']])
        require(len({w['pid'] for w in workers}) == 50, 'worker process identity reused')
        expected = aggregate(inventory, workers)
        require(read(directory / 'summary.json') == expected, 'saved scale aggregates differ')
        result['measurements'] = expected
    if corruption_controls:
        result['corruption_controls'] = controls(examples, worker_example)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', required=True, type=Path)
    parser.add_argument('--prepared', action='store_true')
    parser.add_argument('--corruption-controls', action='store_true')
    args = parser.parse_args()
    print(json.dumps(check(args.results, args.prepared, args.corruption_controls), sort_keys=True, indent=2))
