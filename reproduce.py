#!/usr/bin/env python3
"""Run the complete bounded suite and optionally compare semantic results.

Uses only Python's standard library. No download, package installation, external
service, or non-loopback network access is performed. Timing is remeasured and is
not required to match the retained sample.
"""
from __future__ import annotations
import argparse
import csv
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from itertools import zip_longest

ROOT = Path(__file__).resolve().parent
MEMORY = 512 * 1024**2
TIME_FIELDS = {'cpu_seconds','child_cpu_seconds','wall_seconds','peak_rss_kib',
    'wall_ns','rpc_median_ms','rpc_p95_ms','checker_median_ns','checker_min_ns',
    'dp_median_ns','install_median_ns','endpoint_vm_hwm_kib','solver_wall_ns','solver_wall_ms'}
JOBS = [('tests.unit','unit.json',False), ('tests.pilot','pilot.json',False), ('tests.finite','finite.json',False),
        ('tests.frontier','frontier.json',False),
        ('tests.frontier_stress','frontier-stress.json',False),
        ('tests.generalization','generalization.json',True),
        ('tests.journal_analysis','journal-analysis.json',True),
        ('tests.scaling','scaling.json',True),
        ('tests.modelcheck','modelcheck.json',False),
        ('tests.public_history','public-history.json',False),
        ('tests.campaign','network.json',True), ('tests.integration','integration.json',False),
        ('tests.multiprocess','multiprocess.json',False),
        ('tests.observations','observations.json',True), ('tests.costs','costs.json',False),
        ('tests.hardening','hardening.json',False),
        ('tests.replay','replay.json',True)]


def semantic(x):
    if isinstance(x, dict): return {k: semantic(v) for k,v in x.items() if k not in TIME_FIELDS}
    if isinstance(x, list): return [semantic(v) for v in x]
    return x


def compare(destination: Path, reference: Path) -> list[str]:
    compared=[]
    for _, filename, _ in JOBS:
        a=json.loads((destination/filename).read_text()); b=json.loads((reference/filename).read_text())
        if semantic(a) != semantic(b): raise AssertionError('semantic mismatch: '+filename)
        compared.append(filename)
    for filename in ('network.csv','observations.csv','generalization.csv','scaling.csv'):
        with (destination/filename).open(newline='') as a, (reference/filename).open(newline='') as b:
            for row_a,row_b in zip_longest(csv.DictReader(a),csv.DictReader(b)):
                if semantic(row_a) != semantic(row_b): raise AssertionError('semantic mismatch: '+filename)
        compared.append(filename)
    for filename in ('network-trace.jsonl','observation-trace.jsonl'):
        with (destination/filename).open() as a, (reference/filename).open() as b:
            for line_a,line_b in zip_longest(a,b):
                if line_a is None or line_b is None or semantic(json.loads(line_a)) != semantic(json.loads(line_b)):
                    raise AssertionError('semantic mismatch: '+filename)
        compared.append(filename)
    return compared


def limits():
    import resource
    resource.setrlimit(resource.RLIMIT_AS,(MEMORY,MEMORY))
    resource.setrlimit(resource.RLIMIT_CPU,(90,95))
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    if hasattr(os,'sched_getaffinity'):
        available=os.sched_getaffinity(0)
        os.sched_setaffinity(0,{min(available)})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True,help='new or empty results directory')
    parser.add_argument('--check-reference',type=Path,help='retained results directory (read only)')
    args=parser.parse_args()
    out=args.out.resolve()
    reference=args.check_reference.resolve() if args.check_reference else None
    if out == ROOT or ROOT in out.parents:
        parser.error('output must be outside the repository')
    if reference is not None and (out == reference or reference in out.parents):
        parser.error('output must not be the reference directory or its descendant')
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        parser.error('output directory must be new or empty; existing evidence is not replaced')
    out.mkdir(parents=True,exist_ok=True)
    import resource  # POSIX measurements; output refusal is also testable on Windows.
    limits()  # Runner + one job + five endpoint children: at most 7 x 512 MiB = 3.5 GiB.
    env=dict(os.environ, PYTHONHASHSEED='0', PYTHONDONTWRITEBYTECODE='1',
             OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
    records=[]; start=time.perf_counter(); parent_cpu=time.process_time()
    before=resource.getrusage(resource.RUSAGE_CHILDREN)
    for index, (module, filename, takes_directory) in enumerate(JOBS, 1):
        command=[sys.executable,'-m',module] + ([str(out)] if takes_directory else [])
        begin=time.perf_counter()
        print(f'[{index:02d}/{len(JOBS):02d}] start {module}', file=sys.stderr, flush=True)
        try:
            completed=subprocess.run(command,cwd=ROOT,env=env,preexec_fn=limits,
                capture_output=True,text=True,timeout=120,check=False)
        except subprocess.TimeoutExpired as error:
            def decoded(value):
                if value is None: return ''
                if isinstance(value, bytes): return value.decode('utf-8','replace')
                return value
            stdout, stderr = decoded(error.stdout), decoded(error.stderr)
            (out/'failure.txt').write_text(
                ' '.join(['python','-m',module])+'\nTIMEOUT after 120 seconds\n'+stdout+'\n'+stderr)
            print(f'[{index:02d}/{len(JOBS):02d}] timeout {module}', file=sys.stderr, flush=True)
            raise RuntimeError(f'{module} exceeded 120-second wall timeout; see failure.txt') from error
        if len(completed.stdout)>2*1024**2 or len(completed.stderr)>2*1024**2:
            raise RuntimeError('bounded log size exceeded')
        if completed.returncode != 0:
            (out/'failure.txt').write_text(' '.join(['python','-m',module])+'\n'+completed.stdout+'\n'+completed.stderr)
            raise RuntimeError(f'{module} failed with exit {completed.returncode}; see failure.txt')
        try:
            answer=json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            (out/'failure.txt').write_text(
                ' '.join(['python','-m',module])+'\nINVALID JSON OUTPUT\n'+
                completed.stdout+'\n'+completed.stderr)
            raise RuntimeError(f'{module} emitted invalid JSON; see failure.txt') from error
        # Directory-taking jobs also write JSON/CSV/trace data. Replayer only prints.
        if not takes_directory or module == 'tests.replay':
            (out/filename).write_text(json.dumps(answer,indent=2,sort_keys=True)+'\n')
        records.append(dict(command=['python','-m',module]+(['<output>'] if takes_directory else []),
            exit_code=0,wall_seconds=time.perf_counter()-begin,
            reported_cpu_seconds=answer['cpu_seconds'],
            reported_child_cpu_seconds=answer.get('child_cpu_seconds',0),
            reported_peak_rss_kib=answer['peak_rss_kib'],stderr=completed.stderr))
        print(f'[{index:02d}/{len(JOBS):02d}] done  {module} '
              f'({time.perf_counter()-begin:.3f}s)', file=sys.stderr, flush=True)
    required = ({filename for _, filename, _ in JOBS} |
                {'network.csv','observations.csv','generalization.csv','scaling.csv','network-trace.jsonl',
                 'observation-trace.jsonl'})
    missing = sorted(filename for filename in required if not (out / filename).is_file())
    if missing:
        message = 'missing generated outputs: ' + ', '.join(missing)
        (out/'failure.txt').write_text(message + '\n')
        raise RuntimeError(message + '; see failure.txt')
    print('[compare] semantic outputs', file=sys.stderr, flush=True)
    try:
        matched=compare(out,reference) if reference else []
        from verify_claims import verify
        bindings_verified=verify(out)
    except (AssertionError, OSError, ValueError, json.JSONDecodeError) as error:
        (out/'failure.txt').write_text('SEMANTIC COMPARISON FAILED\n' + repr(error) + '\n')
        raise RuntimeError('semantic comparison failed; see failure.txt') from error
    after=resource.getrusage(resource.RUSAGE_CHILDREN)
    report=dict(status='completed',runs=records,numeric_claim_bindings_verified=bindings_verified,semantic_reference=('matched' if reference else 'not-requested'),
        compared_files=matched,generated_files=sorted(required),
        independently_replayed_trace_files=['network-trace.jsonl'],
        reference_compared_trace_files=['network-trace.jsonl','observation-trace.jsonl'],
        comparison_excludes=sorted(TIME_FIELDS),
        limits=dict(affinity_cores=1,child_address_space_bytes=MEMORY,job_wall_timeout_seconds=120,
                    job_cpu_soft_seconds=90,maximum_simultaneous_project_processes=7, theoretical_aggregate_address_space_bytes=7*MEMORY),
        wall_seconds=time.perf_counter()-start,parent_cpu_seconds=time.process_time()-parent_cpu,
        children_cpu_seconds=after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
        largest_child_peak_rss_kib=after.ru_maxrss,
        scope='semantic reproduction, not byte-identical timing or proof of model correctness')
    (out/'execution.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print('[complete] execution.json written', file=sys.stderr, flush=True)
    print(json.dumps(report,indent=2,sort_keys=True))

if __name__=='__main__':
    main()
