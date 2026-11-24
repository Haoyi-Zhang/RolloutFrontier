"""Independently bind saved session-identity controls to durable owner evidence.

No production controller, session, transport, or application code is imported.
The independent physical-owner replay also decodes saved ProtoJSON effects from
the retained schema descriptors. This program checks evidence already captured
by session_identity_regression; it does not re-execute its response withholding,
task cancellation, or constructor exceptions. Those recorded outcomes are kept
separate from the facts reconstructed from the journals and owner audit rows.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile

from tests.check_factored_execution import (
    canonical, check_owner, load, read_state, require, session_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE_NAMES = (
    'src/controller.py', 'src/network.py', 'src/checker.py', 'src/envelope.py',
    'src/factored_planner.py', 'src/factored_runtime.py', 'src/factored_session.py',
    'src/schema_runtime.py', 'src/schema_contracts.py',
    'tests/session_identity_regression.py',
)
FLOW = [
    {'id': 'source', 'owner': 'a', 'parents': []},
    {'id': 'sink', 'owner': 'b', 'parents': ['source']},
]
CYCLE = [
    {'id': 'source', 'owner': 'a', 'parents': []},
    {'id': 'middle', 'owner': 'b', 'parents': ['source']},
    {'id': 'sink', 'owner': 'a', 'parents': ['middle']},
]
REVERSED_CYCLE = [
    {'id': 'source', 'owner': 'b', 'parents': []},
    {'id': 'middle', 'owner': 'a', 'parents': ['source']},
    {'id': 'sink', 'owner': 'b', 'parents': ['middle']},
]
VALUE = {'key': 'retained-\u03ba', 'value': 17, 'status': 1}
LATER_VALUE = {'key': 'later', 'value': 29, 'status': 1}

# These are the producer's explicitly recorded outcomes. Journal and audit
# checks below supply separate evidence; equality here alone proves no fault.
RECORDED = {
    'fresh_and_repeated_journal': {
        'foreign_journal_rejections': 2, 'pending_holds_preserved': 2,
        'old_exact_retry_recovered': True, 'fresh_births_distinct': True,
        'later_same_label_and_request_id': 'independent-completion',
        'admission_manifest_characters_at_label_limit': 201,
        'final_effects': 4, 'final_holds': 0,
    },
    'precreated_journal': {
        'created_before_other_session': True, 'foreign_journal_rejections': 1,
        'old_exact_retry_recovered': True, 'precreated_birth_preserved': True,
        'admitted_after_previous_drain': True, 'final_effects': 2, 'final_holds': 0,
    },
    'workflow_binding': {
        'different_workflow_same_obligations': 'rejected',
        'altered_journal_controls_rejected': 4,
        'old_exact_retry_recovered': True, 'final_effects': 3, 'final_holds': 0,
    },
    'acquisition_cancellation': {
        'birth_durable_before_prepare': True, 'holds_at_cut': 1,
        'same_birth_on_reopen': True, 'recovered_owner_a_sequence': 2,
        'final_effects': 2, 'final_holds': 0,
    },
    'request_cancellation': {
        'effects_at_cut': 1, 'pending_holds_preserved': 2,
        'active_tasks_after_cancellation': 0, 'exact_retry_recovered': True,
        'final_effects': 2, 'final_holds': 0,
    },
    'retirement_cancellation': {
        'holds_at_cut': 1, 'same_birth_on_reopen': True,
        'final_effects': 0, 'final_holds': 0,
    },
}


def db_rows(path):
    """Read the complete request ledger without importing session validation."""
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
        require(db.execute('PRAGMA quick_check').fetchall() == [('ok',)],
                'session database integrity')
        shape = [(r[1], str(r[2]).upper(), r[3], r[5])
                 for r in db.execute('PRAGMA table_info(requests)')]
        require(shape == [('request_id', 'TEXT', 0, 1), ('input', 'TEXT', 1, 0),
                          ('status', 'TEXT', 1, 0), ('output', 'TEXT', 0, 0)],
                'session request ledger schema')
        return db.execute('SELECT request_id,input,status,output FROM requests ORDER BY request_id').fetchall()


def requirements(session):
    steps = {s['id']: s for s in session['workflow']}
    result = {o: {'emit:' + codec} for o, codec in session['codecs'].items()}
    for step in session['workflow']:
        for parent in step['parents']:
            result[step['owner']].add('accept:' + session['codecs'][steps[parent]['owner']])
    return {owner: sorted(terms) for owner, terms in result.items()}


def binding(session, registry):
    """Derive immutable admission identity and local obligations from a journal."""
    require(set(session) == {'schema', 'manifest', 'birth_token', 'registry', 'window',
                            'workflow', 'family', 'codecs', 'stage', 'certificates',
                            'admission_certificates', 'journal_sequence'},
            'session state field inventory')
    require(session['schema'] == 'factored-schema-session' and
            session['registry'] == registry and session['window'] == 8 and
            session['family'] == 'enum-alias' and
            session['codecs'] == {'a': 'old-name', 'b': 'old-name'},
            'session registered application binding')
    require(session['stage'] in {'acquiring', 'open', 'closing', 'retired'} and
            type(session['journal_sequence']) is int and session['journal_sequence'] >= 0,
            'session lifecycle fields')
    seen, covered = set(), set()
    for step in session['workflow']:
        require(set(step) == {'id', 'owner', 'parents'} and
                re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,31}', step['id']) is not None and
                step['id'] not in seen and step['owner'] in registry['owners'] and
                len(step['parents']) == len(set(step['parents'])) and
                set(step['parents']) <= seen, 'session ordered workflow')
        seen.add(step['id'])
        covered.add(step['owner'])
    require(covered == set(registry['owners']), 'workflow physical-owner coverage')
    manifest = session_manifest(session)
    required = requirements(session)
    admitted = session['admission_certificates']
    require(set(admitted) in (set(), set(registry['owners'])), 'partial historical admission')
    if session['stage'] == 'acquiring':
        require(not admitted and not session['certificates'], 'acquiring journal has published authority')
    elif session['stage'] == 'retired':
        require(not session['certificates'], 'retired journal retains active authority')
    elif session['certificates']:
        require(session['certificates'] == admitted, 'active/historical admission differs')
    for owner, cert in admitted.items():
        require(set(cert) == {'box', 'manifest', 'mode', 'origin', 'receipts', 'sequences'} and
                cert['manifest'] == manifest, 'session certificate manifest differs from its immutable binding')
        require(cert['origin'] == 2 and cert['mode'] == 'envelope' and
                set(cert['sequences']) == {'0'} and type(cert['sequences']['0']) is int and
                cert['sequences']['0'] > 0 and len(cert['receipts']) == 1 and
                cert['box'] == {'0': [required[owner]]}, 'session admission certificate shape')
        receipt = cert['receipts'][0]
        require(receipt == {'status': 'held', 'node': 0, 'origin': 2,
                            'sequence': cert['sequences']['0'], 'manifest': manifest,
                            'requires': [], 'options': [required[owner]],
                            'observed_generation': 0}, 'session admission receipt fields')
    return manifest


def session_specs(group):
    """The finite control inventory, including sessions that issue no requests."""
    if group == 'fresh_and_repeated_journal':
        return {'active.sqlite': (FLOW, 'm' * 128, VALUE),
                'unrelated.sqlite': (FLOW, 'm' * 128, LATER_VALUE)}
    if group == 'precreated_journal':
        return {'active.sqlite': (FLOW, 'same-label', VALUE),
                'precreated.sqlite': (FLOW, 'same-label', None)}
    if group == 'workflow_binding':
        return {'active.sqlite': (CYCLE, 'same-label', VALUE)}
    label = {'acquisition_cancellation': 'acquisition-cut',
             'request_cancellation': 'request-cut',
             'retirement_cancellation': 'retirement-cut'}[group]
    return {'session.sqlite': (FLOW, label, None if group == 'retirement_cancellation' else VALUE)}


def check_trace(trace, owners, sessions, group):
    """Bind the complete trace, and reconstruct holds/effects in commit order."""
    counters = {o: 0 for o in owners}
    held, committed, first_commits, cuts = {}, set(), {}, []
    receipts, closed = {}, {}
    by_manifest = {session_manifest(s): s for s in sessions.values()}
    for index, event in enumerate(trace):
        require(set(event) == {'owner', 'source', 'request', 'response', 'owner_order',
                               'response_disposition'}, 'operation trace field inventory')
        owner = event['owner']
        require(owner in owners and event['source'] == 2, 'operation physical origin')
        counters[owner] += 1
        ordinal = event['owner_order']
        require(ordinal == counters[owner], 'operation trace omits or reorders an owner audit row')
        require(ordinal in owners[owner]['history'], 'operation lacks committed audit evidence')
        audit = owners[owner]['history'][ordinal]
        request, response = event['request'], event['response']
        require(request == audit['request'] and response == audit['response'],
                'operation trace differs from its committed owner audit row')
        op = request['op']
        require(op in {'read', 'prepare', 'close', 'schema'}, 'unexpected identity-control owner operation')
        if op in {'prepare', 'close', 'schema'}:
            require(request['origin'] == 2, 'non-application origin in identity control')
            key = (owner, request['origin'], request['sequence'])
        if op == 'prepare':
            require(response['status'] == 'held' and request['manifest'] in by_manifest,
                    'unbound session preparation')
            session = by_manifest[request['manifest']]
            require(request['requires'] == [] and request['options'] == [requirements(session)[owner]],
                    'prepare obligations differ from bound workflow')
            receipt = response['receipt']
            if key in receipts:
                require(receipts[key][1] == receipt, 'changed receipt for an existing owner sequence')
            else:
                receipts[key] = (index, receipt)
            held[key] = receipt
        elif op == 'close':
            require(response['status'] == 'closed', 'incomplete owner retirement')
            held.pop(key, None)
            closed.setdefault(key, index)
        elif op == 'schema':
            require(response['status'] == 'applied' and request['manifest'] in by_manifest,
                    'unbound schema application')
            session = by_manifest[request['manifest']]
            for admitted_owner, cert in session['admission_certificates'].items():
                held_key = (admitted_owner, 2, cert['sequences']['0'])
                require(held.get(held_key) == cert['receipts'][0],
                        'schema application outside its all-owner retained admission')
            cert = session['admission_certificates'][owner]
            require(request['sequence'] == cert['sequences']['0'], 'schema application under another admission')
            effect_key = (owner, request['origin'], request['sequence'], request['manifest'], request['request_id'])
            require(type(response['duplicate']) is bool and response['duplicate'] == (effect_key in committed),
                    'duplicate receipt contradicts commit history')
            if effect_key not in committed:
                first_commits[effect_key] = index
            committed.add(effect_key)
        disposition = event['response_disposition']
        require(disposition in {'returned', 'withheld-after-commit', 'cancelled-after-commit'},
                'unexpected recorded response disposition')
        if disposition != 'returned':
            cuts.append({'index': index, 'owner': owner, 'op': op, 'disposition': disposition,
                         'sequence': request['sequence'], 'holds': len(held), 'effects': len(committed)})
    require(all(counters[o] == owners[o]['audit_rows'] for o in owners),
            'operation trace omits committed owner operations')
    require(not held, 'operation replay leaves retained owner authority')
    expected_effects = {(owner, *key) for owner, replay in owners.items() for key in replay['effects']}
    require(committed == expected_effects, 'owner effects lack exactly one first committed operation')
    require(len(cuts) == 1, 'identity control cut inventory')
    cut = cuts[0]
    if group in {'fresh_and_repeated_journal', 'precreated_journal', 'workflow_binding'}:
        expected = ('schema', 'withheld-after-commit', 2, 1)
    elif group == 'request_cancellation':
        expected = ('schema', 'cancelled-after-commit', 2, 1)
    elif group == 'acquisition_cancellation':
        expected = ('prepare', 'cancelled-after-commit', 1, 0)
    else:
        expected = ('close', 'cancelled-after-commit', 1, 0)
    require((cut['op'], cut['disposition'], cut['holds'], cut['effects']) == expected and
            cut['owner'] == 'a' and cut['sequence'] == 1, 'recorded cut differs from reconstructed owner state')
    return {'receipts': receipts, 'closed': closed, 'cuts': cuts, 'first_commits': first_commits}


def check_completed(path, session, owners, trace):
    """Bind every complete ledger row to each physical input and returned receipt."""
    rows = db_rows(path)
    expected_effects = {owner: set() for owner in owners}
    manifest = session_manifest(session)
    definitions = {s['id']: s for s in session['workflow']}
    parent_ids = {p for s in session['workflow'] for p in s['parents']}
    sinks = set(definitions) - parent_ids
    completed = []
    for rid, raw, status, raw_output in rows:
        require(rid == 'retained-request' and status == 'complete' and raw_output is not None,
                'admitted final session contains an incomplete request')
        seed, output = json.loads(raw), json.loads(raw_output)
        require(raw == canonical(seed) and raw_output == canonical(output), 'request ledger canonical encoding')
        require(set(seed) == {'key', 'value', 'status'} and type(seed['value']) is int and
                seed['status'] == 1, 'completed request seed schema')
        require(set(output) == {'records', 'steps'} and set(output['steps']) == set(definitions) and
                set(output['records']) == sinks, 'completed workflow output inventory')
        for step_id, step in definitions.items():
            owner = step['owner']
            cert = session['admission_certificates'][owner]
            effect_key = (2, cert['sequences']['0'], manifest, rid + ':' + step_id)
            require(effect_key in owners[owner]['effects'], 'completed step lacks a durable physical effect')
            effect = owners[owner]['effects'][effect_key]
            expected_effects[owner].add(effect_key)
            expected_input = {
                'input_classes': [session['codecs'][definitions[p]['owner']] for p in step['parents']],
                'emit_class': session['codecs'][owner],
                'inputs': [output['steps'][p]['output']['wire'] for p in step['parents']],
                'seed': None if step['parents'] else seed,
            }
            require(effect['input'] == expected_input, 'completed input differs from its durable physical effect')
            reply = output['steps'][step_id]
            require(reply['status'] == 'applied' and reply['output'] == effect['output'] and
                    reply['applied_generation'] == effect['generation'] and
                    reply['applied_rank'] == effect['rank'],
                    'completed output differs from its durable physical effect')
            require(effect['output']['record'] == seed, 'completed workflow changes semantic content')
            matches = [event for event in trace if event['owner'] == owner and
                       event['request'].get('op') == 'schema' and
                       (event['request']['origin'], event['request']['sequence'],
                        event['request']['manifest'], event['request']['request_id']) == effect_key and
                       event['response'] == reply and event['response_disposition'] == 'returned']
            require(len(matches) == 1, 'complete result has no unique returned physical receipt')
        require(all(output['records'][sink] == output['steps'][sink]['output']['record'] for sink in sinks),
                'completed sink output differs from its physical effect')
        completed.append({'request_id': rid, 'input': seed, 'output': output})
    return completed, expected_effects


def check_altered_journals(directory, active, registry):
    pending = deepcopy(active)
    pending.update(stage='closing', certificates=deepcopy(active['admission_certificates']), journal_sequence=2)
    changes = [('workflow', REVERSED_CYCLE), ('manifest', 'different-readable-label'),
               ('birth_token', '0' * 32), ('birth_token', 'invalid-token')]
    for index, (field, value) in enumerate(changes):
        path = directory / ('changed-' + str(index) + '.sqlite')
        altered = read_state(path)
        expected = deepcopy(pending)
        expected[field] = deepcopy(value)
        require(altered == expected, 'saved altered journal changes fields outside its control')
        require(db_rows(path) == [('retained-request', canonical(VALUE), 'pending', None)],
                'altered journal lost retained pending input')
        try:
            binding(altered, registry)
        except ValueError:
            pass
        else:
            raise ValueError('saved altered journal passes independent immutable-binding validation')
    foreign = read_state(directory / 'different-workflow.sqlite')
    foreign_manifest = binding(foreign, registry)
    require(foreign['workflow'] == REVERSED_CYCLE and foreign['manifest'] == active['manifest'] and
            foreign['stage'] == 'acquiring' and foreign['journal_sequence'] == 0 and
            foreign['birth_token'] != active['birth_token'] and
            requirements(foreign) == requirements(active) and
            foreign_manifest != session_manifest(active) and
            not db_rows(directory / 'different-workflow.sqlite'), 'different-workflow journal control')
    return foreign['birth_token']


def check_group(directory, probe):
    group = directory.name
    specs = session_specs(group)
    registry = {'deployment': 'session-identity-control', 'owners': {
        owner: {'family': 'enum-alias', 'initial': deepcopy(probe['profiles'][0]),
                'catalog': deepcopy(probe['profiles'])} for owner in ('a', 'b')}}
    owners = {owner: check_owner(directory / (owner + '.sqlite'), owner, registry, probe)
              for owner in ('a', 'b')}
    trace = load(directory / 'operations.json')
    sessions, births = {}, set()
    for filename, (workflow, label, _) in specs.items():
        session = read_state(directory / filename)
        binding(session, registry)
        require(session['workflow'] == workflow and session['manifest'] == label and
                session['stage'] == 'retired' and session['journal_sequence'] == 3 and
                set(session['admission_certificates']) == {'a', 'b'}, 'final admitted session inventory')
        require(session['birth_token'] not in births, 'independently created journals share a birth token')
        births.add(session['birth_token'])
        sessions[filename] = session
    history = check_trace(trace, owners, sessions, group)
    accounted = {owner: set() for owner in owners}
    complete_count = 0
    completed_rows = {}
    for filename, session in sessions.items():
        for owner, cert in session['admission_certificates'].items():
            key = (owner, 2, cert['sequences']['0'])
            require(key in history['receipts'] and key in history['closed'] and
                    history['receipts'][key][1] == cert['receipts'][0] and
                    history['receipts'][key][0] < history['closed'][key],
                    'historical admission has no matching owner hold and retirement')
        completed, effects = check_completed(directory / filename, session, owners, trace)
        completed_rows[filename] = completed
        seed = specs[filename][2]
        require(len(completed) == (0 if seed is None else 1) and
                (seed is None or completed[0]['input'] == seed), 'control completed-request inventory')
        complete_count += len(completed)
        for owner in owners:
            require(not (accounted[owner] & effects[owner]), 'two sessions share a physical effect identity')
            accounted[owner].update(effects[owner])
    for owner, replay in owners.items():
        require(accounted[owner] == set(replay['effects']), 'unaccounted physical session effect')
        require(not replay['state']['slots'] and replay['state']['generation'] == 0 and
                replay['state']['support'] == registry['owners'][owner]['initial'], 'owner final cleanup')
        index = ('a', 'b').index(owner)
        origin = read_state(directory / 'application-origins' / ('owner-' + format(index, '04d')) / 'origin-2.sqlite')
        maximum = max(k[2] for k in history['receipts'] if k[0] == owner)
        require(origin == {'attempts': {}, 'next': [maximum], 'node_count': 1,
                           'origin': 2, 'policy': 'predicate', 'serial': maximum, 'window': 8},
                'application origin did not drain or lost its sequence allocator')
        require(replay['state']['floor'] == [0, 0, maximum, 0, 0, 0], 'owner retirement frontier differs')
    if group in {'fresh_and_repeated_journal', 'precreated_journal'}:
        later_name = 'unrelated.sqlite' if group == 'fresh_and_repeated_journal' else 'precreated.sqlite'
        active, later = sessions['active.sqlite'], sessions[later_name]
        require(session_manifest(active) != session_manifest(later), 'same label aliases independent sessions')
        for owner in owners:
            old = (owner, 2, active['admission_certificates'][owner]['sequences']['0'])
            new = (owner, 2, later['admission_certificates'][owner]['sequences']['0'])
            require(new[2] > old[2] and history['closed'][old] < history['receipts'][new][0],
                    'later journal acquired a retired session sequence')
        if group == 'fresh_and_repeated_journal':
            require(len(session_manifest(active)) == len(session_manifest(later)) == 201,
                    'maximum readable-label admission length')
    if group in {'fresh_and_repeated_journal', 'precreated_journal', 'workflow_binding', 'request_cancellation'}:
        filename = 'session.sqlite' if group == 'request_cancellation' else 'active.sqlite'
        require(completed_rows[filename][0]['output']['steps']['source']['duplicate'] is True,
                'retained first effect was not recovered by exact retry')
    if group == 'acquisition_cancellation':
        session = sessions['session.sqlite']
        require(session['admission_certificates']['a']['sequences']['0'] == 2 and
                history['closed'][('a', 2, 1)] < history['receipts'][('a', 2, 2)][0],
                'cancelled preparation sequence was reused')
    if group == 'workflow_binding':
        foreign_birth = check_altered_journals(directory, sessions['active.sqlite'], registry)
        require(foreign_birth not in births, 'foreign workflow journal shares an active birth')
        births.add(foreign_birth)
    expected_sqlite = {'a.sqlite', 'b.sqlite', *specs,
                       'application-origins/owner-0000/origin-2.sqlite',
                       'application-origins/owner-0001/origin-2.sqlite'}
    if group == 'workflow_binding':
        expected_sqlite.update({'different-workflow.sqlite', *(f'changed-{i}.sqlite' for i in range(4))})
    require({p.relative_to(directory).as_posix() for p in directory.rglob('*.sqlite')} == expected_sqlite,
            'identity-control SQLite inventory')
    effects = sum(len(o['effects']) for o in owners.values())
    require(effects == RECORDED[group]['final_effects'], 'recorded final effect count differs from journals')
    return {'owner_databases': len(owners), 'origin_databases': len(owners),
            'session_databases': len(expected_sqlite) - 2 * len(owners),
            'admitted_sessions': len(sessions), 'completed_requests': complete_count,
            'durable_effects': effects, 'owner_audit_rows': sum(o['audit_rows'] for o in owners.values()),
            'trace_operations': len(trace),
            'independent_wire_decodes': effects + sum(o['parser_calls'] for o in owners.values()),
            'duplicate_receipts': sum(o['duplicate_receipts'] for o in owners.values()),
            'independently_invalid_altered_journals': 4 if group == 'workflow_binding' else 0,
            'cut_state_reconstructions': len(history['cuts']), 'final_held_obligations': 0,
            'births': births}


def check_mode(directory, probe, optimization):
    summary = load(directory / 'summary.json')
    require(summary['status'] == 'pass' and summary['control_groups'] == 6 and
            summary['controls'] == RECORDED, 'producer-recorded control outcomes')
    require(summary['runtime']['optimized'] == optimization and
            summary['scope'] == 'actual in-process Endpoint, SQLite and ProtoJSON; task/response cuts after committed operations',
            'recorded execution scope')
    require(set(summary['source_sha256']) == set(SOURCE_NAMES), 'captured source manifest inventory')
    captured = directory / 'sources'
    require({p.relative_to(captured).as_posix() for p in captured.rglob('*') if p.is_file()} == set(SOURCE_NAMES),
            'captured source file inventory')
    for name in SOURCE_NAMES:
        content = (captured / name).read_bytes()
        require(content == (ROOT / name).read_bytes(), 'captured source differs from current artifact: ' + name)
        require(hashlib.sha256(content).hexdigest() == summary['source_sha256'][name],
                'captured source content differs from producer manifest: ' + name)
    require({p.name for p in directory.iterdir() if p.is_dir()} == {*RECORDED, 'sources'},
            'identity control group inventory')
    groups, births = {}, set()
    for group in sorted(RECORDED):
        result = check_group(directory / group, probe)
        require(not (births & result['births']), 'independent control journals share a birth token')
        births.update(result.pop('births'))
        groups[group] = result
    totals = {field: sum(group[field] for group in groups.values()) for field in next(iter(groups.values()))}
    totals.update(control_groups=len(groups), captured_sources=len(SOURCE_NAMES), independent_births=len(births))
    return {'reconstructed': totals, 'groups': groups,
            'producer_recorded': {'foreign_journal_rejections': 4, 'altered_journal_rejections': 4,
                                  'post_commit_task_cancellations': 3, 'withheld_effect_replies': 3}}


def corruption_controls(directory, probe):
    """Reject independently modified evidence after the unchanged corpus passes."""
    results = []
    for mode in ('normal', 'optimized'):
        for name in ('session-birth', 'completed-input', 'completed-output', 'missing-committed-operation'):
            with tempfile.TemporaryDirectory(prefix='identity-evidence-') as temporary:
                source = directory / mode / 'acquisition_cancellation'
                target = Path(temporary) / source.name
                shutil.copytree(source, target)
                journal = target / 'session.sqlite'
                if name == 'session-birth':
                    state = read_state(journal)
                    state['birth_token'] = ('1' if state['birth_token'][0] != '1' else '2') + state['birth_token'][1:]
                    with sqlite3.connect(journal) as db:
                        db.execute('UPDATE state SET payload=? WHERE id=1', (canonical(state),))
                    expected = 'session certificate manifest differs from its immutable binding'
                elif name in {'completed-input', 'completed-output'}:
                    with sqlite3.connect(journal) as db:
                        raw, raw_output = db.execute('SELECT input,output FROM requests').fetchone()
                        if name == 'completed-input':
                            value = json.loads(raw)
                            value['value'] += 1
                            db.execute('UPDATE requests SET input=?', (canonical(value),))
                            expected = 'completed input differs from its durable physical effect'
                        else:
                            output = json.loads(raw_output)
                            output['steps']['source']['output']['record']['value'] += 1
                            db.execute('UPDATE requests SET output=?', (canonical(output),))
                            expected = 'completed output differs from its durable physical effect'
                else:
                    path = target / 'operations.json'
                    events = load(path)
                    index = next(i for i, e in enumerate(events) if e['request']['op'] == 'schema')
                    del events[index]
                    path.write_text(json.dumps(events) + '\n')
                    expected = 'operation trace omits or reorders an owner audit row'
                try:
                    check_group(target, probe)
                except ValueError as error:
                    require(str(error) == expected, 'evidence corruption failed for an unrelated reason: ' + str(error))
                else:
                    raise ValueError('evidence corruption escaped: ' + name)
                results.append({'mode': mode, 'name': name, 'rejected': True, 'reason': expected})
    return results


def check(directory, include_corruptions=False):
    directory = Path(directory).resolve()
    probes = load(ROOT / 'results/schema-census/probes.json')
    matches = [p for p in probes if p['family'] == 'enum-alias']
    require(len(matches) == 1, 'saved enum-alias descriptor probe inventory')
    probe = matches[0]
    require({p.name for p in directory.iterdir() if p.is_dir()} == {'normal', 'optimized'},
            'normal/optimized identity corpus inventory')
    modes = {mode: check_mode(directory / mode, probe, optimization)
             for mode, optimization in (('normal', 0), ('optimized', 1))}
    require(modes['normal'] == modes['optimized'], 'normal/optimized identity-control semantics differ')
    total = {key: sum(mode['reconstructed'][key] for mode in modes.values())
             for key in modes['normal']['reconstructed']}
    result = {'status': 'pass', 'scope': 'independent replay of saved journals, owner audits, effects and operation bindings',
              'recorded_outcome_scope': 'producer-recorded constructor rejection and task/response-cut outcomes; faults are not rerun',
              'modes': modes, 'totals': total}
    if include_corruptions:
        result['evidence_corruption_controls'] = corruption_controls(directory, probe)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, default=ROOT / 'results/session-identity')
    parser.add_argument('--corruption-controls', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = check(args.results, args.corruption_controls)
    rendered = json.dumps(result, sort_keys=True, indent=2) + '\n'
    if args.output:
        args.output.write_text(rendered)
    print(rendered, end='')


if __name__ == '__main__':
    main()
