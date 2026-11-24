"""Fixed generated evaluation of supplied-batch and unseen-batch guard choice.

This driver keeps original cohorts unchanged. Its literal rectangle oracle and
transition replay do not use planner or checker implementations. It compares
three frozen policies under the supplied batch, independent same-demand batch,
and reversed-owner-demand batch; it makes no external-workload claim.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import platform
import random
import sqlite3
import sys
import time
from pathlib import Path

from src.batch import choose_batch_box
from src.checker import frontier_certificate, safe_envelope
from src.controller import Endpoint
from src.envelope import frontier_synthesize, synthesize
from tests.generalization import relation_for

ROOT = Path(__file__).resolve().parents[1]
FAMILIES = ('diagonal', 'cycle', 'staircase', 'planted', 'sparse', 'capped-random')
SEEDS = tuple(range(6000, 6080))
PROFILES = tuple(range(4))
STEPS = 48
REGIMES = ('supplied', 'same-demand', 'reversed-demand')
POLICIES = ('mass', 'greedy', 'batch')
RESOURCE_REFUSALS = {'exact frontier local-library bound', 'exact frontier search-state bound',
                     'exact frontier result bound'}
SOURCES = ('tests/batch_generalization.py', 'tests/generalization.py', 'src/batch.py',
           'src/envelope.py', 'src/checker.py', 'src/controller.py',
           'docs/BATCH-GENERALIZATION-DESIGN.md')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n', encoding='utf-8')


def identities():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCES}


def nonempty_subsets():
    return [frozenset(part) for size in range(1, 5)
            for part in itertools.combinations(PROFILES, size)]


def literal_rectangles(cells, initial):
    """All anchored safe rectangles, with no producer/helper dependency."""
    subsets = nonempty_subsets()
    safe = [(left, right) for left in subsets for right in subsets
            if initial[0] in left and initial[1] in right
            and all((a, b) in cells for a in left for b in right)]
    frontier = [(left, right) for left, right in safe if not any(
        (left, right) != (a, b) and left <= a and right <= b for a, b in safe)]
    require(bool(safe), 'Literal oracle has no seeded safe rectangle')
    return safe, frontier


def literal_replay(cells, initial, allowed, schedule):
    state = list(initial)
    counts = dict(installed=0, blocked=0, unchanged=0)
    statuses = []
    for owner, target in schedule:
        if target == state[owner]:
            status = 'unchanged'
        elif target not in allowed[owner]:
            status = 'blocked'
        else:
            state[owner] = target
            status = 'installed'
        counts[status] += 1
        statuses.append(status)
        require(tuple(state) in cells, 'Literal guarded replay violated relation')
    return dict(counts, final=state, statuses=statuses)


def atom(owner, value):
    return ('left.' if owner == 0 else 'right.') + str(value)


def proposal_batch(schedule):
    return [dict(node=str(owner), support=[atom(owner, value)]) for owner, value in schedule]


def allowed_by_box(box):
    return tuple(frozenset(value for value in PROFILES if any(
        set(option).issubset({atom(owner, value)}) for option in box[str(owner)]))
        for owner in range(2))


def endpoint_replay(cells, initial, box, schedule):
    endpoints = {owner: Endpoint(owner, [atom(owner, initial[owner])]) for owner in range(2)}
    try:
        for owner, endpoint in endpoints.items():
            reply = endpoint.prepare(0, 1, 'batch-generalization', [], options=box[str(owner)])
            require(reply['status'] == 'held', 'Actual owner refused selected guard')
        counts = dict(installed=0, blocked=0, unchanged=0)
        statuses = []
        for owner, value in schedule:
            status = endpoints[owner].install([atom(owner, value)])['status']
            require(status in counts, 'Unexpected installation status')
            counts[status] += 1
            statuses.append(status)
            state = tuple(int(endpoints[i].state['support'][0].split('.')[1]) for i in range(2))
            require(state in cells, 'Actual guarded replay violated relation')
        return dict(counts, final=list(state), statuses=statuses)
    finally:
        for endpoint in endpoints.values():
            endpoint.disconnect()


def demand_batch(seed, preferred):
    rng = random.Random(seed)
    return [(preferred if rng.random() < .85 else 1 - preferred, rng.randrange(4))
            for _ in range(STEPS)]


def one(family, seed):
    cells = relation_for(family, seed)
    initial = sorted(cells)[random.Random(seed ^ 0x5A17).randrange(len(cells))]
    current = {str(i): [atom(i, initial[i])] for i in range(2)}
    candidates = {str(i): [[atom(i, v)] for v in PROFILES] for i in range(2)}
    branches = [{'0': [atom(0, a)], '1': [atom(1, b)]} for a, b in sorted(cells)]
    safe, frontier = literal_rectangles(cells, initial)
    base_seed = seed * 1009 + sum((i + 1) * ord(c) for i, c in enumerate(family))
    preferred = seed % 2
    training = demand_batch(base_seed, preferred)
    schedules = {
        'supplied': training,
        'same-demand': demand_batch(base_seed ^ 0x38F15A, preferred),
        'reversed-demand': demand_batch(base_seed ^ 0x6E9B73, 1 - preferred),
    }
    context = dict(family=family, seed=seed, relation=sorted(cells), initial=initial,
                   training_preferred_owner=preferred, training=training,
                   schedules=schedules, safe_rectangles=len(safe), oracle_frontier=len(frontier))
    try:
        plan = frontier_synthesize(branches, current, candidates)
        greedy = synthesize(branches, current, candidates)
        selected = choose_batch_box(branches, current, candidates, proposal_batch(training))
    except ValueError as error:
        if str(error) not in RESOURCE_REFUSALS:
            raise
        context.update(status='refused', reason=str(error))
        return context, []
    require(frontier_certificate(branches, current, candidates, plan), 'Frontier certificate rejected')
    require(selected['frontier_plan'] == plan, 'Batch selector changed the original frontier')
    returned = {allowed_by_box(member['box']) for member in plan['frontier']}
    require(returned == set(frontier), 'Complete frontier differs from literal oracle')
    require(plan['product_mass'] == max(len(a) * len(b) for a, b in safe), 'Mass optimum differs')
    boxes = dict(mass=plan['box'], greedy=greedy['box'], batch=selected['box'])
    for name, box in boxes.items():
        require(safe_envelope(branches, box), name + ' guard rejected')
        require(allowed_by_box(box) in safe, name + ' rectangle not independently safe')
    expected_forecast = literal_replay(cells, initial, allowed_by_box(selected['box']), training)
    require(selected['forecast']['installed'] == expected_forecast['installed'], 'Training forecast differs')
    context.update(status='completed', boxes=boxes,
                   changed_from_mass=not selected['kept_max_mass'], observations={})
    rows = []
    for regime, schedule in schedules.items():
        best = max(literal_replay(cells, initial, rectangle, schedule)['installed'] for rectangle in safe)
        row = dict(family=family, seed=seed, regime=regime, proposals=STEPS,
                   safe_rectangles=len(safe), frontier_size=len(frontier),
                   batch_changed_from_mass=not selected['kept_max_mass'], static_hindsight_installed=best)
        context['observations'][regime] = {}
        for name, box in boxes.items():
            reference = literal_replay(cells, initial, allowed_by_box(box), schedule)
            observed = endpoint_replay(cells, initial, box, schedule)
            require(observed == reference, name + ' actual transitions differ from independent replay')
            require(sum(observed[key] for key in ('installed', 'blocked', 'unchanged')) == STEPS,
                    'Proposal denominator differs')
            context['observations'][regime][name] = observed
            for key in ('installed', 'blocked', 'unchanged'):
                row[name + '_' + key] = observed[key]
            row[name + '_regret'] = best - observed['installed']
            require(row[name + '_regret'] >= 0, 'Policy exceeds exhaustive static hindsight reference')
        if regime == 'supplied':
            require(row['batch_regret'] == 0, 'Catalog-covered batch is not static-optimal')
        row['batch_minus_mass'] = row['batch_installed'] - row['mass_installed']
        row['batch_minus_greedy'] = row['batch_installed'] - row['greedy_installed']
        rows.append(row)
    return context, rows


def aggregate(rows):
    output = {}
    for regime in REGIMES:
        subset = [row for row in rows if row['regime'] == regime]
        output[regime] = {
            'schedules': len(subset), 'proposals_per_policy': sum(row['proposals'] for row in subset),
            'static_hindsight_installed': sum(row['static_hindsight_installed'] for row in subset),
            'policies': {name: {key: sum(row[name + '_' + key] for row in subset)
                               for key in ('installed', 'blocked', 'unchanged', 'regret')}
                         for name in POLICIES},
            'batch_vs_mass': {name: sum(predicate(row['batch_minus_mass']) for row in subset)
                              for name, predicate in (('wins', lambda d: d > 0), ('ties', lambda d: d == 0),
                                                      ('losses', lambda d: d < 0))},
            'batch_vs_greedy': {name: sum(predicate(row['batch_minus_greedy']) for row in subset)
                                for name, predicate in (('wins', lambda d: d > 0), ('ties', lambda d: d == 0),
                                                        ('losses', lambda d: d < 0))},
        }
    return output


def run(out):
    out = out.resolve()
    require(not out.exists() and not out.is_relative_to(ROOT), 'Fresh output outside artifact required')
    out.mkdir(parents=True)
    before = identities()
    registration = dict(design='docs/BATCH-GENERALIZATION-DESIGN.md', families=FAMILIES,
                        seeds=[min(SEEDS), max(SEEDS)], contexts=len(FAMILIES) * len(SEEDS),
                        regimes=REGIMES, proposals_per_schedule=STEPS, preferred_owner_probability=.85,
                        source_sha256=before, platform=platform.platform(), python=sys.version,
                        sqlite=sqlite3.sqlite_version, scope='Fixed generated study; no field prevalence or performance claim')
    write_json(out / 'registration.json', registration)
    start = time.monotonic()
    rows, contexts = [], []
    try:
        with (out / 'contexts.jsonl').open('w', encoding='utf-8') as trace:
            for family in FAMILIES:
                for seed in SEEDS:
                    context, observed = one(family, seed)
                    contexts.append(context)
                    rows.extend(observed)
                    trace.write(json.dumps(context, sort_keys=True, separators=(',', ':')) + '\n')
                    trace.flush()
        with (out / 'observations.csv').open('w', newline='', encoding='utf-8') as stream:
            if rows:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
        after = identities()
        require(before == after, 'Source changed during study; observations are not a stable-source run')
        complete = [context for context in contexts if context['status'] == 'completed']
        refused = [context for context in contexts if context['status'] != 'completed']
        summary = dict(status='PASS', planned_contexts=len(FAMILIES) * len(SEEDS),
                       completed_contexts=len(complete), refused_contexts=len(refused),
                       refusals=[dict(family=c['family'], seed=c['seed'], reason=c['reason']) for c in refused],
                       schedules=len(rows), proposals_per_policy=sum(row['proposals'] for row in rows),
                       batch_choices_changed_from_mass=sum(c['changed_from_mass'] for c in complete),
                       independent_frontier_mismatches=0, endpoint_replay_mismatches=0,
                       incompatible_guarded_snapshots=0, source_unchanged=True,
                       by_regime=aggregate(rows),
                       by_family={family: aggregate([r for r in rows if r['family'] == family]) for family in FAMILIES},
                       wall_seconds=time.monotonic() - start,
                       scope=registration['scope'])
        write_json(out / 'summary.json', summary)
        # Preserve exact source used by this separate cohort.
        for name in SOURCES:
            destination = out / 'source-preimage' / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((ROOT / name).read_bytes())
        print(json.dumps({key: value for key, value in summary.items() if key != 'by_family'}, sort_keys=True))
        return summary
    except BaseException as error:
        write_json(out / 'failure.json', dict(status='FAILED_OR_PARTIAL', contexts=len(contexts),
                                            schedules=len(rows), error=repr(error)))
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    run(parser.parse_args().out)
