# Three-service application rollout

The encoder, transformer and SQLite sink run as separate TCP owner processes.
Eighteen fixed-deployment and migrating trials cover client concurrency 1, 4
and 16, with three trials per condition and 96 requests per trial. Every
request retains its input, wire representations, output and owner receipts.
Separate mechanism controls cover draining, required authority and recovery
after committing an effect before a lost reply.

The complete traffic corpus contains 1,728 requests and 5,184 owner effects.
`summary.json` reports all trial samples, overlap and latency statistics;
`check-normal.json` and `check-optimized.json` contain the independent
reconstruction and altered-evidence controls. The raw runs, SQLite files,
contract probes, catalog plans and executed source bytes remain alongside them.

See `../../docs/APPLICATION-STUDY.md` for the exact workload, counting units,
latency interval and commands for fresh captures. These records use strict
UTF-8 input validation before pending-request binding. Earlier captures are
retained separately under `../retained-input-validation/application-rollout/`.
