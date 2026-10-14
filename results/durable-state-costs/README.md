# Complete same-host durable lifecycle costs

`measurements.json` contains48fresh-store trials and1152proposals across four
policies, two payload scales, matched/reverse batches and three repetitions.
`environment.json` records actual hardware, operating system, Python/SQLite and
source bytes captured before execution and checked unchanged after execution.
`stdout.txt` and `stderr.txt` retain completion and progress. Costs include
planning, checks, process startup, FULL/DELETE SQLite, TCP, reopen, use,
retirement, inspection and shutdown. Application frames include six acknowledged
management exchanges, separately from RPC frames; they are not packet capture.

Regenerate to a fresh path with
`python -B -m tests.full_path_costs --out ../lifecycle-measurements.json --repeats 3`.
Scientific checks and lifecycle actions execute explicitly, including in optimized
Python; malformed repeat counts are rejected before creating output directories.
The historical cohorts remain separate. All policies share the relation and
schedules; counts retain blocked changes and no-ops. Batch selection and greedy
install the same number in the matched case; maximum mass wins the reverse case.

This Windows11/Python3.12.14/SQLite3.53.1 sample uses an i7-12700KF12core/20logical
host. Scope is an owned same-host lifecycle, with retained SQLite files, not
WAN or power-loss behavior. CPU time and energy were not measured.
