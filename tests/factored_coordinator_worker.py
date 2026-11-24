"""Restartable coordinator process with explicit post-RPC SIGKILL cuts."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import signal
import time
from src.controller import canonical
from src.factored_runtime import FactoredCoordinator
from tests.factored_network import RegisteredTransport


async def execute(args):
    registry = json.loads(args.registry.read_text())
    ports = json.loads(args.routes.read_text())
    transport = RegisteredTransport(args.directory,registry,ports,trace_name='coordinator-transport.jsonl')
    plan = json.loads(args.plan.read_text()) if args.plan else None
    def observe(event):
        if event['event'] == args.cut_event and event['phase_index'] == args.cut_phase and (
                args.cut_owner is None or event.get('owner') == args.cut_owner):
            with open(args.directory/'coordinator-cuts.jsonl','a',encoding='utf-8') as stream:
                stream.write(canonical({'event':'coordinator-sigkill','pid':os.getpid(),
                    'time_ns':time.perf_counter_ns(),'cut':event})+'\n')
                stream.flush(); os.fsync(stream.fileno())
            os.kill(os.getpid(),signal.SIGKILL)
    coordinator = FactoredCoordinator(transport,args.journal,plan=plan,manifest=args.manifest,observer=observe)
    try:
        result = await coordinator.run()
        print(canonical(result),flush=True)
    finally:
        coordinator.disconnect(); transport.disconnect()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--registry',type=Path,required=True)
    parser.add_argument('--routes',type=Path,required=True)
    parser.add_argument('--journal',type=Path,required=True)
    parser.add_argument('--plan',type=Path)
    parser.add_argument('--manifest')
    parser.add_argument('--cut-event')
    parser.add_argument('--cut-phase',type=int,default=0)
    parser.add_argument('--cut-owner')
    asyncio.run(execute(parser.parse_args()))
