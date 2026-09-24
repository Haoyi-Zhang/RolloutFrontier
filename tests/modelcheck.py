"""Independent exhaustive model of one two-owner acquisition/retirement.

The model intentionally imports no implementation module.  It explores request/
reply loss, duplication by replay, arbitrary reordering, origin and endpoint crash/
restart, support additions/removals, durable commit, explicit retirement, and a
single nonwrapping sequence.  It is an exact check of this finite abstraction, not
of the full Python/SQLite implementation or the public parameter envelope.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass, replace
import json
import resource
import time

IDLE, ACQUIRING, COMMITTED, RETIRING, DONE = range(5)
NONE, HELD, CLOSED = range(3)
PHASE = {IDLE: "idle", ACQUIRING: "acquiring", COMMITTED: "committed",
         RETIRING: "retiring", DONE: "done"}
HOLD = {NONE: "none", HELD: "held", CLOSED: "closed"}


@dataclass(frozen=True, slots=True)
class State:
    phase: int = IDLE
    acks: int = 0              # volatile prepare replies known at the origin
    hold0: int = NONE
    hold1: int = NONE
    support: int = 3           # bit i means owner i supports required atom a
    alive: int = 3             # process liveness; durable state survives crashes
    close_acks: int = 0        # volatile close replies in the current retry

    def hold(self, i: int) -> int:
        return self.hold0 if i == 0 else self.hold1

    def with_hold(self, i: int, value: int) -> "State":
        return replace(self, **({"hold0": value} if i == 0 else {"hold1": value}))


def summarize(s: State) -> dict:
    return dict(phase=PHASE[s.phase], acks=s.acks,
                holds=[HOLD[s.hold0], HOLD[s.hold1]],
                support=[bool(s.support & 1), bool(s.support & 2)],
                alive=[bool(s.alive & 1), bool(s.alive & 2)],
                close_acks=s.close_acks)


def successors(s: State, mode: str):
    """Yield (action, state). Self loops are omitted but replay remains enabled."""
    if s.phase == IDLE:
        yield "origin:start-and-persist-intent", replace(s, phase=ACQUIRING)

    # Origin recovery discards volatile replies.  An incomplete acquisition is
    # conservatively retired; a committed one remains committed.
    if s.phase == ACQUIRING:
        yield "origin:crash-recover-to-retiring", replace(
            s, phase=RETIRING, acks=0, close_acks=0)
        yield "origin:abort-or-timeout", replace(
            s, phase=RETIRING, acks=0, close_acks=0)
        if s.acks == 3:
            yield "origin:durable-commit", replace(s, phase=COMMITTED, acks=0)
    elif s.phase == COMMITTED:
        yield "origin:begin-durable-retirement", replace(
            s, phase=RETIRING, acks=0, close_acks=0)
        if s.acks or s.close_acks:
            yield "origin:crash-recover-committed", replace(s, acks=0, close_acks=0)
    elif s.phase == RETIRING:
        if s.close_acks:
            yield "origin:crash-retry-retirement", replace(s, acks=0, close_acks=0)
        if s.close_acks == 3:
            yield "origin:finish-retirement", replace(
                s, phase=DONE, acks=0, close_acks=0)

    for i in (0, 1):
        bit = 1 << i
        alive = bool(s.alive & bit)
        h = s.hold(i)

        if alive:
            yield f"owner{i}:crash", replace(s, alive=s.alive & ~bit)
        else:
            yield f"owner{i}:restart", replace(s, alive=s.alive | bit)
            continue

        # Any sent prepare may be duplicated or delayed. A closed floor rejects
        # it; otherwise a truthful supporting owner can install/replay the hold.
        if s.phase != IDLE and h != CLOSED and (s.support & bit):
            held = s.with_hold(i, HELD)
            if held != s:
                yield f"net:deliver-prepare{i}-lose-reply", held
            if s.phase == ACQUIRING:
                acknowledged = replace(held, acks=held.acks | bit)
                if acknowledged != s:
                    yield f"net:deliver-prepare{i}-and-reply", acknowledged

        # A close can overtake a delayed prepare. Replays remain idempotent.
        if s.phase in (RETIRING, DONE):
            closed = s.with_hold(i, CLOSED)
            if closed != s:
                yield f"net:deliver-close{i}-lose-reply", closed
            if s.phase == RETIRING:
                acknowledged = replace(closed, close_acks=closed.close_acks | bit)
                if acknowledged != s:
                    yield f"net:deliver-close{i}-and-reply", acknowledged

        # Platform changes are local. Guarded removal is disabled while a hold
        # is live; addition is always compatible in this positive one-atom model.
        if not (s.support & bit):
            yield f"owner{i}:install-support", replace(s, support=s.support | bit)
        elif mode == "unguarded" or h != HELD:
            yield f"owner{i}:remove-support", replace(s, support=s.support & ~bit)

        # Explicitly model the excluded unsafe alternative of timeout/lease
        # reclamation, which can discard a live hold without a durable close.
        if mode == "timeout-reclaim" and h == HELD:
            yield f"owner{i}:unsafe-timeout-reclaim", s.with_hold(i, NONE)


def violation(s: State) -> bool:
    return s.phase == COMMITTED and (
        s.hold0 != HELD or s.hold1 != HELD or s.support != 3)


def explore(mode: str):
    initial = State()
    queue = deque([initial])
    parent: dict[State, tuple[State, str] | None] = {initial: None}
    edges: dict[State, list[State]] = {}
    transition_count = 0
    resurrection_edges = 0
    first_bad: State | None = None

    while queue:
        state = queue.popleft()
        out = []
        for action, nxt in successors(state, mode):
            if nxt == state:
                continue
            transition_count += 1
            out.append(nxt)
            if ((state.hold0 == CLOSED and nxt.hold0 == HELD) or
                    (state.hold1 == CLOSED and nxt.hold1 == HELD)):
                resurrection_edges += 1
            if nxt not in parent:
                parent[nxt] = (state, action)
                queue.append(nxt)
                if first_bad is None and violation(nxt):
                    first_bad = nxt
        edges[state] = out

    # Exact reachability-to-cleanup check on the explored graph. This is an
    # existential finite reachability fact, not an asynchronous fairness theorem.
    reverse: dict[State, list[State]] = {s: [] for s in parent}
    for src, targets in edges.items():
        for dst in targets:
            reverse[dst].append(src)
    can_finish = set(s for s in parent if s.phase == DONE)
    work = deque(can_finish)
    while work:
        dst = work.popleft()
        for src in reverse[dst]:
            if src not in can_finish:
                can_finish.add(src); work.append(src)

    def trace(end: State | None):
        if end is None:
            return None
        steps = []
        cur = end
        while parent[cur] is not None:
            prev, action = parent[cur]
            steps.append(dict(action=action, state=summarize(cur)))
            cur = prev
        steps.reverse()
        return steps

    retiring = [s for s in parent if s.phase == RETIRING]
    committed = [s for s in parent if s.phase == COMMITTED]
    bad_states = [s for s in parent if violation(s)]
    return dict(
        mode=mode,
        reachable_states=len(parent),
        explored_transitions=transition_count,
        committed_states=len(committed),
        retiring_states=len(retiring),
        done_states=sum(s.phase == DONE for s in parent),
        committed_states_with_cleanup_path=sum(s in can_finish for s in committed),
        retiring_states_with_cleanup_path=sum(s in can_finish for s in retiring),
        closed_to_held_edges=resurrection_edges,
        invariant_violations=len(bad_states),
        shortest_violation_trace=trace(first_bad),
        scope=("exact reachable-state enumeration for one attempt, two owners, "
               "one positive atom and one nonwrapping sequence"),
    )


def run():
    started, cpu = time.perf_counter(), time.process_time()
    guarded = explore("guarded")
    unguarded = explore("unguarded")
    reclaimed = explore("timeout-reclaim")
    assert guarded["invariant_violations"] == 0
    assert guarded["closed_to_held_edges"] == 0
    assert guarded["committed_states_with_cleanup_path"] == guarded["committed_states"]
    assert guarded["retiring_states_with_cleanup_path"] == guarded["retiring_states"]
    assert unguarded["invariant_violations"] > 0
    assert reclaimed["invariant_violations"] > 0
    assert unguarded["shortest_violation_trace"]
    assert reclaimed["shortest_violation_trace"]
    return dict(
        guarded=guarded,
        negative_controls={"unguarded-install": unguarded,
                           "unsafe-timeout-reclamation": reclaimed},
        cpu_seconds=time.process_time() - cpu,
        wall_seconds=time.perf_counter() - started,
        peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        interpretation=("guarded safety and no-resurrection are exhaustive only for the stated "
                        "finite abstraction; cleanup is reachability, not a fairness proof"),
    )


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
