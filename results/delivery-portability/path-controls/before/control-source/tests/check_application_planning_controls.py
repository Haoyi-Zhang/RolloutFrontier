"""Standard-library independent check of path-order and fallback observations."""
from __future__ import annotations
import argparse
from collections import deque,Counter
import gzip
import itertools
import json
from pathlib import Path
from tests.check_application_rollout import safe,phase,require,read,validate_plan,PROFILES


def check(application_results,output):
    states=[s for s in itertools.product(range(4),repeat=3) if safe(s)];valid=set(states)
    with gzip.open(application_results/'catalog-plans.jsonl.gz','rt') as stream:
        original={(tuple(r['source']),tuple(r['target'])):r['plan'] for r in map(json.loads,stream)}
    recognition=read(output/'recognition.json')
    require(recognition['recognized'] is False and recognition['checked_placements']==64
            and recognition['compatible_placements']==36, 'incorrect fallback recognition')
    low=[min(s[i] for s in states) for i in range(3)];high=[max(s[i] for s in states) for i in range(3)]
    bounds=[[max(s[i]-s[j] for s in states) for j in range(3)] for i in range(3)]
    witness=tuple(recognition['hull_counterexample'])
    require(not safe(witness) and all(low[i]<=witness[i]<=high[i] for i in range(3))
            and all(witness[i]-witness[j]<=bounds[i][j] for i in range(3) for j in range(3)), 'invalid hull counterexample')
    orders=list(itertools.permutations(range(3)))
    counters={order:Counter() for order in orders};seen=set();portfolio=Counter()
    with gzip.open(output/'plans.jsonl.gz','rt') as stream:
        for row in map(json.loads,stream):
            source,target=tuple(row['source']),tuple(row['target']);key=(source,target)
            require(key in original and key not in seen, 'fallback goal inventory');seen.add(key)
            answer=row['answer'];old=original[key]
            require(answer['strategy']=='complete-frontier' and answer['structure']==recognition, 'fallback route differs')
            require(answer['status']==old['status'] and answer['cost']==old['cost'], 'fallback answer differs from executed backend')
            if answer['status']=='planned':validate_plan(answer,source,target)
            require([tuple(r['order']) for r in row['routes']]==orders, 'path-order inventory')
            phases=[]
            for route in row['routes']:
                order=tuple(route['order']);path=route['path']
                if answer['status']=='unreachable':
                    require(path is None and route['phases'] is None, 'unreachable route reported')
                    continue
                # Reconstruct this exact priority policy independently. Paths
                # contain only directed +1 steps, so every found route is also
                # minimum-installation in this physical catalog.
                todo=deque([source]);parents={source:None}
                while todo and target not in parents:
                    here=todo.popleft()
                    for node in order:
                        next_state=list(here);next_state[node]+=1;next_state=tuple(next_state)
                        if next_state in valid and next_state not in parents:
                            parents[next_state]=here;todo.append(next_state)
                require(target in parents,'route lost reachable goal')
                expected=[];cursor=target
                while cursor is not None:expected.append(cursor);cursor=parents[cursor]
                expected.reverse()
                require(path==[list(x) for x in expected],'priority path differs')
                dp=[0]+[1000]*(len(expected)-1)
                for finish in range(1,len(expected)):
                    dp[finish]=min(dp[begin]+1 for begin in range(finish) if phase(expected[begin],expected[finish]))
                require(route['phases']==dp[-1],'segmentation is not optimal for selected path')
                phases.append(dp[-1])
                if source!=target:
                    counters[order]['phases']+=dp[-1]
                    counters[order]['gaps']+=dp[-1]>answer['cost']['phases']
                    counters[order]['queries']+=1
            if source!=target and phases:
                portfolio['queries']+=1;portfolio['phases']+=min(phases)
                portfolio['gaps']+=min(phases)>answer['cost']['phases']
    require(seen==set(original) and len(seen)==1296,'incomplete fallback experiment')
    stats=read(output/'statistics.json')
    require(stats['queries']==stats['fallback_queries']==1296 and stats['structured_queries']==0,'incorrect fallback counter')
    summary={'status':'pass','queries':1296,'fallback_queries':1296,'hull_counterexample':list(witness),
        'priority_orders':[{'order':list(order),**dict(counters[order])} for order in orders],
        'best_of_six':dict(portfolio),'exact_total_phases':sum(p['cost']['phases'] for p in original.values() if p['status']=='planned')}
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--application-results',required=True,type=Path)
    parser.add_argument('--results',required=True,type=Path)
    parser.add_argument('--out',type=Path)
    args=parser.parse_args();value=check(args.application_results.resolve(),args.results.resolve())
    encoded=json.dumps(value,sort_keys=True,indent=2)+'\n'
    if args.out:args.out.write_text(encoded)
    print(encoded)
