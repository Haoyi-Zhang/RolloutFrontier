"""Execute one existing cohort into a fresh output, preserving executed bytes.

Run studies sequentially for descriptive cost samples. The source inventory is a
conservative superset of local module dependencies, not evidence that every line
was executed. This wrapper never replaces an existing cohort.
"""
from __future__ import annotations
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def write(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n', encoding='utf-8')


def dependencies(names):
    pending = list(names)
    found = {}
    while pending:
        name = pending.pop()
        if name in found:
            continue
        path = ROOT / name
        raw = path.read_bytes()
        found[name] = raw
        if not name.endswith('.py'):
            continue
        tree = ast.parse(raw, filename=name)
        package = name.rsplit('/', 1)[0].replace('/', '.') if '/' in name else ''
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ''
                if node.level:
                    base = '.'.join(package.split('.')[:len(package.split('.')) - node.level + 1] + ([base] if base else []))
                modules = [base] + [base + '.' + item.name for item in node.names]
            for module in modules:
                if not module:
                    continue
                candidate = module.replace('.', '/') + '.py'
                if (ROOT / candidate).is_file():
                    pending.append(candidate)
                init = module.replace('.', '/') + '/__init__.py'
                if (ROOT / init).is_file():
                    pending.append(init)
    return found


def pack_effects(out):
    paths = sorted(out.glob('case-*/*.sqlite')) + sorted(out.glob('case-*/net/*.sqlite'))
    if len(paths) != 96:
        raise ValueError('Incomplete owned-effect database inventory')
    identities = {}
    with zipfile.ZipFile(out / 'databases.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            raw = path.read_bytes()
            name = path.relative_to(out).as_posix()
            identities[name] = dict(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
            archive.writestr(name, raw)
    write(out / 'database-identities.json', identities)
    # All application and protocol snapshots are retained in the verified archive.
    # The composition-negative-control JSON retains that separate outcome.
    for directory in sorted(out.glob('case-*')):
        if directory.is_dir():
            shutil.rmtree(directory)
    shutil.rmtree(out / 'composition-negative-control')


def run(study, out):
    out = out.resolve()
    if out.exists() or out.is_relative_to(ROOT):
        raise ValueError('Study output must be fresh and outside artifact')
    out.parent.mkdir(parents=True, exist_ok=True)
    named = {
        'effects': ('tests/effect_drain_study.py', ['-m', 'tests.effect_drain_study', '--out', str(out)]),
        'costs': ('tests/full_path_costs.py', ['-m', 'tests.full_path_costs', '--out', str(out / 'measurements.json'), '--repeats', '3']),
        'semantic': ('reproduce.py', ['reproduce.py', '--out', str(out), '--check-reference', 'results']),
    }
    entry, arguments = named[study]
    selected = [entry, 'tests/capture_revision_study.py']
    if study == 'costs':
        selected += ['tests/cost_endpoint.py']
    elif study == 'semantic':
        from reproduce import JOBS
        selected += [module.replace('.', '/') + '.py' for module, _, _ in JOBS]
        selected += ['tests/process_endpoint.py', 'tests/process_tcp_endpoint.py',
                     'claim_bindings.json', 'data/android-history.csv', 'data/android-class-introductions.csv']
    sources = dependencies(selected)
    before = {name: hashlib.sha256(raw).hexdigest() for name, raw in sources.items()}
    affinity = sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None
    pin = affinity[-1] if affinity and study == 'costs' else None
    cpu = next((line.split(':', 1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines()
                if line.startswith('model name')), None) if Path('/proc/cpuinfo').is_file() else platform.processor()
    environment = dict(study=study, started_utc=datetime.now(timezone.utc).isoformat(),
                       python=sys.version, sqlite=sqlite3.sqlite_version, platform=platform.platform(),
                       processor_model=cpu, available_logical_cpus=len(affinity) if affinity else os.cpu_count(),
                       pinned_logical_cpu=pin, source_sha256=before,
                       argv=[sys.executable, '-B'] + [arg.replace(str(out), '<OUTPUT>') for arg in arguments],
                       scope='Current source; own same-host processes and durable stores; no WAN or power-loss claim')
    temporary_registration = out.parent / (out.name + '-registration.tmp.json')
    write(temporary_registration, environment)
    stdout = out.parent / (out.name + '-stdout.tmp.log')
    stderr = out.parent / (out.name + '-stderr.tmp.log')
    def set_affinity():
        if pin is not None:
            os.sched_setaffinity(0, {pin})
    start = time.monotonic()
    with stdout.open('w', encoding='utf-8') as standard, stderr.open('w', encoding='utf-8') as errors:
        process = subprocess.Popen([sys.executable, '-B'] + arguments, cwd=ROOT,
                                   env=dict(os.environ, PYTHONHASHSEED='0', PYTHONDONTWRITEBYTECODE='1'),
                                   stdout=standard, stderr=errors, start_new_session=True,
                                   preexec_fn=set_affinity if pin is not None else None)
        try:
            code = process.wait(timeout=300)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            code = -1
    out.mkdir(parents=True, exist_ok=True)
    after = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sources}
    environment.update(finished_utc=datetime.now(timezone.utc).isoformat(),
                       wall_seconds=time.monotonic() - start, returncode=code,
                       source_bytes_unchanged_during_run=before == after)
    write(out / 'environment.json', environment)
    temporary_registration.replace(out / 'source-registration.json')
    stdout.replace(out / 'stdout.log')
    stderr.replace(out / 'stderr.log')
    for name, raw in sources.items():
        path = out / 'source-preimage' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    if code != 0 or before != after:
        raise ValueError('Study failed or source changed; retained partial evidence')
    if study == 'effects':
        pack_effects(out)
    print(json.dumps(dict(status='PASS', study=study, source_files=len(sources),
                          source_unchanged=True, output=str(out))))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('study', choices=('semantic', 'effects', 'costs'))
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    run(args.study, args.out)
