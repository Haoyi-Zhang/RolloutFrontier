"""Read-only independent checks of saved Unicode input and retirement controls.

No production module or test producer is imported. Owner histories are replayed
by the existing independent readers; request-domain coverage and the rejected
checkpoints are reconstructed here from the retained JSON and SQLite evidence.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile

from tests.check_application_rollout import owner_database
from tests.check_factored_execution import check_owner, session_manifest

ROOT = Path(__file__).resolve().parents[1]
SOURCE_NAMES = (
    'src/controller.py', 'src/network.py', 'src/checker.py', 'src/envelope.py',
    'src/factored_planner.py', 'src/factored_runtime.py', 'src/factored_session.py',
    'src/schema_runtime.py', 'src/schema_contracts.py', 'src/application.py',
    'tests/factored_network.py', 'tests/factored_tcp_relay.py',
    'tests/application_network.py', 'tests/multiprocess.py',
    'tests/check_factored_execution.py', 'tests/factored_planning_oracle.py',
    'tests/check_application_rollout.py',
    'tests/utf8_input_regression.py', 'tests/check_utf8_inputs.py',
)
PROGRAMS = {
    'enum-alias': ('legacy', 'accepting', 'emitting', 'current'),
    'field-key': ('legacy', 'accepting', 'emitting', 'current'),
    'field-addition': ('legacy', 'accepting', 'emitting'),
    'integer-widening': ('legacy', 'accepting', 'emitting'),
}
GOOD_KEYS = ('plain', 'κλειδί-中文', 'supplementary-🧪-𐐀', '\x00key',
             '\u007f\u0080\u07ff\u0800\ud7ff\ue000\uffff', '\U0010ffff',
             '🧪' * 128, 'after-reopen')
BAD_KEYS = ('\ud800', '\udfff', 'left\ud800right', '\ud800\udc00', '', 'a' * 129)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def read(path):
    return json.loads(path.read_text())


def rows(path, sql):
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        require(db.execute('PRAGMA quick_check').fetchall() == [('ok',)], 'SQLite integrity')
        return db.execute(sql).fetchall()


def state(path):
    raw = rows(path, 'SELECT id,payload FROM state')
    require(len(raw) == 1 and raw[0][0] == 1, 'canonical state singleton')
    return json.loads(raw[0][1])


def inputs(kind, family=None, rank=None):
    if kind == 'factored':
        bits = 31 if family == 'integer-widening' and rank < 2 else 63
        lower, upper = -(1 << bits), (1 << bits) - 1
        def value(key, number):
            result = {'key': key, 'value': number}
            if family == 'enum-alias':
                result['status'] = 1
            if family == 'field-addition':
                result['tag'] = 'migrated-δ' if rank == 2 else ''
            return result
    else:
        lower = -(((1 << 62) + 7) // 3)
        upper = ((1 << 62) - 8) // 3
        def value(key, number):
            return {'key': key, 'amount': number}
    bad = [value(key, 0) for key in BAD_KEYS]
    bad += [value('range', number) for number in (lower - 1, upper + 1, True)]
    good = [value(key, number) for key, number in
            zip(GOOD_KEYS, (lower, -1, 0, 1, upper, 17, -29, 31))]
    return bad, good


def common(report):
    bad, good = inputs(report['kind'], report.get('family'), report.get('rank'))
    require(len(report['rejections']) == len(bad) == 9, 'rejected input coverage')
    counts = set()
    for index, (observed, value) in enumerate(zip(report['rejections'], bad)):
        require(observed['request_id'] == 'input-' + str(index) and
                canonical(observed['input']) == canonical(value) and observed['error'] == 'ValueError',
                'rejection identity, domain, or exception type')
        # JSON decoding combines adjacent surrogate escape pairs. Preserve and
        # check the actual Python input scalars separately from that transport.
        require(observed['key_codepoints'] == [ord(character) for character in value['key']],
                'rejected input code points differ')
        require(type(observed['rpc_count_before']) is int and
                observed['rpc_count_before'] == observed['rpc_count_after'],
                'rejected input performed a physical RPC')
        counts.add(observed['rpc_count_before'])
        if index < 4:
            require(observed['message'] == 'semantic key must be valid UTF-8', 'UTF-8 rejection reason')
            try:
                value['key'].encode('utf-8')
            except UnicodeEncodeError:
                pass
            else:
                raise ValueError('negative Unicode control is valid')
    require(len(counts) == 1, 'rejection-only interval contains physical work')
    require(len(report['requests']) == len(good) == 8, 'valid input coverage')
    for index, (observed, value) in enumerate(zip(report['requests'], good)):
        require(observed['request_id'] == 'input-' + str(index) and
                canonical(observed['input']) == canonical(value), 'valid Unicode and boundary corpus')
        value['key'].encode('utf-8')
    require(report['reopened_exact_retry'] == report['requests'][0]['output'] and
            report['retired_after_reopen'] is True, 'reopen retry or retirement result')
    return {row['request_id']: row for row in report['requests']}


def check_factored(directory, report):
    registry, probe = read(directory / 'registry.json'), read(directory / 'schema-probe.json')
    requests = common(report)
    require(probe['family'] == report['family'] and
            probe['programs'][report['rank']] == report['program'] and
            set(registry['owners']) == {'a', 'b'}, 'registered schema control binding')
    checkpoint = directory / 'rejected'
    require(rows(checkpoint / 'session.sqlite', 'SELECT * FROM requests') == [],
            'rejected input retained a pending or complete request')
    before, final = state(checkpoint / 'session.sqlite'), state(directory / 'session.sqlite')
    require(before['stage'] == 'open' and final['stage'] == 'retired' and
            not final['certificates'] and before['certificates'] == final['admission_certificates'],
            'request gate or retained admission changed')
    manifest = session_manifest(final)
    require(session_manifest(before) == manifest, 'reopen changed the admission identity')
    checked, audit_rows = {}, 0
    for index, owner in enumerate(('a', 'b')):
        initial = check_owner(checkpoint / f'owner-{index}.sqlite', owner, registry, probe)
        require(not initial['effects'] and
                not any(row['request']['op'] == 'schema' for row in initial['history'].values()),
                'rejected input reached an owner or created an effect')
        origin = state(checkpoint / f'origin-{index}.sqlite')
        require(len(origin['attempts']) == 1 and all(r['status'] == 'committed'
                for r in origin['attempts'].values()), 'rejection invalidated committed authority')
        checked[owner] = check_owner(directory / 'network' / f'owner-{index:04d}.sqlite', owner, registry, probe)
        actual = checked[owner]
        require(actual['state'] == report['final_owners'][owner] and
                not actual['state']['slots'] and actual['state']['floor'][2] == 1,
                'final owner retains a guard')
        require(len(actual['effects']) == 8, 'schema effect denominator')
        origin_path = directory / 'network' / 'application-origins' / f'owner-{index:04d}' / 'origin-2.sqlite'
        require(not state(origin_path)['attempts'], 'origin retains retired authority')
        audit_rows += actual['audit_rows']
    request_rows = rows(directory / 'session.sqlite', 'SELECT request_id,input,status,output FROM requests')
    require(len(request_rows) == 8, 'final request denominator')
    for request_id, raw_input, status, raw_output in request_rows:
        observed = requests[request_id]
        require(status == 'complete' and raw_input == canonical(observed['input']) and
                json.loads(raw_output) == observed['output'], 'durable session request binding')
        expected = observed['input']
        require(observed['output']['records'] == {'sink': expected}, 'Unicode semantic sink output')
        for owner, step in (('a', 'source'), ('b', 'sink')):
            sequence = final['admission_certificates'][owner]['sequences']['0']
            effect = checked[owner]['effects'][2, sequence, manifest, request_id + ':' + step]
            reply = observed['output']['steps'][step]
            require(reply['output'] == effect['output'] and effect['output']['record'] == expected and
                    effect['rank'] == report['rank'] and reply['applied_rank'] == report['rank'],
                    'retained serializer output or rank changed')
    events = [json.loads(line) for line in (directory / 'network' / 'transport.jsonl').read_text().splitlines()]
    issued = {event['call']: event for event in events if event['event'] == 'rpc-issued'}
    for event in events:
        if event['event'] == 'rpc-result':
            require(event['response'] is not None and event['request'] == issued[event['call']]['request'],
                    'physical request/reply trace')
            actual = checked[event['owner']]['history'][event['owner_order']]
            require(actual['request'] == event['request'] and actual['response'] == event['response'],
                    'TCP response differs from durable owner audit')
    require(sum(event['event'] == 'owner-start' for event in events) == 3 and
            sum(event['event'] == 'owner-stop' and event['signal_requested'] == 'KILL' for event in events) == 1,
            'actual owner restart coverage')
    return {'rejections': 9, 'requests': 8, 'effects': 16, 'audit_rows': audit_rows,
            'owner_restarts': 1, 'final_holds': 0}


def check_pipeline(directory, report):
    requests = common(report)
    checkpoint = directory / 'rejected'
    require(rows(checkpoint / 'origin.sqlite', 'SELECT * FROM application_requests') == [],
            'rejected pipeline input retained a request')
    require(len(state(checkpoint / 'origin.sqlite')['attempts']) == 1,
            'rejected input changed pipeline authority')
    effects, audit_rows = {}, 0
    for node in range(3):
        require(rows(checkpoint / f'owner-{node}.sqlite', 'SELECT * FROM application_results') == [],
                'rejected pipeline input caused an effect')
        require(not any(json.loads(row[0])['op'] == 'application' for row in
                        rows(checkpoint / f'owner-{node}.sqlite', 'SELECT request FROM application_audit')),
                'rejected pipeline input reached a handler')
        effects[node], stats = owner_database(directory, report, node)
        require(set(effects[node]) == set(requests), 'pipeline effect denominator')
        path = directory / 'databases' / report['program'] / f'process-node-{node}.sqlite'
        actual = state(path)
        require(actual == report['final_owners'][str(node)] and not actual['slots'] and
                actual['floor'][2] == 1, 'pipeline owner retains a guard')
        audit_rows += len(rows(path, 'SELECT ordinal FROM application_audit'))
    origin = directory / 'databases' / report['program'] / 'origin-2.sqlite'
    require(not state(origin)['attempts'], 'pipeline origin retains authority')
    require(rows(origin, 'SELECT closing FROM application_sessions') == [(1,)], 'pipeline drain gate')
    request_rows = rows(origin, 'SELECT request_id,input,status,output FROM application_requests')
    require(len(request_rows) == 8, 'pipeline request denominator')
    for request_id, raw_input, status, raw_output in request_rows:
        observed = requests[request_id]
        require(status == 'complete' and raw_input == canonical(observed['input']) and
                json.loads(raw_output) == observed['output'], 'pipeline durable request binding')
        value = observed['input']
        expected = {'key': value['key'], 'amount': 3 * value['amount'] + 7}
        require(observed['output']['record'] == expected == effects[2][request_id]['output']['record'],
                'pipeline valid Unicode or boundary result')
        current = value
        for node in range(3):
            effect = effects[node][request_id]
            require(effect['input'] == current and effect['codec'] == report['codec'] and
                    effect['program'] == report['program'], 'pipeline input, codec, or program')
            current = effect['output'].get('wire') if node < 2 else effect['output']['record']
    require(sum(event['event'] == 'process-start' for event in report['trace']) == 4 and
            sum(event['event'] == 'process-stop' and event['killed'] for event in report['trace']) == 1,
            'pipeline actual owner restart coverage')
    return {'rejections': 9, 'requests': 8, 'effects': 24, 'audit_rows': audit_rows,
            'owner_restarts': 1, 'final_holds': 0}


def check(directory):
    directory = directory.resolve()
    summary = read(directory / 'summary.json')
    require(summary['sources'] == list(SOURCE_NAMES), 'frozen source inventory')
    for name in SOURCE_NAMES:
        require((directory / 'sources' / name).read_bytes() == (ROOT / name).read_bytes(),
                'captured source differs: ' + name)
    require(summary['optimization'] in (0, 1) and
            summary['owner_optimization_environment'] == str(summary['optimization']),
            'owner optimization mode')
    expected = {'factored/' + family + '/' + str(rank)
                for family, programs in PROGRAMS.items() for rank in range(len(programs))}
    expected |= {'pipeline/' + program for program in PROGRAMS['enum-alias']}
    require({case['path'] for case in summary['cases']} == expected and len(summary['cases']) == 18,
            'four-family and pipeline-program coverage')
    total = {'cases': 18, 'rejections': 0, 'requests': 0, 'effects': 0,
             'audit_rows': 0, 'owner_restarts': 0, 'final_holds': 0}
    for case in summary['cases']:
        report = read(directory / case['path'] / 'observations.json')
        require(report['kind'] == case['kind'] and case['rejections'] == 9 and case['requests'] == 8,
                'case binding')
        if case['kind'] == 'factored':
            require(report['family'] == case['family'] and report['rank'] == case['rank'] and
                    case['path'] == 'factored/' + report['family'] + '/' + str(report['rank']),
                    'schema control placement')
            counts = check_factored(directory / case['path'], report)
        else:
            require(report['program'] == case['program'] and case['path'] == 'pipeline/' + report['program'],
                    'pipeline program placement')
            counts = check_pipeline(directory / case['path'], report)
        for name, value in counts.items():
            total[name] += value
    require(total['rejections'] == 162 and total['requests'] == 144 and total['effects'] == 320 and
            total['owner_restarts'] == 18 and total['final_holds'] == 0, 'aggregate control denominator')
    return total


def altered_evidence_controls(directory):
    """Reject changed evidence in disposable copies; never alter the source run."""
    rejected = []
    for kind in ('rejection-claim', 'missing-request', 'changed-owner-effect'):
        with tempfile.TemporaryDirectory(prefix='utf8-check-', dir=directory.parent) as temporary:
            copy = Path(temporary) / 'evidence'
            shutil.copytree(directory, copy)
            case = copy / 'factored' / 'enum-alias' / '0'
            if kind == 'rejection-claim':
                path = case / 'observations.json'
                value = read(path)
                value['rejections'][0]['error'] = 'SchemaRequestPending'
                path.write_text(canonical(value) + '\n')
            elif kind == 'missing-request':
                with sqlite3.connect(str(case / 'session.sqlite')) as db:
                    db.execute("DELETE FROM requests WHERE request_id='input-0'")
            else:
                with sqlite3.connect(str(case / 'network' / 'owner-0000.sqlite')) as db:
                    db.execute("UPDATE schema_results SET output='{}' WHERE request_id='input-0:source'")
            try:
                check(copy)
            except (ValueError, KeyError, TypeError) as error:
                rejected.append({'control': kind, 'error': type(error).__name__, 'reason': str(error)})
            else:
                raise ValueError('altered evidence was accepted: ' + kind)
    return rejected


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    result = check(args.directory)
    if args.self_test:
        result['altered_evidence_rejections'] = altered_evidence_controls(args.directory.resolve())
    print(canonical(result))
