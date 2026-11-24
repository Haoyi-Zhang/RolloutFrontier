"""Independent validation of supporting scientific cohorts.

This module imports no planner, network, controller or experiment driver. It
checks preserved source identities, literal transitions in the batch study,
actual SQLite contents for effects, and derives costs from complete raw rows.
It does not turn preserved observations into independent execution evidence.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
import csv
import hashlib
import itertools
import json
from pathlib import Path
import random
import sqlite3
import tempfile
import zipfile
from lifecycle_table import derive as derive_cost_rows
from tests.check_same_information import (
    accepted as singleton_acceptance, deterministic_choices, same,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'results/supporting-studies'
FAMILIES = ('diagonal', 'cycle', 'staircase', 'planted', 'sparse', 'capped-random')
REGIMES = ('supplied', 'same-demand', 'reversed-demand')
POLICIES = ('mass', 'greedy', 'batch')
BATCH_SOURCE_FILES = {
    'tests/batch_generalization.py', 'tests/generalization.py', 'src/batch.py',
    'src/envelope.py', 'src/checker.py', 'src/controller.py',
    'docs/BATCH-GENERALIZATION-DESIGN.md',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def check_sources(directory, batch=False):
    metadata = load(directory / ('registration.json' if batch else 'environment.json'))
    entries = metadata['source_sha256']
    require(isinstance(entries, dict) and bool(entries), 'Missing source inventory')
    for name, expected in entries.items():
        snapshot = directory / 'source-preimage' / name
        require(snapshot.resolve().is_relative_to((directory / 'source-preimage').resolve()), 'Source path escape')
        require(snapshot.is_file(), 'Missing source snapshot ' + name)
        require(hashlib.sha256(snapshot.read_bytes()).hexdigest() == expected, 'Source snapshot differs ' + name)
        require((ROOT / name).is_file() and hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected,
                'Current source differs from revision cohort ' + name)
    if not batch:
        require(metadata['returncode'] == 0 and metadata['source_bytes_unchanged_during_run'] is True,
                'Failed or source-changing execution')
        require(load(directory / 'source-registration.json')['source_sha256'] == entries,
                'Source registration differs from completion inventory')
    return len(entries)


def rectangles(cells, initial):
    subsets = [frozenset(values) for size in range(1, 5)
               for values in itertools.combinations(range(4), size)]
    safe = [(a, b) for a in subsets for b in subsets
            if initial[0] in a and initial[1] in b and all((x, y) in cells for x in a for y in b)]
    front = [(a, b) for a, b in safe if not any((a, b) != (x, y) and a <= x and b <= y for x, y in safe)]
    return safe, front


def accepted(box):
    return tuple(frozenset(values) for values in singleton_acceptance(box))


def registered_batch_relation(family, seed):
    """Independent reconstruction of the original cohort's six generators."""
    require(type(family) is str and family in FAMILIES and
            type(seed) is int and 6000 <= seed < 6080, 'Invalid registered family/seed')
    grid = list(itertools.product(range(4), repeat=2))
    if family == 'diagonal':
        return {(a, b) for a, b in grid if a == b}
    if family == 'cycle':
        return {(a, b) for a, b in grid if (b - a) % 4 in (0, 1)}
    if family == 'staircase':
        return {(a, b) for a, b in grid if b == a or b == a + 1}
    rng = random.Random(seed * 256 ^ sum(ord(char) for char in family))
    if family == 'planted':
        rows, columns = rng.sample(range(4), 2), rng.sample(range(4), 2)
        planted = set(itertools.product(rows, columns))
        return planted | set(rng.sample([cell for cell in grid if cell not in planted], 4))
    return set(rng.sample(grid, 5 if family == 'sparse' else 8))


def registered_batch_schedules(family, seed):
    preferred = seed % 2
    base = seed * 1009 + sum((index + 1) * ord(char) for index, char in enumerate(family))
    schedules = {}
    for regime, stream, owner in (
            ('supplied', base, preferred),
            ('same-demand', base ^ 0x38F15A, preferred),
            ('reversed-demand', base ^ 0x6E9B73, 1 - preferred)):
        rng = random.Random(stream)
        schedules[regime] = [
            [owner if rng.random() < .85 else 1 - owner, rng.randrange(4)]
            for _ in range(48)
        ]
    return schedules


def fixed_order_greedy(cells, initial):
    """Replay every safe singleton extension in fixed owner/profile order.

    Profiles absent from every relation cell project to an empty option in the
    producer and fail strong safety. Rejecting their literal row/column extension
    has the same effect. All remaining labels have the declared lexical order.
    """
    allowed = [{initial[0]}, {initial[1]}]
    for owner, profile in itertools.product(range(2), range(4)):
        if profile in allowed[owner]:
            continue
        trial = [set(values) for values in allowed]
        trial[owner].add(profile)
        if set(itertools.product(*trial)) <= cells:
            allowed = trial
    return tuple(frozenset(values) for values in allowed)


def replay(cells, initial, allowed, proposals):
    state = list(initial)
    statuses = []
    for owner, target in proposals:
        require(type(owner) is int and owner in (0, 1) and type(target) is int and target in range(4),
                'Invalid registered proposal')
        if target == state[owner]:
            status = 'unchanged'
        elif target in allowed[owner]:
            status = 'installed'
            state[owner] = target
        else:
            status = 'blocked'
        statuses.append(status)
        require(tuple(state) in cells, 'Incompatible recorded guard replay')
    return {**{name: statuses.count(name) for name in ('installed', 'blocked', 'unchanged')},
            'final': state, 'statuses': statuses}


def aggregate(rows):
    result = {}
    for regime in REGIMES:
        chosen = [row for row in rows if row['regime'] == regime]
        entry = dict(schedules=len(chosen), proposals_per_policy=48 * len(chosen),
                     static_hindsight_installed=sum(row['static_hindsight_installed'] for row in chosen),
                     policies={policy: {key: sum(row[policy + '_' + key] for row in chosen)
                                        for key in ('installed', 'blocked', 'unchanged', 'regret')}
                               for policy in POLICIES})
        for comparator in ('mass', 'greedy'):
            differences = [row['batch_installed'] - row[comparator + '_installed'] for row in chosen]
            entry['batch_vs_' + comparator] = dict(wins=sum(d > 0 for d in differences),
                                                  ties=sum(d == 0 for d in differences),
                                                  losses=sum(d < 0 for d in differences))
        result[regime] = entry
    return result


def check_batch(directory):
    registration = load(directory / 'registration.json')
    require(isinstance(registration['source_sha256'], dict) and
            set(registration['source_sha256']) == BATCH_SOURCE_FILES,
            'Batch source inventory differs')
    source_count = check_sources(directory, batch=True)
    require(registration['families'] == list(FAMILIES) and registration['regimes'] == list(REGIMES)
            and registration['seeds'] == [6000, 6079] and registration['contexts'] == 480
            and registration['proposals_per_schedule'] == 48 and registration['preferred_owner_probability'] == .85,
            'Batch design differs')
    contexts = [json.loads(line) for line in (directory / 'contexts.jsonl').read_text().splitlines()]
    require([(c['family'], c['seed']) for c in contexts] ==
            list(itertools.product(FAMILIES, range(6000, 6080))), 'Incomplete/reordered batch contexts')
    require(all(c['status'] == 'completed' for c in contexts), 'Unexpected refused batch context')
    expected_rows = []
    for context in contexts:
        family, seed = context['family'], context['seed']
        cells = registered_batch_relation(family, seed)
        require(same(context['relation'], [list(cell) for cell in sorted(cells)]),
                'Registered batch relation differs')
        expected_initial = sorted(cells)[random.Random(seed ^ 0x5A17).randrange(len(cells))]
        require(same(context['initial'], list(expected_initial)), 'Registered initial state differs')
        require(type(context['training_preferred_owner']) is int and
                context['training_preferred_owner'] == seed % 2, 'Registered preferred owner differs')
        schedules = registered_batch_schedules(family, seed)
        require(same(context['schedules'], schedules), 'Registered batch schedules differ')
        initial = tuple(context['initial'])
        safe, frontier = rectangles(cells, initial)
        require(context['safe_rectangles'] == len(safe) and context['oracle_frontier'] == len(frontier),
                'Rectangle counts differ')
        require(same(context['training'], schedules['supplied']),
                'Supplied-batch identity differs')
        require(set(context['schedules']) == set(REGIMES), 'Regime inventory differs')
        boxes = context['boxes']
        require(isinstance(boxes, dict) and set(boxes) == set(POLICIES), 'Policy guard inventory differs')
        require(set(context['observations']) == set(REGIMES), 'Observation regime inventory differs')
        for policy in POLICIES:
            require(accepted(boxes[policy]) in safe, 'Recorded guard is not a safe seeded rectangle')
        require(accepted(boxes['mass']) in frontier and accepted(boxes['batch']) in frontier,
                'Selected choice is outside the acceptance frontier')
        require(len(accepted(boxes['mass'])[0]) * len(accepted(boxes['mass'])[1]) ==
                max(len(a) * len(b) for a, b in safe), 'Mass optimum differs')
        ordered_frontier = [tuple(tuple(sorted(values)) for values in rectangle) for rectangle in frontier]
        expected_mass, expected_batch = deterministic_choices(
            cells, initial, ordered_frontier, schedules['supplied'])
        require(accepted(boxes['mass']) == tuple(map(frozenset, expected_mass)), 'Mass tie rule differs')
        require(accepted(boxes['batch']) == tuple(map(frozenset, expected_batch)), 'Batch tie rule differs')
        require(accepted(boxes['greedy']) == fixed_order_greedy(cells, initial),
                'Fixed-order greedy choice differs')
        require(type(context['changed_from_mass']) is bool and
                context['changed_from_mass'] == (boxes['batch'] != boxes['mass']), 'Changed-choice count differs')
        for regime in REGIMES:
            proposals = context['schedules'][regime]
            require(len(proposals) == 48, 'Proposal denominator differs')
            best = max(replay(cells, initial, rectangle, proposals)['installed'] for rectangle in safe)
            row = dict(family=context['family'], seed=context['seed'], regime=regime, proposals=48,
                       safe_rectangles=len(safe), frontier_size=len(frontier),
                       batch_changed_from_mass=context['changed_from_mass'], static_hindsight_installed=best)
            require(set(context['observations'][regime]) == set(POLICIES),
                    'Observation policy inventory differs')
            for policy in POLICIES:
                actual = context['observations'][regime][policy]
                expected = replay(cells, initial, accepted(boxes[policy]), proposals)
                require(same(actual, expected), 'Recorded per-event observations differ from literal replay')
                row.update({policy + '_' + key: actual[key] for key in ('installed', 'blocked', 'unchanged')})
                row[policy + '_regret'] = best - actual['installed']
                require(row[policy + '_regret'] >= 0, 'Static hindsight is exceeded')
            require(regime != 'supplied' or row['batch_regret'] == 0, 'Supplied-batch optimum differs')
            row['batch_minus_mass'] = row['batch_installed'] - row['mass_installed']
            row['batch_minus_greedy'] = row['batch_installed'] - row['greedy_installed']
            expected_rows.append(row)
    with (directory / 'observations.csv').open(newline='', encoding='utf-8') as stream:
        recorded = list(csv.DictReader(stream))
    require(recorded == [{key: str(value) for key, value in row.items()} for row in expected_rows],
            'CSV rows differ from detailed observations')
    summary = load(directory / 'summary.json')
    require(summary['status'] == 'PASS' and summary['source_unchanged'] is True
            and summary['planned_contexts'] == summary['completed_contexts'] == 480
            and summary['refused_contexts'] == 0 and summary['refusals'] == []
            and summary['schedules'] == 1440 and summary['proposals_per_policy'] == 69120,
            'Summary denominator differs')
    require(all(summary[key] == 0 for key in ('independent_frontier_mismatches',
            'endpoint_replay_mismatches', 'incompatible_guarded_snapshots')), 'Recorded discrepancy count differs')
    require(summary['batch_choices_changed_from_mass'] == sum(c['changed_from_mass'] for c in contexts),
            'Summary changed-choice count differs')
    require(same(summary['by_regime'], aggregate(expected_rows)), 'Regime aggregates differ')
    require(same(summary['by_family'], {family: aggregate([r for r in expected_rows if r['family'] == family])
                                       for family in FAMILIES}), 'Family aggregates differ')
    return dict(status='PASS', source_files=source_count, contexts=480, schedules=1440,
                per_event_policy_observations=207360, snapshot_scope='in-memory owner conformance, no network faults')


def check_effects(directory):
    source_count = check_sources(directory)
    registration = load(directory / 'registration.json')
    for name, expected in registration['source_bindings'].items():
        require(hashlib.sha256((directory / 'source-preimage' / name).read_bytes()).hexdigest() == expected,
                'Original effect-driver source binding differs')
    rows = load(directory / 'rows.json')
    expected_design = set(itertools.product(('predicate', 'epoch'), ('commit', 'cancel'),
                                           ('none', 'endpoint', 'coordinator'), (False, True)))
    require(len(rows) == 24 and {(r['policy'], r['completion'], r['restart'], r['release_partition']) for r in rows}
            == expected_design, 'Incomplete effect design')
    identities = load(directory / 'database-identities.json')
    with zipfile.ZipFile(directory / 'databases.zip') as archive, tempfile.TemporaryDirectory() as temporary:
        require(len(archive.namelist()) == len(identities) == 96 and set(archive.namelist()) == set(identities),
                'Effect snapshot inventory differs')
        for name, expected in identities.items():
            raw = archive.read(name)
            require(len(raw) == expected['size'] and hashlib.sha256(raw).hexdigest() == expected['sha256'],
                    'Effect snapshot bytes differ')
        for index, row in enumerate(rows):
            require(row['initial_retirement'] == 'draining' and row['incompatible_install_while_active'] == 'blocked'
                    and row['new_work_rejected'] is True and row['stale_effect_rejected'] is True,
                    'Effect authorization outcome differs')
            require(row['first_release'] == ('release-pending' if row['release_partition'] else 'retired')
                    and row['final_release'] == 'retired', 'Effect release outcome differs')
            require(row['actual_stored_value'] == ('committed' if row['completion'] == 'commit' else None),
                    'Effect value observation differs')
            for suffix in ('effects.sqlite', 'net/node-0.sqlite', 'net/node-1.sqlite', 'net/origin-0.sqlite'):
                path = Path(temporary) / 'read.sqlite'
                path.write_bytes(archive.read(f'case-{index}/' + suffix))
                db = sqlite3.connect('file:' + path.as_posix() + '?mode=ro', uri=True)
                try:
                    require(db.execute('PRAGMA integrity_check').fetchall() == [('ok',)], 'Snapshot integrity failed')
                    if suffix == 'effects.sqlite':
                        require(db.execute('SELECT phase FROM leases').fetchall() == [('closed',)], 'Lease fence missing')
                        require(db.execute('SELECT phase FROM operations').fetchall() ==
                                [('done' if row['completion'] == 'commit' else 'cancelled',)], 'Operation phase differs')
                        require(db.execute('SELECT value FROM effects').fetchall() ==
                                ([('committed',)] if row['completion'] == 'commit' else []), 'Stored effect differs')
                    else:
                        entries = db.execute('SELECT id,payload FROM state').fetchall()
                        require(len(entries) == 1 and entries[0][0] == 1, 'Protocol singleton differs')
                        state = json.loads(entries[0][1])
                        if 'origin' in suffix:
                            require(state['attempts'] == {}, 'Origin release incomplete')
                        else:
                            require(state['slots'] == {} and state['floor'][0] >= 1, 'Owner can resurrect or retains hold')
                            require(state['support'] == (['b'] if 'node-0' in suffix else ['a', 'b']), 'Owner support differs')
                finally:
                    db.close()
    summary = load(directory / 'summary.json')
    require(summary['status'] == 'PASS' and summary['cases'] == summary['planned_cases'] == 24
            and summary['stored_commits'] == summary['cancelled_without_write'] == 12
            and summary['new_effects_during_drain_rejected'] == summary['stale_effects_after_retirement_rejected'] == 24,
            'Effect summary differs')
    return dict(status='PASS', source_files=source_count, lifecycles=24, database_snapshots=96)


def check_costs(directory):
    source_count = check_sources(directory)
    measurements = load(directory / 'measurements.json')
    rows = derive_cost_rows(measurements)
    for row in measurements['rows']:
        require(row['owner_processes'] == 5 and row['owner_reopens'] == row['origin_reopens'] == 1
                and row['sqlite_files'] == 6 and row['total_tcp_connections'] == row['rpc_count'] + row['management_connections'],
                'Lifecycle process/connection accounting differs')
    return dict(status='PASS', source_files=source_count, lifecycles=48, proposals=1152,
                table_rows=rows.replace('results/durable-state-costs/measurements.json',
                                       'results/supporting-studies/lifecycle-costs/measurements.json'))


def check_semantic(directory):
    source_count = check_sources(directory)
    execution = load(directory / 'execution.json')
    require(execution['status'] == 'completed' and execution['semantic_reference'] == 'matched'
            and len(execution['runs']) == 17 and len(execution['compared_files']) == 23
            and execution['numeric_claim_bindings_verified'] == 33, 'Semantic suite report differs')
    require(all(row['exit_code'] == 0 for row in execution['runs']), 'A semantic job failed')
    return dict(status='PASS', source_files=source_count, jobs=17, semantic_outputs=23, numeric_bindings=33)


def verify(directory=DATA):
    costs = check_costs(directory / 'lifecycle-costs')
    costs.pop('table_rows')
    return dict(batch=check_batch(directory / 'batch-generalization'),
                effects=check_effects(directory / 'effect-drain'), costs=costs,
                semantic=check_semantic(directory / 'semantic'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=DATA)
    parser.add_argument('--cost-table', action='store_true')
    args = parser.parse_args()
    if args.cost_table:
        print(check_costs(args.data / 'lifecycle-costs')['table_rows'], end='')
    else:
        print(json.dumps(verify(args.data), sort_keys=True, indent=2))
