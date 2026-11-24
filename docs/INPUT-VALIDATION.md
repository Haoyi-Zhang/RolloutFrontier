# Request domains and durable binding

Both application entry points validate a request before storing its immutable
pending binding. The key must have the existing string type and length and must
encode strictly as UTF-8. Numeric values must fit every retained emitter's
business domain. Rejected input consumes neither a request identifier nor an
application effect; the caller may correct the input and reuse that identifier.

This order matters for retirement. A Python string can contain an isolated
surrogate even though a Protobuf string cannot. Persisting that input first
would create a request that the handler can never execute, leaving its guards
held on every retry. `schema_contracts.validate_payload` and
`application.semantic_record` now reject such keys before either request
journal is changed. They preserve valid scalar values, including supplementary
characters, without normalizing or replacing the caller's key.

## Actual execution evidence

`results/utf8-inputs/` contains normal and optimized Python captures. Each mode
runs 18 separate controls: all 14 programs of the four schema families and all
four programs of the transformed pipeline. Owners are real separate processes,
communication uses loopback TCP, and effects and requests use SQLite.

| Observation | Per interpreter mode | Both modes |
| --- | ---: | ---: |
| Program controls | 18 | 36 |
| Rejected inputs before binding | 162 | 324 |
| Completed valid requests | 144 | 288 |
| Durable owner effects | 320 | 640 |
| Owner kills and restarts | 18 | 36 |
| Owner audit rows | 468 | 936 |
| Remaining guards | 0 | 0 |

Every control retains the empty request/effect checkpoint after rejection.
Eight corrected inputs then reuse rejected request identifiers and complete.
The valid corpus includes NUL, the largest Unicode scalar, supplementary
characters, 128-character keys and the relevant integer limits. Original
Python code points are recorded for rejected keys because JSON decoding can
combine adjacent surrogate escapes.

The owner restart follows the successful requests. Reopening validates its
retained effects, and the session returns the identical cached result of a
completed request before retiring. This control creates no new effect after
the restart. The separate application and factored-runtime campaigns contain
the execution and uncertain-effect recovery workloads.

`tests/check_utf8_inputs.py` imports independent saved-data readers, never the
application or session implementation. It checks owner histories, request
bindings, semantic outputs, rejected checkpoints and final retirement. The
reported call-site exception and RPC-counter observations remain identified as
recorded outcomes. The checker rejects changed rejection claims, missing
requests and altered owner effects. `tests/check_utf8_campaign.py` binds the
two execution modes and verifies their identical summaries.

## Retained failure captures

`results/utf8-inputs/counterexamples/` preserves the two original failure
captures separately from the corrected controls. The schema session retained
one pending request and one owner hold after three encoding failures; the
pipeline retained one pending request and three holds after two encoding
failures. Both had zero effects, a closed admission gate, and recorded failed
retirement attempts before and after reopening the original journal.
`tests/check_input_counterexamples.py` uses only the standard library to bind
those observations to the saved request rows, owner audits, TCP replies and
retained authority. It checks historical consistency without executing old
code. The manifest lists every retained file; only the two changed source
preimages and the two historical driver scripts are included, not a complete
old source tree or standalone replay environment. These two failure captures
do not enter the corrected execution counts above. The original source edit is checked
against the first retained post-fix snapshots under
`results/retained-session-reliability/utf8-inputs/normal/sources/`.
Later implementation repairs do not alter that historical comparison. Fresh
current-source controls separately cover Python string objects, readable
SQLite identities, complete concurrent results and initialization recovery;
see [SESSION-RELIABILITY.md](SESSION-RELIABILITY.md).

## Reproduction

From `artifact/`, check the saved records:

```sh
python -B -m tests.check_utf8_campaign --results results/utf8-inputs --corruption-controls
python -O -B -m tests.check_utf8_campaign --results results/utf8-inputs --corruption-controls
```

Run fresh controls into new directories:

```sh
python -B -m tests.utf8_input_regression --output /tmp/rollout-inputs/normal
python -O -B -m tests.utf8_input_regression --output /tmp/rollout-inputs/optimized
python -B -m tests.check_utf8_inputs /tmp/rollout-inputs/normal --self-test
python -O -B -m tests.check_utf8_inputs /tmp/rollout-inputs/optimized --self-test
```

Earlier captures and their executed source bytes are retained under
`results/retained-input-validation/`. The current application and schema
directories contain fresh captures of the corrected code. Existing journals
containing invalid pending input are rejected on reopening; the implementation
does not silently erase their durable request binding or release its authority.
