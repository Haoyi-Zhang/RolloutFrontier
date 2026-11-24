# Session birth identity and recovery

Six groups in each Python execution mode use the actual Endpoint, SQLite and
ProtoJSON implementations. The normal and optimized directories retain every
owner database, origin journal, session journal, operation trace and captured
source. They cover new and previously initialized foreign journals, repeated
rejection, immutable workflow bindings, legitimate reuse after draining and
cancellation after committed prepare, effect and retirement operations.

`check-normal.json` and `check-optimized.json` independently reconstruct saved
journals, traces, effects and post-commit cut states. Both are identical. The
checker distinguishes these reconstructed facts from producer-recorded
constructor exceptions and cancellation propagation. It does not rerun faults.
Four evidence corruption types are rejected for both saved execution modes.

From the artifact directory:

```sh
python -B -m tests.check_session_identity --results results/session-identity --corruption-controls
python -O -B -m tests.check_session_identity --results results/session-identity --corruption-controls
```

Fresh execution uses a new directory:

```sh
python -B -m tests.session_identity_regression --out results/session-identity-reproduction
```

The separate current physical campaign records real socket and process-kill
controls, including repeated rejection of fresh and previously initialized
journals while a genuinely pending request still owns its application guards.
