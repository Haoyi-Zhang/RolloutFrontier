#!/usr/bin/env python3
"""Verify retained numeric claim bindings. This checks data consistency, not truth of a theorem."""
from __future__ import annotations
import argparse,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def verify(results: Path) -> int:
    manifest=json.loads((ROOT/'claim_bindings.json').read_text())
    cache={}
    for item in manifest:
        name=item['result_file']
        if Path(name).name != name: raise ValueError('result path must be a basename')
        if name not in cache: cache[name]=json.loads((results/name).read_text())
        value=cache[name]
        for part in item['path']: value=value[part]
        if type(value) is not type(item['expected']) or value != item['expected']:
            raise ValueError(f"claim binding mismatch: {item['id']} {name} {item['path']}")
    return len(manifest)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results',type=Path,default=ROOT/'results')
    args=parser.parse_args()
    print(json.dumps({'verified_numeric_bindings':verify(args.results)}))
