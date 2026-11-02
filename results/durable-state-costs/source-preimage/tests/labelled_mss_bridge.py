"""Literal labelled-MSS control for P011 planning, not a new SAT algorithm.

Enumerates Boolean assignments and soft label subsets independently of planner
and checker internals. Original profile labels are retained before projection.
No network, live admission, device, or external solver is invoked.
"""
from __future__ import annotations

import argparse
import gzip
from itertools import product
import json
from pathlib import Path

from src.envelope import frontier_synthesize, verify_box
from src.checker import frontier_certificate, safe_envelope

ROOT = Path(__file__).resolve().parents[1]


def clause_true(clause, assignment):
    return any(bool(assignment & (1 << (abs(literal)-1))) == (literal > 0)
               for literal in clause)


def labelled_msses(hard, groups, variables):
    """Hard clauses always present; each label activates its entire clause group."""
    models = [a for a in range(1 << variables) if all(clause_true(c,a) for c in hard)]
    feasible = set()
    for labels in range(1 << len(groups)):
        if any(all(clause_true(c,a) for i,g in enumerate(groups)
                   if labels & (1 << i) for c in g) for a in models):
            feasible.add(labels)
    result = [s for s in sorted(feasible) if all(s | (1 << i) not in feasible
              for i in range(len(groups)) if not s & (1 << i))]
    return result


def rectangle_encoding(rows, columns, relation, seed):
    hard = [[seed[0]+1], [rows+seed[1]+1]]
    hard += [[-(i+1),-(rows+j+1)] for i in range(rows) for j in range(columns)
             if (i,j) not in relation]
    groups = [[[v+1]] for v in range(rows+columns)]
    return hard, groups


def raw_acceptance(box, candidates):
    flags = [any(set(term)<=set(profile) for term in box[n])
             for n in sorted(candidates) for profile in candidates[n]]
    return sum(1 << i for i,accepted in enumerate(flags) if accepted)


def relation_case(rows, columns, relation, seed):
    candidates = {"0":[[f"r{i}"] for i in range(rows)],
                  "1":[[f"c{j}"] for j in range(columns)]}
    current = {"0":candidates["0"][seed[0]],"1":candidates["1"][seed[1]]}
    branches = ([{"0":[],"1":[]}] if len(relation)==rows*columns else
                [{"0":[f"r{i}"],"1":[f"c{j}"]} for i,j in sorted(relation)])
    hard, groups = rectangle_encoding(rows,columns,relation,seed)
    msses = labelled_msses(hard,groups,rows+columns)
    plan = frontier_synthesize(branches,current,candidates)
    assert frontier_certificate(branches,current,candidates,plan)
    observed = sorted(raw_acceptance(member["box"],candidates) for member in plan["frontier"])
    assert observed == msses, (relation,seed,observed,msses)
    return dict(rows=rows,columns=columns,relation=sorted(relation),seed=seed,
                inputs=dict(branches=branches,current=current,candidates=candidates),
                hard_clauses=hard,label_groups=groups,labelled_msses=msses,
                decoded_frontier_masks=observed,selected_mass=plan["product_mass"],
                frontier=plan["frontier"],certificate_checked=True)


def guard_choice_boundary():
    """Candidate-only SAT omits minimal off-catalog supports; strong clauses fix it."""
    branches = [{"0":["a"],"1":["a"]},{"0":["b"],"1":["b"]}]
    candidates = {"0":[["a","b"]],"1":[["a","b"]]}
    current = {n:["a","b"] for n in candidates}
    unsafe = {"0":[["a"],["b"]],"1":[["a"],["b"]]}
    assert all(any(all(set(b[n])<=set(s) for n,s in zip(("0","1"),corner))
                   for b in branches) for corner in product(*candidates.values()))
    verdict = verify_box(branches,unsafe)
    assert not verdict["safe"] and not safe_envelope(branches,unsafe)
    guards = [[["a"]],[["b"]],[["a","b"]],[["a"],["b"]]]
    # q_0,0..q_1,3 select one guard per owner, z_0,z_1 name profile labels.
    hard = []
    for base in (1,5):
        hard.append(list(range(base,base+4)))
        hard += [[-x,-y] for x in range(base,base+4) for y in range(x+1,base+4)]
    forbidden = []
    for i,j in product(range(4),repeat=2):
        box = {"0":guards[i],"1":guards[j]}
        literal_safe = all(any(all(set(b[n])<=set(s) for n,s in zip(("0","1"),corner))
                              for b in branches) for corner in product(guards[i],guards[j]))
        if not literal_safe:
            hard.append([-(i+1),-(j+5)])
            forbidden.append([i,j])
    hard += [[-9,1,2,3,4],[-10,5,6,7,8]]
    groups = [[[9]],[[10]]]
    msses = labelled_msses(hard,groups,10)
    assert msses == [3]
    # The unsafe guard pair is excluded even though both profile labels fit.
    assignment = (1<<3)|(1<<7)|(1<<8)|(1<<9)
    assert not all(clause_true(c,assignment) for c in hard)
    plan = frontier_synthesize(branches,current,candidates)
    assert frontier_certificate(branches,current,candidates,plan)
    assert [raw_acceptance(m["box"],candidates) for m in plan["frontier"]] == msses
    return dict(inputs=dict(branches=branches,current=current,candidates=candidates),
                candidate_only_safe=True,unsafe_box=unsafe,strong_verdict=verdict,
                hard_clauses=hard,label_groups=groups,forbidden_guard_pairs=forbidden,
                labelled_msses=msses,production_frontier=plan["frontier"])


def run(out):
    if not __debug__:
        raise SystemExit('labelled-MSS conformance requires enabled assertions')
    out = Path(out).resolve()
    if ROOT == out or out in ROOT.parents or any(out == ROOT/name or (ROOT/name) in out.parents
                                                for name in ('src','tests','data')):
        raise ValueError('output overlaps protected artifact inputs or sources')
    out.mkdir(parents=True,exist_ok=False)
    cells = list(product(range(3),repeat=2))
    cases = members = 0
    with gzip.open(out/"relations.jsonl.gz","xt",encoding="utf-8") as stream:
        for mask in range(1,1<<9):
            relation = {cell for i,cell in enumerate(cells) if mask & (1<<i)}
            for seed in sorted(relation):
                row = relation_case(3,3,relation,seed)
                stream.write(json.dumps(row,sort_keys=True)+"\n")
                cases += 1
                members += len(row["labelled_msses"])
    objective = relation_case(2,4,{(0,j) for j in range(4)}|{(1,j) for j in range(3)},(0,0))
    sizes = [mask.bit_count() for mask in objective["labelled_msses"]]
    masses = sorted(member["product_mass"] for member in objective["frontier"])
    assert sizes == [5,5] and masses == [4,6] and objective["selected_mass"]==6
    boundary = guard_choice_boundary()
    atomic_group = labelled_msses([],[[[1],[2]], [[-1]], [[-2]]],2)
    assert atomic_group == [1,6]  # the two-clause label is removed/retained together
    result = dict(relation_count=511,seeded_cases=cases,frontier_members=members,
                  objective_counterexample=objective,guard_boundary=boundary,
                  atomic_group_msses=atomic_group,mismatches=0,
                  scope="planning acceptance-vector correspondence only; literal bounded Boolean enumeration, no solver performance or live admission claim")
    (out/"summary.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k not in {"objective_counterexample","guard_boundary"}},sort_keys=True))


if __name__=="__main__":
    if not __debug__:
        raise RuntimeError("assertions required")
    parser = argparse.ArgumentParser()
    parser.add_argument("--out",required=True)
    run(parser.parse_args().out)
