"""Path-order sensitivity and automatic fallback on the retained ProtoJSON catalog."""
from __future__ import annotations
import argparse
from collections import deque
import gzip
import itertools
import json
from pathlib import Path


def run(results, output):
    from src.structured_planner import CertifiedGoalPlanner
    if output.exists() and any(output.iterdir()):
        raise ValueError('use an empty output directory')
    output.mkdir(parents=True, exist_ok=True)
    source = json.loads((results / 'plan.json').read_text())
    inputs = {key: source[key] for key in ('branches','catalog','transitions')}
    # The raw study orders physical profiles by migration stage, preserving
    # separate accepting/emitting handlers despite overlapping projections.
    names = ('legacy','accepting','emitting','current')
    profiles = {node: [next(p for p in inputs['catalog'][node] if 'program:'+name in p)
                       for name in names] for node in inputs['catalog']}
    def compatible(state):
        return any(all(set(branch[str(i)]) <= set(profiles[str(i)][state[i]]) for i in range(3))
                   for branch in inputs['branches'])
    states = [state for state in itertools.product(range(4),repeat=3) if compatible(state)]
    valid = set(states)
    def safe_segment(path):
        local = [sorted({point[i] for point in path}) for i in range(3)]
        return all(point in valid for point in itertools.product(*local))
    planner = CertifiedGoalPlanner(inputs['branches'],inputs['catalog'],inputs['transitions'])
    (output/'inputs.json').write_text(json.dumps(inputs,sort_keys=True,indent=2)+'\n')
    (output/'recognition.json').write_text(json.dumps(planner.recognition(),sort_keys=True,indent=2)+'\n')
    with gzip.open(output/'plans.jsonl.gz','wt') as stream:
        for start in states:
            by_order = {}
            for order in itertools.permutations(range(3)):
                todo = deque([start]); paths = {start:[start]}
                while todo:
                    current = todo.popleft()
                    for node in order:
                        target = tuple(value+(i==node) for i,value in enumerate(current))
                        if target in valid and target not in paths:
                            paths[target]=paths[current]+[target];todo.append(target)
                by_order[order] = paths
            for target in states:
                answer = planner.plan({str(i):profiles[str(i)][start[i]] for i in range(3)},
                                      {str(i):profiles[str(i)][target[i]] for i in range(3)})
                routes=[]
                for order,paths in by_order.items():
                    if target not in paths:
                        routes.append({'order':order,'path':None,'phases':None})
                        continue
                    path=paths[target];cost=[0]+[len(path)+1]*(len(path)-1)
                    for end in range(1,len(path)):
                        for begin in range(end):
                            if safe_segment(path[begin:end+1]):cost[end]=min(cost[end],cost[begin]+1)
                    routes.append({'order':order,'path':path,'phases':cost[-1]})
                stream.write(json.dumps({'source':start,'target':target,'answer':answer,'routes':routes},sort_keys=True)+'\n')
    (output/'statistics.json').write_text(json.dumps(planner.statistics(),sort_keys=True,indent=2)+'\n')
    from tests.check_application_planning_controls import check
    summary=check(results,output)
    (output/'summary.json').write_text(json.dumps(summary,sort_keys=True,indent=2)+'\n')
    print(json.dumps(summary,sort_keys=True))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--application-results',required=True,type=Path)
    parser.add_argument('--out',required=True,type=Path)
    args=parser.parse_args();run(args.application_results.resolve(),args.out.resolve())
