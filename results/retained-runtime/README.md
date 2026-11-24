# Retained runtime observations

These complete observations precede the session birth-identity correction.
Their executed source snapshots and original reports remain unchanged. They
are not used for the current runtime latency table or presented as measurements
of the corrected implementation. Current runtime observations are in the
sibling `factored-runtime/` directory. Current isolation and cancellation
controls are in `session-identity/`.

The old runtime could resume a genuine pending journal, but an unrelated journal
with the same readable label could adopt its active authority. The current
runtime binds admissions to a persisted birth identity and the immutable
workflow, registry and codecs. Old active journals are not silently migrated.
The stored `retention.json` binds every preserved file.
