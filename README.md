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

`trimesh` and `rtree` are core dependencies (they back `lamad re compare`
with an STL reference). The `reverse-engineering` extra only adds `shapely`,
which lamad itself does not import yet:

```bash
uv sync --extra reverse-engineering   # shapely
```

## Reverse engineering

`lamad re inspect part.step` describes a STEP/BREP file (assembly tree,
solids, analytic faces, adjacency) and writes labeled views; `lamad re
compare REFERENCE SCRIPT` checks a trusted build123d script against a
reference model. Both print one JSON object on stdout, progress on stderr,
and a JSON error with exit 1 on failure. `compare` never overwrites: it
writes a new `<script>_compare/` directory (or `--out DIR`), and `--param
K=V` overrides a script's top-level literals exactly as `lamad run` does.

The reference's extension picks the comparison mode, reported as `"mode"` in
the JSON and in `report.json`:

| Reference | Mode | Numbers | Outputs |
|-----------|------|---------|---------|
| `.step`, `.stp`, `.brep` | `solid` | OCCT booleans in authored coordinates: `difference.{missing_volume, extra_volume, intersection_over_union, ...}` plus per-side metrics | `report.json`, `comparison.png`, `reconstruction.step`, `script.py`, and `missing.step` / `extra.step` when those solids are non-empty |
| `.stl` | `mesh` | Sampled surface distances between the STL and the tessellated script result: `distance_mm.{reference_to_reconstruction, reconstruction_to_reference}.{mean, p95, max}`, `samples_each_direction`, `bounds_mm`, and `volume_mm3` (watertight meshes only). No IoU or missing/extra volumes. | `report.json`, `comparison.png`, `reconstruction.stl`, `script.py` |

```bash
lamad re compare part.step part.py                      # solid mode
lamad re compare part.step part.py --boolean-tol 1e-5   # OCCT fuzzy tolerance (solid only)
lamad re compare scan.stl part.py                       # mesh mode
lamad re compare scan.stl part.py --tol 0.05 --ang 0.2 --samples 10000
```

Options: `--tol` is the tessellation linear deflection in mm (preview only in
solid mode; the reconstruction mesh itself in mesh mode), `--ang` the angular
deflection in radians and `--samples` the surface samples per direction
(mesh mode only), `--boolean-tol` the OCCT boolean tolerance (solid mode
only; a warning on stderr says it is ignored for `.stl`), and
`--no-preview` skips `comparison.png`.

Mesh-mode distances are deterministic samples to the closest point on the
other mesh, not a Hausdorff bound; both meshes are chordal approximations,
so differences below roughly the STL's export deflection plus `--tol` are
tessellation noise. Neither mode aligns or scales anything: both models are
compared in their authored coordinates.

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

## Web viewer

`lamad web` runs a build123d script and serves the result in the browser
viewer straight from memory: no project, no version, no STEP on disk. Each
`show_object()` part gets its own color (the script's `color=` if given,
otherwise the export palette) and a visibility checkbox.

```bash
lamad web examples/stand.py                      # opens http://localhost:8080
lamad web stand.py --param width=120 --port 9000 # same --param overrides as run
lamad web stand.py --no-browser --watch          # re-run and refresh on file change
```

One JSON object (script, params, parts with colors, url) is printed on stdout
before the server blocks; ctrl-c stops it. `lamad view` still serves recorded
versions and STEP files.
