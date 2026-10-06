"""Durable endpoint and finite compatibility model.

Each endpoint has one serialization point. The optional SQLite file persists a
complete endpoint state before any acknowledgement is returned. The protocol
assumes non-Byzantine origins, truthful contract descriptions, and no mutation
of the installed platform outside the guarded transition operation.
"""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

MAX_NODES = 6
MAX_CONTRACTS = 12000
MAX_REQUIREMENTS = 96
MAX_SEQ = (1 << 63) - 1
MAX_BRANCHES = 8


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def initialize_state_table(db: sqlite3.Connection) -> None:
    """Create or validate the one-row durable-state table.

    A nonempty table that lacks the canonical ``id=1`` row must not be treated
    as a fresh store: doing so would silently discard previously durable guards.
    The schema check also rejects shadow columns or a non-primary-key identifier.
    """
    db.execute("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
    info = db.execute("PRAGMA table_info(state)").fetchall()
    shape = [(row[1], str(row[2]).upper(), row[3], row[5]) for row in info]
    if shape != [("id", "INTEGER", 0, 1), ("payload", "TEXT", 1, 0)]:
        raise ValueError("invalid durable state table schema")


def load_singleton_state(db: sqlite3.Connection) -> Any | None:
    """Return the sole canonical payload, or ``None`` only for a truly empty table."""
    rows = db.execute("SELECT id, payload FROM state ORDER BY id").fetchall()
    if not rows:
        return None
    if len(rows) != 1 or rows[0][0] != 1 or not isinstance(rows[0][1], str):
        raise ValueError("invalid durable state row set")
    return json.loads(rows[0][1])


def atoms(values: Iterable[str], cap: int) -> list[str]:
    if not isinstance(values, (list, tuple, set, frozenset)):
        raise ValueError("contracts must be an explicit finite collection")
    if len(values) > cap:
        raise ValueError("contract bound exceeded")
    if any(not isinstance(x, str) or not x or len(x) > 512 for x in values):
        raise ValueError("invalid contract atom")
    return sorted(set(values))


def closure(roots: Iterable[str], dependencies: dict[str, list[str]]) -> list[str]:
    """Least finite conjunctive dependency closure, including cycles."""
    seen = set(atoms(list(roots), MAX_REQUIREMENTS))
    todo = list(seen)
    while todo:
        for value in atoms(dependencies.get(todo.pop(), []), MAX_REQUIREMENTS):
            if value not in seen:
                seen.add(value)
                todo.append(value)
                if len(seen) > MAX_REQUIREMENTS:
                    raise ValueError("closed requirement bound exceeded")
    return sorted(seen)


class Endpoint:
    def __init__(self, node: int, support: Iterable[str], path: Path | None = None,
                 window: int = 8, policy: str = "predicate") -> None:
        if type(node) is not int or not 0 <= node < MAX_NODES:
            raise ValueError("invalid node")
        if not 1 <= window <= 64 or policy not in ("predicate", "epoch", "unguarded"):
            raise ValueError("invalid policy/window")
        self.node, self.path = node, path
        self.db = None
        self.state = dict(node=node, generation=0, support=atoms(support, MAX_CONTRACTS),
                          window=window, policy=policy, floor=[0] * MAX_NODES,
                          slots={}, catalog={})
        self.state["catalog"][str(node)] = self.profile()
        if path is not None:
            self.db = sqlite3.connect(str(path))
            try:
                self.db.execute("PRAGMA synchronous=FULL")
                self.db.execute("PRAGMA journal_mode=DELETE")
                initialize_state_table(self.db)
                loaded = load_singleton_state(self.db)
                if loaded is not None:
                    self._validate_loaded_state(loaded, window, policy)
                    self.state = loaded
                else:
                    self.persist()
            except Exception:
                self.db.close()
                self.db = None
                raise

    def _validate_loaded_state(self, state: Any, window: int, policy: str) -> None:
        """Fail closed on malformed or configuration-incompatible durable state."""
        fields = {"node", "generation", "support", "window", "policy",
                  "floor", "slots", "catalog"}
        if not isinstance(state, dict) or set(state) != fields:
            raise ValueError("invalid durable endpoint schema")
        if type(state["node"]) is not int or state["node"] != self.node:
            raise ValueError("durable node identity mismatch")
        if type(state["window"]) is not int or state["window"] != window:
            raise ValueError("durable window mismatch")
        if state["policy"] != policy or policy not in ("predicate", "epoch", "unguarded"):
            raise ValueError("durable policy mismatch")
        generation = state["generation"]
        if type(generation) is not int or not 0 <= generation <= MAX_SEQ:
            raise ValueError("invalid durable generation")
        support = state["support"]
        if not isinstance(support, list) or atoms(support, MAX_CONTRACTS) != support:
            raise ValueError("noncanonical durable support")
        floor = state["floor"]
        if (not isinstance(floor, list) or len(floor) != MAX_NODES or
                any(type(value) is not int or not 0 <= value <= MAX_SEQ for value in floor)):
            raise ValueError("invalid durable sequence floors")
        slots = state["slots"]
        if not isinstance(slots, dict) or len(slots) > MAX_NODES * window:
            raise ValueError("invalid durable slot map")
        for key, hold in slots.items():
            if not isinstance(key, str):
                raise ValueError("invalid durable slot key")
            parts = key.split(":")
            if (len(parts) != 2 or any(not part or part != str(int(part)) for part in parts)):
                raise ValueError("noncanonical durable slot key")
            origin, sequence = map(int, parts)
            if (not 0 <= origin < MAX_NODES or not 1 <= sequence <= MAX_SEQ or
                    not floor[origin] < sequence <= floor[origin] + window):
                raise ValueError("durable slot outside sequence window")
            if not isinstance(hold, dict) or hold.get("status") not in ("held", "closed"):
                raise ValueError("invalid durable slot record")
            if hold["status"] == "closed":
                if set(hold) != {"status"}:
                    raise ValueError("invalid durable closed slot")
                continue
            base = {"status", "node", "origin", "sequence", "manifest",
                    "requires", "observed_generation"}
            if set(hold) not in (base, base | {"options"}):
                raise ValueError("invalid durable hold schema")
            if (hold["node"] != self.node or type(hold["node"]) is not int or
                    hold["origin"] != origin or type(hold["origin"]) is not int or
                    hold["sequence"] != sequence or type(hold["sequence"]) is not int):
                raise ValueError("durable hold binding mismatch")
            if (not isinstance(hold["manifest"], str) or not hold["manifest"] or
                    len(hold["manifest"]) > 256):
                raise ValueError("invalid durable manifest")
            if (type(hold["observed_generation"]) is not int or
                    not 0 <= hold["observed_generation"] <= generation):
                raise ValueError("invalid durable observed generation")
            if not isinstance(hold["requires"], list) or atoms(hold["requires"], MAX_REQUIREMENTS) != hold["requires"]:
                raise ValueError("noncanonical durable requirements")
            if "options" in hold:
                options = hold["options"]
                if hold["requires"] or not isinstance(options, list) or not 1 <= len(options) <= 8:
                    raise ValueError("invalid durable options")
                normalized = sorted({tuple(atoms(option, MAX_CONTRACTS)) for option in options})
                if options != [list(option) for option in normalized]:
                    raise ValueError("noncanonical durable options")
            if policy != "unguarded" and not self.satisfies(hold, support):
                raise ValueError("durable hold is not satisfied")
        catalog = state["catalog"]
        if not isinstance(catalog, dict) or not 1 <= len(catalog) <= MAX_NODES:
            raise ValueError("invalid durable catalog")
        for text, profile in catalog.items():
            if (not isinstance(text, str) or not text or text != str(int(text)) or
                    not 0 <= int(text) < MAX_NODES or not isinstance(profile, dict) or
                    set(profile) != {"node", "generation", "support"}):
                raise ValueError("invalid durable profile schema")
            owner = int(text)
            if type(profile["node"]) is not int or profile["node"] != owner:
                raise ValueError("durable profile owner mismatch")
            if (type(profile["generation"]) is not int or
                    not 0 <= profile["generation"] <= MAX_SEQ):
                raise ValueError("invalid durable profile generation")
            if (not isinstance(profile["support"], list) or
                    atoms(profile["support"], MAX_CONTRACTS) != profile["support"]):
                raise ValueError("noncanonical durable profile support")
        own = catalog.get(str(self.node))
        expected_own = dict(node=self.node, generation=generation, support=support)
        if own != expected_own:
            raise ValueError("durable self profile mismatch")

    def profile(self) -> dict[str, Any]:
        return dict(node=self.node, generation=self.state["generation"],
                    support=list(self.state["support"]))

    def persist(self) -> None:
        if self.db is not None:
            with self.db:
                self.db.execute("INSERT OR REPLACE INTO state VALUES (1,?)", (canonical(self.state),))

    def disconnect(self) -> None:
        if self.db is not None:
            self.db.close()
            self.db = None

    def _key(self, origin: int, sequence: int) -> tuple[str, str | None]:
        if type(origin) is not int or not 0 <= origin < MAX_NODES:
            raise ValueError("invalid origin")
        if type(sequence) is not int or not 1 <= sequence <= MAX_SEQ:
            raise ValueError("invalid nonwrapping sequence")
        floor = self.state["floor"][origin]
        if sequence <= floor:
            return f"{origin}:{sequence}", "closed"
        if sequence > floor + self.state["window"]:
            return f"{origin}:{sequence}", "window"
        return f"{origin}:{sequence}", None

    def prepare(self, origin: int, sequence: int, manifest: str,
                requires: list[str], options: list[list[str]] | None = None) -> dict[str, Any]:
        requires = atoms(requires, MAX_REQUIREMENTS)
        if options is not None:
            if requires or not isinstance(options, list) or not 1 <= len(options) <= 8:
                raise ValueError("invalid envelope options")
            options = sorted({tuple(atoms(x, MAX_CONTRACTS)) for x in options})
            options = [list(x) for x in options]
        if not isinstance(manifest, str) or not manifest or len(manifest) > 256:
            raise ValueError("invalid manifest binding")
        key, error = self._key(origin, sequence)
        if error:
            return dict(status=error)
        existing = self.state["slots"].get(key)
        if existing:
            if existing["status"] == "closed":
                return dict(status="closed")
            if existing["manifest"] != manifest or existing["requires"] != requires or existing.get("options") != options:
                return dict(status="binding-conflict")
            return dict(status="held", receipt=dict(existing))
        missing = sorted(set(requires) - set(self.state["support"]))
        accepts = (not missing) if options is None else any(set(x).issubset(self.state["support"]) for x in options)
        if not accepts:
            return dict(status="missing", missing=missing, observed=self.profile())
        slot = dict(status="held", node=self.node, origin=origin, sequence=sequence,
                    manifest=manifest, requires=requires,
                    observed_generation=self.state["generation"])
        if options is not None:
            slot["options"] = options
        self.state["slots"][key] = slot
        self.persist()  # Acknowledgement follows durable installation of the guard.
        return dict(status="held", receipt=dict(slot))

    def close(self, origin: int, sequence: int) -> dict[str, Any]:
        key, error = self._key(origin, sequence)
        if error:
            return dict(status=error)
        self.state["slots"][key] = dict(status="closed")
        floor = self.state["floor"][origin]
        while self.state["slots"].get(f"{origin}:{floor + 1}", {}).get("status") == "closed":
            del self.state["slots"][f"{origin}:{floor + 1}"]
            floor += 1
        self.state["floor"][origin] = floor
        self.persist()
        return dict(status="closed", floor=floor)

    @staticmethod
    def satisfies(hold: dict, support: list[str]) -> bool:
        return any(set(option).issubset(support) for option in hold.get("options", [hold["requires"]]))

    def install(self, support: list[str]) -> dict[str, Any]:
        new = atoms(support, MAX_CONTRACTS)
        if new == self.state["support"]:
            return dict(status="unchanged", observed=self.profile())
        if self.state["generation"] == MAX_SEQ:
            return dict(status="generation-exhausted")
        blocking = []
        for key, hold in sorted(self.state["slots"].items()):
            if hold["status"] != "held":
                continue
            if self.state["policy"] == "epoch" or (
                    self.state["policy"] == "predicate" and
                    not self.satisfies(hold, new)):
                blocking.append(key)
        if blocking:
            return dict(status="blocked", holds=blocking)
        self.state["generation"] += 1
        self.state["support"] = new
        self.state["catalog"][str(self.node)] = self.profile()
        self.persist()
        return dict(status="installed", observed=self.profile())

    def merge(self, profile: dict[str, Any]) -> dict[str, Any]:
        owner, gen = profile.get("node"), profile.get("generation")
        if type(owner) is not int or not 0 <= owner < MAX_NODES:
            raise ValueError("invalid profile owner")
        if type(gen) is not int or not 0 <= gen <= MAX_SEQ:
            raise ValueError("invalid profile generation")
        p = dict(node=owner, generation=gen, support=atoms(profile.get("support"), MAX_CONTRACTS))
        # Another endpoint may not overwrite this endpoint's authoritative profile.
        if owner == self.node:
            if p != self.profile():
                return dict(status="self-authority-rejected")
            return dict(status="unchanged")
        old = self.state["catalog"].get(str(owner))
        if old and gen == old["generation"] and p != old:
            return dict(status="equivocation-rejected")
        if old is None or gen > old["generation"]:
            self.state["catalog"][str(owner)] = p
            self.persist()
            return dict(status="merged")
        return dict(status="unchanged")

    def use(self, origin: int, sequence: int, manifest: str) -> dict[str, Any]:
        key, error = self._key(origin, sequence)
        hold = self.state["slots"].get(key, {})
        if error or hold.get("status") != "held" or hold.get("manifest") != manifest:
            return dict(status="not-authorized")
        compatible = self.satisfies(hold, self.state["support"])
        # This is a benign marker workload, NOT a real Android API invocation.
        return dict(status="used" if compatible else "incompatible", node=self.node,
                    manifest=manifest, generation=self.state["generation"])

    def handle(self, req: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(req, dict):
            raise ValueError("object request required")
        op = req.get("op")
        schemas = {
            "read": {"op"},
            "close": {"op", "origin", "sequence"},
            "install": {"op", "support"},
            "merge": {"op", "profile"},
            "use": {"op", "origin", "sequence", "manifest"},
            "inspect": {"op"},
        }
        if op == "prepare":
            base = {"op", "origin", "sequence", "manifest", "requires"}
            if set(req) not in (base, base | {"options"}):
                raise ValueError("invalid prepare request schema")
            return self.prepare(req["origin"], req["sequence"], req["manifest"],
                                req["requires"], req.get("options"))
        if op not in schemas or set(req) != schemas[op]:
            raise ValueError("invalid operation schema")
        if op == "read":
            return dict(status="observed", observed=self.profile())
        if op == "close":
            return self.close(req["origin"], req["sequence"])
        if op == "install":
            return self.install(req["support"])
        if op == "merge":
            return self.merge(req["profile"])
        if op == "use":
            return self.use(req["origin"], req["sequence"], req["manifest"])
        if op == "inspect":
            return dict(status="state", state=json.loads(canonical(self.state)))
        raise AssertionError("validated operation was not dispatched")


def minimum_obstruction(branches: list[set[tuple[int, str]]],
                        available: set[tuple[int, str]]) -> list[tuple[int, str]] | None:
    """Exact minimum-cardinality false-atom cover for a frozen observed vector.

    None means some branch is compatible. An empty branch is compatible. Empty
    branch families are invalid (a malformed manifest is not a compatibility
    rejection). Cost is O(m*2**b*b) with explicit b <= 8; it is not polynomial in b.
    """
    if not 1 <= len(branches) <= MAX_BRANCHES:
        raise ValueError("branch bound")
    bad = [branch - available for branch in branches]
    if any(not s for s in bad):
        return None
    candidates = sorted(set().union(*bad))
    coverage = [(a, sum(1 << i for i, b in enumerate(bad) if a in b)) for a in candidates]
    target = (1 << len(branches)) - 1
    dp: dict[int, tuple[tuple[int, str], ...]] = {0: ()}
    for mask in range(target + 1):
        if mask not in dp:
            continue
        for a, cover in coverage:
            next_mask = mask | cover
            if next_mask == mask:
                continue
            answer = tuple(sorted(dp[mask] + (a,)))
            old = dp.get(next_mask)
            if old is None or (len(answer), answer) < (len(old), old):
                dp[next_mask] = answer
    return list(dp[target])
