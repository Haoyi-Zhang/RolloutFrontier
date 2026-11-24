"""Cold-worker scaling of the measured alias contract on overlapping graphs.

Preparation records immutable inputs and untimed full witnesses. Measurement
is a separate explicit command so other campaigns can finish before the timed
window. Every measured cohort rereads and parses its input, builds a fresh
planner, recognizes every local factor, plans the full goal, checks all positive
guard products, and serializes the returned witness.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import platform
import resource
import statistics
import subprocess
import sys
import time

import src.factored_planner as implementation


ROOT = Path(__file__).resolve().parents[1]
SIZES = (8, 32, 128, 512, 1024)
ROUNDS = 5
TARGET_CPU_NS = 100_000_000
MAX_COHORTS = 256
CPU_BUDGET_SECONDS = 30
PROBE_SOURCE = 'results/schema-census/probes.json'
SOURCES = ('src/factored_planner.py', 'src/controller.py', 'src/envelope.py',
           'src/schema_contracts.py', 'tests/factored_scale_study.py',
           'tests/check_factored_scale.py', 'tests/factored_planning_oracle.py')
COMPONENTS = ('input_cpu_ns', 'model_cpu_ns', 'recognition_cpu_ns',
              'query_other_cpu_ns', 'phase_other_cpu_ns', 'positive_guard_cpu_ns',
              'serialization_cpu_ns')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded(value) + b'\n')


def read(path):
    return json.loads(path.read_bytes())


def graph(size, topology):
    if topology == 'single-edge':
        require(size == 2, 'single-edge control has two owners')
        return [(0, 1)]
    if topology == 'ring':
        return [(i, (i + 1) % size) for i in range(size)]
    if topology == 'complete-digraph':
        require(size == 3, 'complete-digraph control has three owners')
        return [(i, j) for i in range(size) for j in range(size) if i != j]
    require(topology == 'circulant-four', 'unknown topology')
    # Set construction also makes the intended simple graph explicit.
    return sorted({(i, (i + step) % size) for i in range(size) for step in (1, 2, 3, 4)
                   if i != (i + step) % size})


def instance(probe, size, topology):
    edges = graph(size, topology)
    profiles = probe['profiles']
    catalog = {str(i): deepcopy(profiles) for i in range(size)}
    factors = [{'id': f'edge-{i}-{j}', 'branches': [
        {str(i): ['emit:' + cls], str(j): ['accept:' + cls]}
        for cls in probe['classes']]} for i, j in edges]
    transitions = {n: [{'source': p[r], 'target': p[r + 1]} for r in range(len(p) - 1)]
                   for n, p in catalog.items()}
    return {'name': f'{topology}-{size}', 'family': 'enum-alias', 'topology': topology,
            'owners': size, 'edges': [list(e) for e in edges], 'factors': factors,
            'catalog': catalog, 'transitions': transitions,
            'initial': {n: p[0] for n, p in catalog.items()},
            'target': {n: p[-1] for n, p in catalog.items()}}


def outcome(data):
    try:
        planner = implementation.FactoredChainPlanner(data['factors'], data['catalog'], data['transitions'])
        return planner.plan(data['initial'], data['target'])
    except implementation.FactoredPlanningRefusal as error:
        return {'status': 'refused', 'reason': error.reason, 'witness': error.witness}


def prepare(directory):
    require(not directory.exists(), 'prepare requires a new output directory')
    directory.mkdir(parents=True)
    probe_bytes = (ROOT / PROBE_SOURCE).read_bytes()
    probes = json.loads(probe_bytes)
    probe = next(p for p in probes if p['family'] == 'enum-alias')
    require(len(probe['profiles']) == 4, 'alias profile inventory changed')
    (directory / 'probes.json').write_bytes(probe_bytes)
    source_bindings = {name: digest((ROOT / name).read_bytes()) for name in SOURCES}
    for name in SOURCES:
        path = directory / 'sources' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / name).read_bytes())
    entries, controls = [], []
    specifications = [(size, topology, False) for size in SIZES
                      for topology in ('ring', 'circulant-four')]
    specifications += [(2, 'single-edge', True), (3, 'ring', True),
                       (3, 'complete-digraph', True)]
    for size, topology, control in specifications:
        data = instance(probe, size, topology)
        model_bytes, result_bytes = encoded(data), encoded(outcome(data))
        prefix = 'controls' if control else 'conditions'
        base = directory / prefix / data['name']
        base.mkdir(parents=True)
        (base / 'input.json').write_bytes(model_bytes)
        (base / 'witness.json').write_bytes(result_bytes)
        row = {'name': data['name'], 'topology': topology, 'owners': size,
               'factors': len(data['factors']), 'input_bytes': len(model_bytes),
               'input_sha256': digest(model_bytes), 'output_bytes': len(result_bytes),
               'output_sha256': digest(result_bytes), 'status': json.loads(result_bytes)['status']}
        (controls if control else entries).append(row)
    for name, expected in source_bindings.items():
        require(digest((ROOT / name).read_bytes()) == expected, 'source changed during preparation: ' + name)
    require((ROOT / PROBE_SOURCE).read_bytes() == probe_bytes, 'probe source changed during preparation')
    write(directory / 'inventory.json', {'conditions': entries, 'controls': controls,
        'rounds': ROUNDS, 'order': [
            {'round': r, 'position': p, 'condition': entries[(p + r) % len(entries)]['name']}
            for r in range(ROUNDS) for p in range(len(entries))]})
    write(directory / 'environment.json', {'python': platform.python_version(),
        'platform': platform.platform(), 'machine': platform.machine(),
        'clock': 'time.process_time_ns; time.perf_counter_ns for accompanying wall time',
        'clock_resolution_seconds': time.get_clock_info('process_time').resolution,
        'sources': source_bindings, 'probe_source': PROBE_SOURCE,
        'probe_sha256': digest(probe_bytes), 'target_cpu_ns': TARGET_CPU_NS,
        'max_cohorts': MAX_COHORTS, 'cpu_budget_seconds': CPU_BUDGET_SECONDS,
        'rss_unit': 'KiB on Linux, process maximum across all cohorts',
        'components': list(COMPONENTS),
        'included': ['input file read and JSON parse', 'chain/factor normalization',
                     'local relation recognition and contiguous axis tables',
                     'complete goal query and returned certificate copies',
                     'local path and positive guard construction',
                     'every positive factor corner check', 'full JSON result serialization'],
        'excluded': ['interpreter startup and module imports', 'postcondition hashes',
                     'evidence file writes', 'independent oracle validation'],
        'instrumentation': 'Nested wrappers around unchanged _Model.__init__, _phase, and check_box; '
                           'all timing overhead stays in charged total. Query-other includes copies '
                           'and state conversion as well as numeric updates.'})
    print(json.dumps({'status': 'prepared', 'conditions': len(entries), 'controls': len(controls)}))


class Timers:
    """Observe component boundaries without changing the measured planner."""
    def __init__(self):
        self.model = self.phase = self.guard = 0
        self.model_calls = self.phase_calls = self.guard_calls = 0
        self.original_model = implementation._Model.__init__
        self.original_phase = implementation.FactoredChainPlanner._phase
        self.original_guard = implementation._Model.check_box

    def __enter__(self):
        observer = self

        def model(obj, *args, **kwargs):
            start = time.process_time_ns()
            try:
                return observer.original_model(obj, *args, **kwargs)
            finally:
                observer.model += time.process_time_ns() - start
                observer.model_calls += 1

        def phase(obj, *args, **kwargs):
            start = time.process_time_ns()
            try:
                return observer.original_phase(obj, *args, **kwargs)
            finally:
                observer.phase += time.process_time_ns() - start
                observer.phase_calls += 1

        def guard(obj, *args, **kwargs):
            start = time.process_time_ns()
            try:
                return observer.original_guard(obj, *args, **kwargs)
            finally:
                observer.guard += time.process_time_ns() - start
                observer.guard_calls += 1

        implementation._Model.__init__ = model
        implementation.FactoredChainPlanner._phase = phase
        implementation._Model.check_box = guard
        return self

    def __exit__(self, *args):
        implementation._Model.__init__ = self.original_model
        implementation.FactoredChainPlanner._phase = self.original_phase
        implementation._Model.check_box = self.original_guard


def cohort(path):
    with Timers() as timing:
        wall_start, start = time.perf_counter_ns(), time.process_time_ns()
        raw = path.read_bytes()
        data = json.loads(raw)
        parsed = time.process_time_ns()
        try:
            planner = implementation.FactoredChainPlanner(data['factors'], data['catalog'], data['transitions'])
        except implementation.FactoredPlanningRefusal as error:
            built = time.process_time_ns()
            result = {'status': 'refused', 'reason': error.reason, 'witness': error.witness}
            planned = time.process_time_ns()
        else:
            built = time.process_time_ns()
            try:
                result = planner.plan(data['initial'], data['target'])
            except implementation.FactoredPlanningRefusal as error:
                result = {'status': 'refused', 'reason': error.reason, 'witness': error.witness}
            planned = time.process_time_ns()
        result_bytes = encoded(result)
        serialized = time.process_time_ns()
        wall = time.perf_counter_ns() - wall_start
    components = {'input_cpu_ns': parsed - start, 'model_cpu_ns': timing.model,
                  'recognition_cpu_ns': built - parsed - timing.model,
                  'query_other_cpu_ns': planned - built - timing.phase,
                  'phase_other_cpu_ns': timing.phase - timing.guard,
                  'positive_guard_cpu_ns': timing.guard,
                  'serialization_cpu_ns': serialized - planned}
    total = serialized - start
    require(all(type(v) is int and v >= 0 for v in components.values()), 'negative component timer')
    require(sum(components.values()) == total, 'component timers do not partition total')
    return {'total_cpu_ns': total, 'wall_ns': wall, 'components': components,
            'model_calls': timing.model_calls, 'phase_calls': timing.phase_calls,
            'guard_calls': timing.guard_calls, 'input_sha256': digest(raw),
            'output_sha256': digest(result_bytes), 'output_bytes': len(result_bytes),
            'status': result['status']}


def worker(directory, condition, round_number, position):
    import os
    require(platform.system() == 'Linux', 'RSS measurement currently requires Linux')
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_BUDGET_SECONDS, CPU_BUDGET_SECONDS + 1))
    environment, inventory = read(directory / 'environment.json'), read(directory / 'inventory.json')
    for name, expected in environment['sources'].items():
        require(digest((ROOT / name).read_bytes()) == expected, 'worker source changed: ' + name)
    entry = next(e for e in inventory['conditions'] if e['name'] == condition)
    base = directory / 'workers' / f'round-{round_number}' / condition
    require(not base.exists(), 'worker evidence already exists')
    base.mkdir(parents=True)
    cohorts, charged = [], 0
    with (base / 'cohorts.jsonl').open('w') as stream:
        while charged < TARGET_CPU_NS and len(cohorts) < MAX_COHORTS:
            row = cohort(directory / 'conditions' / condition / 'input.json')
            stream.write(encoded(row).decode('utf-8') + '\n')
            stream.flush()
            cohorts.append(row)
            charged += row['total_cpu_ns']
            require(row['input_sha256'] == entry['input_sha256'], 'timed input differs from prepared input')
            require(row['output_sha256'] == entry['output_sha256'], 'timed output differs from untimed witness')
    require(charged >= TARGET_CPU_NS, 'cohort target not reached within the declared count bound')
    summary = {'condition': condition, 'round': round_number, 'position': position,
               'pid': os.getpid(), 'python_hash_seed': os.environ.get('PYTHONHASHSEED'),
               'cohorts': len(cohorts), 'charged_cpu_ns': charged,
               'zero_cpu_cohorts': sum(r['total_cpu_ns'] == 0 for r in cohorts),
               'mean_total_cpu_ns': statistics.mean(r['total_cpu_ns'] for r in cohorts),
               'mean_wall_ns': statistics.mean(r['wall_ns'] for r in cohorts),
               'mean_components': {key: statistics.mean(r['components'][key] for r in cohorts)
                                   for key in COMPONENTS},
               'maximum_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
               'status': entry['status'], 'output_sha256': entry['output_sha256']}
    write(base / 'summary.json', summary)
    print(encoded(summary).decode('utf-8'))


def aggregate(inventory, workers):
    rows = []
    for entry in inventory['conditions']:
        selected = [w for w in workers if w['condition'] == entry['name']]
        totals = [w['mean_total_cpu_ns'] / 1e6 for w in selected]
        wall = [w['mean_wall_ns'] / 1e6 for w in selected]
        rows.append({'name': entry['name'], 'owners': entry['owners'], 'factors': entry['factors'],
            'status': entry['status'], 'workers': len(selected),
            'zero_cpu_cohorts': sum(w['zero_cpu_cohorts'] for w in selected),
            'cpu_ms': {'median': statistics.median(totals), 'min': min(totals), 'max': max(totals)},
            'wall_ms': {'median': statistics.median(wall), 'min': min(wall), 'max': max(wall)},
            'component_cpu_ms': {key.removesuffix('_cpu_ns'): {
                'median': statistics.median(w['mean_components'][key] / 1e6 for w in selected),
                'min': min(w['mean_components'][key] / 1e6 for w in selected),
                'max': max(w['mean_components'][key] / 1e6 for w in selected)} for key in COMPONENTS},
            'maximum_rss_kib': {'median': statistics.median(w['maximum_rss_kib'] for w in selected),
                'min': min(w['maximum_rss_kib'] for w in selected),
                'max': max(w['maximum_rss_kib'] for w in selected)},
            'input_bytes': entry['input_bytes'], 'output_bytes': entry['output_bytes']})
    return {'status': 'complete', 'conditions': rows, 'workers': len(workers),
            'cohorts': sum(w['cohorts'] for w in workers),
            'zero_cpu_cohorts': sum(w['zero_cpu_cohorts'] for w in workers),
            'statistic': 'median and full range of five fresh-worker cohort means'}


def measure(directory):
    import os
    require(directory.exists() and not (directory / 'workers').exists(), 'measurement requires fresh prepared evidence')
    inventory, environment = read(directory / 'inventory.json'), read(directory / 'environment.json')
    for name, expected in environment['sources'].items():
        require(digest((ROOT / name).read_bytes()) == expected, 'source changed since preparation: ' + name)
    require((ROOT / PROBE_SOURCE).read_bytes() == (directory / 'probes.json').read_bytes(),
            'schema source changed since preparation')
    workers = []
    for item in inventory['order']:
        command = [sys.executable, '-B', '-m', 'tests.factored_scale_study', '--out', str(directory),
                   '--worker', item['condition'], '--round', str(item['round']),
                   '--position', str(item['position'])]
        process = subprocess.run(command, cwd=ROOT, env=dict(os.environ, PYTHONHASHSEED='0'),
                                 text=True, capture_output=True, timeout=120)
        if process.returncode:
            write(directory / 'worker-error.json', {'item': item, 'returncode': process.returncode,
                'stdout': process.stdout, 'stderr': process.stderr})
            raise ValueError('worker failed; partial evidence retained: ' + item['condition'])
        summary = json.loads(process.stdout)
        workers.append(summary)
        print(json.dumps({'round': item['round'], 'condition': item['condition'],
                          'cpu_ms': summary['mean_total_cpu_ns'] / 1e6}), flush=True)
    for name, expected in environment['sources'].items():
        require(digest((ROOT / name).read_bytes()) == expected, 'source changed during measurement: ' + name)
    write(directory / 'summary.json', aggregate(inventory, workers))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare', action='store_true')
    mode.add_argument('--measure', action='store_true')
    mode.add_argument('--worker')
    parser.add_argument('--round', type=int)
    parser.add_argument('--position', type=int)
    args = parser.parse_args()
    path = args.out.resolve()
    if args.prepare:
        prepare(path)
    elif args.measure:
        measure(path)
    else:
        worker(path, args.worker, args.round, args.position)
