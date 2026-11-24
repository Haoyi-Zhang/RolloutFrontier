"""Registered same-information greedy versus complete-frontier batch choice."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import random
import sys
import time
from pathlib import Path

from src.batch import choose_batch_box
from src.checker import frontier_certificate, safe_envelope
from src.envelope import frontier_synthesize
from tests.batch_generalization import (atom, proposal_batch, allowed_by_box,
    literal_rectangles, literal_replay, endpoint_replay)
from tests.generalization import relation_for

ROOT = Path(__file__).resolve().parents[1]
FAMILIES = ('diagonal', 'cycle', 'staircase', 'planted', 'sparse', 'capped-random')
SEEDS = range(7000, 7040)
PROBABILITIES = (50, 70, 90)
REGIMES = ('supplied', 'same-demand', 'swapped-owner')
POLICIES = ('mass', 'batch_greedy', 'batch_exact')
RESOURCE_REFUSALS = {'exact frontier local-library bound', 'exact frontier search-state bound',
                     'exact frontier result bound'}
SOURCES = ('tests/same_information.py', 'tests/batch_generalization.py',
           'tests/generalization.py', 'src/batch.py', 'src/envelope.py',
           'src/checker.py', 'src/controller.py', 'docs/SAME-INFORMATION-DESIGN.md')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')


def identities():
    return {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in SOURCES}


def encoded_box(rectangle):
    return {str(i): [[atom(i, value)] for value in sorted(values)]
            for i, values in enumerate(rectangle)}


def batch_greedy(cells, initial, training):
    """Repeatedly take the safe one-profile expansion with best exact forecast."""
    rectangle = tuple(frozenset([v]) for v in initial)
    trace = []
    evaluations = 0
    while True:
        trials = []
        previous = literal_replay(cells, initial, rectangle, training)['installed']
        for owner in range(2):
            for value in range(4):
                if value in rectangle[owner]:
                    continue
                candidate = list(rectangle)
                candidate[owner] = candidate[owner] | {value}
                candidate = tuple(candidate)
                if not all((a, b) in cells for a in candidate[0] for b in candidate[1]):
                    continue
                count = literal_replay(cells, initial, candidate, training)['installed']
                evaluations += 1
                mass = len(candidate[0]) * len(candidate[1])
                trials.append(((-count, -mass, owner, value), candidate))
        if not trials:
            break
        rank, rectangle = min(trials, key=lambda trial: trial[0])
        require(-rank[0] >= previous, 'Covered expansion reduced installation count')
        trace.append({'owner': rank[2], 'profile': rank[3], 'training_installed': -rank[0],
                      'gain': -rank[0]-previous, 'mass': -rank[1],
                      'accepted': [sorted(values) for values in rectangle]})
    return encoded_box(rectangle), trace, evaluations


def batch(seed, preferred, percent):
    rng = random.Random(seed)
    return [(preferred if rng.random() < percent/100 else 1-preferred, rng.randrange(4))
            for _ in range(48)]


def evaluate(cells, initial, schedules, identity):
    current = {str(i): [atom(i, value)] for i, value in enumerate(initial)}
    candidates = {str(i): [[atom(i, value)] for value in range(4)] for i in range(2)}
    branches = [{'0': [atom(0, a)], '1': [atom(1, b)]} for a, b in sorted(cells)]
    safe, frontier = literal_rectangles(cells, initial)
    context = {**identity, 'relation': sorted(cells), 'initial': list(initial),
               'schedules': schedules, 'safe_products': len(safe), 'frontier_size': len(frontier)}
    try:
        plan = frontier_synthesize(branches, current, candidates)
        exact = choose_batch_box(branches, current, candidates, proposal_batch(schedules['supplied']))
    except ValueError as error:
        if str(error) not in RESOURCE_REFUSALS:
            raise
        context.update(status='refused', reason=str(error))
        return context, []
    greedy, trace, trials = batch_greedy(cells, initial, schedules['supplied'])
    require(frontier_certificate(branches, current, candidates, plan), 'Frontier certificate rejected')
    require({allowed_by_box(m['box']) for m in plan['frontier']} == set(frontier), 'Frontier mismatch')
    require(exact['frontier_plan'] == plan, 'Exact batch uses a different frontier')
    boxes = {'mass': plan['box'], 'batch_greedy': greedy, 'batch_exact': exact['box']}
    for name, box in boxes.items():
        require(safe_envelope(branches, box), name + ' unsafe guard')
        require(allowed_by_box(box) in frontier, name + ' product not maximal')
    context.update(status='completed', boxes=boxes, greedy_trace=trace,
                   greedy_trial_evaluations=trials, observations={})
    rows = []
    for regime, schedule in schedules.items():
        optimum = max(literal_replay(cells, initial, rectangle, schedule)['installed'] for rectangle in safe)
        row = {**identity, 'regime': regime, 'proposals': len(schedule),
               'frontier_size': len(frontier), 'greedy_trial_evaluations': trials,
               'static_hindsight_installed': optimum}
        context['observations'][regime] = {}
        for name, box in boxes.items():
            expected = literal_replay(cells, initial, allowed_by_box(box), schedule)
            observed = endpoint_replay(cells, initial, box, schedule)
            require(expected == observed, name + ' endpoint/replay mismatch')
            context['observations'][regime][name] = observed
            for outcome in ('installed', 'blocked', 'unchanged'):
                row[name+'_'+outcome] = observed[outcome]
            row[name+'_regret'] = optimum - observed['installed']
            require(row[name+'_regret'] >= 0, 'Exceeded literal static optimum')
        if regime == 'supplied':
            require(row['batch_exact_regret'] == 0, 'Exact batch missed supplied optimum')
        row['exact_minus_greedy'] = row['batch_exact_installed'] - row['batch_greedy_installed']
        rows.append(row)
    return context, rows


def one(family, seed, percent):
    cells = relation_for(family, seed)
    initial = sorted(cells)[random.Random(seed ^ 0x7139).randrange(len(cells))]
    salt = sum((i+1)*ord(c) for i,c in enumerate(family))
    base = seed*1009 + salt + percent*1000003
    preferred = seed % 2
    schedules = {'supplied': batch(base, preferred, percent),
                 'same-demand': batch(base ^ 0x157A3, preferred, percent),
                 'swapped-owner': batch(base ^ 0x2BE71, 1-preferred, percent)}
    return evaluate(cells, initial, schedules,
                    {'family': family, 'seed': seed, 'preferred_owner_percent': percent})


def mechanism_control():
    cells = {(0,0), (0,1), (0,2), (0,3), (1,0), (2,0)}
    proposals = [(0, v) for _ in range(10) for v in (1,2)] + [(1,1), (1,0)]
    context, rows = evaluate(cells, (0,0), {'supplied': proposals},
                             {'family':'mechanism-control', 'seed':0, 'preferred_owner_percent':None})
    require(context['status'] == 'completed', 'Mechanism control refused')
    require(rows[0]['batch_greedy_installed'] == 2 and rows[0]['batch_exact_installed'] == 20,
            'Greedy complementarity control differs')
    return {'context':context, 'row':rows[0], 'scope':'Separate deterministic control; excluded from generated aggregates.'}


def aggregate(rows):
    result = {}
    for regime in REGIMES:
        subset = [row for row in rows if row['regime'] == regime]
        result[regime] = {
            'schedules':len(subset), 'proposals_per_policy':sum(r['proposals'] for r in subset),
            'static_hindsight_installed':sum(r['static_hindsight_installed'] for r in subset),
            'policies':{name:{key:sum(r[name+'_'+key] for r in subset)
                              for key in ('installed','blocked','unchanged','regret')} for name in POLICIES},
            'exact_vs_greedy':{
                'wins':sum(r['exact_minus_greedy'] > 0 for r in subset),
                'ties':sum(r['exact_minus_greedy'] == 0 for r in subset),
                'losses':sum(r['exact_minus_greedy'] < 0 for r in subset)},
        }
    return result


def run(out):
    out = out.resolve()
    require(not out.exists() and not out.is_relative_to(ROOT), 'New output outside artifact required')
    out.mkdir(parents=True)
    before = identities()
    registration = {'design':'docs/SAME-INFORMATION-DESIGN.md', 'families':FAMILIES,
                    'seeds':[7000,7039], 'structural_contexts':240, 'planned_conditions':720,
                    'preferred_owner_percent':PROBABILITIES, 'steps':48, 'regimes':REGIMES,
                    'source_sha256':before, 'python':sys.version, 'platform':platform.platform(),
                    'scope':'Fixed generated same-information comparison; shared contexts; no field inference.'}
    write_json(out/'registration.json', registration)
    contexts, rows = [], []
    started = time.monotonic()
    try:
        with (out/'contexts.jsonl').open('w') as stream:
            for family in FAMILIES:
                for seed in SEEDS:
                    for percent in PROBABILITIES:
                        context, observed = one(family, seed, percent)
                        contexts.append(context); rows.extend(observed)
                        stream.write(json.dumps(context,sort_keys=True,separators=(',',':'))+'\n')
                        stream.flush()
        with (out/'observations.csv').open('w',newline='') as stream:
            if rows:
                writer = csv.DictWriter(stream,fieldnames=list(rows[0]))
                writer.writeheader(); writer.writerows(rows)
        write_json(out/'mechanism-control.json', mechanism_control())
        require(identities() == before, 'Source changed during execution')
        completed = [c for c in contexts if c['status']=='completed']
        refused = [c for c in contexts if c['status']!='completed']
        summary = {'status':'PASS', 'planned_conditions':720, 'completed_conditions':len(completed),
                   'refused_conditions':len(refused),
                   'refusals':[{k:c[k] for k in ('family','seed','preferred_owner_percent','reason')} for c in refused],
                   'schedules':len(rows), 'proposals_per_policy':sum(r['proposals'] for r in rows),
                   'per_event_policy_observations':len(POLICIES)*sum(r['proposals'] for r in rows),
                   'by_regime':aggregate(rows),
                   'by_demand':{str(p):aggregate([r for r in rows if r['preferred_owner_percent']==p]) for p in PROBABILITIES},
                   'by_family':{f:aggregate([r for r in rows if r['family']==f]) for f in FAMILIES},
                   'mismatches':0, 'unsafe_guarded_snapshots':0, 'source_unchanged':True,
                   'wall_seconds':time.monotonic()-started, 'scope':registration['scope']}
        write_json(out/'summary.json',summary)
        for name in SOURCES:
            p = out/'source-preimage'/name; p.parent.mkdir(parents=True,exist_ok=True)
            p.write_bytes((ROOT/name).read_bytes())
        print(json.dumps({k:v for k,v in summary.items() if k not in ('by_family','by_demand')},sort_keys=True))
    except BaseException as error:
        write_json(out/'failure.json',{'status':'FAILED_OR_PARTIAL','conditions':len(contexts),
                                     'schedules':len(rows),'error':repr(error)})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    run(parser.parse_args().out)
