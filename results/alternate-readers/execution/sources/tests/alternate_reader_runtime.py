"""Execute both compatible-reader choices on separate physical deployments.

The full deployment keeps three original owner identities and full endpoint
catalogs. A session fixes a two-owner transport view for its entire lifetime;
pending requests never change reader. The controls retain actual owner SQLite
audits, process restart events, session journals, and the final global rollout.
"""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import platform
import sys

from google.protobuf import __version__ as protobuf_version

from src.factored_planner import FactoredChainPlanner
from src.factored_runtime import FactoredCoordinator, FactoredExecutionError
from src.factored_session import FactoredSession, SchemaRequestPending
from src.schema_contracts import actual_probes
from tests.factored_network import PhysicalNetwork


ROOT = Path(__file__).resolve().parents[1]
TEST_SOURCES = ('tests/factored_network.py', 'tests/factored_tcp_relay.py',
                'tests/check_factored_execution.py', 'tests/factored_planning_oracle.py',
                'tests/alternate_reader_runtime.py', 'tests/alternate_reader_runtime_check.py')


def require(value, reason):
    if not value:
        raise ValueError(reason)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + '\n')


class FixedReaderView:
    """A stable subset of the original registry; physical RPC identities persist."""
    def __init__(self, network, selected):
        self.network = network
        self.directory = network.directory / 'session-transport'
        self.directory.mkdir(parents=True, exist_ok=True)
        self.window, self.policy = network.window, network.policy
        self.registry = {'deployment': network.registry['deployment'],
                         'owners': {owner: deepcopy(network.registry['owners'][owner])
                                    for owner in ('a', selected)}}

    async def rpc(self, owner, request, source=0, drop=False):
        require(owner in self.registry['owners'], 'owner outside fixed reader view')
        return await self.network.rpc(owner, request, source=source, drop=drop)


async def checkpoint(network, name):
    states = {}
    for owner in sorted(network.registry['owners']):
        response = await network.rpc(owner, {'op': 'inspect'})
        require(response is not None and response['status'] == 'state', 'owner inspection failed')
        states[owner] = response['state']
    network.record('choice-checkpoint', name=name, states=states)
    return states


def holds(states):
    return {owner: [key for key, hold in state['slots'].items() if hold['status'] == 'held']
            for owner, state in states.items()}


async def conditional_install(network, owner, state, support):
    request = {'op': 'install_if_current', 'expected_generation': state['generation'],
               'expected_support': state['support'], 'support': support}
    response = await network.rpc(owner, request)
    require(response is not None, 'conditional installation response missing')
    return {'owner': owner, 'request': request, 'response': response}


async def deployment(directory, selected, probe):
    unused = 'c' if selected == 'b' else 'b'
    profiles = probe['profiles']
    ranks = {'a': 2, selected: 2, unused: 0}
    registry = {'deployment': 'alternate-reader-' + selected, 'owners': {
        owner: {'family': 'field-addition', 'initial': profiles[ranks[owner]], 'catalog': profiles}
        for owner in ('a', 'b', 'c')}}
    workflow = [{'id': 'source', 'owner': 'a', 'parents': []},
                {'id': 'selected', 'owner': selected, 'parents': ['source']}]
    value = {'key': 'selected-' + selected + '-κλειδί', 'value': 7, 'tag': 'migrated-δ'}
    factors = [{'id': 'either-reader', 'branches': []}]
    for reader in ('b', 'c'):
        for cls in probe['classes']:
            branch = {'a': ['emit:' + cls], 'b': [], 'c': []}
            branch[reader] = ['accept:' + cls]
            factors[0]['branches'].append(branch)
    catalog = {owner: profiles for owner in ('a', 'b', 'c')}
    transitions = {owner: [{'source': a, 'target': b} for a, b in zip(profiles, profiles[1:])]
                   for owner in catalog}
    planner = FactoredChainPlanner(factors, catalog, transitions)
    case = {'selected': selected, 'unused': unused, 'registry': registry, 'workflow': workflow,
            'input': value, 'factors': factors, 'catalog': catalog, 'transitions': transitions,
            'recognition': planner.recognition(),
            'request_id': 'retained-choice', 'manifest': 'fixed-compatible-reader',
            'scope': 'Two owner choices in separate three-owner deployments; no route changes '
                     'after a request is pending. The first unused-reader update is a direct '
                     'guard control; the final update is a new global rollout.'}
    save(directory / 'case.json', case)
    save(directory / 'schema-probe.json', probe)
    network = PhysicalNetwork(directory, registry)
    session, recovered, coordinator = None, None, None
    result = {'selected': selected, 'unused': unused}
    try:
        network.start()
        initial = await checkpoint(network, 'initial')
        candidates = [owner for owner in ('b', 'c') if 'accept:extended' in initial[owner]['support']]
        require(candidates == [selected], 'live observations did not select exactly the prepared reader')
        result['eligible_readers'] = candidates
        view = FixedReaderView(network, candidates[0])
        path = directory / 'session.sqlite'
        session = await FactoredSession.begin(view, path, workflow, case['manifest'])
        require(session.state['stage'] == 'open', 'compatible choice was not admitted')
        admission = session.state
        result['admitted_session'] = admission
        source_receipts = []

        async def stop_after_source(step, response):
            if step['id'] == 'source':
                source_receipts.append(response)
                raise RuntimeError('caller stopped after confirmed source effect')

        try:
            await session.request(case['request_id'], value, after_step=stop_after_source)
        except SchemaRequestPending:
            result['request_paused_after_source'] = True
        else:
            raise ValueError('request did not remain pending at the selected observation point')
        require(len(source_receipts) == 1 and source_receipts[0]['duplicate'] is False,
                'source effect was not executed exactly once before the pause')
        result['initial_source_receipt'] = source_receipts[0]
        require(not await session.close(), 'pending request retired its codec guards')
        paused = await checkpoint(network, 'pending')
        require(set(owner for owner, keys in holds(paused).items() if keys) == {'a', selected},
                'pending request did not retain exactly its chosen owners')
        result['blocked_selected_regression'] = await conditional_install(
            network, selected, paused[selected], profiles[0])
        require(result['blocked_selected_regression']['response']['status'] == 'blocked',
                'selected old parser replaced a retained compatible reader')
        result['unused_reader_preparation'] = await conditional_install(
            network, unused, paused[unused], profiles[1])
        require(result['unused_reader_preparation']['response']['status'] == 'installed',
                'unselected reader could not prepare while the request was pending')
        controlled = await checkpoint(network, 'after-controls')
        session_before = session.state
        session.disconnect()
        session = None
        wrong = None
        try:
            wrong = FactoredSession(FixedReaderView(network, unused), path)
        except FactoredExecutionError as error:
            result['pending_reroute'] = {'rejected': True, 'exception': type(error).__name__,
                                         'selected': selected, 'attempted': unused}
            network.record('pending-route-change-rejected', **result['pending_reroute'])
        else:
            raise ValueError('a pending request journal was reopened with another reader')
        finally:
            if wrong is not None:
                wrong.disconnect()
        await network.restart_owner(selected, kill=True)
        restarted = await checkpoint(network, 'after-restart')
        require(restarted == controlled, 'owner restart lost state or retained guards')
        recovered = FactoredSession(view, path)
        require(recovered.state == session_before, 'reopen changed the durable session binding')
        output = await recovered.request(case['request_id'], value)
        require(output['records'] == {'selected': value}, 'selected reader changed application values')
        require(output['steps']['source']['duplicate'] is True and
                output['steps']['selected']['duplicate'] is False, 'retry effect identity differs')
        require(await recovered.request(case['request_id'], value) == output, 'cached request output changed')
        result['output'] = output
        result['same_session_after_reopen'] = True
        result['cached_retry_unchanged'] = True
        require(await recovered.close(), 'completed request did not retire its session')
        result['retired_session'] = recovered.state
        recovered.disconnect()
        recovered = None
        drained = await checkpoint(network, 'after-drain')
        require(not any(holds(drained).values()), 'retired application left a physical guard')
        plan = planner.plan({owner: state['support'] for owner, state in drained.items()},
                            {owner: profiles[2] for owner in ('a', 'b', 'c')})
        require(plan['status'] == 'planned' and plan['cost']['phases'] == 1 and
                plan['cost']['installations'] == 1, 'unexpected follow-on target plan')
        save(directory / 'plan.json', plan)
        coordinator = FactoredCoordinator(network, directory / 'rollout.sqlite',
                                         plan=plan, manifest='alternate-reader-follow-on')
        result['rollout'] = await coordinator.run()
        require(result['rollout']['status'] == 'complete', 'follow-on global rollout did not complete')
        coordinator.disconnect()
        coordinator = None
        final = await checkpoint(network, 'final')
        require(all(state['support'] == profiles[2] and not state['slots'] for state in final.values()),
                'final target or guard cleanup differs')
        result['checkpoints'] = {'initial': initial, 'pending': paused, 'after-controls': controlled,
                                 'after-restart': restarted, 'after-drain': drained, 'final': final}
        result['status'] = 'PASS'
        save(directory / 'result.json', result)
    finally:
        for item in (session, recovered, coordinator):
            if item is not None:
                item.disconnect()
        network.close()
    return {'selected': selected, 'physical_owners': 3, 'logical_requests': 1,
            'durable_effects': 2, 'owner_restarts': 1, 'blocked_selected_regressions': 1,
            'unused_reader_preparations': 1, 'pending_route_changes_rejected': 1,
            'follow_on_phases': 1, 'follow_on_installations': 1,
            'pending_requests_at_end': 0, 'held_guards_at_end': 0}


def run(output):
    require(not output.exists(), 'Use a fresh execution output directory')
    output.mkdir(parents=True)
    names = sorted([str(path.relative_to(ROOT)) for path in (ROOT / 'src').glob('*.py')] + list(TEST_SOURCES))
    sources = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names}
    probe = next(row for row in actual_probes() if row['family'] == 'field-addition')
    results = [asyncio.run(deployment(output / ('selected-' + reader), reader, probe)) for reader in ('b', 'c')]
    require(sources == {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names},
            'a bound source changed during physical collection')
    for name in names:
        target = output / 'sources' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    save(output / 'metadata.json', {'python': sys.version, 'platform': platform.platform(),
                                   'protobuf': protobuf_version, 'sources': sources,
                                   'sources_unchanged': True, 'timing_comparison': False})
    summary = {'status': 'PASS', 'deployments': results,
               'physical_owners_per_deployment': 3, 'logical_requests': 2, 'durable_effects': 4,
               'owner_restarts': 2, 'blocked_selected_regressions': 2,
               'unused_reader_preparations': 2, 'pending_route_changes_rejected': 2,
               'follow_on_phases': 2, 'follow_on_installations': 2,
               'pending_requests_at_end': 0, 'held_guards_at_end': 0}
    save(output / 'summary.json', summary)
    print(json.dumps(summary, sort_keys=True, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    run(parser.parse_args().out.resolve())
