"""Bounded exact oracles and state-space checks, not mechanized general proofs."""
from __future__ import annotations
from collections import deque
from itertools import combinations, product
import copy, json, resource, time
from src.controller import Endpoint, canonical, minimum_obstruction, closure, MAX_SEQ
from src.checker import obstruction, safe_envelope, endpoint_invariant, certificate
from src.envelope import verify_box, synthesize


def powerset(values):
    return [set(c) for n in range(len(values)+1) for c in combinations(values,n)]


def witness_oracle():
    universe=[(0,'a'),(0,'b'),(1,'a'),(1,'b')]
    subsets=powerset(universe)
    checked, incompatible = 0,0
    for branches in product(subsets,repeat=3):
        for available in subsets:
            answer=minimum_obstruction(list(branches),available)
            feasible=any(b.issubset(available) for b in branches)
            if feasible:
                assert answer is None
            else:
                incompatible+=1
                assert answer is not None and obstruction(list(branches),available,answer,True)
                false=sorted(set().union(*branches)-available)
                exact=next(list(c) for k in range(len(false)+1) for c in combinations(false,k)
                           if all(set(c)&b for b in branches))
                assert answer==exact
            checked+=1
    return dict(instances=checked,incompatible=incompatible,atoms=4,branches=3,
                oracle='enumerate false-atom subsets by cardinality and lexical order')


def rectangles():
    checked, safe=0,0
    profiles=[0,1,2]
    subsets=[sorted(s) for s in powerset(profiles) if s]
    # Every nonempty 3x3 relation except the 9-branch full relation (bound 8).
    for bits in range(1,511):
        pairs={(i,j) for i in profiles for j in profiles if bits&(1<<(3*i+j))}
        branches=[{'0':[f'a{i}'],'1':[f'b{j}']} for i,j in sorted(pairs)]
        for left,right in product(subsets,repeat=2):
            box={'0':[[f'a{i}'] for i in left],'1':[[f'b{j}'] for j in right]}
            expected=all((i,j) in pairs for i in left for j in right)
            producer=verify_box(branches,box)['safe']
            checker=safe_envelope(branches,box)
            assert producer==checker==expected
            checked+=1; safe+=expected
    # Greedy row-first growth is maximal but loses to a wider rectangle.
    pairs=[(0,j) for j in range(7)]+[(1,0)]
    b=[{'0':[f'a{i}'],'1':[f'b{j}']} for i,j in pairs]
    plan=synthesize(b,{'0':['a0'],'1':['b0']},
                    {'0':[['a0'],['a1']],'1':[[f'b{j}'] for j in range(7)]})
    volume=len(plan['box']['0'])*len(plan['box']['1'])
    assert volume==2 and not plan['bounded']
    optimum=max(len(L)*len(R) for L in powerset([0,1]) if 0 in L
                for R in powerset(list(range(7))) if 0 in R
                and all((i,j) in pairs for i in L for j in R))
    assert optimum==7
    return dict(instances=checked,safe=safe,relations=510,boxes_per_relation=49,
                greedy_counterexample=dict(pairs=pairs,seed=[0,0],greedy_volume=volume,
                                          optimal_volume=optimum,plan=plan))


def endpoint_states(policy='predicate',depth=6):
    e=Endpoint(0,['a'],window=2,policy=policy)
    actions=[dict(op='prepare',origin=0,sequence=s,manifest=f'm{s}',requires=req)
             for s in (1,2) for req in (['a'],['b'])]
    actions += [dict(op='close',origin=0,sequence=s) for s in (1,2)]
    actions += [dict(op='install',support=s) for s in ([],['a'],['b'],['a','b'])]
    initial=canonical(e.state); queue=deque([(initial,[])])
    seen={initial}; transitions=0
    while queue:
        state,path=queue.popleft()
        if len(path)>=depth: continue
        for action in actions:
            x=Endpoint(0,[],window=2,policy=policy); x.state=json.loads(state)
            answer=x.handle(action); transitions+=1
            next_path=path+[dict(request=action,response=answer)]
            if not endpoint_invariant(x.state):
                return dict(policy=policy,depth=depth,states=len(seen),transitions=transitions,
                            violation=next_path)
            encoded=canonical(x.state)
            if encoded not in seen:
                seen.add(encoded); queue.append((encoded,next_path))
    return dict(policy=policy,depth=depth,states=len(seen),transitions=transitions,violation=None)


def directed():
    n=0
    e=Endpoint(0,['a'],window=2)
    assert e.close(0,2)['status']=='closed'; n+=1
    assert e.prepare(0,2,'late',['a'])['status']=='closed'; n+=1
    assert e.prepare(0,3,'overflow',['a'])['status']=='window'; n+=1
    assert e.close(0,1)['status']=='closed' and e.state['floor'][0]==2; n+=1
    assert e.prepare(0,1,'late',['a'])['status']=='closed'; n+=1
    assert e.prepare(0,3,'bound',['a'])['status']=='held'; n+=1
    assert e.prepare(0,3,'different',['a'])['status']=='binding-conflict'; n+=1
    assert e.install(['a','b'])['status']=='installed'; n+=1
    assert e.install(['a'])['status']=='installed' and e.state['generation']==2; n+=1
    assert e.use(0,3,'bound')['status']=='used'; n+=1
    assert e.use(0,3,'wrong')['status']=='not-authorized'; n+=1
    assert e.install(['b'])['status']=='blocked'; n+=1
    assert closure(['a'],{'a':['b'],'b':['a','c']})==['a','b','c']; n+=1
    try: closure(['0'],{str(i):[str(i+1)] for i in range(97)})
    except ValueError: n+=1
    else: raise AssertionError('closure bound not enforced')
    e.state['generation']=MAX_SEQ
    assert e.install(['a','b'])['status']=='generation-exhausted'; n+=1
    assert safe_envelope([{'0':['a']}],{'0':[[]]}) is False; n+=1
    assert safe_envelope([{'0':'a'}],{'0':[['a']]}) is False; n+=1
    return dict(assertions=n)


def run():
    start=time.perf_counter(); cpu=time.process_time()
    w=witness_oracle(); r=rectangles(); d=directed()
    positive=endpoint_states(); negative=endpoint_states('unguarded')
    assert positive['violation'] is None and negative['violation'] is not None
    return dict(witness=w,rectangles=r,directed=d,state_space=positive,
                negative_control=negative,cpu_seconds=time.process_time()-cpu,
                wall_seconds=time.perf_counter()-start,
                peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)

if __name__=='__main__': print(json.dumps(run(),indent=2,sort_keys=True))
