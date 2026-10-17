"""Owned direct-Endpoint returned-data isolation; no sockets or third parties.

Raw before/after observations live only in a fresh RolloutFrontier candidate/private folder.
The journal and caller-copy edits are benign local conformance tests, not a test
of remote compromise. The TCP boundary already serializes returned objects.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import sqlite3
import sys

from src.controller import Endpoint

ROOT = Path(__file__).resolve().parents[1]


def run(out):
    if not __debug__:
        raise SystemExit('receipt conformance requires enabled assertions')
    out = Path(out).resolve()
    if ROOT == out or out in ROOT.parents or any(out == ROOT/name or (ROOT/name) in out.parents
                                                for name in ('src','tests','data')):
        raise ValueError('output overlaps protected artifact inputs or sources')
    out.mkdir(parents=True, exist_ok=False)
    rows = []
    for durable in (False, True):
        for duplicate in (False, True):
            for kind in ("requires", "option-inner", "options-outer"):
                tag = f"disk-{durable}-duplicate-{duplicate}-{kind}"
                path = out / (tag + ".sqlite") if durable else None
                endpoint = Endpoint(0, ["a", "noise"], path)
                arguments = dict(origin=0, sequence=1, manifest="owned-snapshot",
                                 requires=["a"] if kind == "requires" else [],
                                 options=None if kind == "requires" else [["a"], ["b"]])
                first = endpoint.prepare(**deepcopy(arguments))
                reply = endpoint.prepare(**deepcopy(arguments)) if duplicate else first
                assert reply == first and reply["status"] == "held"
                frozen = deepcopy(endpoint.state)
                before_receipt = deepcopy(reply["receipt"])
                if kind == "requires":
                    reply["receipt"]["requires"].clear()
                elif kind == "option-inner":
                    reply["receipt"]["options"][0].clear()
                else:
                    reply["receipt"]["options"].append([])
                after_edit = deepcopy(endpoint.state)
                installed = endpoint.install(["noise"])
                after_install = deepcopy(endpoint.state)
                endpoint.disconnect()
                reopened, reopen_error = None, None
                if durable:
                    try:
                        endpoint = Endpoint(0, ["a", "noise"], path)
                        reopened = deepcopy(endpoint.state)
                        endpoint.disconnect()
                    except ValueError as error:
                        reopen_error = str(error)
                checks = dict(return_detached=after_edit == frozen,
                              installation_blocked=installed["status"] == "blocked",
                              whole_state_preserved=after_install == frozen,
                              durable_preserved=(not durable or reopened == frozen))
                rows.append(dict(case=tag, durable=durable, duplicate=duplicate,
                                 edit=kind, prepare_inputs=arguments,
                                 returned_receipt=before_receipt,
                                 caller_receipt_after_edit=reply["receipt"],
                                 frozen_state=frozen, after_caller_edit=after_edit,
                                 install_input=["noise"], install_reply=installed,
                                 after_install=after_install, reopened=reopened,
                                 reopen_error=reopen_error, checks=checks,
                                 passed=all(checks.values())))
    result = dict(case_count=len(rows), failures=sum(not r["passed"] for r in rows),
                  cases=rows, environment=dict(python=sys.version, sqlite=sqlite3.sqlite_version,
                  platform=platform.platform(), observed_utc=datetime.now(timezone.utc).isoformat()),
                  scope="owned direct Endpoint API and SQLite reopen; not TCP, origins, power loss or remote exploitation")
    (out / "observations.json").write_text(json.dumps(result, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k!="cases"}, sort_keys=True))
    return result["failures"]


if __name__ == "__main__":
    if not __debug__:
        raise RuntimeError("assertions required")
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    raise SystemExit(bool(run(parser.parse_args().out)))
