"""Actual TCP/SQLite counterexample for a permanently unexecutable seed.

No production source or captured experiment result is changed.
"""
import argparse
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

from src.factored_session import FactoredSession
from src.schema_contracts import actual_probes, validate_payload
from tests.factored_network import PhysicalNetwork


async def run(directory):
    directory.mkdir(parents=True, exist_ok=False)
    probe = next(p for p in actual_probes() if p['family'] == 'enum-alias')
    registry = {'deployment': 'utf8-review', 'owners': {'owner': {
        'family': 'enum-alias', 'initial': deepcopy(probe['profiles'][0]),
        'catalog': deepcopy(probe['profiles'])}}}
    net = PhysicalNetwork(directory / 'network', registry)
    session_path = directory / 'session.sqlite'
    flow = [{'id': 'only', 'owner': 'owner', 'parents': []}]
    value = {'key': '\ud800', 'value': 17, 'status': 1}
    report = {'transport': 'real TCP owner process and relay',
              'invalid_key_json': json.dumps(value['key'])}
    session = None
    try:
        net.start()
        validate_payload('enum-alias', 3, value)
        report['seed_prevalidation'] = 'accepted'
        session = await FactoredSession.begin(net, session_path, flow, 'utf8-review')
        for attempt in range(3):
            try:
                await session.request('bad-input', value)
            except Exception as error:
                report.setdefault('request_outcomes', []).append({
                    'attempt': attempt, 'error': type(error).__name__, 'message': str(error)})
            else:
                raise ValueError('unexpectedly accepted the invalid UTF-8 input')
        report['request_rows'] = session.db.execute('SELECT request_id,input,status,output FROM requests').fetchall()
        report['close_before_reopen'] = await session.close()
        session.disconnect()
        session = FactoredSession(net, session_path)
        report['close_after_reopen'] = await session.close()
        report['durable_stage_after_reopen'] = session.state['stage']
        inspection = await net.rpc('owner', {'op': 'inspect'}, source=2)
        report['remaining_holds'] = sum(h['status'] == 'held' for h in inspection['state']['slots'].values())
        with sqlite3.connect(str(net.database('owner'))) as db:
            report['durable_effects'] = db.execute('SELECT count(*) FROM schema_results').fetchone()[0]
            report['schema_audit'] = [json.loads(row[0]) for row in db.execute(
                "SELECT response FROM schema_audit WHERE json_extract(request,'$.op')='schema'")]
        report['counterexample_reproduced'] = (
            all(row['status'] == 'invalid' for row in report['schema_audit']) and
            report['close_before_reopen'] is False and report['close_after_reopen'] is False and
            report['remaining_holds'] == 1 and report['durable_effects'] == 0)
        if not report['counterexample_reproduced']:
            raise ValueError('counterexample evidence disagrees')
    finally:
        if session is not None:
            session.disconnect()
        net.close()
        (directory / 'observations.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    asyncio.run(run(parser.parse_args().directory))
