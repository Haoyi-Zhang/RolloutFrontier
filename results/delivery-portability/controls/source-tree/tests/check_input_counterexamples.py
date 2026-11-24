"""Read-only reconstruction of two retained input-domain failure captures.

Only the standard library is used. This checks the consistency of historical
JSON/TCP observations, SQLite state, and the two changed-source preimages. It
neither imports nor executes the old application, driver, or protocol code.
"""
from __future__ import annotations

import argparse
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
RETAINED = ROOT / 'results/retained-session-reliability'
POST_FIX = RETAINED / 'utf8-inputs/normal/sources'
SCHEMA = 'utf8-observed'
PIPELINE = 'utf8-pipeline-observed'
PATHS = (
    'historical-drivers/repro_invalid_utf8.py',
    'historical-drivers/repro_invalid_utf8_pipeline.py',
    'source-preimages/src/application.py',
    'source-preimages/src/schema_contracts.py',
    SCHEMA + '/network/application-origins/owner-0000/origin-2.sqlite',
    SCHEMA + '/network/identity-0000.json',
    SCHEMA + '/network/owner-0000.sqlite',
    SCHEMA + '/network/registry.json',
    SCHEMA + '/network/relay-events.jsonl',
    SCHEMA + '/network/relay-routes.json',
    SCHEMA + '/network/relay-targets.json',
    SCHEMA + '/network/transport.jsonl',
    SCHEMA + '/observations.json',
    SCHEMA + '/session.sqlite',
    PIPELINE + '/observations.json',
    PIPELINE + '/origin-2.sqlite',
    PIPELINE + '/process-node-0.sqlite',
    PIPELINE + '/process-node-1.sqlite',
    PIPELINE + '/process-node-2.sqlite',
    PIPELINE + '/transport.jsonl',
)
PREIMAGES = (
    {'path': 'source-preimages/src/schema_contracts.py',
     'current_source': 'src/schema_contracts.py', 'function': 'validate_payload'},
    {'path': 'source-preimages/src/application.py',
     'current_source': 'src/application.py', 'function': 'semantic_record'},
)
TABLES = {
    SCHEMA + '/session.sqlite': {'state', 'requests'},
    SCHEMA + '/network/application-origins/owner-0000/origin-2.sqlite': {'state'},
    SCHEMA + '/network/owner-0000.sqlite': {'state', 'physical_identity', 'schema_results', 'schema_audit'},
    PIPELINE + '/origin-2.sqlite': {'state', 'application_sessions', 'application_requests'},
    **{PIPELINE + '/process-node-' + str(node) + '.sqlite':
       {'state', 'application_results', 'application_audit'} for node in range(3)},
}
BAD_SCHEMA = {'key': '\ud800', 'value': 17, 'status': 1}
BAD_PIPELINE = {'key': '\ud800', 'amount': 17}
ERROR_REPLY = {'reason': 'UnicodeEncodeError', 'status': 'invalid'}
SCHEMA_PROFILES = [
    ['accept:old-name', 'emit:old-name', 'program:enum-alias:legacy'],
    ['accept:new-name', 'accept:old-name', 'emit:old-name', 'program:enum-alias:accepting'],
    ['accept:new-name', 'accept:old-name', 'emit:new-name', 'program:enum-alias:emitting'],
    ['accept:new-name', 'emit:new-name', 'program:enum-alias:current'],
]
PIPELINE_SUPPORT = ['emit:ACTIVE', 'parse:ACTIVE', 'parse:ENABLED', 'program:accepting']


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def role(path):
    if path.startswith('source-preimages/'):
        return 'source-preimage'
    if path.startswith('historical-drivers/'):
        return 'historical-driver'
    if path.endswith('.sqlite'):
        return 'durable-database'
    name = Path(path).name
    return {'observations.json': 'recorded-outcomes', 'relay-events.jsonl': 'relay-trace',
            'transport.jsonl': 'transport-trace'}.get(name, 'configuration')


def load(directory):
    directory = directory.resolve()
    manifest = json.loads((directory / 'manifest.json').read_text())
    require(manifest['capture_kind'] == 'retained-pre-fix-counterexamples' and
            manifest['cases'] == [SCHEMA, PIPELINE], 'historical capture inventory')
    require(manifest['source_preimages'] == list(PREIMAGES) and
            manifest['historical_drivers'] == list(PATHS[:2]), 'preimage or driver inventory')
    require(manifest['full_historical_source_tree'] is False and
            manifest['historical_drivers_standalone'] is False and
            manifest['included_in_post_fix_counts'] is False and
            manifest['file_inventory_excludes_manifest_itself'] is True,
            'historical evidence scope changed')
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file()}
    require(actual == set(PATHS) | {'manifest.json'}, 'historical payload file inventory')
    inventory = [{'path': name, 'bytes': (directory / name).stat().st_size, 'role': role(name)}
                 for name in PATHS]
    require(manifest['payload_files'] == inventory, 'historical file sizes or roles changed')
    data = {'json': {}, 'events': {}, 'db': {}, 'text': {}, 'payload_bytes': sum(r['bytes'] for r in inventory)}
    for name in PATHS:
        path = directory / name
        if name.endswith('.sqlite'):
            with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
                db.execute('PRAGMA query_only=ON')
                require(db.execute('PRAGMA quick_check').fetchall() == [('ok',)], 'SQLite integrity: ' + name)
                tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                require(tables == TABLES[name], 'SQLite table inventory: ' + name)
                data['db'][name] = {table: [list(row) for row in db.execute('SELECT * FROM ' + table)]
                                    for table in sorted(tables)}
        elif name.endswith('.jsonl'):
            data['events'][name] = [json.loads(line) for line in path.read_text().splitlines()]
        elif name.endswith('.json'):
            data['json'][name] = json.loads(path.read_text())
        else:
            data['text'][name] = path.read_text()
    # Bind the original repair to its actually captured post-fix source. Later
    # session repairs must not rewrite this historical comparison or pretend
    # that the historical driver ran against today's implementation.
    retention = json.loads((RETAINED / 'retention.json').read_text())['files']
    data['post_fix_text'] = {}
    for record in PREIMAGES:
        path = POST_FIX / record['current_source']
        relative = path.relative_to(RETAINED).as_posix()
        require(hashlib.sha256(path.read_bytes()).hexdigest() == retention[relative],
                'retained post-fix source binding differs: ' + relative)
        data['post_fix_text'][record['current_source']] = path.read_text()
    return data


def state(tables):
    rows = tables['state']
    require(len(rows) == 1 and rows[0][0] == 1 and len(rows[0]) == 2, 'durable state singleton')
    return json.loads(rows[0][1])


def check_preimages(data):
    result = []
    for record, variable in zip(PREIMAGES, ('payload', 'value')):
        old = data['text'][record['path']]
        post_fix = data['post_fix_text'][record['current_source']]
        added = ("    try:\n        " + variable + "['key'].encode('utf-8')\n"
                 "    except UnicodeEncodeError as error:\n"
                 "        raise ValueError('semantic key must be valid UTF-8') from error\n")
        require(post_fix.count(added) == 1 and post_fix.replace(added, '', 1) == old,
                'changed-source preimage differs: ' + record['current_source'])
        functions = [node for node in ast.parse(old).body
                     if isinstance(node, ast.FunctionDef) and node.name == record['function']]
        require(len(functions) == 1 and not any(isinstance(node, ast.Call) and
                isinstance(node.func, ast.Attribute) and node.func.attr == 'encode'
                for node in ast.walk(functions[0])), 'old input validation already contained an encoder')
        result.append(dict(record,
            post_fix_source=(POST_FIX / record['current_source']).relative_to(ROOT).as_posix(),
            comparison='retained first post-fix source minus the original UTF-8 validation block'))
    for name in PATHS[:2]:
        tree = ast.parse(data['text'][name])
        require(any(isinstance(node, ast.Constant) and node.value == '\ud800' for node in ast.walk(tree)),
                'historical driver missing the retained bad input')
    return result


def bad_key(value):
    require(value['key'] == '\ud800' and [ord(c) for c in value['key']] == [55296],
            'retained bad key changed')
    try:
        value['key'].encode('utf-8')
    except UnicodeEncodeError:
        return
    raise ValueError('retained key is UTF-8 encodable')


def replay_owner(tables, node, support, manifest, required, operation, application_request, expected_failures):
    """Reconstruct the finite recorded history, without running owner code."""
    profile = {'node': node, 'generation': 0, 'support': support}
    replay = {'node': node, 'generation': 0, 'support': support, 'window': 8, 'policy': 'predicate',
              'floor': [0] * 6, 'slots': {}, 'catalog': {str(node): profile}}
    prefix = 'schema' if operation == 'schema' else 'application'
    require(tables[prefix + '_results'] == [], 'historical failed input has an application effect')
    prepare = {'op': 'prepare', 'origin': 2, 'sequence': 1, 'manifest': manifest,
               'requires': [] if operation == 'schema' else required}
    receipt = {'status': 'held', 'node': node, 'origin': 2, 'sequence': 1,
               'manifest': manifest, 'requires': prepare['requires'], 'observed_generation': 0}
    if operation == 'schema':
        prepare['options'] = [required]
        receipt['options'] = [required]
    failures, preparations, inspections, history = 0, 0, 0, {}
    for expected_order, row in enumerate(tables[prefix + '_audit'], 1):
        ordinal, raw_request, raw_response, raw_profile = row
        request, response, observed = map(json.loads, (raw_request, raw_response, raw_profile))
        require(ordinal == expected_order and observed == profile, 'owner audit order or profile')
        if request['op'] == 'read':
            require(request == {'op': 'read'} and response == {'status': 'observed', 'observed': profile},
                    'recorded read differs')
        elif request['op'] == 'prepare':
            require(request == prepare and not replay['slots'] and set(required) <= set(support),
                    'historical admission differs')
            require(response == {'status': 'held', 'receipt': receipt}, 'held receipt differs')
            replay['slots']['2:1'] = receipt
            preparations += 1
        elif request['op'] == operation:
            require(request == application_request and replay['slots'] == {'2:1': receipt},
                    'failed request has no matching retained authority')
            require(response == ERROR_REPLY, 'recorded encoding-failure response differs')
            failures += 1
        elif request['op'] == 'inspect':
            require(request == {'op': 'inspect'} and response == {'status': 'state', 'state': replay},
                    'final inspection differs from retained holds')
            inspections += 1
        else:
            raise ValueError('unexpected historical transition: ' + request['op'])
        history[ordinal] = {'request': request, 'response': response}
    require(preparations == inspections == 1 and failures == expected_failures,
            'historical preparation, failure, or inspection denominator')
    require(state(tables) == replay and replay['slots'] == {'2:1': receipt},
            'durable owner state differs from its recorded history')
    return {'receipt': receipt, 'history': history, 'state': replay, 'failures': failures}


def check_origin(tables, count, certificate):
    sequences = {str(node): 1 for node in range(count)}
    require(state(tables) == {'origin': 2, 'node_count': count, 'window': 8, 'policy': 'predicate',
            'next': [1] * count, 'serial': 1, 'attempts': {'1': {'status': 'committed',
            'manifest': certificate['manifest'], 'sequences': sequences, 'certificate': certificate}}},
            'origin lost or retired the unresolved request authority')


def check_schema_trace(data, identity, owner):
    events = data['events'][SCHEMA + '/network/transport.jsonl']
    starts = [e for e in events if e['event'] == 'owner-start']
    relays = [e for e in events if e['event'] == 'relay-start']
    stops = [e for e in events if e['event'] == 'owner-stop']
    relay_stops = [e for e in events if e['event'] == 'relay-stop']
    require(len(events) == 16 and len(starts) == len(relays) == len(stops) == len(relay_stops) == 1,
            'historical physical process record inventory')
    start, relay = starts[0], relays[0]
    require(start['owner'] == 'owner' and start['pid'] == stops[0]['pid'] and
            relay['pid'] == relay_stops[0]['pid'] and start['pid'] != relay['pid'], 'physical process bindings')
    command = start['command']
    require(command[command.index('-m') + 1] == 'src.schema_runtime', 'historical owner entry point')
    require(data['json'][SCHEMA + '/network/relay-targets.json'] == {'owner': start['port']} and
            data['json'][SCHEMA + '/network/relay-routes.json'] == relay['ports'], 'historical TCP routes')
    issued = {e['call']: e for e in events if e['event'] == 'rpc-issued'}
    received = {e['call']: e for e in events if e['event'] == 'rpc-result'}
    require(set(issued) == set(received) == set(range(1, 7)), 'historical schema RPC inventory')
    sizes = {}
    for call in issued:
        before, after = issued[call], received[call]
        require(before['owner'] == after['owner'] == 'owner' and before['source'] == after['source'] == 2 and
                before['pid'] == after['pid'] and before['request'] == after['request'] and
                before['time_ns'] <= after['time_ns'], 'historical schema RPC binding')
        actual = owner['history'][after['owner_order']]
        require(actual == {'request': after['request'], 'response': after['response']},
                'TCP reply differs from owner SQLite audit')
        request_bytes = len((canonical({'identity': identity, 'request': after['request']}) + '\n').encode())
        response_bytes = len((canonical({'identity': identity, 'response': after['response'],
                                         'owner_order': after['owner_order']}) + '\n').encode())
        require(after['bytes'] == request_bytes + response_bytes, 'historical schema frame sizes')
        sizes[call] = (request_bytes, response_bytes)
    trace = data['events'][SCHEMA + '/network/relay-events.jsonl']
    require(len(trace) == 25 and trace[0]['event'] == 'relay-start' and
            trace[0]['pid'] == relay['pid'] and trace[0]['ports'] == relay['ports'], 'relay trace header')
    for call in issued:
        group = [event for event in trace if event.get('connection') == call]
        require([event['event'] for event in group] ==
                ['socket-accepted', 'request-forwarded', 'reply-forwarded', 'socket-closed'],
                'relay connection record sequence')
        require(all(e['pid'] == relay['pid'] and e['owner'] == 'owner' for e in group),
                'relay identity changed')
        forward, reply = group[1:3]
        require(forward['operation'] == reply['operation'] == issued[call]['request']['op'] and
                forward['target_port'] == start['port'] and
                (forward['request_bytes'], reply['response_bytes']) == sizes[call], 'relay forwarded frame binding')
    return len(received)


def check_schema(data):
    tables = data['db'][SCHEMA + '/session.sqlite']
    session = state(tables)
    bad_key(BAD_SCHEMA)
    pending = [['bad-input', canonical(BAD_SCHEMA), 'pending', None]]
    require(tables['requests'] == pending, 'historical schema request is not the bad pending input')
    registry = {'deployment': 'utf8-review', 'owners': {'owner': {'family': 'enum-alias',
                'initial': SCHEMA_PROFILES[0], 'catalog': SCHEMA_PROFILES}}}
    require(data['json'][SCHEMA + '/network/registry.json'] == registry and
            re.fullmatch('[0-9a-f]{32}', session['birth_token']) is not None, 'historical session identity')
    binding = {'birth_token': session['birth_token'], 'manifest': 'utf8-review', 'registry': registry,
               'window': 8, 'workflow': [{'id': 'only', 'owner': 'owner', 'parents': []}],
               'family': 'enum-alias', 'codecs': {'owner': 'old-name'}}
    manifest = 'utf8-review:session:' + hashlib.sha256(canonical(binding).encode()).hexdigest()
    request = {'op': 'schema', 'origin': 2, 'sequence': 1, 'manifest': manifest,
               'request_id': 'bad-input:only', 'input_classes': [], 'emit_class': 'old-name',
               'inputs': [], 'seed': BAD_SCHEMA}
    owner_tables = data['db'][SCHEMA + '/network/owner-0000.sqlite']
    owner = replay_owner(owner_tables, 0, SCHEMA_PROFILES[0], manifest, ['emit:old-name'], 'schema', request, 3)
    cert = {'mode': 'envelope', 'origin': 2, 'manifest': manifest, 'box': {'0': [['emit:old-name']]},
            'sequences': {'0': 1}, 'receipts': [owner['receipt']]}
    expected = {**binding, 'schema': 'factored-schema-session', 'stage': 'closing',
                'certificates': {'owner': cert}, 'admission_certificates': {'owner': cert}, 'journal_sequence': 2}
    require(session == expected, 'historical closing session lost its binding or authority')
    check_origin(data['db'][SCHEMA + '/network/application-origins/owner-0000/origin-2.sqlite'], 1, cert)
    identity = {'deployment': 'utf8-review', 'owner': 'owner', 'family': 'enum-alias',
                'initial': SCHEMA_PROFILES[0], 'catalog': SCHEMA_PROFILES, 'window': 8, 'policy': 'predicate'}
    require(owner_tables['physical_identity'] == [[1, canonical(identity)]] and
            data['json'][SCHEMA + '/network/identity-0000.json'] == identity, 'physical owner registry binding')
    observed = data['json'][SCHEMA + '/observations.json']
    require(observed['seed_prevalidation'] == 'accepted' and observed['request_rows'] == pending and
            observed['schema_audit'] == [ERROR_REPLY] * 3 and observed['durable_effects'] == 0 and
            observed['remaining_holds'] == 1 and observed['durable_stage_after_reopen'] == 'closing' and
            observed['close_before_reopen'] is False and observed['close_after_reopen'] is False and
            observed['counterexample_reproduced'] is True, 'recorded schema failure outcome differs')
    require(observed['request_outcomes'] == [{'attempt': i, 'error': 'SchemaRequestPending',
            'message': 'physical schema effect unconfirmed at owner'} for i in range(3)], 'recorded retry outcomes')
    calls = check_schema_trace(data, identity, owner)
    return {'pending_requests': 1, 'closing_gate': True, 'held_owner_obligations': 1,
            'durable_effects': 0, 'recorded_encoding_failure_replies': 3, 'owner_audit_rows': 6,
            'recorded_tcp_calls': calls, 'retirement_before_and_after_reopen_recorded_false': True}


def check_pipeline_trace(data, owners):
    trace = data['events'][PIPELINE + '/transport.jsonl']
    starts = [e for e in trace if e['event'] == 'process-start']
    stops = [e for e in trace if e['event'] == 'process-stop']
    calls = [e for e in trace if e['event'] == 'rpc']
    require(len(trace) == 14 and len(starts) == len(stops) == 3 and len(calls) == 8 and
            {e['node'] for e in starts} == {e['node'] for e in stops} == {0, 1, 2},
            'historical pipeline process/RPC record inventory')
    require(len({e['pid'] for e in starts}) == 3, 'historical pipeline process identities')
    for start in starts:
        command = start['command']
        require(command[command.index('-m') + 1] == 'src.application' and
                command[command.index('--serve') + 1] == str(start['node']) and
                command[command.index('--initial') + 1] == 'accepting', 'historical pipeline executable binding')
    require({e['call'] for e in calls} == set(range(1, 9)), 'pipeline call identities')
    seen = set()
    for event in calls:
        node, ordinal = event['target'], event['owner_order']
        require(node in owners and event['source'] == 2 and (node, ordinal) not in seen,
                'pipeline RPC owner binding')
        seen.add((node, ordinal))
        require(owners[node]['history'][ordinal] == {'request': event['request'], 'response': event['response']},
                'pipeline TCP reply differs from owner SQLite audit')
        require(event['end_ns'] >= event['start_ns'] and
                event['wall_ns'] == event['end_ns'] - event['start_ns'], 'pipeline RPC interval')
        expected_bytes = len((canonical(event['request']) + '\n').encode()) + len((canonical(
            {'response': event['response'], 'owner_order': ordinal}) + '\n').encode())
        require(event['bytes'] == expected_bytes, 'pipeline frame sizes')
    require(seen == {(node, ordinal) for node, owner in owners.items() for ordinal in owner['history']},
            'pipeline audit/RPC coverage')
    return len(calls)


def check_pipeline(data):
    tables = data['db'][PIPELINE + '/origin-2.sqlite']
    bad_key(BAD_PIPELINE)
    manifest, codec = 'utf8-pipeline-review', ['ACTIVE', 'ACTIVE']
    pending = [[manifest, 'bad-input', canonical(BAD_PIPELINE), canonical(codec), 'pending', None]]
    require(tables['application_requests'] == pending and
            tables['application_sessions'] == [[manifest, canonical(codec), 1]], 'pipeline bad pending input or drain gate')
    request = {'op': 'application', 'origin': 2, 'sequence': 1, 'manifest': manifest,
               'request_id': 'bad-input', 'codec': codec, 'input': BAD_PIPELINE}
    owners = {}
    requirements = [['emit:ACTIVE'], ['emit:ACTIVE', 'parse:ACTIVE'], ['parse:ACTIVE']]
    for node in range(3):
        owners[node] = replay_owner(data['db'][PIPELINE + '/process-node-' + str(node) + '.sqlite'],
            node, PIPELINE_SUPPORT, manifest, requirements[node], 'application', request, 2 if node == 0 else 0)
    cert = {'branch': 0, 'manifest': manifest, 'origin': 2, 'sequences': {'0': 1, '1': 1, '2': 1},
            'receipts': [owners[node]['receipt'] for node in range(3)]}
    check_origin(tables, 3, cert)
    observed = data['json'][PIPELINE + '/observations.json']
    require(observed['request_rows'] == [['bad-input', canonical(BAD_PIPELINE), 'pending', None]] and
            observed['retire_before_reopen'] is False and observed['retire_after_reopen'] is False and
            observed['remaining_holds'] == 3 and observed['durable_effects'] == 0 and
            observed['counterexample_reproduced'] is True, 'recorded pipeline retirement outcome differs')
    outcomes = observed['request_outcomes']
    require(len(outcomes) == 2 and all(row['attempt'] == i and row['error'] == 'RuntimeError' and
            row['message'] == "pipeline call incomplete: {'reason': 'UnicodeEncodeError', 'status': 'invalid'}"
            for i, row in enumerate(outcomes)), 'pipeline recorded failure replies')
    calls = check_pipeline_trace(data, owners)
    return {'pending_requests': 1, 'closing_gate': True, 'held_owner_obligations': 3,
            'durable_effects': 0, 'recorded_encoding_failure_replies': 2, 'owner_audit_rows': 8,
            'recorded_tcp_calls': calls, 'retirement_before_and_after_reopen_recorded_false': True}


def check_loaded(data):
    preimages = check_preimages(data)
    schema, pipeline = check_schema(data), check_pipeline(data)
    return {'status': 'PASS', 'historical_cases': 2, 'schema_session': schema, 'pipeline_session': pipeline,
            'pending_requests': 2, 'held_owner_obligations': 4, 'durable_effects': 0,
            'recorded_encoding_failure_replies': 5, 'owner_audit_rows': 14, 'databases': 7,
            'payload_files': len(PATHS), 'payload_bytes': data['payload_bytes'], 'source_preimages': preimages,
            'full_historical_source_tree': False, 'old_code_reexecuted': False,
            'included_in_post_fix_counts': False,
            'scope': 'Read-only consistency of retained failure observations, TCP/owner-audit replies, '
                     'durable pending requests, blocked drain state, and two changed-source preimages. '
                     'Before/after-reopen retirement returns are recorded outcomes; old code is not executed.'}


def corruption_controls(data):
    """Mutate disposable in-memory copies; the captured files remain read-only."""
    results = []
    for name in ('pending-binding', 'owner-hold', 'owner-effect', 'failure-reply',
                 'source-preimage', 'post-fix-source'):
        changed = deepcopy(data)
        if name == 'pending-binding':
            changed['db'][SCHEMA + '/session.sqlite']['requests'][0][2] = 'complete'
        elif name == 'owner-hold':
            tables = changed['db'][PIPELINE + '/process-node-0.sqlite']
            altered = state(tables); altered['slots'] = {}
            tables['state'][0][1] = canonical(altered)
        elif name == 'owner-effect':
            changed['db'][SCHEMA + '/network/owner-0000.sqlite']['schema_results'].append(['unexpected'])
        elif name == 'failure-reply':
            changed['db'][SCHEMA + '/network/owner-0000.sqlite']['schema_audit'][2][2] = canonical({'status': 'applied'})
        elif name == 'source-preimage':
            changed['text']['source-preimages/src/schema_contracts.py'] += '\n'
        else:
            changed['post_fix_text']['src/schema_contracts.py'] += '\n'
        try:
            check_loaded(changed)
        except (ValueError, KeyError, TypeError) as error:
            results.append({'control': name, 'rejected': True, 'reason': str(error)})
        else:
            raise ValueError('changed historical evidence accepted: ' + name)
    return results


def verify(directory, controls=False):
    data = load(Path(directory))
    result = check_loaded(data)
    result['corruption_controls'] = corruption_controls(data) if controls else []
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--corruption-controls', action='store_true')
    args = parser.parse_args()
    print(json.dumps(verify(args.results, args.corruption_controls), indent=2, sort_keys=True))
