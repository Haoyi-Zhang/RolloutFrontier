"""Coupled Kubernetes policy boundaries with finite oracles and durable replay.

Run from artifact/: python -B -m tests.kubernetes_policy_boundaries --out /new/path
This executes declared support transitions, not Kubernetes binaries. All 45
vectors, every compatible seed, refusals and three single-rule witnesses remain
in the output. The existing policy cohort and implementation are unchanged.
"""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
import hashlib
import itertools
import json
from pathlib import Path
import platform
import shutil
import sqlite3
import sys
import tempfile
import time

from src.batch import choose_batch_box
from src.checker import frontier_certificate
from src.envelope import compatible, frontier_synthesize
from src.network import Client, Network

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'data/kubernetes-policy-boundaries.json'
DESIGN = ROOT / 'docs/POLICY-BOUNDARY-DESIGN.md'
RULES = ('ha_gap', 'not_newer', 'max_lag')
RESOURCE_REFUSALS = {'exact frontier local-library bound',
                     'exact frontier search-state bound', 'exact frontier result bound'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def source_identities():
    paths = [FIXTURE, DESIGN, Path(__file__), ROOT / 'tests/check_policy_boundaries.py',
             *sorted((ROOT / 'src').glob('*.py'))]
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths}


def rule_values(versions):
    a, b, c = versions
    require(all(type(v) is int for v in versions) and c >= 25, 'Outside registered minor domain')
    return {'ha_gap': abs(a - b) <= 1,
            'not_newer': c <= a and c <= b,
            'max_lag': a - c <= 3 and b - c <= 3}


def policy(versions, omit=None):
    return all(value for name, value in rule_values(versions).items() if name != omit)


def encoding(facts):
    servers = facts['server_minor_catalog']
    clients = facts['client_minor_catalog']
    profiles = {str(i): {v: list(facts['server_profiles'][str(v)]) for v in servers}
                for i in (0, 1)}
    profiles['2'] = {v: [f'client.{v}'] for v in clients}
    branches = [{'0': [f'allows.{c}', f'ha.{window}'],
                 '1': [f'allows.{c}', f'ha.{window}'], '2': [f'client.{c}']}
                for c in clients for window in facts['alternative_windows'][str(c)]]
    candidates = {node: list(values.values()) for node, values in profiles.items()}
    require(len(branches) == 7, 'Registered seven-alternative encoding differs')
    return profiles, branches, candidates


def subsets(domain, anchor):
    return [tuple(v for bit, v in enumerate(domain) if mask & (1 << bit))
            for mask in range(1, 1 << len(domain))
            if mask & (1 << domain.index(anchor))]


def direct_frontier(domains, initial):
    safe = [box for box in itertools.product(*(subsets(d, v) for d, v in zip(domains, initial)))
            if all(policy(vector) for vector in itertools.product(*box))]
    frontier = sorted(box for box in safe if not any(
        box != other and all(set(a) <= set(b) for a, b in zip(box, other)) for other in safe))
    return safe, frontier


def accepted_versions(box, profiles):
    return tuple(tuple(version for version, atoms in profiles[str(i)].items()
                       if any(set(term) <= set(atoms) for term in box[str(i)]))
                 for i in range(3))


def exhaustive(facts, profiles, branches, candidates):
    domains = [list(profiles[str(i)]) for i in range(3)]
    rows = []
    for versions in itertools.product(*domains):
        current = {str(i): profiles[str(i)][value] for i, value in enumerate(versions)}
        expected = policy(versions)
        actual = compatible(branches, {node: set(atoms) for node, atoms in current.items()})
        require(actual == expected, 'Positive encoding differs from numerical policy')
        row = {'versions': list(versions), 'rules': rule_values(versions),
               'compatible': expected, 'encoded_compatible': actual}
        if expected:
            safe, frontier = direct_frontier(domains, versions)
            row.update(safe_products=len(safe), literal_frontier=[list(map(list, box)) for box in frontier])
            try:
                plan = frontier_synthesize(branches, current, candidates)
            except ValueError as exc:
                if str(exc) not in RESOURCE_REFUSALS:
                    raise
                row.update(status='refused', reason=str(exc))
            else:
                require(frontier_certificate(branches, current, candidates, plan), 'Certificate rejected')
                produced = sorted(accepted_versions(member['box'], profiles) for member in plan['frontier'])
                require(produced == frontier, 'Positive frontier differs from version-subset frontier')
                require(plan['product_mass'] == max(len(a) * len(b) * len(c) for a, b, c in safe),
                        'Selected mass differs from all-product optimum')
                row.update(status='completed', plan=plan)
        rows.append(row)
    return rows


def domain_controls(facts, rows):
    vectors = [row['versions'] for row in rows]
    deletions = []
    for witness in facts['boundary_cases']:
        omitted = witness['omitted_rule']
        false_positives = [vector for vector in vectors if not policy(vector) and policy(vector, omit=omitted)]
        flags = rule_values(witness['incompatible'])
        require(flags[omitted] is False and sum(not flag for flag in flags.values()) == 1,
                'Witness does not isolate one policy rule')
        require(witness['incompatible'] in false_positives and policy(witness['compatible']),
                'Missing rule-deletion witness or positive boundary')
        require([i for i, (a, b) in enumerate(zip(witness['compatible'], witness['incompatible'])) if a != b]
                == [witness['changed_owner']], 'Boundary probe changes multiple owners')
        deletions.append({'omitted_rule': omitted, 'newly_admitted': false_positives,
                          'newly_admitted_count': len(false_positives),
                          'witness': deepcopy(witness), 'witness_rules': flags})
    safe_vectors = [vector for vector in vectors if policy(vector)]
    marginal_domains = [sorted({vector[i] for vector in safe_vectors}) for i in range(3)]
    false_positives = [list(vector) for vector in itertools.product(*marginal_domains) if not policy(vector)]
    return {'rule_deletions': deletions,
            'marginals': {'domains': marginal_domains, 'newly_admitted': false_positives,
                          'newly_admitted_count': len(false_positives)}}


async def boundary_lifecycle(witness, row, profiles, branches, directory, output):
    rule = witness['omitted_rule']
    if row['status'] == 'refused':
        return {'rule': rule, 'status': 'not-run', 'reason': row['reason']}
    plan = row['plan']
    initial = witness['compatible']
    state = list(initial)
    current = {str(i): profiles[str(i)][value] for i, value in enumerate(state)}
    net = Network(directory, [current[str(i)] for i in range(3)])
    await net.start()
    client = Client(net)
    events = []
    result = None
    try:
        admission = await client.acquire_box('policy-boundary-' + rule, branches, plan['box'])
        require(admission['status'] == 'admitted', 'Boundary seed admission failed')
        certificate = admission['certificate']
        owner = witness['changed_owner']
        proposals = [(owner, witness['incompatible'][owner], 'rule-witness')]
        proposals += [(i, value, 'catalog') for i in range(3) for value in profiles[str(i)]]
        for owner, value, kind in proposals:
            target = profiles[str(owner)][value]
            accepted = any(set(term) <= set(target) for term in plan['box'][str(owner)])
            expected = 'unchanged' if value == state[owner] else 'installed' if accepted else 'blocked'
            reply = await net.rpc(0, owner, {'op': 'install', 'support': target})
            require(reply is not None and reply['status'] == expected, 'Boundary event differs from literal guard')
            if kind == 'rule-witness':
                require(reply['status'] == 'blocked', 'Rule witness installed under the full guard')
            if reply['status'] == 'installed':
                state[owner] = value
            require(policy(state), 'Guarded boundary execution violates numerical policy')
            events.append({'owner': owner, 'proposed_minor': value, 'kind': kind,
                           'status': reply['status'], 'versions_after': list(state),
                           'rules_after': rule_values(state)})
        await net.crash(1)
        client.disconnect()
        client = Client(net)
        use = await client.use(certificate)
        require(len(use) == 3 and all(reply is not None and reply['status'] == 'used' for reply in use),
                'Boundary reopen lost authorization')
        require(await client.retire(certificate), 'Boundary retirement did not complete')
        late = await net.rpc(0, 1, {'op': 'prepare', 'origin': 0,
                                  'sequence': certificate['sequences']['1'],
                                  'manifest': certificate['manifest'], 'requires': [],
                                  'options': plan['box']['1']})
        require(late is not None and late['status'] == 'closed', 'Boundary late prepare resurrected')
        require(not client.state['attempts'] and all(not endpoint.state['slots'] for endpoint in net.nodes.values()),
                'Completed boundary retirement retained a live attempt or hold')
        result = {'rule': rule, 'status': 'completed', 'initial': list(initial),
                  'box': plan['box'], 'certificate': certificate, 'events': events,
                  'final_versions': list(state), 'owner_and_origin_reopen': 'authorized',
                  'retirement': 'closed', 'delayed_prepare': late['status'],
                  'outcomes': {name: sum(e['status'] == name for e in events)
                               for name in ('installed', 'blocked', 'unchanged')},
                  'owner_states': {str(i): deepcopy(endpoint.state) for i, endpoint in net.nodes.items()},
                  'origin_state': deepcopy(client.state),
                  'logical_rpc_trace': deepcopy(net.trace)}
    finally:
        client.disconnect()
        await net.stop()
    result['databases'] = []
    for name in ('node-0.sqlite', 'node-1.sqlite', 'node-2.sqlite', 'origin-0.sqlite'):
        target = output / 'databases' / rule / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(directory / name, target)
        result['databases'].append({'path': str(target.relative_to(output)),
                                    'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
    return result


def literal_replay(initial, rectangle, proposals):
    state = list(initial)
    counts = {'installed': 0, 'blocked': 0, 'unchanged': 0}
    for proposal in proposals:
        owner, value = proposal['owner'], proposal['minor']
        status = 'unchanged' if state[owner] == value else 'installed' if value in rectangle[owner] else 'blocked'
        if status == 'installed':
            state[owner] = value
        counts[status] += 1
        require(policy(state), 'Literal static replay violates policy')
    return {**counts, 'final': state}


def checkpoint(net, clients, directory, output, stage):
    snapshot = {'owner_states': {str(i): deepcopy(endpoint.state) for i, endpoint in net.nodes.items()},
                'origin_states': {str(origin): deepcopy(client.state) for origin, client in clients.items()},
                'databases': []}
    for name in ('node-0.sqlite', 'node-1.sqlite', 'node-2.sqlite', 'origin-0.sqlite', 'origin-1.sqlite'):
        target = output / 'databases' / 'handoff' / stage / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect((directory / name).as_uri() + '?mode=ro', uri=True) as source:
            with sqlite3.connect(target) as destination:
                source.backup(destination)
        snapshot['databases'].append({'path': str(target.relative_to(output)),
                                       'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
    return snapshot


async def coordinated_handoff(facts, rows, profiles, branches, candidates, directory, output):
    design = facts['handoff']
    initial = design['initial']
    planning_state = design['handoff_planning_state']
    first = next(row for row in rows if row['versions'] == initial)
    second = next(row for row in rows if row['versions'] == planning_state)
    for row in (first, second):
        if row['status'] == 'refused':
            return {'status': 'not-run', 'reason': row['reason'], 'refused_seed': row['versions']}
    old_plan = first['plan']
    domains = [list(profiles[str(i)]) for i in range(3)]
    products, _ = direct_frontier(domains, initial)
    static_best = max(literal_replay(initial, product, design['goal_proposals'])['installed'] for product in products)
    require(static_best == 2, 'Registered full-path static optimum differs')
    current = {str(i): profiles[str(i)][value] for i, value in enumerate(initial)}
    net = Network(directory, [current[str(i)] for i in range(3)])
    await net.start()
    clients = {}
    events = []
    state = list(initial)

    async def install(proposal, stage, source, active_boxes):
        owner, value = proposal['owner'], proposal['minor']
        target = profiles[str(owner)][value]
        allowed = all(any(set(term) <= set(target) for term in box[str(owner)]) for box in active_boxes.values())
        expected = 'unchanged' if state[owner] == value else 'installed' if allowed else 'blocked'
        reply = await net.rpc(source, owner, {'op': 'install', 'support': target})
        require(reply is not None and reply['status'] == expected, 'Handoff installation differs from live-guard intersection')
        if reply['status'] == 'installed':
            state[owner] = value
        require(policy(state), 'Handoff installation violates policy')
        event = {'stage': stage, 'owner': owner, 'proposed_minor': value, 'active_origins': sorted(active_boxes),
                 'status': reply['status'], 'versions_after': list(state), 'rules_after': rule_values(state)}
        events.append(event)
        return reply

    try:
        clients[0] = Client(net, origin=design['old_origin'])
        admission = await clients[0].acquire_box(design['manifest'], branches, old_plan['box'])
        require(admission['status'] == 'admitted', 'First handoff phase not admitted')
        old_certificate = admission['certificate']
        for proposal in design['goal_proposals']:
            await install(proposal, 'first-static-phase', 0, {0: old_plan['box']})
        require(state == planning_state and [event['status'] for event in events] == ['installed', 'installed', 'blocked'],
                'First static phase differs from the registered path')
        current = {str(i): profiles[str(i)][value] for i, value in enumerate(state)}
        batch = [{'node': str(p['owner']), 'support': profiles[str(p['owner'])][p['minor']]}
                 for p in design['remaining_goal_proposals']]
        choice = choose_batch_box(branches, current, candidates, batch)
        require(choice['frontier_plan'] == second['plan'], 'Second phase frontier differs from its registered seed')
        require(choice['forecast']['installed'] == 1 and choice['max_mass_forecast']['installed'] == 0
                and not choice['kept_max_mass'], 'Remaining-target batch did not select its enabling guard')
        clients[1] = Client(net, origin=design['new_origin'])
        next_admission = await clients[1].acquire_box(design['manifest'], branches, choice['box'])
        require(next_admission['status'] == 'admitted', 'Second handoff phase not admitted')
        new_certificate = next_admission['certificate']
        overlap = await install(design['remaining_goal_proposals'][0], 'both-guards-probe', 1,
                                {0: old_plan['box'], 1: choice['box']})
        require(overlap['status'] == 'blocked' and overlap.get('holds') == ['0:1'],
                'The old guard did not block the overlap probe')
        snapshots = {'both-held': checkpoint(net, clients, directory, output, 'both-held')}
        require(await clients[0].retire(old_certificate), 'Old handoff phase did not retire')
        old_use_after_retirement = await clients[0].use(old_certificate)
        require(old_use_after_retirement == [{'status': 'not-authorized'}], 'Retired old token still authorizes')
        snapshots['old-retired'] = checkpoint(net, clients, directory, output, 'old-retired')
        final_reply = await install(design['remaining_goal_proposals'][0], 'second-static-phase', 1, {1: choice['box']})
        require(final_reply['status'] == 'installed' and state == design['target'], 'Coordinated target not reached')
        await net.crash(1)
        for origin in (0, 1):
            clients[origin].disconnect()
            clients[origin] = Client(net, origin=origin)
        old_use_after_reopen = await clients[0].use(old_certificate)
        require(old_use_after_reopen == [{'status': 'not-authorized'}], 'Reopen restored old authorization')
        new_use = await clients[1].use(new_certificate)
        require(len(new_use) == 3 and all(reply is not None and reply['status'] == 'used' for reply in new_use),
                'Reopen lost the new phase authorization')
        require(await clients[1].retire(new_certificate), 'New handoff phase did not retire')
        late = await net.rpc(0, 1, {'op': 'prepare', 'origin': 0, 'sequence': old_certificate['sequences']['1'],
                                  'manifest': design['manifest'], 'requires': [], 'options': old_plan['box']['1']})
        require(late is not None and late['status'] == 'closed', 'Late old prepare resurrected after handoff')
        snapshots['both-closed'] = checkpoint(net, clients, directory, output, 'both-closed')
        totals = {'goal_steps': len(design['goal_proposals']), 'single_static_optimum': static_best,
                  'first_phase_targets_completed': sum(a == b for a, b in zip(planning_state, design['target'])),
                  'final_targets_completed': sum(a == b for a, b in zip(state, design['target'])),
                  'target_reached': state == design['target'], 'installation_requests': len(events),
                  **{name: sum(event['status'] == name for event in events) for name in ('installed', 'blocked', 'unchanged')},
                  'database_snapshots': sum(len(snapshot['databases']) for snapshot in snapshots.values())}
        return {'status': 'completed', 'design': deepcopy(design), 'single_static_optimum': static_best,
                'static_products_considered': len(products), 'first_box': old_plan['box'],
                'old_certificate': old_certificate, 'new_certificate': new_certificate,
                'remaining_batch': batch, 'second_choice': choice, 'events': events, 'snapshots': snapshots,
                'old_use_after_retirement': old_use_after_retirement, 'old_use_after_reopen': old_use_after_reopen,
                'new_use_after_reopen': new_use, 'late_old_prepare': late,
                'logical_rpc_trace': deepcopy(net.trace), 'totals': totals,
                'scope': design['scope']}
    finally:
        for client in clients.values():
            client.disconnect()
        await net.stop()


async def run(out):
    out = out.resolve()
    require(not out.exists() and not out.is_relative_to(ROOT), 'Use a new output directory outside artifact')
    out.mkdir(parents=True)
    facts = json.loads(FIXTURE.read_text(encoding='utf-8'))
    require(facts['server_minor_catalog'] == [35, 36, 37]
            and facts['client_minor_catalog'] == [33, 34, 35, 36, 37], 'Registered domain differs')
    before = source_identities()
    registration = {'design': str(DESIGN.relative_to(ROOT)), 'fixture': str(FIXTURE.relative_to(ROOT)),
                    'source_sha256': before, 'python': sys.version, 'platform': platform.platform(),
                    'sqlite': sqlite3.sqlite_version, 'default_bounds': True,
                    'planned_vectors': 45, 'planned_rule_controls': 3, 'planned_lifecycles': 3,
                    'planned_handoffs': 1, 'handoff_goal_steps': 3}
    write_json(out / 'registration.json', registration)
    for name in before:
        path = out / 'source-preimage' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / name).read_bytes())
    started = time.monotonic()
    try:
        profiles, branches, candidates = encoding(facts)
        rows = exhaustive(facts, profiles, branches, candidates)
        controls = domain_controls(facts, rows)
        lifecycles = []
        with tempfile.TemporaryDirectory(prefix='policy-boundaries-') as scratch:
            for witness in facts['boundary_cases']:
                row = next(r for r in rows if r['versions'] == witness['compatible'])
                lifecycles.append(await boundary_lifecycle(witness, row, profiles, branches,
                    Path(scratch) / witness['omitted_rule'], out))
            handoff = await coordinated_handoff(facts, rows, profiles, branches, candidates,
                                                Path(scratch) / 'handoff', out)
        after = source_identities()
        require(before == after, 'Source changed during policy-boundary execution')
        complete = [row for row in rows if row.get('status') == 'completed']
        refused = [row for row in rows if row.get('status') == 'refused']
        completed_lifecycles = [run for run in lifecycles if run['status'] == 'completed']
        totals = {'vectors': len(rows), 'compatible_vectors': sum(row['compatible'] for row in rows),
                  'completed_seeds': len(complete), 'refused_seeds': len(refused),
                  'frontier_members_across_completed_seeds': sum(row['plan']['frontier_size'] for row in complete),
                  'rule_deletion_false_positives': {r['omitted_rule']: r['newly_admitted_count']
                                                  for r in controls['rule_deletions']},
                  'marginal_false_positives': controls['marginals']['newly_admitted_count'],
                  'completed_lifecycles': len(completed_lifecycles),
                  'lifecycle_proposals': sum(len(run['events']) for run in completed_lifecycles),
                  'blocked_rule_witnesses': sum(run['events'][0]['status'] == 'blocked'
                                                for run in completed_lifecycles),
                  'database_snapshots': sum(len(run['databases']) for run in completed_lifecycles)}
        result = {'schema': 1, 'status': 'PASS', 'source': facts, 'source_sha256': after,
                  'source_bytes_unchanged_during_run': True, 'branches': branches,
                  'profiles': {node: {str(v): atoms for v, atoms in values.items()} for node, values in profiles.items()},
                  'exhaustive': rows, 'controls': controls, 'lifecycles': lifecycles, 'totals': totals,
                  'handoff': handoff,
                  'refusals': [{'versions': row['versions'], 'reason': row['reason']} for row in refused],
                  'elapsed_seconds': time.monotonic() - started,
                  'scope': 'All registered numerical-policy boundaries, declared-support guards and local TCP/SQLite transitions; not Kubernetes binaries, upgrade orchestration or incident prevalence.'}
        write_json(out / 'results.json', result)
        write_json(out / 'execution.json', {'status': 'PASS', 'returncode': 0,
                    'source_bytes_unchanged_during_run': True, 'source_sha256': after,
                    'elapsed_seconds': result['elapsed_seconds']})
        print(json.dumps({'status': 'PASS', **totals, 'handoff': handoff.get('totals', {'status': handoff['status']})}, sort_keys=True))
        return result
    except Exception as exc:
        write_json(out / 'execution.json', {'status': 'FAIL', 'returncode': 1,
                    'error': type(exc).__name__ + ': ' + str(exc),
                    'elapsed_seconds': time.monotonic() - started,
                    'source_bytes_unchanged_during_run': before == source_identities()})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    asyncio.run(run(parser.parse_args().out))
