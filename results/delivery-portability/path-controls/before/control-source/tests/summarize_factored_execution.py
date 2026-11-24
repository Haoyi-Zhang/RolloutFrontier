"""Reconstruct steady-only latency and workload denominators from raw records."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import statistics


def load(path): return json.loads(Path(path).read_text())


def records(path): return [json.loads(line) for line in Path(path).read_text().splitlines() if line]


def quantile(values,probability):
    values = sorted(values)
    point = (len(values)-1)*probability
    lower,upper = math.floor(point),math.ceil(point)
    return values[lower]+(values[upper]-values[lower])*(point-lower)


def describe(nanoseconds):
    values = [v/1000000 for v in nanoseconds]
    return {'n':len(values),'minimum_ms':min(values),'median_ms':statistics.median(values),
            'p95_ms':quantile(values,0.95),'maximum_ms':max(values)}


def summarize(root):
    root = Path(root)
    summary = load(root/'summary.json')
    rows,groups,fault = [],{},None
    for item in summary['cases']:
        directory = root/item['directory']
        case,result,observations = load(directory/'case.json'),load(directory/'result.json'),records(directory/'requests.jsonl')
        if item['kind']=='fault-cohort':
            events = records(directory/'transport.jsonl')
            fault = {'directory':item['directory'],'controls':result['controls'],
                'owner_sigkill_exits':sum(e['event']=='owner-stop' and e['returncode']==-9 for e in events),
                'coordinator_sigkill_exits':sum(e['event']=='coordinator-stop' and e['returncode']==-9 for e in events),
                'verification':item['verification']}
            continue
        elapsed = [r['elapsed_ns'] for r in observations if r['category']=='steady-target']
        if sorted(elapsed)!=sorted(result['steady_target_request_elapsed_ns']):
            raise ValueError('steady-only request samples differ from recorded result')
        row = {'directory':item['directory'],'family':item['family'],'topology':item['topology'],
            'owners':len(case['owners']),'factors':len(case['plan']['factors']),
            'workflow_hops_per_request':len(case['workflow']),
            'input_parses_per_request':sum(len(s['parents']) for s in case['workflow']),
            'completed_requests':len(observations),'durable_effects':item['verification']['durable_effects'],
            'installations':item['verification']['installations'],'phases':item['verification']['phases'],
            'old_pause_requests':sum(r['category']=='old-overlap' for r in observations),
            'current_pause_requests':sum(r['category']=='current-overlap' for r in observations),
            'compatible_installs_during_old_pause':result['compatible_installs_during_old_pause'],
            'cleanup_installs_during_current_pause':result['cleanup_installs_during_current_pause'],
            'maximum_owner_slots':item['verification']['max_owner_slots'],
            'steady_target_latency':describe(elapsed)}
        rows.append(row)
        key = (item['family'],item['topology'],len(case['owners']))
        group = groups.setdefault(key,{'elapsed':[],'medians':[],'trials':[]})
        group['elapsed'] += elapsed
        group['medians'].append(row['steady_target_latency']['median_ms'])
        group['trials'].append(item['directory'])
    aggregate = []
    for (family,topology,owners),group in groups.items():
        aggregate.append({'family':family,'topology':topology,'owners':owners,'trials':group['trials'],
            'pooled_steady_target_latency':describe(group['elapsed']),
            'trial_median_range_ms':[min(group['medians']),max(group['medians'])]})
    return {'quantile_rule':'linear interpolation at (n-1)*p after sorting',
        'latency_scope':'steady-target requests only; paused overlap and fault requests excluded; fully audited single-host loopback TCP',
        'per_trial':rows,'groups':aggregate,'fault_inventory':fault,
        'totals':{'cohorts':len(summary['cases']),'requests':summary['total_requests'],
                  'durable_effects':summary['total_effects'],
                  'conditional_installations':summary['total_conditional_installations'],
                  'dataflow_input_parses':sum(c['verification']['parser_calls'] for c in summary['cases'])}}


if __name__=='__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory',type=Path)
    parser.add_argument('--output',type=Path)
    args = parser.parse_args()
    answer = summarize(args.directory)
    encoded = json.dumps(answer,sort_keys=True,separators=(',',':'))+'\n'
    if args.output: args.output.write_text(encoded)
    else: print(encoded,end='')
