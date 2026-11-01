# Historical application-effect evidence

The 24 lifecycle observations and 96 database snapshots in this directory belong
to the recorded study, not the currently repaired implementation. Neither raw
measurements nor the source IDs in `registration.json` or
`execution-provenance.json` were changed by the source-binding repair. No study
or timing campaign was rerun.

`tests.check_effect_drain` authenticates the executed driver from
`execution-source.py.gz`. For each other registered input it accepts the live
file only if its SHA-256 matches the recorded digest; otherwise it requires an
exact matching file under `source-preimage/`. Missing or mismatched historical
bytes remain errors. Preserved source files are read as data, never imported or
executed by this check.

The current `src/network.py` and `src/effect_ledger.py` copy caller-owned mutable
inputs before waiting on lifecycle locks. Keep those fixes. Their measured
preimages are separate:

- `source-preimage/src/network.py` was already preserved and matches recorded
  SHA-256 `a6ecad280440e13688edf1607fb016754640b6e4a6f2ab3a9f63cc603dd41ecc`.
- `source-preimage/src/effect_ledger.py` is an exact byte copy recovered from
  a retained pre-edit source file. Its SHA-256 was
  verified against the unchanged registration before preservation and again
  afterward: `98e0dd72c63d50b7cfe42f4211c653f4f686ddc58b8582c1e552f5f9afc27940`.
  It was not reconstructed from the current implementation. Verification needs
  only the preserved bytes in this artifact.

The same recorded network digest also occurs in the retained durable-cost and
owner/origin persistence receipts. Those source IDs still describe their
historical execution, not a new execution of the current code. This repair does
not relabel or remeasure any cohort, including directories named `current`.

Run the data-only checker and missing/corrupt/current-source substitution
controls in both interpreter modes:

```sh
python -B -m tests.check_effect_drain
python -O -B -m tests.check_effect_drain
python -B -m unittest tests.effect_drain_bindings -v
python -O -B -m unittest tests.effect_drain_bindings -v
```

Current-code lifecycle conformance is tested separately by `tests.effect_drain`
and `tests.origin_serialization`; those regressions do not refresh these saved
measurements or prove that historical code included later mutation repairs.
