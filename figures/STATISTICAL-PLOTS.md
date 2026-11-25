# Statistical plots and their data

The [manuscript figure map](../../paper/figures/README.md) identifies the figures
used in the main article and supplement. The compiled
[figure atlas](../../paper/figure_atlas.pdf) shows their actual numbering,
placements and grayscale inspection copies.

| Scientific comparison | Python generator under `paper/` | Retained inputs under `artifact/results/` |
| --- | --- | --- |
| Preparation-inclusive planning cost of the four routes through six owners (article Fig. 5) | `figure-source/make_statistical_figures.py` | `structured-planning/timing-summary.json` and all 105 worker records |
| Factored planning CPU cost and peak memory through 1,024 owners (article Fig. 6) | `figure-source/make_statistical_figures.py` | `factored-scale/summary.json`, both checked summaries and the 50 fresh-worker records |
| Owner communication for identical installation paths (article Fig. 7) | `figure-source/make_statistical_figures.py` | `phase-granularity/` paired process traces and summaries |
| Cumulative static-batch planning cost (supplement) | `figure-source/make_statistical_figures.py` | `direct-optimization/` complete repetitions |
| Goals with an extra phase per deployment graph class under two fixed-choice baselines (supplement) | `figure-source/make_statistical_figures.py` | `schema-path-analysis/summary.json` and its motif CSV, cross-checked against `schema-census/summary.json` |

Every plotted number is rebuilt from the retained records by
`paper/statistical_data.py`, which raises instead of drawing when an input is
missing, inconsistent or disagreeing with the manuscript macros; the exact
plotted values are written to `paper/figure-source/data/*.csv`.

The factored scale plot reports medians and full ranges across five worker
mean CPU costs and five process peak-memory observations per condition. Repeated
cold CPU cohorts within a worker are aggregated before that comparison. Its owner axis describes planner input size, while the physical
execution campaign separately uses up to 32 owner processes on one host.

The three data-derived supplement diagrams are drawn from retained probes and
checked relations by `paper/draw_extensions.py`, `paper/draw_alternate_readers.py`
and `paper/figures/draw_policy.py`. `paper/figure-source/render_diagrams.py`
replaces their original Matplotlib style, which embedded Type 3 fonts, with the
manuscript style (Times New Roman TrueType, STIX math, `pdf.fonttype` 42) and
leaves their geometry and data bindings unchanged.

Run `sh paper/build.sh` from the project root with the publication dependencies
listed in [paper/README.md](../../paper/README.md). It regenerates the statistical
figures from retained observations and compiles the manuscripts. Run
`python -B paper/build_figure_atlas.py` afterward to regenerate the atlas from the
newly compiled placements.
