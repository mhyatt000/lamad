# lamad

CAD tooling built on [build123d](https://build123d.readthedocs.io): write a
Python script describing a part, get a STEP file, measurements, a preview
image, and a browser viewer.

## Install

As a standalone command-line tool:

```bash
uv tool install git+https://github.com/mhyatt000/lamad
lamad
```

For development:

```bash
git clone https://github.com/mhyatt000/lamad
cd lamad
uv sync
uv run lamad
```

## Python support

OCCT bindings (`cadquery-ocp`, pulled in by build123d) have no wheels for
Python 3.13+, so the project pins Python 3.11–3.12.

On Intel Macs, torch resolves to the last release that still shipped x86_64
wheels (2.2.x).

## Optional extras

```bash
uv sync --extra reverse-engineering   # trimesh, rtree, shapely
```

## Feature detection

`lamad re det` reads a STEP/BREP file and reports geometric features as one
JSON object on stdout (progress on stderr, JSON error + exit 1 on failure):

```bash
lamad re det                      # help plus the feature support table
lamad re det edges part.step      # line | circle | ellipse | freeform edges
lamad re det corners part.step    # sharp edges (convex/concave) and corner vertices
lamad re det faces part.step      # plane | cylinder | cone | sphere | torus | freeform faces
lamad re det all part.step        # all three in one pass
lamad re det status               # the support table as JSON
```

`corners` takes `--angle-tol DEG` (default 10): an edge is sharp when the
outward normals of its two faces differ by more than that. Every file command
accepts `--out FILE.json` to also write the report to disk.

Fillet, chamfer, hole, boss, and pattern recognition are planned, and STL
(mesh) input is planned for every feature; bare `lamad re det` prints the
current step/stl support table, generated from the same registry the commands
use.
