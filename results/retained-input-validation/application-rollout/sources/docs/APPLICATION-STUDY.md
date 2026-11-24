# ProtoJSON application rollout

The application study upgrades a running encoder, transformer, and durable sink while they process requests over TCP. Each owner runs in a separate operating-system process. Its installed profile selects an actual Google Protocol Buffers descriptor and its JSON parser and serializer. A rollout installation changes that code selection through the existing guarded owner operation.

## Workload and migration

The workload is a connected three-stage pipeline. The encoder serializes a record; the transformer parses it, computes `amount = 3 * amount + 7`, and serializes the result; the sink parses the resulting record and commits it to SQLite. Every request has a stable identity and retains its complete input, intermediate wire representations, observed output, and owner application receipts.

The schema changes an enum name from `ACTIVE` to `ENABLED`, with both names representing value 1. The four programs follow the migration ordering documented in the [Protocol Buffers ProtoJSON guide](https://protobuf.dev/programming-guides/json/#json-wire-safe-changes): add an alias after the old name, update parsers, swap the alias order to change serialization, and remove the old name after old serialized data no longer needs to be parsed.

| Program | Names the parser accepts | Name the serializer emits |
| --- | --- | --- |
| `legacy` | `ACTIVE` | `ACTIVE` |
| `accepting` | `ACTIVE`, `ENABLED` | `ACTIVE` |
| `emitting` | `ACTIVE`, `ENABLED` | `ENABLED` |
| `current` | `ENABLED` | `ENABLED` |

The program descriptors are constructed independently in separate descriptor pools. `schema-probes.json` records eight actual parse attempts and the emitted name from each program. The intermediate programs have the same parser capabilities but a different serializer preference; both remain distinct physical installations. The declaration includes the full program identity, parser support, and serializer choice.

Compatibility concerns both pipeline links. The encoder's emitted name must be parsed by the transformer, and the transformer's emitted name must be parsed by the sink. Four positive alternatives express the two possible names on each link. Local installation graphs follow the four-program sequence. The retained planning cohort includes every ordered pair of the 36 compatible configurations, including no-ops and unreachable targets. The independent checker constructs every safe interval phase and a deterministic shortest safe installation path. It compares frontier plans with the exact phase graph and with the best segmentation of that path.

For the end-to-end migration, every owner changes programs three times. The goal planner returns three phases and nine installations. This is application-handler activation; the executable host process is the same Python service throughout an ordinary installation. Separate process kills test activation recovery from the durable profile.

## Request lifetime and the activation point

An application session acquires a fixed pair of wire contracts, one for each link, through an otherwise unused durable origin. The encoder retains its serializer choice, the transformer retains its input parser and output serializer, and the sink retains its input parser. Every alternative in an owner's application hold must imply these contracts. A broad rollout guard cannot serve as an application lease.

The owner handles protocol operations and application calls synchronously at the same event-loop serialization point. The endpoint support and application rows use the same SQLite connection. A successful guarded installation commits its registered program profile before acknowledgment. Application calls select their parser and serializer from that profile; there is no separately updated process-global active-program variable. A crash between the durable profile commit and its reply therefore reopens the committed program.

Each owner commits a request's identity, wire contract, input, output, program, and generation before replying. A repeated identity with the same input returns the retained result; changed input is rejected. This provides owner-local idempotence, not one transaction across the three owners. The application origin durably binds the end-to-end input and records the acknowledged sink result.

Retirement first closes a durable admission gate, waits for active coroutines, and checks for unresolved request identities. If any request remains unresolved, retirement reports pending and retains all owner holds. Exact retries remain allowed while draining, including after reopening the origin and session. A successful retry records the output before the holds are released. This prevents a lost sink reply from being mistaken for drained application work. The experiment retains the input needed to resume each request.

Input bounds ensure that the integer transform remains within the admitted semantic range. The traffic corpus includes both admissible boundary values, negative values, zero, positive values, and Unicode keys. ProtoJSON represents these integer fields as decimal strings; the independent oracle checks their exact values.

## Traffic design

The design fixes three client-concurrency levels, 1, 4, and 16, and three repetitions per condition. Each trial completes 96 requests. The two conditions are a fixed `legacy` deployment and the complete `legacy`-to-`current` rollout. Condition order alternates across repetitions. Both conditions use the same request corpus, actual owner processes, storage mode, application admissions, and durable audit instrumentation.

A batch shares one retained pair of wire contracts. Its requests run concurrently. At the end of the batch, the session drains and retires; the next batch obtains contracts from the then-current programs. A rollout runs concurrently with these batches and waits when an in-flight request still requires an earlier wire name. Per-RPC and per-request monotonic timestamps establish which requests overlap installation calls. The checker rejects a rollout trial with no observed overlap.

Request latency starts at the first application send and ends at the acknowledged sink result. It excludes batch admission and retirement. Each trial retains all 96 samples; the checker reports the median and nearest-rank 95th percentile. These are instrumented loopback observations with full SQLite synchronization and per-call audit writes enabled. They measure this executable integration and do not estimate multi-host service latency. No throughput or cross-host speedup is inferred from them.

## Mechanism and failure controls

Three separately recorded controls exercise the connection between authority, code, and application effects.

1. **Drain before removal.** Pause a request after encoding. Start retirement and attempt to remove the sink's old-name parser. The installation is blocked and new request identities are refused. Finish the original request, drain, and retire; removal then succeeds. A later request using the retired authority is rejected before an effect.
2. **Required authority.** Remove the transformer's application hold while its parser remains available. A real request reaches the encoder and is rejected at the transformer. A hold that does not retain the requested wire contract also fails. An unregistered support profile cannot be installed as a program.
3. **Commit before lost reply.** The sink kills its own OS process immediately after its SQLite effect commit and before the reply. The origin's retirement remains pending and retains the application authority. Reopen the origin, restart the sink, and retry the exact request. All owners return their existing results. A separate owner restart after changing the serializer confirms that the committed profile selects the reopened handler.

The authority-removal control deliberately disrupts a request and leaves its unresolved origin record for inspection. It is not counted among successful traffic trials. The drain control checks an isolated application lease; its final manual install is not an independently planned whole-pipeline rollout.

## Reproduction and checking

Install the dependency declared in `requirements-application.txt` into the Python environment used for the owner subprocesses. From the artifact directory:

```bash
python -B -m tests.test_application_rollout
python -O -B -m tests.test_application_rollout
python -B -m tests.application_rollout_study --out /path/to/new/application-results
python -B -m tests.check_application_rollout --results /path/to/new/application-results --corruption-controls
python -O -B -m tests.check_application_rollout --results /path/to/new/application-results --corruption-controls
```

The independent checker requires only the Python standard library. It does not import the handler, planner, or protocol implementation. It replays owner audits in their durable order, verifies guard implications and physical activation, reconstructs the complete planning comparison, checks every pipeline output against its input, and matches observed responses with actual retained SQLite rows. Semantic corruption controls alter a returned output, remove a durable effect, and remove an owner audit event; all must be rejected. The output directory retains original observations and input/source files, together with the dependency and runtime environment used for execution.
