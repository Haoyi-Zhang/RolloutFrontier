"""Data-only reconstruction of the registered same-information comparison.

No planner, protocol, generator or experiment driver is imported.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAMILIES = ('diagonal', 'cycle', 'staircase', 'planted', 'sparse', 'capped-random')
REGIMES = ('supplied', 'same-demand', 'swapped-owner')
POLICIES = ('mass', 'batch_greedy', 'batch_exact')
REFUSALS = {'exact frontier local-library bound', 'exact frontier search-state bound',
            'exact frontier result bound'}
SOURCE_FILES = {
    'tests/same_information.py', 'tests/batch_generalization.py',
    'tests/generalization.py', 'src/batch.py', 'src/envelope.py',
    'src/checker.py', 'src/controller.py', 'docs/SAME-INFORMATION-DESIGN.md',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def same(left, right):
    return json.dumps(left, sort_keys=True, separators=(',', ':')) == json.dumps(right, sort_keys=True, separators=(',', ':'))


def load(path):
    return json.loads(path.read_text())


def products(cells, initial):
    subsets = [tuple(v for v in range(4) if mask & (1 << v)) for mask in range(1,16)]
    safe = [box for box in itertools.product(subsets, repeat=2)
            if all(initial[i] in box[i] for i in range(2))
            and set(itertools.product(*box)) <= cells]
    frontier = [box for box in safe if not any(box != other and all(set(a) <= set(b)
                for a,b in zip(box,other)) for other in safe)]
    return safe, frontier


def accepted(box):
    """This cohort's guards must be their exact singleton-profile encoding.

    Merely projecting a general guard onto the four candidates would miss an
    extra off-catalog term, which could admit unsafe runtime supports.
    """
    require(isinstance(box, dict) and set(box) == {'0', '1'}, 'Bad recorded owner set')
    result = []
    for owner in range(2):
        terms = box[str(owner)]
        require(isinstance(terms, list) and 1 <= len(terms) <= 4,
                'Noncanonical singleton guard')
        labels = [('left.' if owner == 0 else 'right.') + str(value) for value in range(4)]
        require(all(isinstance(term, list) and len(term) == 1 and
                    type(term[0]) is str and term[0] in labels for term in terms),
                'Noncanonical singleton guard')
        values = [labels.index(term[0]) for term in terms]
        require(values == sorted(set(values)), 'Noncanonical singleton guard')
        result.append(tuple(values))
    return tuple(result)


def relation_for(family, seed):
    """Reconstruct the six registered finite generators without importing them."""
    require(type(family) is str and family in FAMILIES and
            type(seed) is int and 7000 <= seed < 7040, 'Bad registered family/seed')
    grid = list(itertools.product(range(4), repeat=2))
    if family == 'diagonal':
        return {(a, b) for a, b in grid if a == b}
    if family == 'cycle':
        return {(a, b) for a, b in grid if (b - a) % 4 in (0, 1)}
    if family == 'staircase':
        return {(a, b) for a, b in grid if b == a or b == a + 1}
    rng = random.Random(seed * 256 ^ sum(ord(char) for char in family))
    if family == 'planted':
        rows = rng.sample(range(4), 2)
        columns = rng.sample(range(4), 2)
        planted = set(itertools.product(rows, columns))
        return planted | set(rng.sample([cell for cell in grid if cell not in planted], 4))
    return set(rng.sample(grid, 5 if family == 'sparse' else 8))


def box_key(rectangle):
    return tuple((str(owner), tuple(((('left.' if owner == 0 else 'right.') + str(value)),)
                                   for value in rectangle[owner])) for owner in range(2))


def deterministic_choices(cells, initial, frontier, training):
    """Reconstruct both different tie orders, including the mass default rule."""
    def mass(rectangle):
        return len(rectangle[0]) * len(rectangle[1])

    def terms(rectangle):
        return len(rectangle[0]) + len(rectangle[1])

    # On this uniform singleton domain, local mass is the accepted cardinality
    # and each accepted profile has one guard term. Keep all stated tie levels.
    default = min(frontier, key=lambda box: (
        -mass(box), -sum(map(len, box)), terms(box), box_key(box)))
    selected = default
    score = replay(cells, initial, default, training)['installed']
    ordered = sorted(frontier, key=lambda box: (-mass(box), terms(box), box_key(box)))
    for rectangle in ordered:
        count = replay(cells, initial, rectangle, training)['installed']
        if count > score:
            selected, score = rectangle, count
    return default, selected


def replay(cells, initial, box, schedule):
    current = list(initial)
    decisions = []
    for proposal in schedule:
        require(isinstance(proposal,list) and len(proposal)==2 and
                all(type(v) is int for v in proposal), 'Bad proposal types')
        owner, target = proposal
        require(owner in (0,1) and target in range(4), 'Bad proposal range')
        if current[owner] == target:
            decisions.append('unchanged')
        elif target in box[owner]:
            decisions.append('installed'); current[owner] = target
        else:
            decisions.append('blocked')
        require(tuple(current) in cells, 'Incompatible replay state')
    return {'installed':decisions.count('installed'), 'blocked':decisions.count('blocked'),
            'unchanged':decisions.count('unchanged'), 'final':current, 'statuses':decisions}


def greedy_reference(cells, initial, schedule):
    allowed = [[v] for v in initial]
    trace = []
    trial_count = 0
    while True:
        count_before = replay(cells, initial, allowed, schedule)['installed']
        proposals = []
        for owner, target in itertools.product((0,1), range(4)):
            if target in allowed[owner]:
                continue
            expanded = [list(part) for part in allowed]
            expanded[owner] = sorted(expanded[owner]+[target])
            if set(itertools.product(*expanded)) <= cells:
                forecast = replay(cells, initial, expanded, schedule)['installed']
                proposals.append((forecast,len(expanded[0])*len(expanded[1]),owner,target,expanded))
        if not proposals:
            return tuple(tuple(p) for p in allowed), trace, trial_count
        trial_count += len(proposals)
        forecast,mass,owner,target,allowed = sorted(proposals,key=lambda p:(-p[0],-p[1],p[2],p[3]))[0]
        trace.append({'owner':owner,'profile':target,'training_installed':forecast,
                      'gain':forecast-count_before,'mass':mass,'accepted':allowed})


def schedules_for(family, seed, percent):
    salt = sum((i+1)*ord(char) for i,char in enumerate(family))
    base = seed*1009 + salt + percent*1000003
    result = {}
    for regime, stream, owner in [('supplied',base,seed%2),
        ('same-demand',base ^ 0x157A3,seed%2), ('swapped-owner',base ^ 0x2BE71,1-seed%2)]:
        rng = random.Random(stream)
        result[regime] = [[owner if rng.random()<percent/100 else 1-owner,rng.randrange(4)] for _ in range(48)]
    return result


def check_context(context, control=False):
    require(context['status'] in ('completed','refused'), 'Unrecognized condition status')
    cells = {tuple(v) for v in context['relation']}
    require(len(cells)==len(context['relation']) and 1<=len(cells)<=8, 'Relation encoding bound')
    require(all(len(v)==2 and all(type(x) is int and x in range(4) for x in v) for v in cells), 'Bad relation values')
    initial = context['initial']
    require(isinstance(initial,list) and len(initial)==2 and
            all(type(value) is int for value in initial) and tuple(initial) in cells, 'Invalid anchor')
    if not control:
        require(type(context['preferred_owner_percent']) is int and
                context['preferred_owner_percent'] in (50,70,90), 'Bad registered demand probability')
        expected_relation = [list(cell) for cell in sorted(relation_for(context['family'], context['seed']))]
        require(same(context['relation'], expected_relation), 'Registered relation differs')
        expected_initial = sorted(cells)[random.Random(context['seed'] ^ 0x7139).randrange(len(cells))]
        require(same(initial,list(expected_initial)), 'Registered initial state differs')
        require(same(context['schedules'],schedules_for(context['family'],context['seed'],context['preferred_owner_percent'])),
                'Registered schedule differs')
    safe, frontier = products(cells, initial)
    require(context['safe_products']==len(safe) and context['frontier_size']==len(frontier), 'Product counts differ')
    if context['status']=='refused':
        require(context['reason'] in REFUSALS, 'Non-resource error reported as refusal')
        return []
    require(set(context['boxes'])==set(POLICIES), 'Missing policy guard')
    accepted_boxes = {name:accepted(context['boxes'][name]) for name in POLICIES}
    require(all(box in frontier for box in accepted_boxes.values()), 'Non-maximal or unsafe policy')
    require(len(accepted_boxes['mass'][0])*len(accepted_boxes['mass'][1]) ==
            max(len(a)*len(b) for a,b in safe), 'Mass objective mismatch')
    expected_mass, expected_exact = deterministic_choices(
        cells, initial, frontier, context['schedules']['supplied'])
    require(accepted_boxes['mass'] == expected_mass, 'Mass tie rule differs')
    require(accepted_boxes['batch_exact'] == expected_exact, 'Exact batch tie rule differs')
    greedy, trace, trials = greedy_reference(cells, initial, context['schedules']['supplied'])
    require(greedy==accepted_boxes['batch_greedy'] and same(trace,context['greedy_trace'])
            and trials==context['greedy_trial_evaluations'], 'Greedy expansion differs')
    rows = []
    require(set(context['observations'])==set(context['schedules']), 'Missing schedule observations')
    # contexts.jsonl is serialized with sorted object keys; CSV row order follows
    # the registered regime order, not the JSON parser's insertion order.
    for regime in REGIMES:
        if regime not in context['schedules']:
            continue
        schedule = context['schedules'][regime]
        optimum = max(replay(cells, initial, box, schedule)['installed'] for box in safe)
        row = {key:context[key] for key in ('family','seed','preferred_owner_percent')}
        row.update(regime=regime, proposals=len(schedule), frontier_size=len(frontier),
                   greedy_trial_evaluations=trials, static_hindsight_installed=optimum)
        require(set(context['observations'][regime])==set(POLICIES), 'Missing policy observations')
        for name, box in accepted_boxes.items():
            expected = replay(cells, initial, box, schedule)
            require(same(expected,context['observations'][regime][name]), 'Recorded endpoint event differs')
            for outcome in ('installed','blocked','unchanged'):
                row[name+'_'+outcome] = expected[outcome]
            row[name+'_regret'] = optimum-expected['installed']
        require(regime!='supplied' or row['batch_exact_regret']==0, 'Supplied exact result is suboptimal')
        row['exact_minus_greedy'] = row['batch_exact_installed']-row['batch_greedy_installed']
        rows.append(row)
    return rows


def aggregates(rows):
    result = {}
    for regime in REGIMES:
        subset = [r for r in rows if r['regime']==regime]
        result[regime] = {'schedules':len(subset), 'proposals_per_policy':sum(r['proposals'] for r in subset),
            'static_hindsight_installed':sum(r['static_hindsight_installed'] for r in subset),
            'policies':{name:{key:sum(r[name+'_'+key] for r in subset)
                       for key in ('installed','blocked','unchanged','regret')} for name in POLICIES},
            'exact_vs_greedy':{'wins':sum(r['exact_minus_greedy']>0 for r in subset),
                              'ties':sum(r['exact_minus_greedy']==0 for r in subset),
                              'losses':sum(r['exact_minus_greedy']<0 for r in subset)}}
    return result


def check(directory=ROOT/'results/same-information'):
    directory = Path(directory)
    registration = load(directory/'registration.json')
    sources = registration['source_sha256']
    require(isinstance(sources,dict) and set(sources)==SOURCE_FILES, 'Wrong source inventory')
    for name, expected in sources.items():
        source = (ROOT/name).resolve()
        snapshot = (directory/'source-preimage'/name).resolve()
        require(source.is_relative_to(ROOT.resolve()) and snapshot.is_relative_to((directory/'source-preimage').resolve()), 'Source path escape')
        require(hashlib.sha256(source.read_bytes()).hexdigest()==expected and
                hashlib.sha256(snapshot.read_bytes()).hexdigest()==expected, 'Source identity differs: '+name)
    require(registration['seeds']==[7000,7039] and registration['preferred_owner_percent']==[50,70,90]
            and registration['structural_contexts']==240 and registration['planned_conditions']==720
            and registration['steps']==48 and registration['regimes']==list(REGIMES)
            and registration['families']==list(FAMILIES), 'Registration differs')
    contexts = [json.loads(line) for line in (directory/'contexts.jsonl').read_text().splitlines()]
    expected_ids = list(itertools.product(FAMILIES,range(7000,7040),(50,70,90)))
    require([(c['family'],c['seed'],c['preferred_owner_percent']) for c in contexts]==expected_ids, 'Missing/reordered conditions')
    rows = [row for context in contexts for row in check_context(context)]
    with (directory/'observations.csv').open(newline='') as stream:
        saved = list(csv.DictReader(stream))
    require(len(saved)==len(rows), 'CSV row denominator differs')
    for actual, expected in zip(saved,rows):
        require(actual=={k:str(v) for k,v in expected.items()}, 'CSV differs from literal event reconstruction')
    summary = load(directory/'summary.json')
    complete = sum(c['status']=='completed' for c in contexts)
    refusals = [{k:c[k] for k in ('family','seed','preferred_owner_percent','reason')} for c in contexts if c['status']=='refused']
    checks = {'status':'PASS','planned_conditions':720,'completed_conditions':complete,
              'refused_conditions':len(refusals),'refusals':refusals,'schedules':len(rows),
              'proposals_per_policy':sum(r['proposals'] for r in rows),
              'per_event_policy_observations':3*sum(r['proposals'] for r in rows),
              'by_regime':aggregates(rows),
              'by_demand':{str(p):aggregates([r for r in rows if r['preferred_owner_percent']==p]) for p in (50,70,90)},
              'by_family':{f:aggregates([r for r in rows if r['family']==f]) for f in FAMILIES},
              'mismatches':0,'unsafe_guarded_snapshots':0,'source_unchanged':True,'scope':registration['scope']}
    for key, expected in checks.items():
        require(same(summary[key],expected),'Summary differs: '+key)
    control = load(directory/'mechanism-control.json')
    require(control['context']['relation']==[[0,0],[0,1],[0,2],[0,3],[1,0],[2,0]] and
            control['context']['initial']==[0,0] and control['context']['schedules']=={
              'supplied':[[0,v] for _ in range(10) for v in (1,2)]+[[1,1],[1,0]]}, 'Mechanism input differs')
    derived = check_context(control['context'],control=True)
    require(len(derived)==1 and same(derived[0],control['row']), 'Mechanism result differs')
    require(derived[0]['batch_greedy_installed']==2 and derived[0]['batch_exact_installed']==20, 'Mechanism gap differs')
    return {'status':'PASS','conditions':len(contexts),'schedules':len(rows),
            'per_event_policy_observations':checks['per_event_policy_observations'],
            'source_files':len(sources),'same_information_greedy_control':[2,20]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,default=ROOT/'results/same-information')
    print(json.dumps(check(parser.parse_args().directory),sort_keys=True))
