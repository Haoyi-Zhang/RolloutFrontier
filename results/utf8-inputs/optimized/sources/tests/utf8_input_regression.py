"""Actual TCP/SQLite controls for UTF-8 validation before durable request binding.

All four schema families and all four pipeline programs run in separate owner
processes. Rejected inputs, successful replies, checkpoints, transport events,
and final databases are retained for an implementation-independent reader.
"""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import sys

from src.application import INPUT_MAX, INPUT_MIN, PipelineSession, PROFILES, pipeline_branch
from src.controller import canonical
from src.factored_session import FactoredSession
from src.network import Client
from src.schema_contracts import FAMILIES, actual_probes
from tests.application_network import ApplicationNetwork
from tests.factored_network import PhysicalNetwork

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
BAD_KEYS = ('\ud800', '\udfff', 'left\ud800right', '\ud800\udc00')
GOOD_KEYS = ('plain', 'κλειδί-中文', 'supplementary-🧪-𐐀', '\x00key',
             '\u007f\u0080\u07ff\u0800\ud7ff\ue000\uffff', '\U0010ffff',
             '🧪' * 128, 'after-reopen')
FLOW = [{'id': 'source', 'owner': 'a', 'parents': []},
        {'id': 'sink', 'owner': 'b', 'parents': ['source']}]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def save(path, value):
    Path(path).write_text(canonical(value) + '\n')


def backup(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True) as src:
        with sqlite3.connect(str(destination)) as dst:
            src.backup(dst)


async def rejected_requests(session, bad_inputs, issued):
    records = []
    for index, value in enumerate(bad_inputs):
        before = issued()
        try:
            await session.request('input-' + str(index), value)
        except ValueError as error:
            record = {'request_id': 'input-' + str(index), 'input': value,
                      'key_codepoints': [ord(character) for character in value['key']],
                      'error': type(error).__name__, 'message': str(error),
                      'rpc_count_before': before, 'rpc_count_after': issued()}
            require(type(error) is ValueError and before == issued(),
                    'invalid input was not rejected before physical work')
            records.append(record)
        else:
            raise ValueError('invalid input acquired a durable request binding')
    return records


def schema_value(family, rank, key, value):
    result = {'key': key, 'value': value}
    if family == 'enum-alias':
        result['status'] = 1
    if family == 'field-addition':
        result['tag'] = 'migrated-δ' if rank == 2 else ''
    return result


async def factored_case(directory, probe, rank):
    directory.mkdir(parents=True)
    family = probe['family']
    registry = {'deployment': 'utf8-' + family + '-' + str(rank), 'owners': {
        owner: {'family': family, 'initial': deepcopy(probe['profiles'][rank]),
                'catalog': deepcopy(probe['profiles'])} for owner in ('a', 'b')}}
    save(directory / 'registry.json', registry)
    save(directory / 'schema-probe.json', probe)
    net = PhysicalNetwork(directory / 'network', registry)
    path = directory / 'session.sqlite'
    session = None
    report = {'kind': 'factored', 'family': family, 'rank': rank,
              'program': probe['programs'][rank], 'workflow': FLOW}
    try:
        net.start()
        session = await FactoredSession.begin(net, path, FLOW, 'utf8-inputs')
        bits = 31 if family == 'integer-widening' and rank < 2 else 63
        bad = [schema_value(family, rank, key, 0) for key in (*BAD_KEYS, '', 'a' * 129)]
        bad += [schema_value(family, rank, 'range', number)
                for number in (-(1 << bits) - 1, 1 << bits, True)]
        report['rejections'] = await rejected_requests(session, bad, lambda: net.issued)
        require(session.db.execute('SELECT count(*) FROM requests').fetchone() == (0,),
                'rejected input left a request binding')
        backup(path, directory / 'rejected' / 'session.sqlite')
        for index, owner in enumerate(('a', 'b')):
            backup(net.database(owner), directory / 'rejected' / ('owner-' + str(index) + '.sqlite'))
            backup(session.clients[owner].net.directory / 'origin-2.sqlite',
                   directory / 'rejected' / ('origin-' + str(index) + '.sqlite'))
        values = (-(1 << bits), -1, 0, 1, (1 << bits) - 1, 17, -29, 31)
        report['requests'] = []
        for index, (key, number) in enumerate(zip(GOOD_KEYS, values)):
            value = schema_value(family, rank, key, number)
            result = await session.request('input-' + str(index), value)
            expected = {'source': value, 'sink': value}
            require(result['records'] == {'sink': value} and
                    {step: reply['output']['record'] for step, reply in result['steps'].items()} == expected,
                    'legitimate Unicode or boundary integer changed')
            report['requests'].append({'request_id': 'input-' + str(index), 'input': value, 'output': result})
        first = report['requests'][0]
        session.disconnect()
        await net.restart_owner('a', kill=True)
        session = FactoredSession(net, path)
        report['reopened_exact_retry'] = await session.request(first['request_id'], first['input'])
        require(report['reopened_exact_retry'] == first['output'], 'reopened result changed')
        report['retired_after_reopen'] = await session.close()
        require(report['retired_after_reopen'], 'valid requests failed to drain')
        report['final_owners'] = {owner: (await net.rpc(owner, {'op': 'inspect'}, source=2))['state']
                                  for owner in ('a', 'b')}
        require(not any(h.get('status') == 'held' for state in report['final_owners'].values()
                        for h in state['slots'].values()), 'retired input control left a hold')
    finally:
        if session is not None:
            session.disconnect()
        net.close()
    save(directory / 'observations.json', report)
    return {'kind': 'factored', 'family': family, 'rank': rank,
            'rejections': len(report['rejections']), 'requests': len(report['requests'])}


async def pipeline_case(directory, program):
    directory.mkdir(parents=True)
    network_path = directory / 'databases' / program
    supports = [deepcopy(PROFILES[program]) for _ in range(3)]
    net = ApplicationNetwork(network_path, supports)
    codec = ['ACTIVE', 'ACTIVE'] if program in ('legacy', 'accepting') else ['ENABLED', 'ENABLED']
    client = None
    report = {'kind': 'pipeline', 'program': program, 'name': program,
              'initial': supports, 'codec': codec}
    try:
        net.start()
        client = Client(net, 2)
        response = await client.acquire('utf8-pipeline', [pipeline_branch(codec)])
        require(response['status'] == 'admitted', 'pipeline input control admission')
        certificate = deepcopy(response['certificate'])
        session = PipelineSession(client, certificate, codec)
        bad = [{'key': key, 'amount': 0} for key in (*BAD_KEYS, '', 'a' * 129)]
        bad += [{'key': 'range', 'amount': number} for number in (INPUT_MIN - 1, INPUT_MAX + 1, True)]
        report['rejections'] = await rejected_requests(session, bad, lambda: net.issued)
        require(client.db.execute('SELECT count(*) FROM application_requests').fetchone() == (0,),
                'rejected pipeline input left a request binding')
        backup(network_path / 'origin-2.sqlite', directory / 'rejected' / 'origin.sqlite')
        for node in range(3):
            backup(network_path / f'process-node-{node}.sqlite',
                   directory / 'rejected' / f'owner-{node}.sqlite')
        values = (INPUT_MIN, -1, 0, 1, INPUT_MAX, 17, -29, 31)
        report['requests'] = []
        for index, (key, number) in enumerate(zip(GOOD_KEYS, values)):
            value = {'key': key, 'amount': number}
            result = await session.request('input-' + str(index), value)
            require(result['record'] == {'key': key, 'amount': 3 * number + 7},
                    'pipeline Unicode or transform-domain boundary changed')
            report['requests'].append({'request_id': 'input-' + str(index), 'input': value, 'output': result})
        first = report['requests'][0]
        client.disconnect()
        net.crash(0)
        client = Client(net, 2)
        session = PipelineSession(client, certificate, codec)
        report['reopened_exact_retry'] = await session.request(first['request_id'], first['input'])
        require(report['reopened_exact_retry'] == first['output'], 'pipeline reopened result changed')
        report['retired_after_reopen'] = await session.retire()
        require(report['retired_after_reopen'], 'valid pipeline requests failed to drain')
        report['final_owners'] = {str(node): (await net.rpc(2, node, {'op': 'inspect'}))['state']
                                  for node in range(3)}
        require(not any(h.get('status') == 'held' for state in report['final_owners'].values()
                        for h in state['slots'].values()), 'retired pipeline control left a hold')
    finally:
        if client is not None:
            client.disconnect()
        net.stop()
    report['trace'] = net.trace
    save(directory / 'observations.json', report)
    return {'kind': 'pipeline', 'program': program,
            'rejections': len(report['rejections']), 'requests': len(report['requests'])}


async def run(directory):
    require(not directory.exists() or not any(directory.iterdir()), 'new evidence directory required')
    require(sys.flags.optimize in (0, 1), 'control modes are normal and optimized')
    directory.mkdir(parents=True, exist_ok=True)
    # The physical transport's subprocess launcher inherits this setting.
    os.environ['PYTHONOPTIMIZE'] = str(sys.flags.optimize)
    for name in SOURCE_NAMES:
        destination = directory / 'sources' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
    summaries = []
    for probe in actual_probes():
        for rank in range(len(FAMILIES[probe['family']]['programs'])):
            relative = 'factored/' + probe['family'] + '/' + str(rank)
            result = await factored_case(directory / relative, probe, rank)
            summaries.append(dict(result, path=relative))
    for program in PROFILES:
        relative = 'pipeline/' + program
        result = await pipeline_case(directory / relative, program)
        summaries.append(dict(result, path=relative))
    summary = {'python': platform.python_version(), 'optimization': sys.flags.optimize,
               'owner_optimization_environment': os.environ['PYTHONOPTIMIZE'],
               'transport': 'separate TCP/SQLite owner processes',
               'sources': list(SOURCE_NAMES), 'cases': summaries}
    save(directory / 'summary.json', summary)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(canonical(asyncio.run(run(args.output))))
