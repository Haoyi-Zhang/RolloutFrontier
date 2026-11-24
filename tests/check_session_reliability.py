"""Read saved session controls and historical failures without running old code."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile

from tests.check_session_repairs import (
    GROUPS, SOURCE_NAMES, admission, canonical, check as check_repaired,
    read, require, rows, state, tamper_controls as repaired_corruptions,
)

ROOT = Path(__file__).resolve().parents[1]
OLD_SOURCE_NAMES = {
    'src/' + name + '.py' for name in (
        '__init__', 'android_contracts', 'application', 'batch', 'checker', 'controller',
        'direct_batch', 'effect_ledger', 'envelope', 'factored_planner', 'factored_runtime',
        'factored_session', 'goal_planner', 'heterogeneous_contracts', 'network', 'rollout',
        'schema_contracts', 'schema_runtime', 'structured_planner')
} | {'tests/' + name + '.py' for name in
     ('application_network', 'factored_network', 'factored_tcp_relay', 'multiprocess')}
ORIGINAL_CASES = ('pipeline-concurrent-completion', 'unencodable-manifest', 'empty-journal-retry')
CORRUPTIONS = {'changed-completed-receipt', 'missing-binding', 'fabricated-empty-journal',
               'changed-rejected-journal', 'missing-owner-trace'}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def held(path):
    return sum(slot['status'] == 'held' for slot in state(path)['slots'].values())


def normalized(value):
    if isinstance(value, dict):
        return {key: normalized(item) for key, item in value.items() if key != 'birth_token'}
    if isinstance(value, list):
        return [normalized(item) for item in value]
    return value


def source_inventory(directory, retained):
    inventory = read(directory / 'inventory.json')
    require(inventory['datasets'] == ['counterexamples', 'string-boundaries'] and
            inventory['historical_drivers_are_executed'] is False, 'historical dataset identity')
    actual = {p.relative_to(directory).as_posix(): digest(p) for p in directory.rglob('*')
              if p.is_file() and p != directory / 'inventory.json'}
    require(len(actual) == 82 and actual == inventory['files'], 'historical file inventory or bytes changed')
    source = directory / 'counterexamples' / 'source-preimages'
    manifest = read(directory / 'counterexamples' / 'source-manifest.json')
    require(set(manifest) == OLD_SOURCE_NAMES and
            {p.relative_to(source).as_posix() for p in source.rglob('*') if p.is_file()} == OLD_SOURCE_NAMES,
            'historical source inventory incomplete')
    require(set(inventory['source_anchors']) == OLD_SOURCE_NAMES, 'retained source anchor inventory')
    retention = read(retained / 'retention.json')['files']
    for name in sorted(OLD_SOURCE_NAMES):
        cohort = 'utf8-inputs/normal' if name in ('tests/application_network.py', 'tests/multiprocess.py') else 'factored-runtime'
        relative = cohort + '/sources/' + name
        require(inventory['source_anchors'][name] == 'retained-session-reliability/' + relative,
                'unexpected historical source anchor')
        expected = manifest[name]
        require(digest(source / name) == expected == retention[relative] and
                (source / name).read_bytes() == (retained / relative).read_bytes(),
                'old source preimage differs from retained measured source: ' + name)
    changed = sorted(name for name in OLD_SOURCE_NAMES if name.startswith('src/') and
                     (source / name).read_bytes() != (ROOT / name).read_bytes())
    require(changed == ['src/application.py', 'src/factored_session.py', 'src/schema_contracts.py'],
            'historical and repaired runtime differences changed')
    return {'bound_files': len(actual), 'source_preimages': len(manifest),
            'retained_source_matches': len(manifest), 'changed_runtime_files': changed,
            'counterexample_source_provenance': inventory['counterexample_source_provenance'],
            'string_boundary_source_provenance': inventory['string_boundary_source_provenance']}


def history_links(directory, kind):
    if kind == 'pipeline':
        events = [event for event in read(directory / 'transport.json') if event['event'] == 'rpc']
        databases = {node: directory / f'process-node-{node}.sqlite' for node in range(3)}
        table = 'application_audit'
    else:
        trace = [json.loads(line) for line in (directory / 'transport.jsonl').read_text().splitlines()]
        events = [event for event in trace if event['event'] == 'rpc-result']
        issued = {event['call']: event for event in trace if event['event'] == 'rpc-issued'}
        require(len(events) == len(issued) and len({event['call'] for event in events}) == len(events),
                'historical physical call inventory')
        for event in events:
            require(issued[event['call']]['request'] == event['request'], 'historical transport request changed')
        databases = {'only': directory / 'owner-0000.sqlite'}
        table = 'schema_audit'
    audit = {}
    for owner, path in databases.items():
        records = rows(path, 'SELECT ordinal,request,response FROM ' + table + ' ORDER BY ordinal')
        require([r[0] for r in records] == list(range(1, len(records) + 1)), 'historical audit sequence')
        audit.update({(owner, ordinal): (json.loads(request), json.loads(response))
                      for ordinal, request, response in records})
    linked = set()
    for event in events:
        key = (event['target'] if kind == 'pipeline' else event['owner'], event['owner_order'])
        require(key in audit and key not in linked and event['response'] is not None and
                audit[key] == (event['request'], event['response']), 'historical TCP/audit mismatch')
        linked.add(key)
    require(linked == set(audit), 'historical owner operation lacks a transport record')
    return events


def pending_schema(directory, request_id, value):
    database = directory / 'session.sqlite'
    session = state(database)
    require(session['stage'] == 'closing' and rows(database,
            'SELECT request_id,input,status,output FROM requests') ==
            [(request_id, canonical(value), 'pending', None)], 'historical pending schema binding')
    require(rows(directory / 'owner-0000.sqlite', 'SELECT * FROM schema_results') == [] and
            held(directory / 'owner-0000.sqlite') == 1, 'historical pending effect or hold count')
    manifest = admission(session)
    cert = session['certificates']['only']
    require(cert == session['admission_certificates']['only'] and cert['manifest'] == manifest,
            'historical pending session lost its admission')
    live = [slot for slot in state(directory / 'owner-0000.sqlite')['slots'].values() if slot['status'] == 'held']
    require(len(live) == 1 and live[0]['manifest'] == manifest, 'historical hold belongs to another session')
    origin = state(directory / 'application-origins' / 'owner-0000' / 'origin-2.sqlite')
    require(len(origin['attempts']) == 1 and next(iter(origin['attempts'].values()))['certificate'] == cert,
            'historical pending origin authority differs')
    return session


def historical_completion(directory):
    report = read(directory / 'observations.json')
    first, later, retry = (read(directory / name) for name in
                           ('first-completion.json', 'later-completion.json', 'exact-retry.json'))
    require(first != later and later == retry and first['record'] == later['record'] ==
            {'key': 'same-logical-request', 'amount': 58}, 'historical changed-completion witness')
    require([r['duplicate'] for r in first['owner_replies']] == [True, False, False] and
            [r['duplicate'] for r in later['owner_replies']] == [False, True, True], 'historical receipt difference')
    for name, expected in (('origin-after-first-completion.sqlite', first),
                           ('origin-after-later-completion.sqlite', later), ('origin-2.sqlite', later)):
        saved = rows(directory / name, 'SELECT manifest,request_id,input,status,output FROM application_requests')
        require(len(saved) == 1 and saved[0][:4] == ('concurrent-result', 'request',
                canonical({'key': 'same-logical-request', 'amount': 17}), 'complete') and
                json.loads(saved[0][4]) == expected, 'historical durable completion checkpoint')
    events = history_links(directory, 'pipeline')
    application = [event for event in events if event['request']['op'] == 'application']
    require(len(application) == 6, 'historical concurrent owner call count')
    for node in range(3):
        replies = [event['response'] for event in application if event['target'] == node]
        require([r['duplicate'] for r in replies] == [False, True] and
                first['owner_replies'][node] == replies[1 if node == 0 else 0] and
                later['owner_replies'][node] == replies[0 if node == 0 else 1], 'historical reply provenance')
        require(rows(directory / f'process-node-{node}.sqlite', 'SELECT request_id FROM application_results') ==
                [('request',)] and held(directory / f'process-node-{node}.sqlite') == 0,
                'historical concurrent effect denominator')
    require(report['first_completion_was_durable'] is True and report['completed_response_changed'] is True and
            report['returned_response_changed_on_exact_retry'] is True and report['retired'] is True,
            'historical driver completion outcome differs')
    return {'recorded_driver_outcomes': report,
            'independently_reconstructed': {'completed_rows_per_checkpoint': 1,
                'first_durable_output_differs_from_final': True, 'business_record_unchanged': True,
                'owner_calls': 6, 'effects_per_owner': [1, 1, 1], 'final_held_guards': 0}}


def historical_manifest(directory):
    report = read(directory / 'observations.json')
    value = {'key': 'well-formed', 'value': 7, 'status': 1}
    session = pending_schema(directory, 'valid-request', value)
    require([ord(c) for c in session['manifest']] == [108, 97, 98, 101, 108, 45, 55296],
            'historical unencodable manifest changed')
    before = directory / 'session-before-reopen.sqlite'
    require(state(before) == session and rows(before, 'SELECT * FROM requests') ==
            rows(directory / 'session.sqlite', 'SELECT * FROM requests'), 'historical pending checkpoint changed')
    events = history_links(directory, 'factored')
    calls = [event for event in events if event['request']['op'] == 'schema']
    require(len(calls) == 3 and all(event['response'] == {'status': 'invalid', 'reason': 'UnicodeEncodeError'} and
            event['request']['seed'] == value and event['request']['manifest'] == admission(session)
            for event in calls), 'historical invalid manifest owner replies')
    require(report['retired_before_reopen'] is False and report['retired_after_reopen'] is False and
            report['invalid_replies'] == [event['response'] for event in calls], 'historical manifest driver outcome')
    return {'recorded_driver_outcomes': report,
            'independently_reconstructed': {'pending_requests': 1, 'effects': 0, 'held_guards': 1,
                'owner_unicode_errors': 3, 'before_and_after_named_checkpoints_agree': True}}


def historical_empty(directory):
    report = read(directory / 'observations.json')
    checkpoint = directory / 'empty-journal-after-corrected-begin.sqlite'
    require(rows(checkpoint, 'SELECT * FROM state') == [] and rows(checkpoint, 'SELECT * FROM requests') == [],
            'historical empty-journal checkpoint changed')
    final = state(directory / 'session.sqlite')
    value = {'key': 'well-formed', 'value': 7, 'status': 1}
    request = rows(directory / 'session.sqlite', 'SELECT request_id,input,status,output FROM requests')
    require(final['stage'] == 'retired' and not final['certificates'] and len(request) == 1 and
            request[0][:3] == ('corrected', canonical(value), 'complete') and
            json.loads(request[0][3])['records'] == {'source': value}, 'historical explicit initialization outcome')
    effect = rows(directory / 'owner-0000.sqlite', 'SELECT request_id,output FROM schema_results')
    require(len(effect) == 1 and effect[0][0] == 'corrected:source' and
            json.loads(effect[0][1])['record'] == value and held(directory / 'owner-0000.sqlite') == 0,
            'historical explicit initialization effect')
    events = history_links(directory, 'factored')
    require([event['request']['op'] for event in events] == ['read', 'prepare', 'schema', 'close'],
            'historical initialization transport sequence')
    require(report['begin_errors'] == [
            {'exception': 'FactoredExecutionError', 'message': 'dataflow size'},
            {'exception': 'FactoredExecutionError', 'message': 'invalid physical codec placement'}] and
            report['explicit_constructor_recovery'] is True, 'historical begin error record changed')
    return {'recorded_driver_outcomes': report,
            'independently_reconstructed': {'empty_checkpoint_state_rows': 0,
                'empty_checkpoint_request_rows': 0, 'final_completed_requests': 1, 'final_effects': 1,
                'final_held_guards': 0},
            'interpretation': 'The exception sequence is recorded by the original driver; the empty checkpoint and later completion are reconstructed from retained databases.'}


def historical_python_entries(directory):
    combined = read(directory / 'observations.json')
    require(set(combined) == {'pipeline', 'factored', 'direct-schema', 'effect-ledger'}, 'string audit group inventory')
    for group in combined:
        require(read(directory / group / 'observations.json') == combined[group], 'string audit group/report differs')
    pipeline = directory / 'pipeline'
    request = rows(pipeline / 'origin-2.sqlite', 'SELECT manifest,request_id,input,status,output FROM application_requests')
    pending = [row for row in request if row[3] == 'pending']
    require(pending == [('subclass-key', 'subclass', canonical({'key': '\ud800', 'amount': 1}), 'pending', None)],
            'historical Python pipeline entry lacks its pending row')
    events = history_links(pipeline, 'pipeline')
    calls = [event for event in events if event['request']['op'] == 'application' and
             event['request']['request_id'] == 'subclass']
    require(len(calls) == 1 and calls[0]['target'] == 0 and
            calls[0]['response'] == {'status': 'invalid', 'reason': 'ValueError'} and
            calls[0]['request']['input'] == {'key': '\ud800', 'amount': 1}, 'historical subclass pipeline rejection')
    for node in range(3):
        require(rows(pipeline / f'process-node-{node}.sqlite', 'SELECT request_id FROM application_results') ==
                [('text-🧪-\x00',)] and held(pipeline / f'process-node-{node}.sqlite') == 1,
                'historical subclass pipeline effect/guard count')
    factored = directory / 'factored'
    pending_schema(factored, 'subclass', {'key': '\ud800', 'value': 1, 'status': 1})
    schema_events = history_links(factored, 'factored')
    schema_calls = [event for event in schema_events if event['request']['op'] == 'schema']
    require(len(schema_calls) == 1 and schema_calls[0]['response'] == {'status': 'invalid', 'reason': 'ValueError'}
            and schema_calls[0]['request']['seed'] == {'key': '\ud800', 'value': 1, 'status': 1},
            'historical subclass factored rejection')
    require(combined['pipeline']['subclass_key']['retired'] is False and
            combined['factored']['subclass_key']['retired'] is False, 'historical Python entry driver outcome')
    return {'recorded_driver_outcomes': {name: combined[name]['subclass_key'] for name in ('pipeline', 'factored')},
            'independently_reconstructed': {'pipeline_pending_requests': 1, 'pipeline_failed_owner_calls': 1,
                'pipeline_held_guards': 3, 'pipeline_effects_for_pending_id': 0,
                'factored_pending_requests': 1, 'factored_failed_owner_calls': 1,
                'factored_held_guards': 1, 'factored_effects': 0},
            'input_provenance': 'The retained driver constructs EncodableSubclass at the Python API. SQL and transport records retain its string contents, not a Python class or executable object.'}


def historical_boundary_controls(directory):
    report = read(directory / 'observations.json')
    direct = directory / 'direct-schema'
    for index in (0, 1):
        path = direct / f'owner-{index}.sqlite'
        identity = report['direct-schema'][f'identity-{index}']
        stored = rows(path, 'SELECT identity FROM physical_identity')
        require(stored == [(identity['stored_identity'],)] and stored[0][0].isascii() and
                json.loads(stored[0][0]) == identity['readable_identity'] and held(path) == 0,
                'historical registry text was not stored as canonical JSON')
        history = rows(path, 'SELECT request,response FROM schema_audit ORDER BY ordinal')
        responses = [json.loads(row[1]) for row in history]
        require(len(history) == 4 and [r['status'] for r in responses] == ['invalid', 'applied', 'invalid', 'invalid'] and
                all(r['reason'] == 'UnicodeEncodeError' for r in responses if r['status'] == 'invalid'),
                'historical direct schema text boundary')
        effect = rows(path, 'SELECT manifest,request_id FROM schema_results')
        require(effect == [('valid', 'text-🧪-\x00')], 'historical direct schema effect denominator')
        for sequence, valid, ordinal in ((1, False, 0), (1, True, 1), (2, False, 2), (2, True, 3)):
            recorded = report['direct-schema'][f'{index}-{sequence}-{valid}']
            require(recorded['response'] == responses[ordinal], 'historical direct boundary reply differs')
    ledger = directory / 'effect-ledger' / 'effects.sqlite'
    good = 'text-🧪-\x00'
    require(rows(ledger, 'SELECT * FROM leases') == [('0' * 64, 'closed')] and
            rows(ledger, 'SELECT * FROM operations') == [(1, '0' * 64, good, good, 'done')] and
            rows(ledger, 'SELECT * FROM effects') == [(good, good)], 'historical effect ledger final state')
    return {'recorded_driver_outcomes': {
                'pipeline_invalid_request_id': report['pipeline']['invalid_request_id'],
                'pipeline_invalid_manifest': report['pipeline']['invalid_pipeline_manifest'],
                'effect_ledger': report['effect-ledger']},
            'independently_reconstructed': {'direct_schema_invalid_replies': 6,
                'direct_schema_completed_effects': 2, 'registry_identity_json_is_ascii': True,
                'ledger_completed_operations': 1, 'ledger_effects': 1, 'ledger_closed_leases': 1},
            'interpretation': 'The driver records zero intermediate operations for rejected ledger inputs. The final database independently contains only the subsequent legitimate operation.'}


def check_historical(directory, retained):
    sources = source_inventory(directory, retained)
    counterexamples = directory / 'counterexamples'
    summary = read(counterexamples / 'summary.json')
    require(summary['status'] == 'COUNTEREXAMPLES_OBSERVED' and summary['source_unchanged'] is True and
            set(summary['cases']) == set(ORIGINAL_CASES), 'original counterexample driver completion')
    for name in ORIGINAL_CASES:
        require(summary['cases'][name] == read(counterexamples / name / 'observations.json'),
                'original counterexample summary/group differs')
    reconstructed = {
        'pipeline_concurrent_completion': historical_completion(counterexamples / ORIGINAL_CASES[0]),
        'unencodable_manifest': historical_manifest(counterexamples / ORIGINAL_CASES[1]),
        'empty_journal_retry': historical_empty(counterexamples / ORIGINAL_CASES[2]),
        'custom_python_string_entries': historical_python_entries(directory / 'string-boundaries'),
        'other_text_boundaries': historical_boundary_controls(directory / 'string-boundaries'),
    }
    return {'status': 'PASS', 'historical_drivers_executed': False, 'included_in_post_repair_totals': False,
            'source_binding': sources, 'recorded_failure_cases': 5, 'cases': reconstructed}


def check(results):
    checked = {mode: check_repaired(results / mode) for mode in ('normal', 'optimized')}
    require(checked['normal']['optimization'] == 0 and checked['optimized']['optimization'] == 1,
            'post-repair mode identities')
    normal = {key: value for key, value in checked['normal'].items() if key != 'optimization'}
    optimized = {key: value for key, value in checked['optimized'].items() if key != 'optimization'}
    require(normal == optimized and {key: normal[key] for key in ('requests', 'effects', 'rejections', 'audit_rows')} ==
            {'requests': 11, 'effects': 21, 'rejections': 25, 'audit_rows': 91}, 'post-repair mode denominators differ')
    for group in GROUPS:
        require(normalized(read(results / 'normal' / group / 'observations.json')) ==
                normalized(read(results / 'optimized' / group / 'observations.json')), 'mode-normalized observations differ')
    for name in SOURCE_NAMES:
        require((results / 'normal' / 'sources' / name).read_bytes() ==
                (results / 'optimized' / 'sources' / name).read_bytes(), 'modes used different source bytes')
    for cohort in ('normal', 'optimized'):
        records = []
        for mode in ('normal', 'optimized'):
            record = read(results / 'checks' / cohort / (mode + '.json'))
            require({k: v for k, v in record.items() if k != 'tamper_controls'} == checked[cohort],
                    'saved independent reader result differs')
            require(len(record['tamper_controls']) == 5 and
                    {row['control'] for row in record['tamper_controls']} == CORRUPTIONS and
                    all(row['rejected'] is True for row in record['tamper_controls']), 'saved corruption coverage')
            records.append(record)
        require(records[0] == records[1], 'normal/optimized readers disagree on a completed cohort')
    historical = check_historical(results / 'historical', results.parent / 'retained-session-reliability')
    return {'status': 'PASS', 'post_repair': {'modes': 2, 'groups_per_mode': len(GROUPS),
                'mode_normalized_results_agree': True, 'per_mode': normal,
                'combined': {key: 2 * normal[key] for key in ('requests', 'effects', 'rejections', 'audit_rows')},
                'saved_independent_reader_records': 4}, 'historical': historical}


def corruption_controls(results):
    repaired = {mode: repaired_corruptions(results / mode) for mode in ('normal', 'optimized')}
    historical = results / 'historical'
    retained = results.parent / 'retained-session-reliability'

    def changed_receipt(target):
        path = target / 'counterexamples' / 'pipeline-concurrent-completion' / 'first-completion.json'
        value = read(path)
        value['owner_replies'][0]['duplicate'] = False
        path.write_text(canonical(value) + '\n')

    def missing_pending(target):
        with sqlite3.connect(target / 'counterexamples' / 'unencodable-manifest' / 'session.sqlite') as db:
            db.execute('DELETE FROM requests')

    def nonempty_checkpoint(target):
        path = target / 'counterexamples' / 'empty-journal-retry' / 'empty-journal-after-corrected-begin.sqlite'
        with sqlite3.connect(path) as db:
            db.execute("INSERT INTO state VALUES(1,'null')")

    def missing_python_pending(target):
        with sqlite3.connect(target / 'string-boundaries' / 'factored' / 'session.sqlite') as db:
            db.execute('DELETE FROM requests')

    def changed_old_source(target):
        path = target / 'counterexamples' / 'source-preimages' / 'src' / 'application.py'
        path.write_bytes(path.read_bytes() + b'\n# changed historical source\n')
        manifest = read(target / 'counterexamples' / 'source-manifest.json')
        manifest['src/application.py'] = digest(path)
        (target / 'counterexamples' / 'source-manifest.json').write_text(canonical(manifest) + '\n')

    cases = {'changed-historical-receipt': changed_receipt, 'missing-historical-pending': missing_pending,
             'nonempty-historical-checkpoint': nonempty_checkpoint,
             'missing-python-entry-pending': missing_python_pending, 'changed-historical-source': changed_old_source}
    outcomes = []
    with tempfile.TemporaryDirectory(prefix='historical-check-', dir=results.parent) as temp:
        for name, corrupt in cases.items():
            target = Path(temp) / name
            shutil.copytree(historical, target)
            corrupt(target)
            inventory = read(target / 'inventory.json')
            inventory['files'] = {p.relative_to(target).as_posix(): digest(p) for p in target.rglob('*')
                                  if p.is_file() and p != target / 'inventory.json'}
            (target / 'inventory.json').write_text(canonical(inventory) + '\n')
            try:
                check_historical(target, retained)
            except (ValueError, KeyError, sqlite3.DatabaseError) as error:
                outcomes.append({'control': name, 'rejected': True, 'inventory_rebound': True, 'message': str(error)})
            else:
                raise ValueError('historical reader accepted altered evidence: ' + name)
    return {'post_repair': repaired, 'historical': outcomes,
            'note': 'Historical inventory checksums are recomputed after each edit, so these controls exercise reconstruction and retained-source comparison.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--corruption-controls', action='store_true')
    args = parser.parse_args()
    result = check(args.results.resolve())
    if args.corruption_controls:
        result['corruption_controls'] = corruption_controls(args.results.resolve())
    print(canonical(result))
