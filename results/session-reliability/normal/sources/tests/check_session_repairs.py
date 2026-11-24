"""Read-only checks of saved session-repair controls; imports no runtime code."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE_NAMES = (
    'src/controller.py', 'src/network.py', 'src/checker.py', 'src/envelope.py',
    'src/factored_planner.py', 'src/factored_runtime.py', 'src/factored_session.py',
    'src/schema_runtime.py', 'src/schema_contracts.py', 'src/application.py',
    'tests/factored_network.py', 'tests/factored_tcp_relay.py',
    'tests/application_network.py', 'tests/multiprocess.py',
    'tests/session_repair_regression.py', 'tests/check_session_repairs.py',
)
GROUPS = ('pipeline-completion', 'pipeline-strings', 'factored-strings', 'journal-recovery')
BAD_POINTS = ([55296], [57343], [108, 101, 102, 116, 55296, 114, 105, 103, 104, 116], [55296, 56320])
GOOD_TEXT = ('plain', 'identity-🧪-中文', '\x00identity', '🧪' * 128)
VALUE = {'key': 'record-κ', 'value': 7, 'status': 1}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def read(path):
    return json.loads(path.read_text())


def rows(path, sql):
    require(path.is_file(), 'missing database: ' + path.name)
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        require(db.execute('PRAGMA quick_check').fetchall() == [('ok',)], 'SQLite integrity')
        return db.execute(sql).fetchall()


def state(path):
    saved = rows(path, 'SELECT id,payload FROM state')
    require(len(saved) == 1 and saved[0][0] == 1, 'canonical state singleton')
    return json.loads(saved[0][1])


def admission(session):
    fields = ('birth_token', 'manifest', 'registry', 'window', 'workflow', 'family', 'codecs')
    require(isinstance(session['birth_token'], str) and len(session['birth_token']) == 32 and
            all(c in '0123456789abcdef' for c in session['birth_token']), 'session birth identity')
    return session['manifest'] + ':session:' + hashlib.sha256(
        canonical({name: session[name] for name in fields}).encode()).hexdigest()


def audit_links(directory, kind):
    network = directory / 'network'
    if kind == 'pipeline':
        trace = read(directory / 'transport.json')
        databases = {node: network / f'process-node-{node}.sqlite' for node in range(3)}
        events = [event for event in trace if event['event'] == 'rpc']
        table = 'application_audit'
    else:
        trace = [json.loads(line) for line in (network / 'transport.jsonl').read_text().splitlines()]
        databases = {'only': network / 'owner-0000.sqlite'}
        events = [event for event in trace if event['event'] == 'rpc-result']
        table = 'schema_audit'
        issued = {event['call']: event for event in trace if event['event'] == 'rpc-issued'}
        require(len(issued) == len(events), 'unmatched physical transport request')
        for event in events:
            require(issued[event['call']]['request'] == event['request'], 'transport request changed')
    audits, linked = {}, set()
    for owner, path in databases.items():
        history = rows(path, 'SELECT ordinal,request,response FROM ' + table + ' ORDER BY ordinal')
        require([row[0] for row in history] == list(range(1, len(history) + 1)), 'durable audit sequence')
        audits.update({(owner, ordinal): (json.loads(request), json.loads(response))
                       for ordinal, request, response in history})
        require(not any(slot['status'] == 'held' for slot in state(path)['slots'].values()),
                'final owner retains authority')
    for event in events:
        key = (event['target'] if kind == 'pipeline' else event['owner'], event['owner_order'])
        require(event['response'] is not None and key in audits and key not in linked and
                audits[key] == (event['request'], event['response']), 'socket response differs from durable audit')
        linked.add(key)
    require(linked == set(audits), 'unrecorded owner operation')
    return trace, len(audits)


def pipeline_effects(directory, expected):
    for node in range(3):
        found = rows(directory / 'network' / f'process-node-{node}.sqlite',
                     'SELECT request_id,codec,input,output,generation,program FROM application_results')
        require(len(found) == len(expected), 'pipeline effect denominator')
        for request_id, codec, raw_input, raw_output, generation, program in found:
            require(request_id in expected and json.loads(codec) == ['ACTIVE', 'ACTIVE'] and
                    generation == 0 and program in ('legacy', 'accepting'), 'pipeline physical effect binding')
            value, output = json.loads(raw_input), json.loads(raw_output)
            original = expected[request_id]
            if node == 0:
                require(value == original, 'source input differs')
            else:
                wire = json.loads(value)
                amount = original['amount'] if node == 1 else 3 * original['amount'] + 7
                require(wire == {'key': original['key'], 'amount': str(amount), 'state': 'ACTIVE'},
                        'pipeline wire input differs')
            if node < 2:
                wire = json.loads(output['wire'])
                amount = original['amount'] if node == 0 else 3 * original['amount'] + 7
                require(wire == {'key': original['key'], 'amount': str(amount), 'state': 'ACTIVE'},
                        'pipeline source or transform result differs')
            else:
                require(output == {'record': {'key': original['key'], 'amount': 3 * original['amount'] + 7}},
                        'pipeline sink result differs')
    origin = directory / 'network' / 'origin-2.sqlite'
    require(not state(origin)['attempts'], 'pipeline origin retains retired authority')
    return len(expected) * 3


def check_completion(directory):
    report = read(directory / 'observations.json')
    require(report['kind'] == 'pipeline-completion' and report['input'] == {'key': 'concurrent', 'amount': 17},
            'concurrency input corpus')
    first = report['first_completion']
    require(first == report['later_completion'] == report['reopened_retry'] and
            first['record'] == {'key': 'concurrent', 'amount': 58} and
            [r['duplicate'] for r in first['owner_replies']] == [True, False, False],
            'completed receipt changed across concurrent completion or reopen')
    for name in ('first-completion.sqlite', 'later-completion.sqlite', 'network/origin-2.sqlite'):
        saved = rows(directory / name, 'SELECT manifest,request_id,input,status,output FROM application_requests')
        require(len(saved) == 1 and saved[0][:4] == ('completion', 'same-request', canonical(report['input']), 'complete')
                and json.loads(saved[0][4]) == first, 'durable completion differs from the first returned result')
    require(report['active_after_completions'] == 0 and report['cached_retry_rpc_count'] == 0 and
            report['retired'] is True and report['effects'] == [1, 1, 1] and report['final_holds'] == [0, 0, 0],
            'completion gate or retry outcome')
    trace, audit_count = audit_links(directory, 'pipeline')
    application = [event for event in trace if event.get('request', {}).get('op') == 'application']
    require(len(application) == 6, 'concurrent attempts did not both execute')
    for node in range(3):
        replies = [event['response'] for event in application if event['target'] == node]
        require([r['duplicate'] for r in replies] == [False, True], 'concurrent attempt metadata control')
        require(first['owner_replies'][node] == replies[1 if node == 0 else 0], 'first result receipt provenance')
    require(sum(event['event'] == 'process-restart' for event in trace) == 1, 'process reopen control missing')
    return {'requests': 1, 'effects': pipeline_effects(directory, {'same-request': report['input']}),
            'audit_rows': audit_count, 'concurrent_attempts': 2}


def check_pipeline_text(directory):
    report = read(directory / 'observations.json')
    rejections = report['rejections']
    require(len(rejections) == 6 and rows(directory / 'after-rejections.sqlite', 'SELECT * FROM application_requests') == [],
            'invalid pipeline text retained a request')
    for index, rejection in enumerate(rejections):
        require(rejection['codepoints'] == (BAD_POINTS[index] if index < 4 else BAD_POINTS[0]) and
                rejection['exception'] == 'ValueError' and rejection['rpc_before'] == rejection['rpc_after'] and
                rejection['field'] == ('key' if index == 5 else 'request_id') and
                rejection['input_kind'] == ('builtin-str' if index < 4 else 'str-subclass'),
                'invalid pipeline text coverage or rejection timing')
    bad = report['bad_manifests']
    require(len(bad) == 4, 'pipeline manifest rejection coverage')
    for index, rejection in enumerate(bad):
        require(rejection['codepoints'] == BAD_POINTS[index if index < 3 else 0] and
                rejection['exception'] == 'ValueError' and rejection['session_rows_before'] ==
                rejection['session_rows_after'] == 1 and rejection['retired'] is True,
                'invalid pipeline manifest bound a session or prevented retirement')
    require(report['admission_rejections'] == [{'codepoints': BAD_POINTS[3],
                'outcome': {'status': 'not-justified', 'reasons': []}, 'final_holds': [0, 0, 0]}],
            'surrogate-pair admission rejection or cleanup differs')
    requests = report['good_requests']
    require([row['request_id'] for row in requests] == list(GOOD_TEXT), 'legitimate pipeline identity coverage')
    saved = {row[0]: row[1:] for row in rows(directory / 'network' / 'origin-2.sqlite',
              'SELECT request_id,input,status,output FROM application_requests')}
    require(set(saved) == set(GOOD_TEXT), 'pipeline durable request denominator')
    for index, row in enumerate(requests):
        expected = {'key': 'key-' + str(index), 'amount': index}
        require(row['input'] == expected and row['output']['record'] == {'key': expected['key'], 'amount': 3 * index + 7}
                and saved[row['request_id']] == (canonical(expected), 'complete', canonical(row['output'])),
                'legitimate identity changed its durable result')
    require(report['effects'] == [4, 4, 4] and report['final_holds'] == [0, 0, 0], 'pipeline text denominator')
    _, audit_count = audit_links(directory, 'pipeline')
    return {'rejections': 11, 'requests': 4,
            'effects': pipeline_effects(directory, {row['request_id']: row['input'] for row in requests}),
            'audit_rows': audit_count}


def schema_rows(directory):
    path = directory / 'network' / 'owner-0000.sqlite'
    effects = rows(path, 'SELECT origin,sequence,manifest,request_id,input,output,generation,rank FROM schema_results')
    result = {}
    for origin, sequence, manifest, request_id, raw_input, raw_output, generation, rank in effects:
        value, output = json.loads(raw_input), json.loads(raw_output)
        require(origin == 2 and generation == rank == 0 and value == {
            'input_classes': [], 'emit_class': 'old-name', 'inputs': [], 'seed': VALUE}, 'schema effect input')
        require(output['record'] == VALUE and json.loads(output['wire']) == {
            'key': VALUE['key'], 'value': str(VALUE['value']), 'status': 'ACTIVE'}, 'schema effect output')
        result[origin, sequence, manifest, request_id] = output
    require(len(result) == len(effects), 'duplicate physical effect identity')
    origin_path = directory / 'network' / 'application-origins' / 'owner-0000' / 'origin-2.sqlite'
    require(not state(origin_path)['attempts'], 'factored origin retains retired authority')
    return result


def session_output(path, request_id, output, effects):
    saved = state(path)
    require(saved['stage'] == 'retired' and not saved['certificates'], 'factored session did not retire')
    request_rows = rows(path, 'SELECT request_id,input,status,output FROM requests')
    require(request_rows == [(request_id, canonical(VALUE), 'complete', canonical(output))], 'durable factored request')
    manifest = admission(saved)
    cert = saved['admission_certificates']['only']
    require(cert['manifest'] == manifest and output['records'] == {'source': VALUE} and
            output['steps']['source']['output'] == effects[2, cert['sequences']['0'], manifest, request_id + ':source'],
            'factored result differs from its retained physical effect')
    return saved


def check_factored_text(directory):
    report = read(directory / 'observations.json')
    require(len(report['bad_manifests']) == 5, 'factored manifest rejection coverage')
    for index, rejection in enumerate(report['bad_manifests']):
        require(rejection['codepoints'] == BAD_POINTS[index if index < 4 else 0] and
                rejection['exception'] == 'FactoredExecutionError' and
                rejection['state_count'] == rejection['request_count'] == rejection['owner_holds'] == 0,
                'factored invalid manifest became durable')
        path = directory / rejection['path']
        require(rows(path, 'SELECT * FROM state') == [] and rows(path, 'SELECT * FROM requests') == [],
                'invalid manifest retained a state or request row')
    rejected_key = report['custom_key_rejection']
    require(rejected_key['exception'] == 'ValueError' and rejected_key['input_kind'] == 'str-subclass' and
            rejected_key['codepoints'] == BAD_POINTS[0] and rejected_key['rpc_before'] == rejected_key['rpc_after'] and
            rejected_key['request_count'] == 0 and
            rows(directory / 'after-custom-key-rejection.sqlite', 'SELECT * FROM requests') == [],
            'custom Python key reached durable binding')
    good = report['good_manifests']
    require([row['manifest'] for row in good] == list(GOOD_TEXT) and
            all(row['retired'] is True for row in good), 'legitimate manifest corpus')
    effects = schema_rows(directory)
    require(len(effects) == report['owner_effects'] == 4 and report['final_holds'] == 0, 'factored text denominator')
    births = set()
    for row in good:
        saved = session_output(directory / row['path'], 'valid-request', row['output'], effects)
        require(saved['manifest'] == row['manifest'], 'readable manifest differs')
        births.add(saved['birth_token'])
    require(len(births) == 4, 'independent manifest journals shared a birth')
    _, audit_count = audit_links(directory, 'factored')
    return {'rejections': 6, 'requests': 4, 'effects': 4, 'audit_rows': audit_count}


def check_journals(directory):
    report = read(directory / 'observations.json')
    require(report['invalid_workflow'] == {'exception': 'FactoredExecutionError', 'message': 'dataflow size'},
            'failed initialization control')
    require(rows(directory / 'empty-initialization.sqlite', 'SELECT * FROM state') == [] and
            rows(directory / 'empty-initialization.sqlite', 'SELECT * FROM requests') == [], 'initial journal was not empty')
    require(report['first_output'] == report['open_reopen_output'] == report['retired_reopen_output'] and
            report['open_reopen_rpc_count'] == report['retired_reopen_rpc_count'] == 0,
            'existing open or retired journal read owners to choose codecs')
    effects = schema_rows(directory)
    require(len(effects) == report['owner_effects'] == 2 and report['final_holds'] == 0 and
            report['retired'] is True and report['pending_retired'] is True, 'journal recovery denominator')
    saved = session_output(directory / report['journal'], 'corrected', report['first_output'], effects)
    require(saved['birth_token'] == report['birth_token'], 'empty-journal recovery changed birth after initialization')
    session_output(directory / 'pending.sqlite', 'pending', report['pending_recovered'], effects)
    require(report['pending_recovered']['steps']['source']['duplicate'] is True, 'pending recovery repeated effect')
    names = {'lost-state', 'missing-requests', 'null-payload', 'wrong-singleton',
             'extra-state', 'unknown-table', 'wrong-schema'}
    require({row['name'] for row in report['rejected_journals']} == names and
            len(report['rejected_journals']) == len(names), 'damaged journal controls')
    for rejection in report['rejected_journals']:
        name = rejection['name'] + '.sqlite'
        require(rejection['rpc_before'] == rejection['rpc_after'] and
                (directory / 'rejected' / name).read_bytes() == (directory / 'before-rejection' / name).read_bytes(),
                'damaged journal recovery changed evidence or requested new authority')
    lost = directory / 'rejected' / 'lost-state.sqlite'
    require(rows(lost, 'SELECT * FROM state') == [] and
            rows(lost, 'SELECT request_id,status FROM requests') == [('pending', 'pending')], 'missing-state control lacks request')
    trace, audit_count = audit_links(directory, 'factored')
    require(sum(event['event'] == 'owner-stop' and event['signal_requested'] == 'KILL' for event in trace) == 2,
            'offline reopen did not stop actual owner processes')
    return {'rejections': 8, 'requests': 2, 'effects': 2, 'audit_rows': audit_count, 'offline_reopens': 2}


def check(directory):
    summary = read(directory / 'summary.json')
    require(summary['optimization'] in (0, 1) and summary['owner_optimization_environment'] == str(summary['optimization'])
            and summary['transport'] == 'separate TCP/SQLite owner processes', 'execution mode or transport')
    require(summary['groups'] == list(GROUPS) and summary['sources'] == list(SOURCE_NAMES), 'control/source inventory')
    for name in SOURCE_NAMES:
        require((directory / 'sources' / name).read_bytes() == (ROOT / name).read_bytes(), 'source differs: ' + name)
    functions = (check_completion, check_pipeline_text, check_factored_text, check_journals)
    results = {name: function(directory / name) for name, function in zip(GROUPS, functions)}
    return {'status': 'PASS', 'optimization': summary['optimization'], 'groups': results,
            'requests': sum(group['requests'] for group in results.values()),
            'effects': sum(group['effects'] for group in results.values()),
            'rejections': sum(group.get('rejections', 0) for group in results.values()),
            'audit_rows': sum(group['audit_rows'] for group in results.values()), 'source_files': len(SOURCE_NAMES)}


def tamper_controls(directory):
    def changed_completion(target):
        path = target / 'pipeline-completion' / 'observations.json'
        value = read(path)
        value['later_completion']['owner_replies'][0]['duplicate'] = False
        path.write_text(canonical(value) + '\n')

    def missing_binding(target):
        with sqlite3.connect(target / 'factored-strings' / 'valid-0.sqlite') as db:
            db.execute('DELETE FROM requests')

    def fabricated_empty(target):
        with sqlite3.connect(target / 'journal-recovery' / 'empty-initialization.sqlite') as db:
            db.execute("INSERT INTO state VALUES(1,'null')")

    def changed_rejected(target):
        with sqlite3.connect(target / 'journal-recovery' / 'rejected' / 'lost-state.sqlite') as db:
            db.execute('DELETE FROM requests')

    def missing_trace(target):
        path = target / 'pipeline-completion' / 'transport.json'
        value = read(path)
        index = next(i for i, event in enumerate(value) if event.get('request', {}).get('op') == 'application')
        del value[index]
        path.write_text(canonical(value) + '\n')

    controls = {'changed-completed-receipt': changed_completion, 'missing-binding': missing_binding,
                'fabricated-empty-journal': fabricated_empty, 'changed-rejected-journal': changed_rejected,
                'missing-owner-trace': missing_trace}
    outcomes = []
    with tempfile.TemporaryDirectory(prefix='session-check-', dir=directory.parent) as temp:
        for name, corrupt in controls.items():
            target = Path(temp) / name
            shutil.copytree(directory, target)
            corrupt(target)
            try:
                check(target)
            except (ValueError, KeyError, sqlite3.DatabaseError) as error:
                outcomes.append({'control': name, 'rejected': True, 'message': str(error)})
            else:
                raise ValueError('checker accepted corruption: ' + name)
    return outcomes


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--tamper-controls', action='store_true')
    args = parser.parse_args()
    result = check(args.directory)
    if args.tamper_controls:
        result['tamper_controls'] = tamper_controls(args.directory)
    print(canonical(result))
