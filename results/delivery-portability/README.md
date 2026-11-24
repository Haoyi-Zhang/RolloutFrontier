# Delivery portability evidence

This directory preserves actual SQLite, TCP, and process-control observations
for artifact reproducibility. `../../docs/DELIVERY-PORTABILITY.md` gives the
portable commands for running the controls and a fresh short execution.

| Location | Retained observation |
| --- | --- |
| `environment/` | Dependency installation, isolated Python imports, and unchanged prior-delivery report |
| `path-controls/before/` | Pre-repair SQLite URI failure, expected failing regression, and its Python source tree |
| `path-controls/after/` | Repaired path controls and 199 archived read-only SQLite connections per interpreter mode |
| `execution/` | Complete fresh live and recovery TCP cohorts, their SQLite files, traces, and 30 captured source files |
| `execution-checks/` | Normal and optimized independent replay, plus ten rejected evidence alterations per mode |
| `interruption/before/` | Actual SIGINT observation with a surviving checker, stale report, and explicit audit cleanup |
| `interruption/direct-controls/` | Normal and optimized interruption and timeout controls immediately after the cleanup repair |
| `interruption/complete-controls/` | Fresh interruption and timeout observations from the integrated delivery wrapper in both modes |
| `controls/` | Complete wrapper JSON results, diagnostics, and the 150-file source tree bound to all four process-control reports |
| `commands/` | Original command records for the retained audit stages |

The fresh execution completed nine requests, stored 36 effects, and performed
18 conditional installations. Its raw elapsed-time fields remain execution
metadata. These observations do not enlarge the paper's performance sample.

`execution-current-bindings.json` compares every captured source file with the
current implementation at its recorded check time. `execution/source-check.json`
records the producer's own comparison before and after execution. The initial
direct interruption controls have their original source identities in each
report; later wrapper checks are separate captures.

Both integrated wrapper invocations passed all four methods. Their source tree
was copied before the invocations and remained unchanged throughout both
modes. `controls/source-check.json` compares each process-control report with
that tree. `execution-current-bindings-at-finalization.json` also confirms that
all 30 source files of the earlier fresh TCP run still matched at finalization.

The pre-repair path and interruption observations are intentional negative
controls. Their nonzero exits and stale `RUNNING` report document the defects.
The successful controls are kept in separate directories. The unrelated failed
instrumentation attempt and private unfinished runs are not included.

All copied records are byte-for-byte unchanged. Absolute paths inside commands,
traces, reports, and interpreter records identify the original capture machine.
The package locations use portable names and are mapped in
`capture-inventory.json`; original strings have not been normalized. The saved
virtual environment is represented by its installation and import records,
without distributing its binaries.

The capture inventory covers the 552 copied records and source files. This
editorial index and the inventory document itself are outside that payload
inventory.
