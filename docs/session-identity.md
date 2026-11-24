# Session identity across journal recovery

An application session owns both its pending-request ledger and the codec
admissions that protect those requests. A readable manifest label identifies the
work to a caller; it cannot identify that durable ownership on its own. Two
journals can use the same label, workflow and codec obligations while retaining
different pending requests.

## Admission binding

On creation, `FactoredSession` generates a UUID birth token and commits it in the
session journal before any owner preparation. The journal retains the readable
label separately. Its internal admission manifest contains that label followed
by a digest of the following immutable fields:

- the birth token and readable label;
- the complete physical registry and admission window;
- the ordered workflow, schema family and selected codec at every owner.

Every owner admission uses this bound manifest. Reopening verifies the binding
of the retained certificates and of every existing local origin attempt before
acquiring, processing requests or retiring authority. A partial acquisition
therefore resumes under its original birth identity. A different journal,
including one created earlier but never admitted, cannot adopt that authority
by presenting the same label and local guard shapes.

At the maximum 128-character readable label, the internal manifest contains
201 characters and fits the unchanged owner's 256-character bound. Effect
identity continues to use origin, admission sequence, bound manifest and
request/hop ID. The session's token remains stable when its transport address
or process changes. The existing single-writer and trusted-peer assumptions
still apply; this binding does not provide leader election or authentication.

## Why the pending ledger matters

The reproduced failure began after an actual source effect committed but its
reply was withheld. The owning session retained one pending request and both
codec holds, then persisted its closing gate and stopped. A separate journal
with the same readable label and obligations could previously reuse those
certificates. Its empty request ledger let it retire both holds, leaving the
original request unable to retry.

A check restricted to newly created journals would miss the same failure when
the unrelated journal had been created before the active session. Persisting a
distinct birth token closes both paths. The original journal keeps its pending
input and authority; the unrelated journal is rejected before an owner change.
After the original session drains, the later journal can acquire its own
admission with fresh, nonreused owner sequences.

## Executable controls

`tests/session_identity_regression.py` runs six groups against the actual
Endpoint, SQLite and ProtoJSON implementations. It retains every owner database,
session journal, operation trace and executed source file in a new output
directory. The controls cover fresh and repeated foreign-journal attempts,
precreated journals, different workflows with equal local obligations, changed
immutable journal fields, sequential reuse after retirement, and cancellation
after committed preparation, application effects and retirement.

```bash
python -B -m tests.session_identity_regression --out results/session-identity-reproduction/normal
python -O -B -m tests.session_identity_regression --out results/session-identity-reproduction/optimized
```

Response withholding and cancellation in these controls occur in the transport
adapter after an actual owner commit. The separate physical campaign supplies
TCP and operating-system process-failure observations. Earlier captured journals
retain their original fields and source implementations; the current runtime
rejects a journal lacking a birth token instead of silently changing an active
session's admission identity.
