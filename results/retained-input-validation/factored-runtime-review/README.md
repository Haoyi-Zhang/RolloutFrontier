# Independent runtime follow-on controls

These controls exercise the actual durable owner endpoint, SQLite journals,
and ProtoJSON handlers in process. The adapter forwards requests directly to
the production endpoint; it contains no admission, retirement, parsing, or
effect-deduplication implementation. Process and transport fault measurements
are recorded separately by the factored execution campaign.

The suite checks four behavior groups:

| Group | Required behavior |
| --- | --- |
| Admission identity and recovery | Fully retired sessions may reuse a human-readable manifest, caller request ID, hop IDs, and business key with a different value. New durable admission sequences separate their effects. A pending request preserves its original admissions across reopening and deduplicates an already committed source effect. |
| Successive rollouts | A later rollout may begin at an advanced registered profile while the physical deployment identity remains unchanged. A plan with a stale source is rejected without changing owner state. |
| Retained integer domains | Any retained narrow emitter rejects a wider value before recording a pending request or owner effect. An all-wide dataflow preserves the value exactly. Both paths leave the session drainable. |
| Concurrent exact retries | Concurrent calls for one bound input preserve the first durable complete output, including receipt metadata; later exact calls return that same result. Each physical effect is recorded once. |

For the pending-request control, the adapter omits one response after the
actual source effect has committed. This is a one-shot regression injection.
The live transport campaign supplies the separate interrupted-connection and
process-kill evidence. No duration from this suite is used as a performance
measurement.

`normal.json` and `optimized.json` retain the actual control outcomes and
interpreter metadata; `summary.json` records their agreement and the compact
control results. `sources/` contains the exact executed control file and
its implementation inputs. The collector rejects a source change during a
run and checks that a subsequent run matches the retained source snapshot.

From the artifact directory, with the recorded protobuf dependency installed:

```bash
python -B -m tests.factored_followon_regression --out results/factored-runtime-review-recomputed/normal.json
python -O -B -m tests.factored_followon_regression --out results/factored-runtime-review-recomputed/optimized.json
```

Use new output files. The tests use explicit checks rather than removable
`assert` statements, and the normal and optimized runs must agree on all
control outcomes.
