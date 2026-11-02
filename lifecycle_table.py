"""Verify retained source bytes and derive the table, without executing sources."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
from statistics import median

ROOT=Path(__file__).resolve().parent
# Identity of the original sorted path/hash pairs, not of today's source tree.
SOURCE_PAIRS_SHA256='f06a23a3641df0f075b73d1246662404ff2de96d7dc12879554546cbc16ef777'
# Independent consequences of the retained tests/full_path_costs.py fixture,
# NOT values learned from measurements.json or from today's planner execution.
# Its branch cells are (a0,b0), (a0,b1), (a0,b2), (a1,b0). Fixed
# keeps the first cell; greedy expands a first (2x1); mass chooses 1x3;
# batch trains on a1/a0 and chooses 2x1. Test proposals alternate 1/0
# twelve times on a (matched) or b (mismatched), starting at a0/b0.
# A disallowed 1 leaves state at 0: twelve blocked and twelve unchanged;
# an allowed 1 permits all 24 alternating installs. Unused padding atoms
# change neither guards nor equality. Each pair is indexed by mismatch.
# These count constraints do not authenticate the recorded timing values.
FIXTURE_OUTCOMES={
    'fixed':((0,12,12),(0,12,12)),
    'greedy':((24,0,0),(0,12,12)),
    'mass':((0,12,12),(24,0,0)),
    'batch':((24,0,0),(0,12,12)),
}
def require(condition,message):
    if not condition:raise ValueError(message)

def verify_sources():
    """Resolve every recorded path/hash as data, not as an import or a rerun."""
    data=ROOT/'results/durable-state-costs'
    environment=json.loads((data/'environment.json').read_text(encoding='utf-8'))
    require(type(environment) is dict,'source environment schema')
    entries=environment.get('sources')
    require(type(entries) is list and len(entries)>0,'source inventory schema')
    seen=set()
    for entry in entries:
        require(type(entry) is dict and set(entry)=={'path','sha256'},'source entry schema')
        rel,digest=entry['path'],entry['sha256']
        require(type(rel) is str and re.fullmatch(r'(?:src|tests)/[a-z_][a-z0-9_]*\.py',rel)
                is not None,'source path schema')
        require(rel not in seen,'duplicate source path')
        require(type(digest) is str and re.fullmatch(r'[0-9a-f]{64}',digest)
                is not None,'source digest schema')
        seen.add(rel)
    original_pairs=json.dumps(sorted((entry['path'],entry['sha256']) for entry in entries),
                              separators=(',',':')).encode('ascii')
    require(hashlib.sha256(original_pairs).hexdigest()==SOURCE_PAIRS_SHA256,
            'original source inventory differs')
    # Reuse already-preserved controller/network bytes rather than duplicating
    # them into this cohort. Each candidate must match this cohort's own hash.
    bases=(ROOT,data/'source-preimage',ROOT/'results/effect-drain/source-preimage')
    resolved={}
    for entry in entries:
        rel,digest=entry['path'],entry['sha256']
        for base in bases:
            candidate=base/rel
            require(candidate.resolve().is_relative_to(base.resolve()),'source path escapes root '+rel)
            try:
                raw=candidate.read_bytes()
            except FileNotFoundError:
                continue
            except OSError as error:
                raise ValueError('measured source unreadable '+rel) from error
            if hashlib.sha256(raw).hexdigest()==digest:
                resolved[rel]=candidate.relative_to(ROOT).as_posix()
                break
        else:
            raise ValueError('measured source missing or differs '+rel)
    return resolved

def derive(data):
    require(type(data) is dict and data.get('status')=='completed','measurement completion')
    for field,value in (('repeats',3),('trials',48),('proposals_total',1152)):
        require(type(data.get(field)) is int and data[field]==value,'measurement denominator '+field)
    rows=data.get('rows');require(type(rows) is list and len(rows)==48,'trial denominator')
    grouped=defaultdict(list)
    for row in rows:
        require(type(row) is dict,'measurement row schema')
        require(type(row['padding_atoms']) is int and row['padding_atoms'] in (0,11999),'payload')
        require(type(row['mismatch']) is bool and row['policy'] in ('fixed','greedy','mass','batch'),'policy/schedule')
        require(type(row['repeat']) is int and row['repeat'] in (0,1,2),'repeat identity')
        for field in ('installed','blocked','unchanged'):
            require(type(row.get(field)) is int and 0<=row[field]<=24,'outcome count '+field)
        require(type(row.get('proposals')) is int and row['proposals']==24,'proposal count')
        require(row['installed']+row['blocked']+row['unchanged']==24,'proposal accounting')
        require(tuple(row[field] for field in ('installed','blocked','unchanged'))==
                FIXTURE_OUTCOMES[row['policy']][row['mismatch']],
                'fixture outcome mismatch for '+row['policy']+' mismatch='+str(row['mismatch']))
        require(all(type(row.get(field)) is int and row[field]==0
                    for field in ('safety_violations','refused_admissions')),'scientific outcome')
        require(type(row['full_lifecycle_ns']) is int and row['full_lifecycle_ns']>0,'lifecycle time')
        require(set(row['timings_ns'])=={'acquisition_ns','external_check_ns','origin_reopen_ns',
            'owner_reopen_ns','planning_ns','retirement_ns','shutdown_ns','startup_ns','updates_ns','use_ns'},'stage boundary')
        require(all(type(x) is int and x>=0 for x in row['timings_ns'].values()),'stage time')
        require(row['full_lifecycle_ns']>=sum(row['timings_ns'].values()),'lifecycle/stage boundary')
        grouped[(row['padding_atoms'],row['mismatch'],row['policy'])].append(row)
    require(sum(row['proposals'] for row in rows)==data['proposals_total'],'proposal denominator')
    require(len(grouped)==16,'group product')
    index={}
    for key,group in grouped.items():
        require(sorted(x['repeat'] for x in group)==[0,1,2],'missing/duplicate repetition')
        require(len({(x['installed'],x['blocked'],x['unchanged']) for x in group})==1,'inconsistent repeated outcome')
        # Match the producer's ns-derived median exactly; round only for display.
        index[key]=(tuple(group[0][field] for field in ('installed','blocked','unchanged')),
                    median(x['full_lifecycle_ns'] for x in group)/1e6)
    require(type(data.get('groups')) is list,'summary schema')
    for group in data['groups']:
        require(type(group) is dict,'summary row schema')
        require(type(group.get('padding_atoms')) is int and group['padding_atoms'] in (0,11999),'summary payload')
        require(type(group.get('mismatch')) is bool and group.get('policy') in ('fixed','greedy','mass','batch'),'summary policy/schedule')
        for field in ('installed','blocked','unchanged'):
            require(type(group.get(field)) is int and 0<=group[field]<=24,'summary outcome count '+field)
    supplied={(x['padding_atoms'],x['mismatch'],x['policy']):x for x in data['groups']}
    require(len(supplied)==len(data['groups'])==16 and set(supplied)==set(index),'summary group product')
    for key,(outcomes,value) in index.items():
        require(tuple(supplied[key][field] for field in ('installed','blocked','unchanged'))==outcomes
                and type(supplied[key]['full_lifecycle_median_ms']) in (int,float)
                and supplied[key]['full_lifecycle_median_ms']==value,'raw/summary disagreement')
    # The table prints one shared outcome cell for both payload sizes. It must
    # not silently discard a payload-dependent outcome hidden by that collapse.
    for mismatch in (False,True):
        for policy in ('fixed','greedy','mass','batch'):
            require(index[(0,mismatch,policy)][0]==index[(11999,mismatch,policy)][0],
                    'payload outcomes disagree for shared table cell')
    labels={'fixed':'Fixed','greedy':'Greedy','mass':'Max mass','batch':'Batch choice'}
    lines=['% Derived from results/durable-state-costs/measurements.json; all48rows/1152proposals.']
    for policy,label in labels.items():
        installed='/'.join(str(index[(0,m,policy)][0][0]) for m in (False,True))
        costs=['/'.join(f'{index[(padding,m,policy)][1]:.1f}' for m in (False,True)) for padding in (0,11999)]
        lines.append(label+' & '+installed+' & '+' & '.join(costs)+r' \\')
    return '\n'.join(lines)+'\n'

def table():
    verify_sources()
    return derive(json.loads((ROOT/'results/durable-state-costs/measurements.json').read_text(encoding='utf-8')))

if __name__=='__main__':print(table(),end='')
