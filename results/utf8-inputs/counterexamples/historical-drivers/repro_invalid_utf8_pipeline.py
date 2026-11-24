"""Actual pre-fix TCP/SQLite evidence for the three-owner pipeline entry."""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import sys

ROOT = Path(os.environ.get('ROLLOUT_REVIEW_ARTIFACT',
                          '/workspace/scratch/e34480916f53/completion/project/artifact'))
sys.path.insert(0, str(ROOT))
from src.application import PipelineSession, PROFILES, pipeline_branch
from src.network import Client
from tests.application_network import ApplicationNetwork


async def run(directory):
    directory.mkdir(parents=True, exist_ok=False)
    net = ApplicationNetwork(directory, [PROFILES['accepting'] for _ in range(3)])
    client = None
    report = {'transport': 'three actual TCP/SQLite owner processes'}
    try:
        net.start()
        client = Client(net, 2)
        codec = ['ACTIVE', 'ACTIVE']
        admitted = await client.acquire('utf8-pipeline-review', [pipeline_branch(codec)])
        certificate = deepcopy(admitted['certificate'])
        session = PipelineSession(client, certificate, codec)
        value = {'key': '\ud800', 'amount': 17}
        for attempt in range(2):
            try:
                await session.request('bad-input', value)
            except Exception as error:
                report.setdefault('request_outcomes', []).append({
                    'attempt': attempt, 'error': type(error).__name__, 'message': str(error)})
            else:
                raise ValueError('invalid UTF-8 unexpectedly applied')
        report['request_rows'] = client.db.execute(
            'SELECT request_id,input,status,output FROM application_requests').fetchall()
        report['retire_before_reopen'] = await session.retire()
        client.disconnect()
        client = Client(net, 2)
        session = PipelineSession(client, certificate, codec)
        report['retire_after_reopen'] = await session.retire()
        report['remaining_holds'] = 0
        report['durable_effects'] = 0
        for node in range(3):
            inspection = await net.rpc(2, node, {'op': 'inspect'})
            report['remaining_holds'] += sum(h['status'] == 'held' for h in inspection['state']['slots'].values())
            with sqlite3.connect(str(directory / f'process-node-{node}.sqlite')) as db:
                report['durable_effects'] += db.execute('SELECT count(*) FROM application_results').fetchone()[0]
        report['counterexample_reproduced'] = (
            report['retire_before_reopen'] is False and report['retire_after_reopen'] is False and
            report['remaining_holds'] == 3 and report['durable_effects'] == 0)
        if not report['counterexample_reproduced']:
            raise ValueError('evidence disagrees')
    finally:
        if client is not None:
            client.disconnect()
        net.stop()
        (directory / 'transport.jsonl').write_text(''.join(json.dumps(event) + '\n' for event in net.trace))
        (directory / 'observations.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    asyncio.run(run(Path(sys.argv[1])))
