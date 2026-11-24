# Durable session reliability

The saved controls connect session-level return values to SQLite request rows,
owner effects and TCP replies. Normal and optimized Python runs use the same
captured source files. Each run completes 11 logical requests, records 21 owner
effects, rejects 25 invalid inputs or damaged journals, and retains 91 owner
audit rows. The two runs agree on their outcomes after removing the independently
allocated session birth token from the cross-run comparison.

## What the controls establish

| Control group | Completed requests | Owner effects | Rejections | Evidence checked |
| --- | ---: | ---: | ---: | --- |
| Concurrent pipeline completion | 1 | 3 | 0 | Two overlapping exact retries return the first durable result, including receipt metadata; a restarted owner and reopened coordinator preserve that result. |
| Pipeline text inputs | 4 | 12 | 11 | Invalid request identities, manifests and a custom Python string key do not leave an application request binding; valid Unicode and embedded NUL identities complete. |
| Factored text inputs | 4 | 4 | 6 | Invalid manifests are rejected before session identity or authority is committed; a custom Python string key is rejected before request binding. |
| Journal recovery | 2 | 2 | 8 | Corrected initialization reuses a genuinely empty journal; open and retired sessions reopen with the owner stopped; seven damaged journal forms are rejected without changing their bytes or the retained authority. |
| **Per execution mode** | **11** | **21** | **25** | **91 durable owner audit rows, each matched to its transport reply.** |

The concurrent control deliberately gives the two attempts different owner
receipt metadata. Completion rechecks the durable binding and returns the first
stored output to both callers. It does not execute an owner effect twice.

Text validation uses the base `str.encode` operation. The custom-string controls
exercise a Python API object whose `encode` method returns unrelated bytes;
socket requests still contain ordinary JSON strings. A two-codepoint surrogate
pair is rejected by the lower admission layer because JSON decoding changes its
string identity. Its guard cleanup is recorded separately from constructor
rejections.

Journal initialization distinguishes two empty, correctly shaped tables from a
journal with missing tables, unexpected schema, malformed singleton state, or
request rows without session state. Reopening an initialized session retains its
stored codecs and birth identity. It does not obtain new codecs from an owner.
A fresh journal continues to record its own birth identity before attempting
admission; existing origin checks prevent it from adopting another session's
authority.

## Saved evidence and independent readers

- `results/session-reliability/normal/` and `optimized/` contain the completed
  executions, database checkpoints, transport histories and 16 captured source
  files per mode.
- `results/session-reliability/checks/<cohort>/<reader-mode>.json` contains four
  independent reader records: both interpreters read each execution cohort.
- `results/session-reliability/campaign-normal.json` and
  `campaign-optimized.json` contain the campaign checks, cross-mode comparison,
  historical reconstruction and corruption controls.
- `tests/check_session_repairs.py` reads a single completed cohort without
  importing production modules. `tests/check_session_reliability.py` combines
  the two cohorts and verifies the historical material described below.

From the artifact directory, verify the complete saved campaign with:

```sh
python -B -m tests.check_session_reliability --results results/session-reliability --corruption-controls
python -B -O -m tests.check_session_reliability --results results/session-reliability --corruption-controls
```

To inspect one cohort directly:

```sh
python -B -m tests.check_session_repairs --directory results/session-reliability/normal --tamper-controls
python -B -O -m tests.check_session_repairs --directory results/session-reliability/optimized --tamper-controls
```

The campaign checks five altered copies of each repaired cohort. It also checks
five altered copies of the historical records: a changed receipt, missing
pending request, nonempty initialization checkpoint, missing custom-string
pending request, and changed old source. For the historical controls the local
file inventory is recomputed after each edit, so rejection depends on the
database/response reconstruction or the retained source comparison.

Fresh current-code executions can be collected in new empty directories:

```sh
python -B -m tests.session_repair_regression --output /tmp/session-reliability-normal
python -B -O -m tests.session_repair_regression --output /tmp/session-reliability-optimized
```

## Historical failure records

`results/session-reliability/historical/` retains only the two completed original
collections, with their drivers and original bytes. Its inventory binds 82
files. All 23 source preimages from the original counterexample collection match
source files already retained under `results/retained-session-reliability/`.
The historical drivers are inspected as files and are never executed by the
campaign reader.

| Historical case | Independently reconstructed facts |
| --- | --- |
| Concurrent pipeline completion | The first checkpoint contains one completed output; the later checkpoint and final journal contain a different receipt set for the same input. The business record is unchanged and each owner has exactly one effect. |
| Unencodable factored manifest | The before/after named checkpoints contain the same pending request; the owner retains one guard, no effect and three `UnicodeEncodeError` replies. |
| Empty-journal retry | The corrected-begin checkpoint has zero state and request rows. The later explicit initialization has one completed request, one owner effect and no held guard. |
| Custom Python string, pipeline | One request remains pending after the first owner rejects its string contents. The three retained guards have no effect for that request ID. |
| Custom Python string, factored session | One request remains pending, one guard remains held and no schema effect was committed. |

The historical JSON output labels `recorded_driver_outcomes` separately from
`independently_reconstructed` facts. For example, the two initialization
exception messages and the calls made around reopening are driver records;
the corresponding empty or pending database checkpoints can be checked directly.
The complete string-boundary collection retains its original driver and uses
the shared pre-repair source preimages. That driver did not produce a separate
before/after source manifest, and the campaign does not attribute one to it.

The auxiliary historical audit also checks direct schema-handler replies,
canonical JSON storage of registry labels, and the final effect-ledger state.
Historical failures and these auxiliary observations are excluded from all
post-repair request, effect, rejection and audit-row totals.
