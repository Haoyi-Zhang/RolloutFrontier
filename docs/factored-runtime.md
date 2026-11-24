# Factored physical execution

The factored runtime executes one checked global interval guard at each physical
owner. Every logical factor incident to that owner refers to the same support
profile, generation counter, and SQLite authority. A deployment with 32 owners
therefore uses 32 owner authorities; it does not create separate owner copies or
separate reservation stores for its edge factors.

## Physical identity and admission

Each owner process hosts the unchanged `Endpoint` in its local one-node namespace.
Its transport envelope binds that local node to a named deployment, physical
owner, executable schema family, complete registered catalog, bootstrap profile,
window, and policy. All replies carry this identity, including reads, prepare
receipts, already-completed effect replies, and conditional-install results. The
transport compares the complete identity with its immutable registry before it
returns a reply to either coordinator. A restart may use a new TCP port without
changing that identity.

The registry's bootstrap profile describes owner initialization. A later job may
start at any member of the same registered catalog. Before each phase admission,
the coordinator reads every owner and checks that the observed supports equal the
planned source. Each actual installation then compares both the source support
and its generation at the owner's serialization point.

The factored planner verifies each small factor against the projections of the
same global owner guards. Its runtime witness checker independently rechecks
factor corners, local paths, directed edges, phase continuity, and installation
accounting. A guard contains the positive minimal profiles needed for the owner's
entire interval, projected onto the union of atoms used by its incident factors.
It is not a product of independently selected factor reservations.

## Durable global rollout

The global job journal follows these stages:

1. Acquire the next phase's local guard at every owner, using the private rollout
   origin selected by phase parity. Each original one-owner `Client` retains its
   own durable intent and certificate. An interrupted partial acquisition leaves
   the preceding phase protected.
2. Record the all-owner certificate set in the global job journal. Only then
   retire the preceding phase. An unconfirmed close leaves the coordinator in
   the retirement stage with the new phase admitted at every owner.
3. Perform the planned conditional installations. A lost reply is reconciled
   against the owner's support and generation; it receives one reconciliation
   credit rather than a second acknowledged-install credit.
4. At the requested endpoint, collect all support/generation pairs twice and
   require matching collections. Retire the final rollout guards and verify the
   target again before reporting completion.

Each phase admission identity binds the readable job manifest, the complete
checked plan, and the phase index. An active guard from another plan cannot be
adopted merely by reusing the same readable manifest and local guard shape.

The deployment keeps stable origin allocators in `rollout-origins` and
`application-origins`. These allocators survive a completed job or session, so a
later admission cannot reuse a sequence below an owner's durable retirement
floor. The global journal's active certificate pointers must match the complete
certificates in those local origin journals.

Run one active writer for each job journal and reserve rollout origins zero and
one for that job. Stop the former process before reopening its journal. The
prototype does not implement distributed leader election or writer fencing.

## Actual dataflow handlers

`schema_runtime.py` uses the descriptor programs and actual ProtoJSON encoders
and parsers in `schema_contracts.py`. Every request performs serialization at its
source, parsing and serialization at intermediate owners, and parsing of every
incoming branch at a join. A cycle is a finite declared traversal with distinct
hop IDs when it revisits a physical owner. A join records one durable effect after
checking all of its declared inputs.

An application session fixes every owner's emitted wire class and retains the
union of that owner's emitter and parser obligations under origin two. One
session can run concurrent logical requests and concurrent fan-out branches. Run
one admitted application session per deployment at a time; later sessions reuse
the durable origin allocator after the preceding session has drained.

Each session commits a fresh UUID birth identity before any owner preparation.
Its internal admission manifest binds that identity, readable label, registry,
window, workflow, schema family and retained codecs. The original journal can
recover its exact admissions; an unrelated journal cannot adopt them by reusing
the same label and obligation shapes. This includes a journal initialized before
the active session began. The [session identity guide](session-identity.md)
describes the reproduced failure, correction and executable controls.

The enum-alias and field-key handlers preserve the complete semantic record. The
field-addition handler preserves `key` and `value`, accepts only the declared
empty or `migrated-δ` metadata values, and normalizes that metadata to its current
producer contract. A join may therefore reconcile old and extended metadata
while requiring equal keys and numeric values. The integer handler preserves the
numeric value. Its session request domain is the intersection of every retained
emitter's numeric domain: if any emitter remains narrow, inputs must fit int32;
an all-wide session accepts the declared int64 boundary corpus. A parser's wider
acceptance alone does not widen a forwarding producer's input domain.

The session snapshots a caller's input before its first await and records that
input before any application RPC. Every physical effect is keyed by origin,
nonreused admission sequence, manifest, and request/hop ID inside the immutable
owner database. Exact retries retain this key across restarts. A later admission
may reuse a readable manifest and a local request ID without colliding with an
earlier effect. Concurrent exact retries return the first durably completed
logical result, including its receipt metadata.

Closing a session first closes its durable admission gate to new request IDs.
Unconfirmed requests keep all owner obligations and remain eligible for exact
retry. No application hold is retired while a request is pending or a local
request task remains active. The completed output is committed before retirement.
After retirement the session keeps historical admission certificates for effect
identity reconstruction and clears its active certificate set.

## Execution environment and fault controls

The execution harness creates separate owner operating-system processes and one
owned TCP relay process on a single host. Each owner has its own TCP listener and
SQLite database. The relay opens real upstream sockets, forwards encoded
requests, and records socket acceptance, forwarding, closure, and reconnection.
This is a single-host process deployment. It does not measure cross-host latency
or failures of independent physical machines.

A controlled TCP interruption closes the selected owner's relay sockets while
the owner process remains alive. The control records that process's PID and
liveness before and after restoration. A lost-reply control forwards the request,
receives the committed owner reply, records it, then closes the caller's socket
without forwarding the reply. Coordinator and owner crash controls use actual
`SIGKILL`, followed by a fresh process and durable reopen.

The loopback transport assumes trusted participants and fail-stop processes.
Its identity checks protect against wrong routing and mismatched registrations;
they are not cryptographic authentication against a malicious transport peer.

## Evidence and reproduction

The final evidence runner is `tests/factored_execution.py`. It stores graph and
plan definitions, descriptor probes, request inputs and outputs, local and global
journals, physical owner databases, process events, and transport/relay traces.
The large cohorts are a 32-owner enum cycle and a 32-owner field-key fan-out/join.
Smaller field-addition and integer-widening dataflows exercise their actual
handlers. Fault controls are stored in a separate cohort.

The retained campaign contains nine cohorts and records 185 completed logical
requests, 4,884 durable effects, and 605 conditional installations. Each of the
three repetitions of each 32-owner workload completes in three phases and 96
installations. The enum cycle has 32 compatibility factors and a declared
33-hop request traversal. The field-key graph has 87 factors and 32 request hops,
with every join parsing its three upstream branch values. Each large repetition
records 24 requests: four with retained old contracts, four with retained current
contracts, and 16 at the final target. The five-owner addition and widening
controls each record 20 requests and ten installations in two phases. The
separate recovery cohort records one recovered logical request and four unique
physical effects.

The counts in `parser_calls` concern dataflow input wires associated with durable
effects. Initialization probes, recovery-time result revalidation, and the
independent checker's own parser calls are outside that count. The complete
campaign records 8,811 such dataflow input parses.

The explicit application pauses in the overlap probes create retained work
while the rollout attempts compatible and incompatible replacements. Their
durations are excluded from steady-target request latency summaries. Steady
request measurements include the actual parser, serializer, SQLite commits,
loopback relay, and durable audit writes. Startup and failure-control runs are
excluded. These measurements describe this fully audited harness.

`tests/check_factored_execution.py` imports none of the production planner,
controller, transport, session, or application modules. It replays owner hold and
generation transitions, verifies global guard intervals against transport events,
reconstructs per-hop effect identities from retained admissions, and executes the
saved protobuf descriptors to check each wire and semantic output. It checks
every finite traversal and fan-out/join dependency against the durable request
ledger and requires exact final target, effect-count, and cleanup agreement.

Run the focused real-process controls with:

```bash
python -B -m unittest tests.test_factored_runtime -v
```

Run a fresh final evidence campaign in an empty directory with:

```bash
python -B -m tests.factored_execution --output results/factored-runtime-reproduction
```

The project environment must provide the protobuf dependency declared by the
artifact's dependency setup. An independent checker invocation for one retained
cohort is:

```bash
python -B -m tests.check_factored_execution results/factored-runtime/enum-alias-cycle/trial-01
```

The normal and optimized aggregate replays are retained as `check-normal.json`
and `check-optimized.json`. Both agree on all nine cohorts, bind reported target
collections to the actual final owner generations, and match all 30 captured
source files. `checker-controls.json` records ten rejected alterations of the
evidence, including owner substitution, a changed semantic result, a missing
hop, a missing phase receipt, changed generation/admission bindings, and changed
session birth, label or workflow bindings. The recovery cohort additionally
rejects fresh and previously initialized unrelated journals twice each while
preserving the original pending input and all owner holds.

The corrected implementation was used to recapture every current physical
cohort. Earlier observations and their executed sources remain unchanged in
`results/retained-runtime/` and `results/retained-input-validation/factored-runtime/`;
their timings are not mixed into the current table.

Reconstruct the per-trial latency denominators and summaries from the raw
request records with:

```bash
python -B -m tests.summarize_factored_execution results/factored-runtime --output results/factored-runtime/statistics.json
```
