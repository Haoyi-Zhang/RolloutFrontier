"""Paired seed sensitivity, a schedule counterexample, and bounded dense stress.

Consumes the generated holdout CSV, not a private or external workload.  The
algorithm/checker are unchanged.  Failure cases are retained rather than excluded.
"""
from __future__ import annotations
import csv
import json
import random
import resource
import sys
import time
from itertools import combinations
from pathlib import Path
from src.envelope import frontier_synthesize
from src.checker import frontier_certificate


def quantile(values: list[float], q: float) -> float:
    values = sorted(values)
    k = (len(values) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


def paired_analysis(path: Path) -> dict:
    with path.open(newline='') as handle:
        rows = list(csv.DictReader(handle))
    families = sorted({r['family'] for r in rows})
    seeds = sorted({int(r['seed']) for r in rows})
    lookup = {(r['family'], int(r['seed'])): r for r in rows}
    if len(lookup) != len(rows) or len(rows) != len(families) * len(seeds):
        raise ValueError('holdout must have exactly one matched case per family/seed')
    differences = {f: [int(lookup[f,s]['exact_installed']) -
                       int(lookup[f,s]['greedy_installed']) for s in seeds] for f in families}
    # Resampling the seed jointly across the fixed families preserves the paired
    # design. No population claim about external workloads is made.
    rng = random.Random(20260923)
    reps = 4000
    distributions = {f: [] for f in families}
    aggregate = []
    for _ in range(reps):
        indices = [rng.randrange(len(seeds)) for _ in seeds]
        means = [sum(differences[f][i] for i in indices) / len(seeds) for f in families]
        aggregate.append(sum(means) / len(families))
        for f, mean in zip(families, means):
            distributions[f].append(mean)
    by_family = []
    for f in families:
        subset = [r for r in rows if r['family'] == f]
        by_family.append(dict(family=f, cases=len(subset),
            exact_installed=sum(int(r['exact_installed']) for r in subset),
            greedy_installed=sum(int(r['greedy_installed']) for r in subset),
            central_installed=sum(int(r['central_installed']) for r in subset),
            difference=sum(differences[f]), mean_difference=sum(differences[f])/len(seeds),
            conditional_percentile_95=[quantile(distributions[f],.025),quantile(distributions[f],.975)]))
    return dict(cases=len(rows), seed_clusters=len(seeds), fixed_families=families,
        bootstrap_seed=20260923, bootstrap_repetitions=reps,
        exact_installed=sum(r['exact_installed'] for r in by_family),
        greedy_installed=sum(r['greedy_installed'] for r in by_family),
        mean_difference=sum(sum(v) for v in differences.values())/len(rows),
        conditional_percentile_95=[quantile(aggregate,.025),quantile(aggregate,.975)],
        by_family=by_family,
        interpretation='conditional paired-seed resampling over six fixed synthetic families; not external-population uncertainty')


def schedule_counterexample(horizon: int = 100) -> dict:
    if type(horizon) is not int or horizon < 1:
        raise ValueError('positive integer horizon required')
    relation = {(0,0),(0,1),(0,2),(1,0)}
    branches = [{'0':[f'a.{a}'],'1':[f'b.{b}']} for a,b in sorted(relation)]
    current = {'0':['a.0'],'1':['b.0']}
    candidates = {'0':[['a.0'],['a.1']], '1':[['b.0'],['b.1'],['b.2']]}
    plan = frontier_synthesize(branches,current,candidates)
    assert frontier_certificate(branches,current,candidates,plan)
    assert plan['product_mass'] == 3 and plan['frontier_size'] == 2
    assert plan['accepted_profiles']['0'] == [['a.0']]
    exact = [0,0]; alternative = [0,0]; installed = [0,0]
    for _ in range(horizon):
        for value in [1,0]:
            if value == 0:  # only a.0 is accepted by the selected maximum-mass box
                if exact[0] != value: installed[0] += 1
                exact[0] = value
            if alternative[0] != value: installed[1] += 1
            alternative[0] = value
            assert tuple(exact) in relation and tuple(alternative) in relation
    assert installed == [0,2*horizon]
    return dict(horizon=horizon, proposals=2*horizon, selected_mass=3,
        alternative_mass=2, selected_installed=installed[0], alternative_installed=installed[1],
        frontier_members=2, safety_violations=0,
        claim='no positive worst-case scheduled-install ratio for frozen maximum-product selection relative to another frozen safe product')


def stress_case(branch_count: int, owners: int, seed: int, budget: int) -> dict:
    names = [f'c.{i}' for i in range(branch_count)]
    nodes = [str(i) for i in range(owners)]
    branches = [{n:[a] for n in nodes} for a in names]
    current = {n:list(names) for n in nodes}
    candidates = {}
    for n in nodes:
        pairs = list(combinations(names,2))
        random.Random(seed*101 + int(n)).shuffle(pairs)
        candidates[n] = [list(p) for p in pairs[:min(4,9-branch_count)]]
    started = time.perf_counter_ns()
    result = dict(branches=branch_count, owners=owners, seed=seed, state_budget=budget)
    try:
        plan = frontier_synthesize(branches,current,candidates,max_states=budget)
    except ValueError as exc:
        if str(exc) != 'exact frontier search-state bound':
            raise
        result.update(status='rejected_search_budget', frontier_size=None,
                      product_mass=None, states=None, certificate_checked=False)
    else:
        assert frontier_certificate(branches,current,candidates,plan)
        result.update(status='exact', frontier_size=plan['frontier_size'],
            product_mass=plan['product_mass'], states=plan['search']['states'],
            certificate_checked=True)
    result['solver_wall_ns'] = time.perf_counter_ns()-started
    return result


def run(out: Path) -> dict:
    cpu = time.process_time(); wall = time.perf_counter()
    paired = paired_analysis(out/'generalization.csv')
    rows = [stress_case(b,n,s,k) for b in [3,4] for n in [2,3]
            for s in [3000,3001,3002] for k in [400,2000]]
    for row in rows:
        if row['state_budget'] != 400 or row['status'] != 'exact': continue
        partner = next(r for r in rows if all(r[x]==row[x] for x in ['branches','owners','seed']) and r['state_budget']==2000)
        assert partner['status']=='exact'
        assert (row['product_mass'],row['frontier_size'])==(partner['product_mass'],partner['frontier_size'])
    completed = [r for r in rows if r['status']=='exact']
    answer = dict(scope='journal supplementary analysis of frozen implementation and synthetic domains',
        paired=paired, schedule_counterexample=schedule_counterexample(),
        dense_stress=dict(calls=len(rows), distinct_instances=len(rows)//2,
            completed=len(completed), rejected=len(rows)-len(completed),
            max_completed_states=max(r['states'] for r in completed),
            max_frontier_size=max(r['frontier_size'] for r in completed),rows=rows),
        cpu_seconds=time.process_time()-cpu,wall_seconds=time.perf_counter()-wall,
        peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    (out/'journal-analysis.json').write_text(json.dumps(answer,indent=2,sort_keys=True)+'\n')
    return answer

if __name__=='__main__':
    if len(sys.argv)!=2: raise SystemExit('usage: python -m tests.journal_analysis OUTPUT_DIR')
    print(json.dumps(run(Path(sys.argv[1])),sort_keys=True))
