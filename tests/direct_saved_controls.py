"""Semantic corruptions of saved direct-query evidence, independent of file hashes."""
from __future__ import annotations
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from tests.check_direct_optimizer import check

ROOT = Path(__file__).resolve().parents[1]
FIRST = 'owners-2-alternatives-2-repeat-0.json'


def write(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2)+'\n')


def controls(directory, out):
    if out.exists():
        raise ValueError('New controls directory required')
    out.mkdir(parents=True)
    original = json.loads((directory/FIRST).read_text())
    tests = []
    def add(name, mutate, expected):
        value = deepcopy(original)
        mutate(value)
        tests.append((name, value, expected))
    add('missing-query', lambda r:r['queries'].pop(), 'Query count')
    add('changed-stream', lambda r:r['queries'][0]['proposals'][0]['support'].append('undeclared'),
        'Registered proposal stream differs')
    add('unsafe-selected-guard', lambda r:r['queries'][0]['direct']['result']['box'].__setitem__('0',[[]]),
        'Unsafe output product')
    add('false-installation-count', lambda r:r['queries'][0]['direct']['result']['forecast'].__setitem__('installed',999),
        'Saved forecast differs')
    add('incorrect-route-budget', lambda r:r['queries'][0]['direct'].__setitem__('budget_available_ns',1),
        'Route budget accounting differs')
    def omit(r):
        r['frontier_plan']['frontier'].pop()
        r['frontier_plan']['frontier_size']-=1
    add('missing-frontier-member', omit, 'Frontier completeness rejected')
    records=[]
    with tempfile.TemporaryDirectory(prefix='rollout-direct-corrupt-') as temp:
        root=Path(temp)
        for p in directory.iterdir():
            if p.name != FIRST:
                (root/p.name).symlink_to(p.resolve(), target_is_directory=p.is_dir())
        for name,value,expected in tests:
            destination=out/(name+'.json')
            write(destination,value)
            shutil.copyfile(destination,root/FIRST)
            try:
                check(root)
            except ValueError as error:
                if expected not in str(error):
                    raise ValueError(name+' failed for an unexpected reason: '+str(error)) from error
                records.append({'case':name,'status':'REJECTED','reason':str(error),
                    'mutated_record':destination.name,
                    'mutated_sha256':hashlib.sha256(destination.read_bytes()).hexdigest()})
            else:
                raise ValueError('Corruption was accepted: '+name)
    result={'status':'PASS','controls':len(records),'records':records,
        'source_summary_sha256':hashlib.sha256((directory/'summary.json').read_bytes()).hexdigest(),
        'checker_sha256':hashlib.sha256((ROOT/'tests/check_direct_optimizer.py').read_bytes()).hexdigest(),
        'driver_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'scope':'Each altered record is supplied directly to semantic validation; its current SHA is retained. No integrity-manifest failure stands in for the stated semantic rejection.'}
    write(out/'summary.json',result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results',type=Path,default=ROOT/'results/direct-optimization')
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(controls(args.results.resolve(),args.out.resolve()),indent=2))
