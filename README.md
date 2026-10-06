# Partition-safe API compatibility artifact

This directory is the standalone research artifact for the TPDS regular-paper
manuscript **Availability Frontiers for Partition-Safe API Rollouts**. It uses only
Python's standard library and local loopback communication. It does not require the
paper directory, a network download, private data, a GPU, an external service, or a
model API.

## Reproduce retained semantic results

From the artifact root:

```sh
python reproduce.py --out /tmp/partition-safe-results --check-reference results
```

The output directory must be new or empty and outside the repository and reference
tree; existing evidence is never replaced. The runner
executes 17 sequential bounded jobs, requires 23 semantic outputs (17 JSON, four CSV,
and two JSONL traces), and verifies 33 numeric manuscript bindings. Each child has a
120-second wall timeout, 90-second CPU soft limit, and 512 MiB address-space limit.
The five-owner process test can create five endpoint children in addition to the
runner and job, so the stated maximum is seven project processes.

Timing, RSS, temporary paths, and instantaneous RPC latency are remeasured and excluded
from semantic equality. Decisions, state, certificates, CSV rows, and complete logical
traces are compared. A successful comparison establishes consistency with the retained
sample, not theorem correctness or production performance.

## Repository map

- `src/envelope.py`: bounded exact frontier and greedy/fixed alternatives.
- `src/checker.py`: independent certificate reconstruction and validation.
- `src/controller.py`: persistent owner/origin state and lifecycle transitions.
- `src/network.py`: loopback protocol, managed channels, event trace, and validation.
- `tests/`: unit, oracle, generated-holdout, protocol, process, hardening, replay,
  cost, and source-boundary jobs.
- `results/`: retained semantic reference outputs.
- `proofs.md`: handwritten theorem and invariant arguments with scope limits.
- `claim_evidence_ledger.csv`: material claim to proof/test/result mapping.
- `claim_bindings.json` and `verify_claims.py`: typed numeric manuscript bindings.
- `reference_audit.csv`, `reference_sources.csv`: ordered scholarly source audit.
- `tpds_calibration.csv`: current TPDS journal structural sample.
- `external_resources.csv`: public data and workflow-source inventory.
- `data/`: exact curated Android declaration-history inputs.
- `docs/ANALYSIS-DESIGN.md`: generated-family and conditional-resampling design.
- `REPAIRS.md`: material implementation defects found and repaired.

## Exact finite synthesis

A manifest is a disjunction of complete placement alternatives. A local guard is a
positive disjunction of conjunctions. The producer enumerates safe independent local
products in a bounded language, removes dominated products, selects a maximum weighted
frontier member, and emits a certificate. The checker independently rebuilds local
libraries, safe products, nondominance, objective and tie-breaking, search counts,
and guard-corner safety.

The retained exact domains include:

- the 510 nonempty edge-encoded 3x3 relations with at most eight allowed cells and
  2,295 seeded instances, with the
  complete returned frontier compared record by record to a direct rectangle oracle;
- 9,369 independently enumerated safe boxes, 3,222 independently derived and 3,222
  returned frontier members, and 19,071 planner states in that exhaustive domain;
- a negative mutation that deletes a valid nonselected frontier member and is rejected;
- 480 sparse seeded 4x4/5x5 cases and 192 sparse seeded 3x3x3 cases checked against
  independent subset oracles;
- a high-pruning case with 260,876 raw local-choice combinations but 37 visited
  prefixes; and
- explicit failure for branch, local-library, corner, state, and frontier bounds.

A greedy counterexample returns mass 2 while the exact product has mass 7. A weighted
case selects objective value 80 where the unweighted choice has value 2. A zero-weight
regression ensures selection remains on the nondominated frontier. These are finite
algorithmic witnesses, not production workload claims.

Branch-local requirements are limited to 96 atoms. Profile-derived guard terms use
the 12,000-atom support encoding bound instead: projecting a profile onto eight
branch requirements can retain up to 768 relevant atoms. The same guard encoding
is used for synthesis, independent checking, durable acquisition, and recovery.
The portable boundary regressions run separately from the retained five-test smoke
denominator:

```sh
python -B -m unittest tests.profile_bounds -v
```

The complete positive-conjunction oracle and output-preservation checks are also
portable standard-library jobs:

```sh
python -B -m tests.positive_oracle
python -B -m unittest tests.output_paths -v
```

The positive oracle exhausts one/two-alternative manifests and compatible current
supports over two atoms at each of two owners, with a fixed three-atom weighted
extension. It checks arbitrary supports directly rather than reusing the producer's
corner test. It also checks the full nine-cell 3x3 relation, represented by one
empty-requirement alternative, at all nine current cells. Projection aggregates
three candidates into one weight-three profile per owner, preserving product mass
nine. Together with the edge-encoded cases, coverage is all 511 nonempty relations
and 2,304 current cells; the retained edge-encoded result counts are unchanged.
The `scientific-checks.yml` workflow runs these jobs and the retained
17-job POSIX suite on pushes to `main`; it has no manual-dispatch trigger. Its
scientific status requires the actual tests and semantic comparisons to succeed,
not merely syntax or file-presence checks.

## Minimum obstruction

The controller's frozen-vector explanation problem selects a smallest set of currently
false atoms that intersects every failed whole alternative. `tests/finite.py` compares
the implementation with direct subset enumeration for all 65,536 four-atom relations.
An unsafe seed is reported as unsatisfiable rather than assigned a false witness.
This is a restricted minimum hitting-set instance, not a new diagnosis theory.

## Protocol and fault evidence

`tests/modelcheck.py` uses an implementation-independent transition system. For one
attempt, two owners, one positive atom, and one nonwrapping sequence, the guarded model
has 296 reachable states and 1,388 transitions, no compatibility violation, and no
closed-to-held edge. Unguarded installation and timeout reclamation produce retained
five-step counterexamples. Cleanup is reachability under stated retry/delivery
premises, not a fairness theorem.

`tests/campaign.py` runs four relation families, six seeds, six policies, 24 proposals
per workload, and five owners: 144 policy cases and 3,456 proposals. Exact, greedy,
fixed-branch, and full-generation guards have no incompatible guarded snapshot in this
campaign. Local marginal and unguarded controls produce 55 and 484 incompatible
snapshots. The bridge family retains an unfavorable result for greedy: 30 installations
versus 34 for fixed branch and exact.

`tests/generalization.py` is a post-development generated holdout with six generators,
seeds 1000--1239, 1,440 cases, and 69,120 proposals. All frontiers match a direct
subset oracle and no guarded safety violation occurs. Exact installs 11,256 and greedy
10,854; exact wins 206 schedules, greedy wins 156, and 1,078 tie. A centralized
same-order authoritative reference installs 16,170 and exceeds exact in 978 cases.
The holdout is generated and post-development, not an external population sample.

`tests/journal_analysis.py` performs joint seed-cluster resampling over the six fixed
holdout families and retains all 24 denser bounded-synthesis calls. It also executes a
200-proposal witness for the theorem that maximum candidate-product mass does not have
a positive worst-case update-throughput ratio against another frozen safe product.

`tests/replay.py` imports neither planner nor controller and reconstructs the network
campaign's 40,992 request/reply exchanges and 4,494,882 canonical serialized
application bytes. The top-level reproduction runner independently performs a second
layer of assurance by comparing both `network-trace.jsonl` and
`observation-trace.jsonl` record by record against retained semantic references; the
observation trace is not claimed to have a separate state-machine replayer.
`tests/multiprocess.py` uses five same-host owner processes and five SQLite files,
records 89 RPCs, one origin reopen, and three SIGKILL events, and exercises restart,
partitioned retirement, delayed prepare, and cleanup. This is not a WAN, power-loss,
or independent-machine experiment.

`tests/hardening.py` rejects 12 certificate-structure mutations and 21 Boolean,
floating-point, or out-of-range substitutions across the selected plan, every frontier
member, search metadata, and nested certificate. It also rejects malformed persistent
stores and unknown-field RPCs, checks async input detachment and 64 serialized
two-client schedules, and verifies that a blocked three-contract update is atomic. A
two-owner fixed-branch interruption retains one unresolved manifest record, stops
fallback when close is unconfirmed, reopens successfully, retires a delayed hold after
healing, and rejects its later resurrection. These are implementation regressions, not
Byzantine or permanent-disk-loss evidence.

## Public input boundary

`data/android-class-introductions.csv` contains 24 curated class-introduction facts
spanning API 8--34 at 18 introduction levels. `data/android-history.csv` contains four
VibrationEffect factory facts. Tests perform 48 declaration-presence boundary checks and generate 96 reference sets.
One implementation performs 96 lower-bound computations and then two checks per result,
for 192 boundary/minimality assertions. The slice is not random or representative and
does not establish behavioral API compatibility.

The repository contains no complete AOSP API-history corpus, APK collection, SDK
binary, emulator, device, production trace, or private application data. Immutable
upstream identifiers retained in `data/SOURCE-NOTES.md` are provenance, not a claim
that the complete source was consumed.

## Reference and journal-positioning records

The paper has 76 unique cited scholarly sources and 85 citation occurrences.
`reference_audit.csv` and `reference_sources.csv` verify ordered inventory and state
each record's verification depth. They do not claim fresh full-text validation of all
76 sources. `literature.md` gives the novelty and applicability boundary.

`tpds_calibration.csv` contains 12 real TPDS articles at metadata/abstract-level
structural depth. It is used to check journal-native problem framing and evidence
organization, not to infer acceptance probability or to pad the manuscript
bibliography.

## Nonclaims

This artifact does not establish behavioral API equivalence, representative fleet
benefit, production deployment, WAN or cross-machine fault independence, Byzantine
or permanent-disk-loss tolerance, concurrent failover for one identity, exactly-once
application effects, safe timeout reclamation, unbounded/polynomial exact synthesis,
or machine-checked refinement. General proofs are handwritten; finite oracles and
models corroborate only their declared domains.
