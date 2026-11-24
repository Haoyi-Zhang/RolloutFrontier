"""Independent replay of the two physical alternative-reader deployments.

No planner, owner, session, transport, or producer implementation is imported.
The existing independent owner-audit and saved-descriptor checker reconstructs
all three original owners; this module checks choice selection, stable session
identity, pending-work guards, real owner restarts, and the follow-on plan.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
from itertools import product
import json
from pathlib import Path
import sqlite3

from google.protobuf import json_format
from tests.check_factored_execution import (WireOracle, canonical, check_owner, check_plan,
                                            load, read_state, records, require, session_manifest)
from tests.factored_planning_oracle import Oracle


ROOT = Path(__file__).resolve().parents[1]
TEST_SOURCES = {'tests/factored_network.py', 'tests/factored_tcp_relay.py',
                'tests/check_factored_execution.py', 'tests/factored_planning_oracle.py',
                'tests/alternate_reader_runtime.py', 'tests/alternate_reader_runtime_check.py'}


def check_probe(probe):
    require(probe['family'] == 'field-addition' and probe['programs'] == ['legacy', 'accepting', 'emitting']
            and probe['classes'] == ['base', 'extended'], 'physical codec inventory differs')
    emits = ['base', 'base', 'extended']
    accepts = [['base'], ['base', 'extended'], ['base', 'extended']]
    profiles = [sorted(['program:field-addition:' + program, 'emit:' + emits[rank],
                        *('accept:' + cls for cls in accepts[rank])])
                for rank, program in enumerate(probe['programs'])]
    require(probe['emitted_classes'] == emits and probe['accepted_classes'] == accepts and
            probe['profiles'] == profiles, 'full physical catalog differs')
    require([d['rank'] for d in probe['descriptors']] == [0, 1, 2], 'descriptor rank inventory')
    wire_oracle = WireOracle(probe)
    observations = {(p['consumer_rank'], p['wire_id']): p for p in probe['parses']}
    require(len(observations) == len(probe['parses']) == 3 * len(probe['wires']), 'parse inventory')
    require(len({w['id'] for w in probe['wires']}) == len(probe['wires']) and
            {w['rank'] for w in probe['wires']} == {0, 1, 2}, 'wire inventory')
    relation = [[1, 1, 1], [1, 1, 1], [0, 1, 1]]
    for wire in probe['wires']:
        rank = wire['rank']
        require(wire['class'] == emits[rank] and wire['program'] == probe['programs'][rank],
                'wire program/class identity')
        require(wire_oracle.decode(rank, wire['wire'], wire['class']) == wire['input'], 'emitted wire semantics')
        for reader in range(3):
            observation = observations[reader, wire['id']]
            require(observation['consumer_program'] == probe['programs'][reader], 'parse program identity')
            try:
                output = wire_oracle.decode(reader, wire['wire'], wire['class'])
            except json_format.ParseError:
                success = False
            else:
                success = output == wire['input']
            require(success == bool(relation[rank][reader]) and observation['accepted'] is success,
                    'retained codec acceptance differs from descriptor execution')
            if success:
                require(observation['output'] == output, 'retained decoded value differs')
            else:
                require(observation['error_type'] == 'ParseError', 'rejected parse lacks evidence')
    require(probe['relation'] == relation, 'physical single-reader relation differs')
    return profiles


def validate_case(case, result, plan, probe, events, owner_states, session, request_rows, rollout):
    selected = case['selected']
    require(selected in ('b', 'c'), 'selected reader inventory')
    unused = 'c' if selected == 'b' else 'b'
    profiles = probe['profiles']
    registry = case['registry']
    require(case['unused'] == unused and result['selected'] == selected and result['unused'] == unused,
            'selected or unused reader identity differs')
    require(registry['deployment'] == 'alternate-reader-' + selected and
            set(registry['owners']) == {'a', 'b', 'c'}, 'complete original three-owner registry differs')
    for owner, entry in registry['owners'].items():
        require(entry == {'family': 'field-addition', 'catalog': profiles,
                          'initial': profiles[0 if owner == unused else 2]},
                'original physical owner catalog or initial state differs')
    workflow = [{'id': 'source', 'owner': 'a', 'parents': []},
                {'id': 'selected', 'owner': selected, 'parents': ['source']}]
    require(case['workflow'] == workflow, 'fixed session workflow differs')
    branches = []
    for reader in ('b', 'c'):
        for cls in ('base', 'extended'):
            branch = {'a': ['emit:' + cls], 'b': [], 'c': []}
            branch[reader] = ['accept:' + cls]
            branches.append(branch)
    factors = [{'id': 'either-reader', 'branches': branches}]
    catalog = {owner: profiles for owner in ('a', 'b', 'c')}
    transitions = {owner: [{'source': profiles[i], 'target': profiles[i + 1]} for i in range(2)]
                   for owner in catalog}
    require(case['factors'] == factors and case['catalog'] == catalog and case['transitions'] == transitions,
            'physical choice model differs')
    oracle = Oracle(factors, catalog, transitions)
    relation = set(product(range(3), repeat=3)) - {(2, 0, 0)}
    require(set(oracle.graph()) == relation and oracle.closed(), 'physical OR relation differs')
    require((2, 2, 0) in relation and (2, 0, 2) in relation and (2, 0, 0) not in relation,
            'physical non-min-closure witness')
    oracle.check_recognition(case['recognition'])
    require(all(plan[key] == case[key] for key in ('factors', 'catalog', 'transitions', 'recognition')),
            'follow-on plan lost its full physical catalog')
    oracle.check_plan(plan, oracle.state(plan['initial']), oracle.state(plan['target']))
    check_plan(plan)
    require(plan['cost'] == {'phases': 1, 'installations': 1, 'handoffs': 0}, 'follow-on exact cost')
    checkpoint_names = ['initial', 'pending', 'after-controls', 'after-restart', 'after-drain', 'final']
    observed = [e for e in events if e['event'] == 'choice-checkpoint']
    require([e['name'] for e in observed] == checkpoint_names and
            set(result['checkpoints']) == set(checkpoint_names), 'checkpoint inventory')
    for event in observed:
        require(event['states'] == result['checkpoints'][event['name']] and
                set(event['states']) == {'a', 'b', 'c'}, 'checkpoint lost an original owner')
        position = events.index(event)
        preceding = events[position - 6:position]
        require(len(preceding) == 6, 'checkpoint missing its owner inspections')
        for index, owner in enumerate(('a', 'b', 'c')):
            issued, reply = preceding[2 * index:2 * index + 2]
            require(issued['event'] == 'rpc-issued' and reply['event'] == 'rpc-result' and
                    issued['owner'] == reply['owner'] == owner and
                    issued['request'] == reply['request'] == {'op': 'inspect'} and
                    reply['response'] == {'status': 'state', 'state': event['states'][owner]},
                    'checkpoint is not backed by three owner replies')
    checkpoints = result['checkpoints']
    initial = checkpoints['initial']
    require(result['eligible_readers'] == [selected] and
            [o for o in ('b', 'c') if 'accept:extended' in initial[o]['support']] == [selected],
            'live codec selection chose an incompatible reader')
    for name in ('pending', 'after-controls', 'after-restart'):
        states = checkpoints[name]
        held = {owner: [h for h in states[owner]['slots'].values() if h['status'] == 'held']
                for owner in states}
        require(set(o for o, values in held.items() if values) == {'a', selected}
                and all(len(held[o]) == 1 and held[o][0]['origin'] == 2 for o in ('a', selected)),
                'pending request did not retain exactly its chosen physical owners')
        for owner in ('a', selected):
            cert = result['admitted_session']['certificates'][owner]
            require(held[owner][0]['sequence'] == cert['sequences']['0'] and
                    held[owner][0]['manifest'] == session_manifest(result['admitted_session']) and
                    held[owner][0]['options'] == cert['box']['0'],
                    'pending physical guard differs from the chosen session certificate')
    require(checkpoints['after-controls'] == checkpoints['after-restart'], 'restart changed guarded owner state')
    require(checkpoints['pending'][unused]['support'] == profiles[0] and
            checkpoints['after-controls'][unused]['support'] == profiles[1], 'unused-reader preparation differs')
    for name in ('after-drain', 'final'):
        require(all(not state['slots'] for state in checkpoints[name].values()), 'drained phase retained guards')
    require(plan['initial'] == {o: s['support'] for o, s in checkpoints['after-drain'].items()} and
            plan['target'] == {o: profiles[2] for o in ('a', 'b', 'c')}, 'follow-on source/target binding')
    require(all(checkpoints['final'][o] == owner_states[o]['state'] and
                owner_states[o]['state']['support'] == profiles[2] for o in owner_states), 'final owner state differs')

    calls = {(e['pid'], e['call']): e for e in events if e['event'] == 'rpc-issued'}
    replies = [e for e in events if e['event'] == 'rpc-result']
    require(len(calls) == len(replies) and len({(e['pid'], e['call']) for e in replies}) == len(replies),
            'RPC issue/result inventory')
    for event in replies:
        issued = calls[event['pid'], event['call']]
        require(issued['owner'] == event['owner'] and issued['request'] == event['request'] and
                issued['time_ns'] < event['time_ns'] and event['response'] is not None,
                'physical RPC result binding')
        actual = owner_states[event['owner']]['history'][event['owner_order']]
        require(actual['request'] == event['request'] and actual['response'] == event['response'],
                'transport result differs from the owner SQLite audit')
    for field, owner, status, rank in (('blocked_selected_regression', selected, 'blocked', 0),
                                      ('unused_reader_preparation', unused, 'installed', 1)):
        record = result[field]
        require(record['owner'] == owner and record['request']['op'] == 'install_if_current' and
                record['request']['support'] == profiles[rank] and record['response']['status'] == status,
                'selected-reader guard control differs')
        matches = [e for e in replies if e['owner'] == owner and e['request'] == record['request'] and
                   e['response'] == record['response']]
        require(len(matches) == 1, 'guard control lacks one actual owner serialization')
    starts = [e for e in events if e['event'] == 'owner-start']
    kills = [e for e in events if e['event'] == 'owner-stop' and e['signal_requested'] == 'KILL']
    require([e['owner'] for e in starts] == ['a', 'b', 'c', selected] and
            len({e['pid'] for e in starts}) == 4, 'actual owner process inventory')
    require(len(kills) == 1 and kills[0]['owner'] == selected and kills[0]['returncode'] == -9 and
            kills[0]['pid'] == next(e['pid'] for e in starts if e['owner'] == selected) and
            kills[0]['time_ns'] < starts[-1]['time_ns'], 'selected owner was not killed and restarted')
    reroutes = [e for e in events if e['event'] == 'pending-route-change-rejected']
    require(len(reroutes) == 1 and result['pending_reroute'] == {
        'rejected': True, 'exception': 'FactoredExecutionError', 'selected': selected, 'attempted': unused},
        'pending request route change was not rejected')
    require(all(reroutes[0][k] == v for k, v in result['pending_reroute'].items()), 'route rejection trace differs')
    admitted = result['admitted_session']
    require(admitted['registry'] == {'deployment': registry['deployment'],
                                     'owners': {o: registry['owners'][o] for o in ('a', selected)}} and
            admitted['workflow'] == workflow and admitted['stage'] == 'open' and
            admitted['codecs'] == {'a': 'extended', selected: 'extended'}, 'stable chosen-view admission binding')
    require(session == result['retired_session'] and session['stage'] == 'retired' and
            session['certificates'] == {}, 'actual session did not retire')
    for key in ('birth_token', 'manifest', 'registry', 'window', 'workflow', 'family', 'codecs', 'admission_certificates'):
        require(session[key] == admitted[key], 'recovery changed the fixed session binding')
    require(session_manifest(session) == session_manifest(admitted), 'session admission identity changed')
    require(result['request_paused_after_source'] is True and result['same_session_after_reopen'] is True
            and result['cached_retry_unchanged'] is True, 'pending/exact-retry outcomes')
    require(result['initial_source_receipt']['duplicate'] is False and
            result['output']['steps']['source']['duplicate'] is True and
            result['output']['steps']['selected']['duplicate'] is False, 'actual effect retry binding')
    require(result['output']['records'] == {'selected': case['input']}, 'request lost semantic values')
    require(request_rows == [(case['request_id'], canonical(case['input']), 'complete', canonical(result['output']))],
            'durable request rows differ from the sole completed request')
    expected_effects = {owner: 0 if owner == unused else 1 for owner in ('a', 'b', 'c')}
    require({o: len(s['effects']) for o, s in owner_states.items()} == expected_effects, 'physical effect count')
    require(owner_states['a']['duplicate_receipts'] == 1 and
            owner_states[selected]['duplicate_receipts'] == owner_states[unused]['duplicate_receipts'] == 0,
            'source retry was not deduplicated exactly once')
    for owner in ('a', selected):
        cert = admitted['certificates'][owner]
        suffix = 'source' if owner == 'a' else 'selected'
        identity = (2, cert['sequences']['0'], session_manifest(session), case['request_id'] + ':' + suffix)
        require(set(owner_states[owner]['effects']) == {identity}, 'effect is outside the retained session')
        effect = owner_states[owner]['effects'][identity]
        require(effect['output']['record'] == case['input'], 'durable effect value differs')
    require(rollout['stage'] == 'complete' and rollout['certificates'] == {} and
            rollout['acknowledged_installs'] + rollout['reconciled_steps'] == 1,
            'follow-on coordinator journal is incomplete')
    digest = hashlib.sha256(canonical(plan).encode()).hexdigest()
    require(rollout['plan_digest'] == digest and result['rollout']['status'] == 'complete' and
            result['rollout']['target_observation']['first'] == result['rollout']['target_observation']['second'],
            'follow-on completion binding differs')
    phase_manifest = rollout['manifest'] + ':plan:' + digest + ':phase:0'
    starts_at, closes_at = [], []
    for owner in ('a', 'b', 'c'):
        admissions = [e for e in replies if e['owner'] == owner and
                      e['response']['status'] == 'held' and
                      e['response']['receipt']['manifest'] == phase_manifest]
        require(len(admissions) == 1, 'follow-on phase lacks one original-owner admission')
        admitted_event = admissions[0]
        receipt = admitted_event['response']['receipt']
        require(receipt['options'] == plan['phases'][0]['box'][owner],
                'follow-on physical guard differs from compiled plan')
        retirement = [e for e in calls.values() if e['owner'] == owner and
                      e['request'] == {'op': 'close', 'origin': receipt['origin'],
                                       'sequence': receipt['sequence']}]
        require(len(retirement) == 1, 'follow-on admission was not retired once')
        starts_at.append(admitted_event['time_ns'])
        closes_at.append(retirement[0]['time_ns'])
    installation = [e for e in replies if e['owner'] == unused and
                    e['request'].get('support') == profiles[2] and e['response']['status'] == 'installed']
    require(len(installation) == 1, 'follow-on target installation inventory')
    installed = installation[0]
    issued = calls[installed['pid'], installed['call']]
    require(max(starts_at) <= issued['time_ns'] < installed['time_ns'] <= min(closes_at),
            'follow-on installation occurred outside the full three-owner guard interval')
    require(result['status'] == 'PASS', 'execution did not finish')
    return {'selected': selected, 'physical_owners': 3, 'logical_requests': 1,
            'durable_effects': 2, 'owner_restarts': 1, 'blocked_selected_regressions': 1,
            'unused_reader_preparations': 1, 'pending_route_changes_rejected': 1,
            'follow_on_phases': 1, 'follow_on_installations': 1,
            'pending_requests_at_end': 0, 'held_guards_at_end': 0}


def collect(directory):
    case, result, plan, probe = [load(directory / name) for name in
                                 ('case.json', 'result.json', 'plan.json', 'schema-probe.json')]
    check_probe(probe)
    require(load(directory / 'registry.json') == case['registry'], 'original registry file differs')
    owners = {owner: check_owner(directory / f'owner-{i:04d}.sqlite', owner, case['registry'], probe)
              for i, owner in enumerate(('a', 'b', 'c'))}
    events = records(directory / 'transport.jsonl')
    session = read_state(directory / 'session.sqlite')
    with sqlite3.connect((directory / 'session.sqlite').resolve().as_uri() + '?mode=ro', uri=True) as db:
        requests = db.execute('SELECT request_id,input,status,output FROM requests ORDER BY request_id').fetchall()
    rollout = read_state(directory / 'rollout.sqlite')
    arguments = [case, result, plan, probe, events, owners, session, requests, rollout]
    return validate_case(*arguments), arguments


def controls(arguments):
    reports = []

    def rejection(name, index, change):
        bad = list(arguments)
        bad[index] = deepcopy(bad[index])
        change(bad[index])
        try:
            validate_case(*bad)
        except (ValueError, KeyError, IndexError, TypeError):
            reports.append({'name': name, 'rejected': True})
        else:
            raise ValueError('corruption control accepted: ' + name)

    unused = arguments[0]['unused']
    rejection('omitted original unused owner', 0, lambda c: c['registry']['owners'].pop(unused))
    rejection('changed selected reader', 0, lambda c: c.__setitem__('selected', unused))
    rejection('selected regression falsely installed', 1,
              lambda r: r['blocked_selected_regression']['response'].__setitem__('status', 'installed'))
    rejection('pending guard omitted', 1,
              lambda r: r['checkpoints']['pending']['a'].__setitem__('slots', {}))
    rejection('recovered output value changed', 1,
              lambda r: r['output']['records']['selected'].__setitem__('value', 8))
    rejection('source effect repeated on retry', 1,
              lambda r: r['output']['steps']['source'].__setitem__('duplicate', False))
    rejection('pending reroute accepted', 1, lambda r: r['pending_reroute'].__setitem__('rejected', False))
    rejection('owner kill evidence omitted', 4,
              lambda e: e.__setitem__(slice(None), [v for v in e if v['event'] != 'owner-stop']))
    rejection('request left pending', 7,
              lambda rows: rows.__setitem__(0, (*rows[0][:2], 'pending', None)))
    return reports


def check(directory, corruption_controls=False):
    metadata = load(directory / 'metadata.json')
    names = {str(p.relative_to(ROOT)) for p in (ROOT / 'src').glob('*.py')} | TEST_SOURCES
    require(set(metadata['sources']) == names and metadata['sources_unchanged'] is True and
            metadata['timing_comparison'] is False, 'runtime source inventory or measurement scope differs')
    for name, digest in metadata['sources'].items():
        for path in (ROOT / name, directory / 'sources' / name):
            require(hashlib.sha256(path.read_bytes()).hexdigest() == digest, 'runtime source binding differs: ' + name)
    deployments, control_reports = [], []
    for reader in ('b', 'c'):
        report, arguments = collect(directory / ('selected-' + reader))
        require(report['selected'] == reader, 'deployment directory/reader binding')
        deployments.append(report)
        if corruption_controls and reader == 'b':
            control_reports = controls(arguments)
    summary = {'status': 'PASS', 'deployments': deployments,
               'physical_owners_per_deployment': 3, 'logical_requests': 2, 'durable_effects': 4,
               'owner_restarts': 2, 'blocked_selected_regressions': 2,
               'unused_reader_preparations': 2, 'pending_route_changes_rejected': 2,
               'follow_on_phases': 2, 'follow_on_installations': 2,
               'pending_requests_at_end': 0, 'held_guards_at_end': 0}
    require(summary == load(directory / 'summary.json'), 'saved runtime summary differs from replay')
    if corruption_controls:
        summary['corruption_controls'] = control_reports
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', required=True, type=Path)
    parser.add_argument('--corruption-controls', action='store_true')
    args = parser.parse_args()
    print(json.dumps(check(args.results, args.corruption_controls), sort_keys=True, indent=2))
