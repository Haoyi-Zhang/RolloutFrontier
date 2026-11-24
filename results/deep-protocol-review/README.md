# Durable protocol boundary suite

Normal and optimized Python each execute 56 test methods with no failures,
errors or skips. The suite covers admission and retirement lifetimes, strict
certificate types, owned effects, storage failures, delayed operations and
process recovery. Durable goal execution and application request recovery have
separate cohorts.

The `normal/` and `optimized/` directories retain each mode's observations,
execution summary, unittest log and exact source inputs. The recorded inputs
identify the modules exercised by this suite; later modules are checked by
their own experiments.

Run from `artifact/` with fresh output directories:

```sh
python -B -m tests.protocol_boundary_suite --out /tmp/protocol-normal
python -O -B -m tests.protocol_boundary_suite --out /tmp/protocol-optimized
```

The controls use actual local SQLite stores and loopback TCP. Process-kill cases
exercise recovery after process loss on one host. The saved-record check in
[REPRODUCTION.md](../../docs/REPRODUCTION.md) checks the observations and source
inputs; the commands above execute the live suite again.
