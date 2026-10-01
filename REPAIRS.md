# Internal repair record

## R1 — zero-weight objective could select a dominated safe plan

**Severity:** P1 for claim consistency; no observed campaign safety violation.

**Affected claim:** the exact planner returns the complete nondominated frontier and
selects its deterministic optimum.

**Defect.** The planner correctly computed the nondominated frontier, but the final
objective comparison was applied to every safe guard representation. When candidate
weights include zero, a dominated plan can tie its dominating superset in both
weighted product mass and sum of local masses. The later term-count or lexical tie
rule could then select the dominated plan even though the returned frontier itself
was correct. This contradicted “select from the frontier.”

**Minimal regression.** One endpoint has current profile `a`, candidate profiles
`a,b`, and weights `[1,0]`. Both `{a}` and `{a,b}` have product mass 1 and local mass
1, but `{a,b}` strictly dominates `{a}`. The selected plan must be `{a,b}`.

**Repair.**

- `src/envelope.py` now restricts final objective selection to records whose accepted
  masks are in the computed nondominated frontier.
- `src/checker.py` independently computes the frontier mask set and evaluates the
  expected optimum only over that set.
- `tests/frontier.py:zero_weight_frontier_case` retains the minimal regression and
  checks both producer and independent certificate.
- `proofs.md` and the manuscript now state the objective domain explicitly.

**Validation.** The regression returns a one-member frontier accepting both profiles.
The original exhaustive 3×3 oracle still agrees for 510 relations and 2,295 seeds;
the added 4×4/5×5 stress oracle agrees on 480 seeded cases. The clean reproduction
includes `frontier.json` and reports semantic equality with the retained result.

## R2 — evidence and manuscript drift after adding new checks

**Severity:** P1 for reproducibility documentation; scientific outputs were present
but the manuscript and README still described the prior 8-job/12-output runner,
768 MiB process limit, and four-row-only public input.

**Repair.** The paper, supplement, README, proofs, research plan, evidence ledger,
source notes, resource accounting, and current state were synchronized to:

- 17 jobs and 23 semantic outputs, including five discoverable unit tests and the holdout/scaling products;
- 512 MiB per project process, at most seven project processes, and a 3.5 GiB
  theoretical aggregate address-space cap;
- the independent finite protocol model checker;
- the five-owner multiprocess failure test;
- 480 larger frontier stress cases; and
- 24 curated Android class facts plus the separate four-factory network slice.

**Boundary retained.** These repairs do not convert the curated declaration history
into a complete SDK corpus, the finite transition systems into general proofs, or the
same-host process test into WAN or power-loss evidence.

## R3 — reused output directories could retain stale untracked files

**Severity:** P2 reproducibility hygiene; retained semantic comparisons were not
affected.

**Defect.** The runner overwrote all expected outputs but allowed an existing output
directory to keep unrelated stale files. It also rejected only exact equality with
the repository/reference path, not an output nested inside them. This could confuse a
manual audit even though the then-current compared files were regenerated and checked.

**Repair.** `reproduce.py` now rejects outputs inside the repository or reference
directory, removes every known generated file before execution, refuses a generated
path that is not a regular file/symlink, verifies that all 23 required semantic
outputs exist, and records the generated-file inventory in `execution.json`.

## R4 — checker bound disagreed with producer pruning

**Severity:** P1 for independently checkable exactness; no campaign safety violation.

**Defect.** The producer bounded the number of visited depth-first prefix states and
could prune an unsafe prefix before enumerating its descendants. The independent
checker instead rejected whenever the raw product of per-endpoint guard-choice counts
exceeded 250,000. A valid highly pruned result could therefore be produced but not
checked under the nominally identical public bound.

**Minimal regression.** A five-endpoint, two-branch case has local guard counts
`[14,11,11,14,11]`: the raw product is 260,876, but incompatibility pruning leaves
only 37 visited prefix states. The producer returns an exact frontier while the old
checker returned false.

**Repair.** `src/checker.py` now performs its own bounded recursive prefix search.
The public `combination_bound` counts visited prefixes in both implementations;
unsafe prefixes and boxes beyond 4,096 corners are rejected by the same declared
language boundary. The checker still imports no producer or planner code.
`tests/frontier_stress.py` retains the 260,876-versus-37 regression.

## R5 — frontier and receipt certificates were under-validated

**Severity:** P1 for certificate integrity; runtime authorization still required live
origin and endpoint state.

**Defect.** The frontier checker verified the selected box's safety but did not compare
all reported frontier metadata. Duplicate frontier members, altered product/local
masses, accepted-profile lists, search counters, objective text, and parts of the
corner certificate could pass. The structural branch/envelope checker also accepted
a missing `observed_generation` and Python booleans in integer sequence fields.

**Repair.** The frontier checker now reconstructs and compares the entire canonical
frontier, selected plan, candidate domains, search counters, objective, scope, and
corner certificate. Branch and envelope receipts require exact integer types,
complete generation metadata, exact receipt cardinality, and canonical sequence
maps. A direct relation oracle now compares the complete frontier record by record for all
2,295 exhaustive 3x3 seed cases and rejects deletion of a valid nonselected member.
Eight frontier-output mutations, twelve strict certificate-schema mutations, and 21
Boolean, same-value floating-point, numeric-for-Boolean, or out-of-range substitutions
across selected, frontier, search, and nested certificate fields are retained as
negative regressions. Offline certificates remain structural evidence, not live use
authority.

## R6 — one TCP connection per RPC exhausted ephemeral ports on repeated runs

**Severity:** P1 for repeatable clean reproduction; logical results were unchanged.

**Defect.** The loopback emulator opened a new client TCP socket for every request.
One campaign contains 40,992 RPCs. Repeating the complete suite in the same host
namespace accumulated more than 21,000 `TIME_WAIT` sockets and could stall a later
observation job near the ephemeral-port limit.

**Repair.** The emulator now reuses one serialized persistent channel per target,
reconnects once after a stale transport, and closes all managed client/server streams
before endpoint restart or shutdown. The campaign opens 1,008 managed channels across
144 isolated cases instead of 40,992. Request/reply payloads, ordering, byte counts,
replay output, policy decisions, and incompatibility counts remain semantically
identical. The runner also emits per-job progress and writes `failure.txt` for timeout,
invalid JSON, missing output, or semantic-comparison failure.

## R7 — higher-dimensional and multi-origin coverage gaps

**Severity:** P2 evidence strengthening; no discovered contradiction.

**Gap.** The direct frontier oracle was two-dimensional, and directed recovery used
one origin even though endpoint floors are origin-indexed.

**Repair.** A direct ternary oracle now checks 192 seeded 3×3×3 instances from 96
sparse relations, enumerating 398 safe boxes and 233 frontier members with exact
agreement. A two-origin integration cut persists overlapping holds at one shared
endpoint, restarts that endpoint, loses one origin's close, verifies that both then
only the surviving origin block a conflicting installation, rejects a delayed prepare
for the retired origin, and advances the two closed floors independently.

## R8 — malformed durable row sets could be mistaken for a fresh store

**Severity:** P1 for fail-closed recovery; no retained run lost acknowledged state.

**Defect.** Startup previously queried only the canonical `id=1` row. If a `state`
table existed but that row had been moved or deleted while another row remained, the
endpoint or origin could interpret the store as empty and initialize new state. The
same path did not reject extra columns or extra singleton rows.

**Repair.** Endpoint and origin startup now validate the exact two-column SQLite
table shape, require either a truly empty table or exactly one text payload at
`id=1`, and then validate every persisted identity, policy, window, counter, catalog,
guard, attempt, and certificate binding before service. Eleven endpoint-store and
twelve origin-store mutations, including extra rows, missing canonical rows, shadow
columns, duplicate manifests, booleans in integer fields, and binding mismatches, are
retained in `tests/hardening.py`. All fail closed; valid reopen still succeeds.

## R9 — mutable caller objects could alter delayed requests or recorded traces

**Severity:** P1 for trace fidelity and asynchronous request semantics; retained
scientific traces were unchanged.

**Defect.** Supports, branch lists, and queued request dictionaries could remain
aliased to caller-owned mutable objects across an asynchronous wait. A later caller
mutation could therefore change the request ultimately sent or the request object
already stored in a logical trace.

**Repair.** Network construction, enqueue, RPC dispatch, and fixed-branch acquisition
now canonicalize and detach these values before yielding. Regressions mutate the
original support, immediate RPC request, and delayed queued request after submission
and verify that endpoint state and retained traces preserve the submitted value. A
separate atomicity case confirms that a three-contract change blocked by one live
guard leaves the complete support and generation unchanged. Sixty-four scheduled
two-client prepare/install races produce only the serialized allowed outcomes and no
invariant violation.

## R10 — the novelty boundary omitted classical maximal-product literature

**Severity:** P1 for contribution positioning; no implementation defect.

**Defect.** The earlier manuscript correctly acknowledged predicate-reservation work
but could still be read as naming a new combinatorial object. Binary safe products are
maximal bicliques/formal concepts, higher-arity closed products have prior mining
literature, and maximum edge biclique is NP-complete.

**Repair.** Four primary scholarly sources now delimit this prior art. The title and
claims retain “availability frontier” only as a rollout interpretation. The paper now
states that the combinatorial object and its worst-case hardness are classical; the
contribution is the API-rollout formulation, bounded checkable synthesis, durable
acquisition/retirement protocol, and negative evidence. The bibliography/source audit
now contains 71 ordered, cited entries.

## R11 — four hand-designed campaign families left an overfitting concern

**Severity:** P1 for empirical credibility; not a safety defect.

**Gap.** The original 144-case campaign used four transparent relation families that
were visible during implementation. It could not distinguish a generally useful
bounded solver from code tuned to those examples.

**Repair.** After freezing the core solver and checker, a separate holdout uses six
new generators and disjoint seeds 1000–1239. Across 1,440 cases and 69,120 scheduled
proposals, exact frontiers match an independent subset oracle and have no safety
violation. Exact installs 11,256 changes versus greedy 10,854, but greedy wins 156
individual schedules and a centralized same-order reference installs 16,170. These
unfavorable results are retained. The suite remains generated and is not described as
external, representative, or statistically independent deployment evidence.

## R12 — standard test discovery found no tests and synthesis scaling was implicit

**Severity:** P1 for ordinary artifact usability; scientific scripts already passed.

**Defect.** The repository exposed executable experiment modules but `unittest`
discovery found zero tests. Solver effort was also visible only indirectly through
oracle totals and corner-check timings.

**Repair.** Five discoverable standard-library smoke tests now cover exact
certification, marginal unsafety, greedy safety, bound rejection, and replay-floor
non-resurrection. The top-level runner executes them as a required job. A 130-case
2D/3D synthesis sweep records visited states, frontier size, and local timing and
checks explicit search/library rejection. The current runner executes 17 jobs and
compares 23 semantic outputs (17 JSON, four CSV, and two JSONL), including the
additional paired/objective-limit analysis.

## R13 — a two-pass clean LaTeX build could stop before references settled

**Severity:** P1 for release reproducibility; the delivered PDF itself was correct.

**Defect.** The prior script invoked LaTeX twice. From an archive with no auxiliary
files, the first pass creates citation and cross-reference state and the second pass
resolves it, but a timed validation interruption left only the first-pass PDF with
question-mark references. The script had no final diagnostic gate.

**Repair.** `paper/build.sh` now deletes auxiliary cross-reference state, audits the
71-entry source inventory, runs three bounded LaTeX passes, and fails if undefined
citations/references, overfull boxes, missing characters, or LaTeX errors remain. A
clean build settles on the same 16-page rendering on passes two and three.



## R14 — uncertain fixed-branch cleanup could create duplicate manifests

**Severity:** P1 for restart-safe retirement under packet loss.

**Defect.** After a fixed-branch prepare failed, acquisition persisted retirement but
ignored a failed close and continued to the next branch for the same manifest. A lost
prepare could later become a hold, while the second branch created another durable
record with the same manifest. Restart validation correctly rejected that duplicate,
so merely weakening validation or deleting the first record would have lost retirement
authority.

**Repair.** Fixed-branch fallback now stops whenever close is unconfirmed and retains
exactly one retiring attempt. The directed regression uses two owners initially
supporting `a`, window two, a blocked origin-to-owner-1 link, and same-manifest
alternatives `{0:a,1:a}` and `{0:a,1:b}`. It confirms one durable record, successful
reopen, retention while partitioned, retirement of an injected late hold after healing,
and rejection of a second delayed prepare by the advanced closed floor.


## Specification and result-presentation corrections

Finite candidate-domain product safety does not imply safety on every support set
accepted by a positive guard. The proof and journal manuscript now state the stronger
all-minimal-corner check separately. Guard-term/corner caps define the language;
input/library/search/result limits instead cause refusal. Generalized hardness is
not misattributed to a fixed-cap implementation. These are specification-precision
corrections; the existing controller and checker are unchanged for the journal analysis.

The journal analysis retains all denser search refusals, reports seed-cluster
variation conditional on the selected generators, and executes the arbitrary-T
schedule-limit construction at T=100. Numeric result bindings and generated figure
inputs prevent a changed retained sample from silently leaving obsolete paper values.
The README's planner-state typo is corrected to the actual 19,071 in frontier.json.
The cost prose explicitly identifies installation timing as in-memory, excluding
SQLite and RPC. The campaign uses six schedule seeds per family, not 24.
