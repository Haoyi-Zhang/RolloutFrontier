# Publication figure review

The article targets IEEE Transactions on Parallel and Distributed Systems. The
current submission carries eight figures in the article (five conceptual
figures drawn from prompts, four of them final and one still a placeholder, and
three statistical plots) and five in the
supplement (two statistical plots and three data-derived diagrams); the compiled
numbering and printed sizes are in `paper/figure_atlas.json`. The review below
records the redrawing of the figure collection at the time the plot generators
were consolidated into `paper/figure-source/make_statistical_figures.py`; it is
retained as a record of that pass.

## Journal calibration

Three published TPDS papers informed the visual organization:

- [Quiver: Consistent Object Sharing for Edge Services](https://reitermk.github.io/papers/2008/TPDS.pdf), 19(7), 878–889. Fixed object positions and a shared legend make successive states comparable.
- [On Mixing Eventual and Strong Consistency: Acute Cloud Types](https://www.cs.put.poznan.pl/pawelw/pdf/tpds22-journal.pdf), 33(6), 1338–1356. Aligned execution lanes expose the relation responsible for each counterexample.
- [FlexRaft: Exploiting Flexible Erasure Coding for Minimum-Cost Consensus and Fast Recovery](https://millyz.github.io/pubs/tpds24flexraft.pdf), 35(10), 1826–1840. Fixed server columns, grouped objects and shared chart axes carry the comparison.

The drawings use original arrangements for this paper. The inspected reference
PDFs are not part of the research distribution.

IEEE's [file-formatting guidance](https://journals.ieeeauthorcenter.ieee.org/create-your-ieee-journal-article/create-graphics-for-your-article/file-formatting/)
asks for consistent type and embedded fonts or outlines. Its
[resolution guidance](https://journals.ieeeauthorcenter.ieee.org/create-your-ieee-journal-article/create-graphics-for-your-article/resolution-and-size/)
sets more than 300 dpi for color and grayscale raster content. Its
[accessibility guidance](https://journals.ieeeauthorcenter.ieee.org/create-your-ieee-journal-article/create-graphics-for-your-article/)
recommends checking grayscale and distinguishing series by shape or pattern.

## Issues, changes and evidence

| Figure or issue | Change | Evidence retained |
| --- | --- | --- |
| The overview's empty cards and overlapping circles did not explain the method | A software-input vignette accompanies two alternative exact planners, owner-local product cards and an overlapping-authority handoff | Four generated illustration candidates and four mechanism-layout candidates were inspected; the final diagram connects retirement to installation and compares two complete support/generation collections |
| Local contracts and global physical state were separated into narrow columns | The local matrix and shared-owner cycle sit above complete configuration endpoints | All 16 local cells, all 24 displayed safe-product corners, the three-phase optimum and all six fixed-owner four-phase paths match the retained records |
| Counterexample routes and safe-product boundaries crossed | Six separate membership matrices sit above paths with explicit phase brackets | Independent enumeration recovers both optima and both installation-shortest routes; the figure shows one such route, as its caption states |
| Scale legends and final owner ticks were crowded | Shorter shared legends, larger plotting areas and redundant marker/line encodings | All ten measured conditions retain their coordinates, five-worker ranges and units |
| Repeated labels obscured the communication comparison | Four aligned pairs of horizontal stacked bars put paired goals, methods and total means on one reading line | All eight bar records and component sums remain unchanged |
| The reuse legend occupied more space than the comparison | Four aligned matrices share row labels and a narrow vertical scale; below-one ratios are bold | All 64 cells retain their values, including eight work-limit cells; glyph weight and hatching also work in grayscale |
| Planning-cost ticks looked like one number across adjacent panels | Wider panel gaps and fewer labelled ticks retain the original log scale and reference grid | The closest cross-panel labelled ticks have more than 21 pt of clear space; all 16 records are unchanged |
| Handler lookup and request persistence were described in detached notes | Explicit handler/rejection mappings and a durable identity/input/codec record surround the Pending-to-Complete transition | Actual probes, journal state names, fixed request binding and drain behavior remain consistent |
| Alternative readers could suggest field-wise routing | A complete record feeds one reader choice, next to its Boolean relation and componentwise closure witness | Seven accepted states, the rejected state and the maximum/minimum witness are unchanged |
| Policy panels repeated their conditioning values | Shared API-server columns and aligned rows expose the three compatibility relations | All 36 policy cells retain the supported counts 9/12, 5/8 and 10/16 |
| A previously chosen bibliography split forced an otherwise unnecessary page | The standard IEEE bibliography split point was rebalanced | The article returns to 12 pages with no change to the preceding eleven rendered pages; the final columns end within 9 pt of each other |

## Selection and typography

Each figure was compared against its previous composition and at least two
new layout candidates. The choices follow the visible comparison: independent
membership matrices remove crossed boundaries, complete configuration tuples
avoid a synchronous-update interpretation, and adjacent bars expose the actual
paired execution contrast. Margin and tick-spacing corrections followed those
structural choices.

## Figure construction

The overview combines one image-generated qualitative software vignette with
exact vector notation and mechanism geometry. The image identifies software
and request objects; it supplies no algorithm branch, measured value or state
transition. The two planning routes, local acceptance-set products, authority
handoff and matching observations are separately drawn and typeset in the
manuscript font. The selected native image is included, so an ordinary rebuild
reproduces the composition without another generation request.

The other five mechanism or compatibility figures use exact vector geometry.
The four numerical figures are generated in Python from retained experimental
observations. Their scripts preserve the original input checks and bind the
rendered outputs to the values they consume.

All ten selected figures include vector PDF and SVG artwork and 600 dpi PNG
exports; the generated vignette retains its original pixels. All figure bodies
use a minimum base label size of 10.5 pt before the small
scale adjustment to the manuscript width; titles use 11.5 pt. Mathematical
subscripts retain their normal relative size. Shapes, line styles and explicit
numbers preserve the interpretation in grayscale. The atlas shows every
figure in color and grayscale at its measured manuscript dimensions.

## Scientific preservation

The implementation, tests, input catalogs and retained experimental records
are unchanged. Their exact comparison with the preceding delivery is included
with the final acceptance. The prior acceptance itself is retained separately.
Redrawing a timing chart does not add a timing cohort. Figure construction,
independent semantic reconstruction, printed-page inspection and archive
verification each retain their own evidence.
