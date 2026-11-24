"""Independent controls for durable sessions and successive rollout jobs.

These controls call the actual Endpoint, SQLite, and ProtoJSON implementations
in process. A one-shot missing response is a regression injection after an
actual effect commit. Network interruption and process-kill measurements are
provided separately by the factored execution campaign.
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
import tempfile

from google.protobuf import __version__ as protobuf_version

from src.factored_planner import FactoredChainPlanner
from src.factored_runtime import FactoredCoordinator
from src.factored_session import FactoredSession, SchemaRequestPending
from src.schema_contracts import actual_probes
from src.schema_runtime import SchemaEndpoint, identity_for

ROOT = Path(__file__).resolve().parents[1]
SOURCE_NAMES = (
    'src/controller.py', 'src/network.py', 'src/checker.py', 'src/envelope.py',
    'src/factored_planner.py', 'src/factored_runtime.py', 'src/factored_session.py',
    'src/schema_runtime.py', 'src/schema_contracts.py',
    'tests/factored_followon_regression.py',
)
FLOW = [
    {'id': 'source', 'owner': 'a', 'parents': []},
    {'id': 'sink', 'owner': 'b', 'parents': ['source']},
]


def require(condition, message):
    if not condition:
        raise ValueError(message)


class DirectOwners:
    """Transport adapter only; all admission and handler logic is production code."""

    def __init__(self, directory, family='enum-alias', ranks=None):
        self.directory = Path(directory)
        self.window, self.policy = 8, 'predicate'
        ranks = {'a': 0, 'b': 0} if ranks is None else ranks
        self.probe = next(p for p in actual_probes() if p['family'] == family)
        self.registry = {'deployment': 'independent-review', 'owners': {
            owner: {'family': family, 'initial': deepcopy(self.probe['profiles'][rank]),
                    'catalog': deepcopy(self.probe['profiles'])}
            for owner, rank in ranks.items()}}
        self.endpoints = {
            owner: SchemaEndpoint(identity_for(self.registry, owner), self.directory / (owner + '.sqlite'))
            for owner in ranks}
        self.drop_next_effect_response = False

    async def rpc(self, owner, request, source=0, drop=False):
        require(not drop, 'unexpected transport drop argument')
        response = self.endpoints[owner].handle(deepcopy(request))
        if (self.drop_next_effect_response and request.get('op') == 'schema'
                and response.get('status') == 'applied'):
            self.drop_next_effect_response = False
            return None
        return response

    def effects(self):
        return sum(endpoint.db.execute('SELECT count(*) FROM schema_results').fetchone()[0]
                   for endpoint in self.endpoints.values())

    def holds(self):
        return sum(slot['status'] == 'held' for endpoint in self.endpoints.values()
                   for slot in endpoint.state['slots'].values())

    def close(self):
        for endpoint in self.endpoints.values():
            endpoint.disconnect()


async def admission_identity_and_recovery(directory):
    owners = DirectOwners(directory)
    reports, sequences = [], []
    try:
        for serial in (1, 2):
            session = await FactoredSession.begin(
                owners, directory / ('session' + str(serial) + '.sqlite'), FLOW, 'reused-human-manifest')
            try:
                sequence = {owner: cert['sequences']['0']
                            for owner, cert in session.state['certificates'].items()}
                sequences.append(sequence)
                value = {'key': 'same-key', 'value': serial, 'status': 1}
                result = await session.request('reused-request-id', value)
                require(result['records']['sink'] == value, 'fresh session aliased older effects')
                require(owners.effects() == 2 * serial, 'fresh admission did not get distinct effects')
                require(await session.close(), 'completed session did not drain')
                require(owners.holds() == 0, 'retired session left a hold')
                require(await session.request('reused-request-id', value) == result,
                        'retirement changed cached output')
                try:
                    await session.request('reused-request-id', {'key': 'same-key', 'value': 99, 'status': 1})
                except ValueError:
                    pass
                else:
                    raise ValueError('same session ID rebound to different input')
                reports.append({'session': serial, 'admission_sequences': sequence,
                                'effects': owners.effects(), 'drained': True})
            finally:
                session.disconnect()
        require(all(sequences[1][owner] > sequences[0][owner] for owner in sequences[0]),
                'retired admission identity was reused')

        path = directory / 'pending.sqlite'
        session = await FactoredSession.begin(owners, path, FLOW, 'reused-human-manifest')
        value = {'key': 'same-key', 'value': 3, 'status': 1}
        admissions = session.state['certificates']
        owners.drop_next_effect_response = True
        try:
            try:
                await session.request('reused-request-id', value)
            except SchemaRequestPending:
                pass
            else:
                raise ValueError('missing response did not leave a pending request')
            require(owners.effects() == 5, 'unexpected partial effect inventory')
            require(not await session.close(), 'pending request released its session')
            require(owners.holds() == 2, 'pending request lost an owner hold')
        finally:
            session.disconnect()
        recovered = FactoredSession(owners, path)
        try:
            require(recovered.state['certificates'] == admissions, 'recovery changed admission identity')
            result = await recovered.request('reused-request-id', value)
            require(result['records']['sink'] == value, 'recovered result differs')
            require(result['steps']['source']['duplicate'] is True, 'committed source was not deduplicated')
            require(owners.effects() == 6, 'retry repeated an already committed effect')
            require(await recovered.close(), 'recovered session did not drain')
            require(owners.holds() == 0, 'recovered retirement left a hold')
            reports.append({'case': 'pending-recovery', 'effects': 6,
                            'same_admissions': True, 'source_duplicate': True, 'drained': True})
        finally:
            recovered.disconnect()
    finally:
        owners.close()
    return reports


async def successive_rollouts(directory):
    owners = DirectOwners(directory)
    profiles = owners.probe['profiles']
    factors = [{'id': 'a-b', 'branches': [
        {'a': ['emit:' + cls], 'b': ['accept:' + cls]} for cls in owners.probe['classes']]}]
    candidates = {owner: profiles for owner in ('a', 'b')}
    transitions = {owner: [{'source': a, 'target': b} for a, b in zip(profiles, profiles[1:])]
                   for owner in ('a', 'b')}
    planner = FactoredChainPlanner(factors, candidates, transitions)
    reports = []
    try:
        for source, target in ((0, 1), (1, 2)):
            plan = planner.plan({owner: profiles[source] for owner in ('a', 'b')},
                                {owner: profiles[target] for owner in ('a', 'b')})
            coordinator = FactoredCoordinator(
                owners, directory / ('rollout' + str(source) + '.sqlite'),
                plan=plan, manifest='reused-rollout-label')
            try:
                result = await coordinator.run()
                require(result['status'] == 'complete', 'valid successive rollout did not complete')
                require(all(endpoint.state['support'] == profiles[target]
                            for endpoint in owners.endpoints.values()), 'rollout endpoint differs')
                require(owners.holds() == 0, 'rollout left a guard after retirement')
                reports.append({'source_rank': source, 'target_rank': target, 'status': result['status']})
            finally:
                coordinator.disconnect()
        plan = planner.plan({owner: profiles[0] for owner in ('a', 'b')},
                            {owner: profiles[1] for owner in ('a', 'b')})
        coordinator = FactoredCoordinator(owners, directory / 'stale-source.sqlite',
                                         plan=plan, manifest='stale-source')
        try:
            result = await coordinator.advance()
            require(result['status'] == 'deviation', 'stale source was admitted')
            require(all(endpoint.state['support'] == profiles[2]
                        for endpoint in owners.endpoints.values()), 'stale-source check changed owners')
            reports.append({'case': 'stale-source', 'status': result['status'], 'owners_unchanged': True})
        finally:
            coordinator.disconnect()
    finally:
        owners.close()
    return reports


async def retained_integer_domains(directory):
    reports = []
    for index, ranks in enumerate(({'a': 0, 'b': 0}, {'a': 2, 'b': 1}, {'a': 2, 'b': 2})):
        path = directory / str(index)
        path.mkdir()
        owners = DirectOwners(path, 'integer-widening', ranks)
        session = await FactoredSession.begin(owners, path / 'session.sqlite', FLOW, 'integer-domain')
        value = {'key': 'wide', 'value': 1 << 40}
        try:
            if 0 in ranks.values() or 1 in ranks.values():
                try:
                    await session.request('outside-domain', value)
                except ValueError:
                    pass
                else:
                    raise ValueError('narrow emitter accepted an out-of-domain request')
                require(session.db.execute('SELECT count(*) FROM requests').fetchone()[0] == 0,
                        'invalid input was bound to a durable pending request')
                require(owners.effects() == 0, 'invalid input caused an owner effect')
                outcome = 'rejected-before-binding'
            else:
                result = await session.request('wide-domain', value)
                require(result['records']['sink'] == value, 'wide value changed')
                require(owners.effects() == 2, 'wide request effect count differs')
                outcome = 'complete'
            pending = session.db.execute("SELECT count(*) FROM requests WHERE status='pending'").fetchone()[0]
            require(pending == 0, 'domain control left a pending request')
            require(await session.close(), 'domain control session did not drain')
            require(owners.holds() == 0, 'domain control retained a hold')
            reports.append({'ranks': ranks, 'request': outcome, 'effects': owners.effects(),
                            'pending_requests': pending, 'drained': True})
        finally:
            session.disconnect()
            owners.close()
    return reports


async def concurrent_exact_retries(directory):
    owners = DirectOwners(directory)
    session = await FactoredSession.begin(owners, directory / 'session.sqlite', FLOW, 'concurrent-retry')
    entered, release = asyncio.Event(), asyncio.Event()

    async def pause(step, response):
        if step['id'] == 'source':
            entered.set()
            await release.wait()

    first = None
    try:
        value = {'key': 'same', 'value': 7, 'status': 1}
        first = asyncio.create_task(session.request('same-request', value, after_step=pause))
        await asyncio.wait_for(entered.wait(), 5)
        second_result = await asyncio.wait_for(session.request('same-request', value), 5)
        release.set()
        first_result = await asyncio.wait_for(first, 5)
        cached = await session.request('same-request', value)
        require(first_result == second_result == cached, 'concurrent completion changed the recorded output')
        require(owners.effects() == 2, 'concurrent retry repeated an owner effect')
        require(session.db.execute('SELECT count(*) FROM requests').fetchone()[0] == 1,
                'exact retries created multiple request records')
        require(await session.close(), 'concurrent retry session did not drain')
        require(owners.holds() == 0, 'concurrent retry retained an owner hold')
        return {'effects': 2, 'request_records': 1, 'identical_complete_outputs': True,
                'first_completion_preserved': True, 'drained': True}
    finally:
        release.set()
        if first is not None and not first.done():
            await asyncio.gather(first, return_exceptions=True)
        session.disconnect()
        owners.close()


def source_inputs():
    return {name: (ROOT / name).read_bytes() for name in SOURCE_NAMES}


async def run():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        controls = {}
        for name, operation in (
            ('admission_identity_and_recovery', admission_identity_and_recovery),
            ('successive_rollouts', successive_rollouts),
            ('retained_integer_domains', retained_integer_domains),
            ('concurrent_exact_retries', concurrent_exact_retries),
        ):
            path = root / name
            path.mkdir()
            controls[name] = await operation(path)
        return controls


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    sources = source_inputs()
    if args.out is not None and args.out.exists():
        raise ValueError('use a new output file')
    controls = asyncio.run(run())
    require(source_inputs() == sources, 'executed source changed during controls')
    result = {'status': 'pass', 'scope': 'actual in-process Endpoint, SQLite, and ProtoJSON controls',
              'response_loss': 'one-shot unit injection after an actual source effect commit',
              'controls': controls,
              'runtime': {'python': sys.version, 'optimized': sys.flags.optimize,
                          'protobuf': protobuf_version, 'platform': platform.platform()},
              'source_sha256': {name: hashlib.sha256(data).hexdigest() for name, data in sources.items()}}
    encoded = json.dumps(result, indent=2, sort_keys=True) + '\n'
    if args.out is None:
        print(encoded, end='')
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        for name, data in sources.items():
            destination = args.out.parent / 'sources' / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                require(destination.read_bytes() == data, 'retained review source differs')
            else:
                destination.write_bytes(data)
        args.out.write_text(encoded)
        print(json.dumps({'status': 'pass', 'output': str(args.out), 'optimized': sys.flags.optimize}))


if __name__ == '__main__':
    main()
