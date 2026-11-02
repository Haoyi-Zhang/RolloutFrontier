# Complete same-host durable lifecycle costs

`measurements.json` contains48fresh-store trials and1152proposals across four
policies, two payload scales, matched/reverse batches and three repetitions.
`environment.json` records actual hardware, operating system, Python/SQLite and
source bytes captured before execution and checked unchanged after execution.
`stdout.txt` and `stderr.txt` retain completion and progress. Costs include
planning, checks, process startup, FULL/DELETE SQLite, TCP, reopen, use,
retirement, inspection and shutdown. Application frames include six acknowledged
management exchanges, separately from RPC frames; they are not packet capture.

The 44 entries in the original `environment.json` source inventory bind measured
bytes, not today's source tree. Currently 35 match live files. Seven exact
preimages are retained under `source-preimage/`: `src/checker.py` and
`tests/{frontier,full_path_costs,labelled_mss_bridge,optimizer_benchmark,receipt_snapshots,window_types}.py`.
The remaining `src/controller.py` and `src/network.py` preimages are already
preserved under `../effect-drain/source-preimage/` and match this inventory's own
hashes. Preimages are data only: do not import or execute them.

From the artifact root, `python -B lifecycle_table.py` checks every recorded
path/SHA-256 against live bytes or those preserved preimages before consuming
the measurements. `python -B -m unittest tests.lifecycle_table_regression -v`
checks missing/tampered bytes, current-source substitution and invalid inventory
paths using in-memory controls. Neither command reruns the measurement. Original
measurements, environment and source bindings are unchanged and are not resealed.

To create a separate new measurement using current code, not replay these exact
historical bytes, use a fresh path with
`python -B -m tests.full_path_costs --out ../lifecycle-measurements.json --repeats 3`.
Scientific checks and lifecycle actions execute explicitly, including in optimized
Python; malformed repeat counts are rejected before creating output directories.
The historical cohorts remain separate. All policies share the relation and
schedules; counts retain blocked changes and no-ops. Batch selection and greedy
install the same number in the matched case; maximum mass wins the reverse case.

This Windows11/Python3.12.14/SQLite3.53.1 sample uses an i7-12700KF12core/20logical
host. Scope is an owned same-host lifecycle, with retained SQLite files, not
WAN or power-loss behavior. CPU time and energy were not measured.
