# Public input and acquisition boundary

The artifact retains two small, auditable declaration-history slices. Neither is a
complete Android SDK history, a representative application sample, or evidence that
an API declaration preserves behavior.

## 24 class-introduction facts

`android-class-introductions.csv` contains 24 manually curated Android framework
classes spanning API levels 8–34 and 18 distinct introduction levels. Every row
records:

- a project-local positive atom;
- the exact fully qualified class name;
- the first public API level shown by the official Android reference;
- the exact official reference URL; and
- the check date, 2026-09-12.

Selection rule: retain a deliberately spread set of public framework classes across
the 8–34 level range, including multiple classes at densely populated levels 21, 23,
and 26. The selection was not random, frequency weighted, or derived from an app
corpus. It is therefore unsuitable for prevalence or representativeness claims.

`tests/public_history.py` uses only the retained CSV. It verifies uniqueness and URL
shape, checks that each declaration is absent immediately before and present at its
recorded first level, generates 96 deterministic reference sets, and checks both the
computed and an independent assembly-time lower bound (192 lower-bound checks). It
also feeds the declarations into a separately labeled synthetic five-owner frontier
fixture. These operations test source plumbing and finite logic; they do not execute
Android or establish compatibility.

## Four VibrationEffect factory facts

`android-history.csv` is a separate manually transcribed slice of the official
`android.os.VibrationEffect` reference. It retains exactly four public factory
methods: three first public at API 26 and `createPredefined(int)` first public at API
29. Selection rule: exactly the four named public factories in the CSV; ignore other
members. These rows drive the end-to-end presence/rollback network trace.

Official reference:
https://developer.android.com/reference/android/os/VibrationEffect

An older AOSP source file was also inspected through the repository connector:
https://github.com/aosp-mirror/platform_frameworks_base/blob/android-8.0.0_r1/core/java/android/os/VibrationEffect.java
The three API-26 factory declarations occur there. A hidden `get(int)` is not the
later public `createPredefined(int)` and is deliberately excluded. No source code from
that file is included in the artifact.

## Complete-history boundary

A complete upstream declaration-history source was identified but not acquired or
bundled:

- repository: `aosp-mirror/platform_development`
- path: `sdk/api-versions.xml`
- immutable commit: `a278b15cda8a07a97686370cb5e944fb4f6bc824`
- Git blob SHA: `16316e39d865c417a0fcd9c630861d9c8cc75efb`
- canonical source URL:
  https://android.googlesource.com/platform/development/+/a278b15cda8a07a97686370cb5e944fb4f6bc824/sdk/api-versions.xml

The official Gitiles metadata view reports an exact file size of 3,539,324 bytes and
the blob identifier above. The available repository interfaces did not yield a
reliable complete byte-for-byte local copy, so the file is not bundled or parsed. It
is recorded only as a fixed future acquisition boundary, not counted as an
experimental input, checksum-verified download, complete corpus, or basis for any
result.

## Generated inputs

All workload alternatives, reference-set combinations, candidate levels, fault
schedules, dependency edges, removals, and semantic-mode changes not explicitly listed
in the two CSV files are generated fixtures. None is described as a mined workload,
observed field failure, or real deployment trace. Reproduction contacts no real
device, application, account, or production service.
