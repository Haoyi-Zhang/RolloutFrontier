"""Export exact numeric figure inputs from retained raw results; no rendering."""
import argparse
import collections
import csv
import json
from pathlib import Path


def main(results, out):
    out.mkdir(parents=True, exist_ok=True)
    groups=collections.defaultdict(lambda:collections.Counter())
    with (results/'network.csv').open(newline='') as f:
        for row in csv.DictReader(f):
            groups[row['family']][row['policy']] += int(row['installed'])
    with (out/'changes.csv').open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['family','branch','envelope','frontier'])
        for name in ['independent','correlated','one-sided','bridge']:
            w.writerow([name,groups[name]['branch'],groups[name]['envelope'],groups[name]['frontier']])
    costs=json.loads((results/'costs.json').read_text())
    with (out/'corners.csv').open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['corners','accept_ms','reject_ms'])
        for n in range(1,7):
            rows={r['accepted']:r for r in costs['corner_checks'] if r['nodes']==n}
            w.writerow([4**n,rows[True]['checker_median_ns']/1e6,rows[False]['checker_median_ns']/1e6])

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results',type=Path,default=Path('results'))
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();main(args.results,args.out)
