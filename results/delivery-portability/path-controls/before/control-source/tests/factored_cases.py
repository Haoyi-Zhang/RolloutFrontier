"""Declared physical graphs and real schema contracts for factored execution."""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from src.factored_planner import FactoredChainPlanner
from src.schema_contracts import actual_probes


@lru_cache(maxsize=None)
def probe_for(family):
    return next(row for row in actual_probes() if row['family'] == family)


def graph_case(family='enum-alias', count=3, topology='cycle', deployment=None):
    if type(count) is not int or count < 2: raise ValueError('physical owner count')
    probe = probe_for(family)
    owners = [f'owner-{i:03d}' for i in range(count)]
    if topology == 'cycle':
        edges = [(owners[i], owners[(i+1)%count]) for i in range(count)]
        workflow = [{'id':f'h{i:04d}', 'owner':owners[i%count],
                     'parents':[] if i == 0 else [f'h{i-1:04d}']} for i in range(count+1)]
    elif topology == 'chain':
        edges = list(zip(owners, owners[1:]))
        workflow = [{'id':f'h{i:04d}', 'owner':owner,
                     'parents':[] if i == 0 else [f'h{i-1:04d}']} for i,owner in enumerate(owners)]
    elif topology == 'fanout-join':
        if count < 4 or (count-2)%3: raise ValueError('fanout-join count must be 2 plus a multiple of 3')
        layers = [[owners[0]], *[owners[i:i+3] for i in range(1,count-1,3)], [owners[-1]]]
        edges = [(a,b) for left,right in zip(layers,layers[1:]) for a in left for b in right]
        workflow = []
        previous = []
        for layer in layers:
            current = []
            for owner in layer:
                step = 'h'+owner.split('-')[-1]
                workflow.append({'id':step,'owner':owner,'parents':list(previous)})
                current.append(step)
            previous = current
    else:
        raise ValueError('physical graph topology')
    factors = [{'id':f'edge-{i:04d}', 'branches':[
        {a:['emit:'+cls], b:['accept:'+cls]} for cls in probe['classes']]}
        for i,(a,b) in enumerate(edges)]
    catalog = {owner:deepcopy(probe['profiles']) for owner in owners}
    transitions = {owner:[{'source':deepcopy(a),'target':deepcopy(b)}
                         for a,b in zip(probe['profiles'],probe['profiles'][1:])]
                   for owner in owners}
    initial = {owner:deepcopy(probe['profiles'][0]) for owner in owners}
    target = {owner:deepcopy(probe['profiles'][-1]) for owner in owners}
    plan = FactoredChainPlanner(factors,catalog,transitions).plan(initial,target)
    registry = {'deployment':deployment or f'{family}-{topology}-{count}',
                'owners':{owner:{'family':family,'initial':initial[owner],
                                 'catalog':deepcopy(plan['catalog'][owner])} for owner in owners}}
    return {'family':family,'topology':topology,'owners':owners,'edges':[list(e) for e in edges],
            'workflow':workflow,'registry':registry,'plan':plan}
