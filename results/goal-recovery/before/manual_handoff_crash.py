"""Actual process cut in the previously delivered hand-written handoff.

Imports only source bytes extracted from the sealed revision-2 package.
The observation is a missing rollout recovery workflow, not an unsafe core hold.
"""
from pathlib import Path
import asyncio
import hashlib
import json
import os
import signal
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ARTIFACT = HERE / 'manual-before-project/artifact'
sys.path.insert(0, str(ARTIFACT))
from src.batch import choose_batch_box
from src.envelope import frontier_synthesize
from src.network import Client, Network
from tests.kubernetes_policy_boundaries import encoding


def write(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')


async def case(directory, recover=False):
    facts = json.loads((ARTIFACT / 'data/kubernetes-policy-boundaries.json').read_text())
    profiles, branches, candidates = encoding(facts)
    initial = {str(i): profiles[str(i)][36] for i in range(3)}
    net = Network(directory / 'network', [initial[str(i)] for i in range(3)])
    await net.start()
    old, new = Client(net, 0), Client(net, 1)
    if not recover:
        first = frontier_synthesize(branches, initial, candidates)
        before = await old.acquire_box('kubernetes-policy-handoff', branches, first['box'])
        assert before['status'] == 'admitted'
        for node in (0, 1):
            assert (await net.rpc(0, node, {'op': 'install', 'support': profiles[str(node)][37]}))['status'] == 'installed'
        current = {'0': profiles['0'][37], '1': profiles['1'][37], '2': profiles['2'][36]}
        second = choose_batch_box(branches, current, candidates, [{'node': '2', 'support': profiles['2'][37]}])
        after = await new.acquire_box('kubernetes-policy-handoff', branches, second['box'])
        assert after['status'] == 'admitted'
        write(directory / 'before-kill.json', {'origin_states': {'0': old.state, '1': new.state},
              'owner_states': {str(i): net.nodes[i].state for i in range(3)},
              'rpc_trace': net.trace, 'cut': 'new phase committed; old phase not retired'})
        os.kill(os.getpid(), signal.SIGKILL)
    try:
        await old.recover()
        await new.recover()
        reply = await net.rpc(1, 2, {'op': 'install', 'support': profiles['2'][37]})
        assert reply['status'] == 'blocked' and reply['holds'] == ['0:1']
        attempts = [r for core in (old, new) for r in core.state['attempts'].values()]
        assert len(attempts) == 2 and all(r['status'] == 'committed' for r in attempts)
        write(directory / 'after-generic-recovery.json', {
            'observation': 'Both valid committed phases survive generic recovery; old phase still blocks final target.',
            'goal_reached': False, 'final_target_reply': reply, 'committed_attempts': len(attempts),
            'origin_states': {'0': old.state, '1': new.state},
            'owner_states': {str(i): net.nodes[i].state for i in range(3)}, 'rpc_trace': net.trace,
            'scope': 'This is a rollout-workflow recovery gap. Retaining both guards is the correct conservative behavior of each standalone Client.'})
    finally:
        old.disconnect(); new.disconnect(); await net.stop()


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--child':
        asyncio.run(case(Path(sys.argv[2])))
    else:
        directory = HERE / 'manual-handoff-crash'
        directory.mkdir(exist_ok=False)
        command = [sys.executable, '-B', str(Path(__file__).resolve()), '--child', str(directory)]
        process = subprocess.run(command, capture_output=True, text=True)
        assert process.returncode == -signal.SIGKILL, process
        asyncio.run(case(directory, recover=True))
        write(directory / 'execution.json', {'status': 'OBSERVED_GAP', 'command': command,
            'returncode': process.returncode, 'signal': 'SIGKILL', 'stdout': process.stdout, 'stderr': process.stderr,
            'source_sha256': {str(p.relative_to(ARTIFACT)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(ARTIFACT.rglob('*.py'))}})
        print(json.dumps({'status': 'OBSERVED_GAP', 'signal': 'SIGKILL', 'goal_reached_after_generic_recovery': False,
                          'directory': str(directory)}))
