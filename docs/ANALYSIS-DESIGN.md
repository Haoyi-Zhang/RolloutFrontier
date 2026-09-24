# Supplementary analysis design

The controller, greedy planner, exact planner, checker, original campaign, and
post-development holdout are inherited unchanged. Additional analyses address the
meaning of the objective rather than tune it to obtain a chosen improvement.

The retained 1,440-case holdout is grouped by six fixed families. Seeds are paired
across policies and resampled jointly across families: 4,000 replicates, seed
20260923, percentile endpoints 2.5% and 97.5%. This interval is conditional on the
chosen generators and seed-resampling scheme, not population-level fleet evidence.

A four-cell relation gives a constructive scheduled-install counterexample. The
maximum-mass safe rectangle has mass three but accepts no change on a chosen
alternating schedule. Another frozen safe rectangle has mass two and accepts all
2T changes. T=100 is an executable instance of the argument, not its proof.

A dense-profile stress test uses three or four alternatives, two or three owners,
seed values 3000--3002, and paired search budgets 400 and 2,000. Current support
contains every relevant atom; candidates are deterministic sampled pairs. This
admits substantially more local guards than singleton-current fixtures. All budget
failures remain in the results. Successful returns are checked independently;
paired successful budgets must agree. Runtime includes the independent checker and
is descriptive only. This design does not claim scalable unbounded synthesis.
