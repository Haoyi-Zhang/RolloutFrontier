"""Derive the manuscript table independently from every current retained row."""
from collections import defaultdict
import json
from pathlib import Path
from statistics import median

ROOT=Path(__file__).resolve().parent
def require(condition,message):
    if not condition:raise ValueError(message)

def derive(data):
    require(data['status']=='completed' and data['repeats']==3,'measurement completion')
    rows=data['rows'];require(len(rows)==48 and data['trials']==48,'trial denominator')
    require(sum(x['proposals'] for x in rows)==data['proposals_total']==1152,'proposal denominator')
    grouped=defaultdict(list)
    for row in rows:
        require(type(row['padding_atoms']) is int and row['padding_atoms'] in (0,11999),'payload')
        require(type(row['mismatch']) is bool and row['policy'] in ('fixed','greedy','mass','batch'),'policy/schedule')
        require(type(row['repeat']) is int and row['repeat'] in (0,1,2),'repeat identity')
        require(row['proposals']==24 and row['installed']+row['blocked']+row['unchanged']==24,'proposal accounting')
        require(row['safety_violations']==0 and row['refused_admissions']==0,'scientific outcome')
        require(type(row['full_lifecycle_ns']) is int and row['full_lifecycle_ns']>0,'lifecycle time')
        require(set(row['timings_ns'])=={'acquisition_ns','external_check_ns','origin_reopen_ns',
            'owner_reopen_ns','planning_ns','retirement_ns','shutdown_ns','startup_ns','updates_ns','use_ns'},'stage boundary')
        require(all(type(x) is int and x>=0 for x in row['timings_ns'].values()),'stage time')
        require(row['full_lifecycle_ns']>=sum(row['timings_ns'].values()),'lifecycle/stage boundary')
        grouped[(row['padding_atoms'],row['mismatch'],row['policy'])].append(row)
    require(len(grouped)==16,'group product')
    index={}
    for key,group in grouped.items():
        require(sorted(x['repeat'] for x in group)==[0,1,2],'missing/duplicate repetition')
        require(len({(x['installed'],x['blocked'],x['unchanged']) for x in group})==1,'inconsistent repeated outcome')
        index[key]=(group[0]['installed'],round(median(x['full_lifecycle_ns'] for x in group)/1e6,4))
    supplied={(x['padding_atoms'],x['mismatch'],x['policy']):x for x in data['groups']}
    require(len(supplied)==len(data['groups'])==16 and set(supplied)==set(index),'summary group product')
    for key,(installed,value) in index.items():
        require(supplied[key]['installed']==installed and supplied[key]['full_lifecycle_median_ms']==value,'raw/summary disagreement')
    labels={'fixed':'Fixed','greedy':'Greedy','mass':'Max mass','batch':'Batch choice'}
    lines=['% Derived from results/durable-state-costs/measurements.json; all48rows/1152proposals.']
    for policy,label in labels.items():
        installed='/'.join(str(index[(0,m,policy)][0]) for m in (False,True))
        costs=['/'.join(f'{index[(padding,m,policy)][1]:.1f}' for m in (False,True)) for padding in (0,11999)]
        lines.append(label+' & '+installed+' & '+' & '.join(costs)+r' \\')
    return '\n'.join(lines)+'\n'

def table():
    return derive(json.loads((ROOT/'results/durable-state-costs/measurements.json').read_text(encoding='utf-8')))

if __name__=='__main__':print(table(),end='')
