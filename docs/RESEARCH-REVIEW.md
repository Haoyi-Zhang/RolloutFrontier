# Research and runtime review

This record connects the five research questions to the paper's mechanisms,
comparisons and executable evidence. It also records the issues found during
review, the changes made and the remaining delivery checks. Evidence paths are
relative to `artifact/`; manuscript paths beginning `../paper/` refer to the
adjacent paper directory.

This review covers the complete planning comparisons, alternative-reader
contracts, durable request behavior, and reproduction entry points. The current
scientific campaigns have independent saved-data checks. Archive verification
and compiled-document review are recorded in the delivery acceptance section;
earlier reports continue to describe their original captured inputs.

## The five research questions

### 1. Does the problem occur in executable systems?

Kubernetes publishes coupled component-version rules, and ProtoJSON documents
parser and serializer changes that require coordinated deployment. The artifact
executes four concrete ProtoJSON migrations: enum renaming, JSON field-key
renaming, field addition and integer widening. Their probes retain 74 wire
strings and 262 parser calls, including 49 expected rejections. Successful
parses must recover the exact registered semantic payload. The application
experiments activate these descriptor programs during physical handler changes.

The heterogeneous study tests a further source of ordering difficulty: the same
local release rank can represent different actions at different services. Eight
channel catalogs use 20 reader-descriptor configurations. Their 100 emitted-wire
records produce 280 parser
observations: 180 accepted values and 100 rejections of unprepared fields.
Fourteen additional before/after event witnesses use 28 parser calls to show
that each preparation or activation changes executable behavior. These measured
contracts yield the rule `emitted fields ⊆ prepared fields`. Reusing a measured
channel in many event-order contexts does not count as another parser test.

Two separate TCP/SQLite executions also exposed a runtime defect. A Python
string containing an isolated surrogate passed request validation and became a
durable pending binding, but the registered Protobuf handler could not encode
it. The factored entry point retained one owner hold; the three-owner pipeline
retained three. Neither could finish retirement after reopening its original
journal. These are observed failures of request admission and recovery, separate
from the planner's finite-domain examples.

Published compatibility requirements and executable parser failures establish
the problem. The complete inventories characterize the declared topologies and
release orders; deployment traces would establish their operational frequency.
The version-policy cohort exercises the declared Kubernetes rules, while the
application cohorts supply direct handler and request evidence.

Evidence: `results/schema-census/probes.json`,
`results/heterogeneous-schema/channel-observations.json`,
`results/heterogeneous-schema/probe-summary.json`, `results/factored-runtime/`,
and `results/utf8-inputs/counterexamples/`. The primary specifications are the
[ProtoJSON format](https://protobuf.dev/programming-guides/json/) and
[Kubernetes version-skew policy](https://kubernetes.io/releases/version-skew-policy/).

### 2. What remains to be solved after existing methods?

Local warranties, treaties and segmented execution already protect global
conditions through local obligations and repeated coordination. Safe update
synthesis also has exact optimization results. The paper now compares the
closest objectives and assumptions directly:

| Prior result | Established guarantee | Relation to this paper |
| --- | --- | --- |
| [NetStack](https://icaps22.icaps-conference.org/workshops/DAPSPAC/papers/schmid2022netstack.pdf) | Minimum concurrent rounds safe for every within-round update order; each changing router moves once from its initial to final configuration | With binary one-change catalogs and the same configuration predicate, the batch objective coincides with the phase objective. This equivalence is inferred from the two definitions. |
| [OrderUpdate](https://www.cs.cornell.edu/~jnfoster/papers/optimal-updates.pdf) | Polynomial greedy minimum-round planning for single-flow per-packet consistency, with at most one change per switch | Its safety check uses the union of configurations between waits. The careful-sequence argument already establishes structural greedy optimality; no inclusion relation with the present max-closed class is assumed. |
| [AllSynth](https://vbn.aau.dk/ws/files/633322620/1-s2.0-S0167642323000746-main.pdf) | Symbolic representations of correct simple and repeated-router update sequences; optimization of the worst intermediate forwarding-path weight | Repeated updates and complete solution representations are established topics. Its cost objective differs from concurrent-round count. |
| [FlexPlan](https://www.usenix.org/system/files/nsdi23-qiu.pdf) | Safe program-snapshot synthesis using increasing sequence lengths and switch-memory constraints | Target-directed multi-step synthesis is already available; atomic program snapshots and all-order physical phases require separate semantic comparisons. |
| [Dlask's projection methods](https://doi.org/10.1007/s10479-024-05980-z) | Greatest feasible points and monotone decreasing projections for closed max-closed sets, including nonconvex sets; additional convexity assumptions for the stated intersection-convergence results | Nonconvexity alone does not distinguish this paper. The rollout endpoint must admit a contiguous physical interval product, and repeated endpoints must minimize the number of such phases. |

The remaining contribution is the precise connection among acceptance-frontier
preservation for bounded positive guards, directed physical installation paths,
greatest safe endpoints for local max-closed factors and durable phase authority.
The paper no longer assigns novelty to minimum safe rounds, repeated updates or
greedy optimization in a structured model by themselves. Source-specific reading
depth and supporting passages are recorded in
`docs/nearest-prior-source-review.json` and `docs/claim-source-audit.csv`.

The empirical comparison also credits effective simpler methods. Across the
four homogeneous schema migrations, all six stage-priority paths together match
the optimum on all 61,938 reachable changes. The fixed-owner portfolio needs an
extra phase on 64 changes, and one fixed stage order does so on 554. Complete
homogeneous migrations admit a specialized optimal ordering on every nonempty
graph: three phases for renaming and two for extensions.

The heterogeneous census exhausts 394,560 release-order contexts. Of these,
122,120 are reachable and 272,440 have no complete migration. Every context is
checked by independent event algorithms; 48,980 also have captured RolloutFrontier
planner results. This latter denominator consists of all 48,960 contexts in the
first three catalog families and 20 controls in the additional-field extension:
16 fixed, evenly spaced identifiers and four further first-outcome witnesses.

| Release-order catalog | Complete contexts | Reachable | Owner + stage portfolio gaps | Preparation-priority portfolio gaps |
| --- | ---: | ---: | ---: | ---: |
| Two services, two fields in each direction | 576 | 244 | 16 | 0 |
| Bidirectional three-service path | 34,560 | 10,980 | 1,760 | 0 |
| Bidirectional triangle | 13,824 | 5,316 | 594 | 2 |
| Triangle with one additional field | 345,600 | 105,580 | 19,578 | 52 |

Each portfolio includes every owner tie order and an optimal partition of each
resulting path. The four families are owner priority, stage priority,
preparation-first priority and its rank-aware variant. Their combined portfolio
matches the optimum on all 122,120 reachable tasks. Individual rules fail on
particular release orders; the measured corpus does not defeat their union.

The same precedence contracts admit an exact weighted event-DAG schedule.
Consecutive local events have weight zero, and preparation-to-emission edges
have weight one. For a nonempty acyclic event graph, one plus its longest path
weight is the minimum phase count. This specialization extends to conjunctions
of cross-owner threshold implications, including the homogeneous renaming
constraints. It is credited as an exact baseline. The separate declared
threshold counterexample also belongs to this subclass: all four owner/stage
paths need three phases, while both exact algorithms give two through the
unique handoff `(2,4)`, with ten installations. It separates the priority
portfolio from exact planning, not the two exact algorithms.

The distinction between constraint classes is structural. For example, the
Boolean relation `A ⇒ (B ∨ C)` is max-closed but not min-closed: it accepts
`110` and `101` but rejects their minimum `100`. Such a disjunctive prerequisite
is outside conjunctions of binary threshold implications. This establishes a
broader recognized class. The new actual-codec study instantiates it in 56
release contexts, all max-closed and not min-closed. Every compatible ordered
pair is retained: 26,737 total pairs, including 8,595 forward pairs. Those
forward pairs comprise 1,205 no-ops, 7,368 reachable changes and 22 unreachable
goals. The other 18,142 pairs fail the direction requirement. Complete literal
phase graphs, the production planner, a polynomial OR-event fixed point and
an independent reader-choice graph oracle agree everywhere. The 10 wire
records, 20 matrix parser calls and two event-witness parser calls are separate
from the planning denominator.

Two fresh three-owner deployments execute each complete-record reader choice.
A pending request retains its selected reader and rejects a recipient change;
the selected reader's legacy-program regression is blocked while the unused
reader can prepare. Actual owner termination and restart precede exact retry.
Across the two deployments, two requests create four durable effects. After
they drain, two final guarded global installations reach the joint target.
Every request and hold is cleared at the end. The exact specialized baseline
ties the planner; the evidence demonstrates an executable non-min-closed
contract rather than a speed or phase-count advantage over that baseline.
See `results/alternate-readers/`, `docs/ALTERNATE-READERS.md` and
`../paper/alternate-readers-supplement.tex`.

Evidence: `results/schema-census/`, `results/schema-path-analysis/`,
`results/heterogeneous-schema/`, `results/priority-counterexample/`,
`docs/HETEROGENEOUS-RELEASES.md` and the corresponding supplemental proofs.

### 3. Why does the method work?

For general directed catalogs, acceptance dominance preserves every admitted
local path and cannot increase its minimum installation count. Complete frontier
search retains every reachable phase endpoint. Replacing each admissible phase
by a dominating frontier member therefore preserves the phase-first optimum,
including its installation tie-break. Physical versions remain distinct when
their compatibility projections agree. The two counterexamples in the paper
explain why furthest endpoints and shortest installation paths cannot replace
this search in general.

For directed chains, the recognizer checks each factor for closure under
componentwise maximum. Contiguous compatible single-owner prefixes combine into
a safe interval box. Every competing safe phase is bounded by the same prefix
limits, so the computed endpoint is greatest. Its monotonicity makes successive
endpoints dominate every competing phase plan. Chain distances fix the
installation count. Shared owners use one physical state and one compiled
local admission; factor checks avoid expanding a global Cartesian catalog.

The runtime preserves the meaning of a planned phase during execution. It
acquires the next protection while the preceding phase is live, persists the
new role and certificate, and then retires the old authority. Conditional
installations check the observed support and generation at the guarded owner
transition. Two matching full collections of nonwrapping generations and
supports establish that the reported target existed jointly. Persisted session
birth identities keep an unrelated journal from adopting pending work through
a reused readable label.

Request-domain validation is part of this execution argument. Both public
application entry points now check strict UTF-8 encodability and the relevant
numeric emitter domains before creating an immutable pending binding. Rejected
inputs consume neither an effect nor a request identity. A corrected request
can reuse that identity, complete normally and release its protection.

Evidence: the frontier and greatest-endpoint theorems in `../paper/main.tex`
and `../paper/structured-planning.tex`; `src/factored_planner.py`,
`src/factored_runtime.py`, `src/factored_session.py`, `src/schema_contracts.py`
and `src/application.py`; `docs/FACTORED-PLANNING.md`,
`docs/DURABLE-ROLLOUT.md` and `docs/INPUT-VALIDATION.md`.

### 4. What determines applicability?

The general route has a fixed positive-guard language and explicit work limits.
Exceeding a work limit returns refusal; completed graph exhaustion establishes
unreachability. The factor route requires directed chains and locally max-closed
relations. Local max-closure is sufficient for the global conjunction, so a
failed recognition test does not settle general reachability. Factor arity and
the size of a returned witness affect the cost of using the structured route.

The objective minimizes phases and then installations. For identical
installations, fewer phases reduce the executor's admission and retirement
RPCs. Latency, downtime and weighted installation costs require their own
objectives and measurements. Specialized event scheduling is exact for the
conjunctive and disjunctive event classes established in the supplement. The
max-closed theorem supplies the common guarantee for every recognized factor
catalog, including those without either specialized event representation.

Runtime protection assumes truthful registered programs, guarded mutations,
durable storage and one active writer per identity. Progress requires eventual
communication and release of conflicting obligations. Every retained emitter's
input domain must be satisfied. Previously malformed pending journals are
rejected on reopening, with their durable bindings and obligations preserved.
Large-catalog planning and process execution are separate experiments; the
application campaign uses up to 32 independent owner processes on one host.
Deployment adapters must additionally express binary replacement, quorum
availability and node draining when those operations affect compatibility.

### 5. What proves or measures the result?

The evidence combines preservation and endpoint proofs, independent finite
oracles, complete catalog inventories, useful exact and heuristic comparisons,
recorded owner execution and semantic corruption controls. No-ops, unreachable
tasks, ties and the distinction between complete enumeration and a planner
subsample remain in the denominators.

| Evidence | Result or inventory | Verification source |
| --- | --- | --- |
| General directed planning | 65,792 queries over 3,304 contexts | Literal safe products, safe-edge reachability and replayed local paths; `results/goal-planning/` |
| Local factor recognition | 991 contexts: 519 recognized and 472 refused; 7,835 compatible ordered goals in recognized contexts | Full phase graphs and concrete missing-maximum witnesses; `results/factored-planning/` |
| Homogeneous schema contracts | 252 contexts and 186,174 queries: 6,522 no-ops, 61,938 reachable changes and 117,714 unreachable goals | Independent codec-derived matrices, path partitions and topology inventory; `results/schema-census/` and `results/schema-path-analysis/` |
| Heterogeneous release orders | 394,560 completely enumerated contexts; 48,980 additional planner-result checks; all 122,120 reachable tasks tied by the four-family union | Weighted-constraint relaxation, a separate serial event-phase recurrence, literal checks of retained witnesses and six corruption controls; `results/heterogeneous-schema/` |
| Alternative compatible readers | 56 max-closed/non-min-closed contexts, 8,595 forward pairs and 22 forward obstructions; four exact methods agree; two physical reader-choice deployments complete | Independent descriptor/JSON decoding, full phase graphs, event comparisons, owner replay and 22 corruption controls; `results/alternate-readers/` |
| Session reliability | 22 completed requests, 42 owner effects, 50 rejected input/identity/journal cases and 182 audit rows across both modes | Concurrent complete-output equality, empty-journal recovery, preserved malformed journals and five historical cases kept separate; `results/session-reliability/` |
| Delivery portability | Fresh dependency installation, actual special-path TCP execution, literal read-only SQLite paths and bounded verifier interruption controls | Two fresh execution cohorts give 9 requests, 36 effects and 18 installations; focused control suites pass in both modes; `results/delivery-portability/` |
| Combined owner/stage counterexample | 27 compatible rank pairs; four priority paths need three phases and the exact plan needs two, all with ten installations | Independent safe-phase graph, the RolloutFrontier witness and semantic corruption controls; `results/priority-counterexample/` |
| Input-domain failures before correction | Two separate TCP/SQLite observations, one per application entry point | Saved pending bindings, handler rejections, owner holds and failed retirement after reopening; `results/utf8-inputs/counterexamples/` |
| Input-domain controls after correction | 36 controls across two interpreter modes; 324 rejected inputs, 288 completed valid requests, 640 effects, 36 owner restarts, 936 audit rows and zero remaining holds | Independent saved-data readers, matching mode summaries and altered-evidence rejection; `results/utf8-inputs/` |
| Phase-boundary cost | 38 paired executions of 19 paths, with 129 installations per route; 129 phases become 39 and 3,234 owner RPCs become 1,386 | Identical installation paths, complete request replay and the derived RPC formula; `results/phase-granularity/` |
| Application execution and recovery | Handler activation, protected in-flight requests, committed-effect retry, session isolation and coherent completion | Current inventories and database observations in `results/application-rollout/`, `results/factored-runtime/`, `results/factored-runtime-review/` and `results/session-identity/` |
| Planning scale | Ten conditions through 1,024 owners and 4,096 factors; 50 fresh workers and 279 complete cohorts | Current captures, worker inventories, timing records and reconstructed witnesses in `results/factored-scale/`; seven corruption controls rejected in both checker modes |

The input-domain counts distinguish the two historical failures from the 36
corrected controls. Each interpreter mode runs the 14 programs from the four
schema families and the four programs of the transformed pipeline. Every
control saves an empty request/effect checkpoint after rejection. Eight valid
corrected inputs reuse rejected identifiers and complete. The corpus includes
NUL, supplementary characters, the largest Unicode scalar, 128-character keys
and the relevant integer limits. Original Python code points are retained for
rejected strings because JSON decoding can combine adjacent surrogate escapes.

The owner restart in each corrected control follows successful requests. The
reopened owner validates retained effects, and exact retry returns the identical
cached result before retirement. This creates no additional post-restart effect;
uncertain-effect recovery is exercised in the separate application campaigns.
The saved-data checker imports neither application nor session implementations.
It reconstructs histories, bindings, outputs and retirement from records, while
call-site exception and RPC-counter observations remain identified as recorded
outcomes.

Scale timing and process-memory values come from the refreshed worker records.
At 1,024 owners, ring and four-neighbor CPU medians are 0.682 and 2.433 seconds;
median peak RSS is 60.57 and 130.21 MiB. Timed work includes parsing, model
construction, recognition, plan and guard construction, and witness
serialization. CPU error bars use worker means and memory error bars use worker
peaks. All 20 zero-CPU deltas at the observable clock resolution remain in their
worker means. Earlier and fresh timing samples retain separate capture
inventories and are not pooled.

## Issue, change and verification record

| Issue found | Change and location | Verification and current disposition |
| --- | --- | --- |
| The novelty argument omitted closest exact update-synthesis results | Added NetStack, OrderUpdate and AllSynth; refined FlexPlan and Dlask comparisons in `../paper/main.tex` and the source ledgers | Claim-scoped primary-source passages are recorded; The refreshed reference audit confirms 47 entries, 47 unique cited keys and 56 citation occurrences, with no unknown or unused entries. |
| Homogeneous local ranks favored one natural stage rule | Added executable preparation/emission events and all local permutations in `tests/heterogeneous_schema_study.py` | All 394,560 contexts retained, including 272,440 unreachable tasks; 48,980 planner results have their exact selection denominator. |
| A stronger competing method was needed for precedence contracts | Added the weighted event-DAG optimum and independent recurrence/relaxation checks; compared four full priority families | The four-family union ties every reachable field-addition task. Specialized exact scheduling is credited; the separate algebraic counterexample supplies the broader owner/stage separation. |
| One linear topology and one path did not isolate path-order effects | Added all 63 nonempty three-owner graphs and all six owner and stage tie orders | Independent checks retain every source/target denominator, all 61,938 stage-portfolio ties, 64 fixed-owner gaps and 554 single-stage gaps; `results/schema-path-analysis/`. |
| Exact difference constraints did not capture measured alias contracts | Added local max-closure recognition, contiguous axis prefixes and shared-owner guard compilation in `src/factored_planner.py` | 991 finite contexts, 7,835 goals in recognized contexts and independent factor-corner/path checks of large witnesses. |
| Malformed strings could become immutable pending requests outside the handler domain | Added strict encodability validation before binding in `schema_contracts.validate_payload` and `application.semantic_record` | Two saved pre-correction failures; 36 corrected controls reject before binding, allow corrected identifier reuse and retire with no remaining holds. |
| A retained narrow forwarding emitter could never complete a wide numeric request | Validate the intersection of retained emitter domains before binding in `src/factored_session.py` | Narrow and mixed sessions reject without a pending row or effect; all-wide sessions preserve the value and drain. |
| Reused readable labels could alias prior effects or adopt active authority | Persist a birth identity before prepare, allocate durable admission identities and bind workflow, registry, window and codecs | Fresh and initialized same-label journals are rejected; genuine journal reopen and exact retry preserve the original effect identity; `results/session-identity/`. |
| Bootstrap identity constrained later rollout sources | Keep immutable registration while checking each job's registered live source in `src/factored_runtime.py` | Consecutive `0→1` and `1→2` jobs complete; an obsolete source is rejected without owner changes. |
| Caller mutation across an await or mixed extension branches could change request semantics | Snapshot request inputs and define the field-addition metadata join while preserving business keys and values | Focused runtime controls and independently replayed extension-handler inputs and outputs. |
| Concurrent retries could replace an already completed output's metadata | Make logical completion transactionally first-writer-wins in both `src/factored_session.py` and `src/application.py` | The actual three-process pipeline now joins the factored session in returning the first complete result across concurrent attempts and reopen; `results/session-reliability/`. |
| The application evidence covered only conjunctive threshold dependencies | Added whole-record alternative-reader contracts, a polynomial OR-event comparison and physical fixed-reader recovery | Every forward pair and both reader choices are checked; strong exact baseline ties are retained. |
| A readable session label could be admitted despite being unencodable as SQLite text | Validate raw text identities before durable session binding | Invalid built-in strings and custom Python string objects are rejected; valid Unicode and NUL identities complete and drain. |
| Overridable Python string methods could bypass semantic-key validation | Use the base string encoder on the actual string contents | Both public Python application entry points reject before any request binding or owner call; no Python subclass is claimed to travel over JSON. |
| A failed initialization left an empty journal that blocked corrected input | Distinguish legal empty initialization from a durable or damaged journal using read-only schema/state checks | Corrected initialization completes; open/retired offline reopen uses retained codecs; seven malformed forms preserve their bytes and existing authority. |
| Special path characters changed the SQLite URI and could remove read-only mode | Use encoded absolute file URIs in all affected readers | Actual special-path TCP execution succeeds; 60 read-only connections and 48 missing-file controls per mode detect wrong files and unwanted writes. |
| Interrupting verification left a child running and a stale report | Clean up the checker-owned process group, retain logs and atomically finish the report | Real SIGINT returns INCOMPLETE/130 with INTERRUPTED and NOT_RUN records; real timeout cleanup permits the next control to finish. |
| A phase label did not bind the complete checked plan | Bind admission to the complete plan and phase index in `src/factored_runtime.py` | Foreign-plan reuse is rejected while existing authority remains active; saved bindings are independently reconstructed. |
| Unconfirmed requests could outlive their protection | Keep request bindings and owner holds until durable completion and exact retry | Actual socket interruption, committed-reply loss and post-effect owner termination recover effects before retirement. |
| Paper numbers and scientific plots could drift from retained records | Generate values, tables and plots from explicit evidence bindings | Current source inventories, units, denominators and generated paper inputs passed their integration checks. Independent verification from the final archive is recorded in the acceptance section below. |

The two historical input failures retain their individual `observations.json`,
SQLite and trace files under `results/utf8-inputs/counterexamples/`. The factored
case records three rejected handler attempts, zero effects and one retained
hold; the pipeline case records two rejected attempts, zero effects and three
holds. Both record failed retirement before and after reopening. The accompanying
historical drivers and changed-source preimages document the observations;
they are not represented as a complete standalone historical environment.

Earlier execution captures and their source evidence remain in
`results/retained-input-validation/`, `results/retained-session-reliability/`
and `results/retained-runtime/`, with their
own retention inventories. Their acceptance reports describe those earlier
inputs. The current captures have their own source bindings; the final archive
acceptance below is separate from these earlier reports.

## Manuscript argument

The manuscript follows the rollout problem from coupled contracts through safe
phase planning to durable execution. The application argument progresses from
fixed schema dependencies to different local release orders and a choice of
compatible readers. Exact specialized baselines remain visible alongside the
general theorems. Complete response identity, initialization and file-path
controls support the executable artifact without replacing the paper's central
research argument with a development report.

The publication uses the journal template, an explicit problem/mechanism/proof/
evaluation structure, and code-generated scientific figures with the same
fonts and visual vocabulary. Reference claims remain linked to the passages
actually inspected. Figure numbering, printed sizes, prose tails and final PDF
appearance are checked from the compiled documents.

## Final delivery acceptance

The candidate ZIP was extracted into a directory whose name contains a space.
All 32 registered evidence and delivery-control tasks passed in both normal and
optimized Python: **64 passed, zero failed and zero omitted**. The checks ran
against that exact extraction. All **17,979 candidate files** remained unchanged
during verification, including the complete verified code inventory. The report
and individual checker logs are retained with the delivery acceptance.

The publication and citation checks ran from the same extracted project.
The combined command in its paper README passed all **15 publication,
citation-inventory and lifecycle-consumer regressions**, without skips.
The reference audit confirms 47 bibliography entries, 47 unique cited keys and
56 citation occurrences, with no unknown or unused entries. Claim support
uses the recorded reading depth and inspected source passages; bibliographic
consistency does not substitute for reading the underlying source.

The final documents contain **12 main-paper pages, 32 supplement pages,
10 figure-atlas pages and one identifying title page**. All **55 pages** have
recorded visual coverage. Clean-build renders were compared pixel for pixel
with the inspected final pages. All ten active figures were inspected in color
and grayscale at their measured manuscript size, and every figure's rendering
changed from the preceding delivery. The ordinary-prose matcher locates
**310 passages**, with no short-tail candidates or unmatched passages; manual
inspection separately covers displayed mathematics and complete page layouts.
The supplement's final orphan paragraph was resolved by refining prose while
preserving its numerical values, control conditions and verification methods.

Each figure has multiple reviewed design candidates. The overview has four
image-generation candidates and four composition candidates. Its selected
qualitative software vignette is retained at its native 1,774-by-887 pixels,
equivalent to approximately **1,086 dpi** at its placed width. Exact labels,
branches, guard products and execution order are separately typeset vector
objects. The other five mechanism figures and four Python statistical figures
also retain exact vector PDF and SVG output. Every active figure additionally
has **600 dpi color and grayscale PNG exports**, each 4,300 pixels wide.

The revision uses the manuscript's Times source faces, consistent mathematical
type, shared legends and explicit object relationships. Separate product masks
replace crossing counterexample contours; aligned request rows replace dense
vertical bar groups; contract and policy matrices expose their actual cells and
denominators. Durable execution shows old-guard retirement before conditional
installations. The minimum ordinary figure-label size is approximately
10.46 points in the manuscript. Independent semantic review and final page inspection cover
the selected diagrams, and all 50 atlas inputs match their current sources.

Every one of the **17,523 prior result and acceptance files** remains
byte-identical, including the earlier delivery review now retained separately.
The implementation, experiment programs and input catalogs also match the
preceding accepted delivery. Every statistical chart preserves its original
values, units, cohort denominators and uncertainty ranges. Fresh scientific
executions, saved-data reconstruction and disposable filesystem/process controls
retain separate records and counting units. This graphical revision adds no
fresh performance measurement.

The delivery records include the complete verification report, publication
checks, the 15-test log, final visual acceptance, figure-integrity review,
verified candidate inventory and prior-evidence retention mapping. Final
packaging compares the scientific payload with this verified candidate,
checks every extracted file and compares the standalone PDFs with their archive
counterparts. These records connect each completed check to the delivered files.
