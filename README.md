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
and a JSON error with exit 1 on failure. Neither overwrites: `inspect`
writes a new `<stem>_inspect/` directory next to the reference file and
`compare` a new `<stem>_compare/` directory next to the script (not in the
current directory), or `--out DIR`; an existing directory is an error.
`--param K=V` overrides a script's top-level literals exactly as `lamad run`
does.

The reference's extension picks the comparison mode, reported as `"mode"` in
the JSON and in `report.json`:

| Reference | Mode | Numbers | Outputs |
|-----------|------|---------|---------|
| `.step`, `.stp`, `.brep` | `solid` | OCCT booleans in authored coordinates: `difference.{missing_volume, extra_volume, intersection_over_union, ...}` plus per-side metrics | `report.json`, `comparison.png`, `reconstruction.step`, `script.py`, and `missing.step` / `extra.step` when those solids are non-empty |
| `.stl` | `mesh` | Sampled surface distances between the STL and the tessellated script result: `distance_mm.{reference_to_reconstruction, reconstruction_to_reference}.{mean, p95, max}`, `samples_each_direction`, `bounds_mm`, and `volume_mm3` (watertight meshes only). No IoU or missing/extra volumes. | `report.json`, `comparison.png`, `reconstruction.stl`, `script.py` |

```bash
lamad re compare part.step part.py                      # solid mode -> part_compare/
lamad re compare part.step part.py --boolean-tol 1e-5   # OCCT fuzzy tolerance (solid only)
lamad re compare vendor.step part.py --solids-only      # ignore cosmetic thread surfaces
lamad re compare scan.stl part.py                       # mesh mode
lamad re compare scan.stl part.py --tol 0.05 --ang 0.2 --samples 10000
lamad re compare asm.step part.py --ref-part housing --part housing   # one part of each
lamad re coverage vendor.step part.py --tol 0.05        # face checklist only -> part_coverage/
```

Options: `--tol` is the tessellation linear deflection in mm (preview only in
solid mode; the reconstruction mesh itself in mesh mode), `--ang` the angular
deflection in radians and `--samples` the surface samples per direction
(mesh mode only), `--boolean-tol` the OCCT boolean tolerance (solid mode
only; a warning on stderr says it is ignored for `.stl`), `--solids-only`
drops the reference's free faces, shells, and wires (solid mode only),
`--coverage-tol` sets the face-coverage match tolerance (below) and
`--no-coverage` skips that pass, `--ref-part` / `--part` pick parts (below),
and `--no-preview` skips `comparison.png`.

Solid mode wants closed solids on both sides. A reference that also carries
free faces or shells (vendor STEPs often add cosmetic thread surfaces) is
refused with a message naming `--solids-only`; with the flag those
non-solid shapes are dropped before comparing, stderr says how many, and
the report records `reference.dropped_non_solids`. When OCCT rejects a
boolean, typically because the reconstruction's faces coincide exactly with
the reference's (a counterbore floor at the same height, say), `compare`
retries the operation with OCCT's glue modes (shift, then full) and then
with ten times `--boolean-tol` as the fuzzy value; the setting that
succeeded is reported as `difference.boolean_strategy` (`plain`,
`glue-shift`, `glue-full`, or `fuzzy`). The preview outlines depth steps,
so a tall feature seen end-on in the top view stays visible against the
face it stands on.

Mesh-mode distances are deterministic samples to the closest point on the
other mesh, not a Hausdorff bound; both meshes are chordal approximations,
so differences below roughly the STL's export deflection plus `--tol` are
tessellation noise. Neither mode aligns or scales anything: both models are
compared in their authored coordinates.

### Face coverage

Volumes say how much is wrong, not what. The `coverage` section of a solid
mode report (and the whole of `lamad re coverage REFERENCE SCRIPT`, which
runs the script and writes only `report.json` into `<stem>_coverage/`) turns
the comparison into a checklist of faces. Every face of the reference is
sampled on its trimmed surface (8 to 200 points by area, uniform in UV,
holes and trimmed corners excluded) and each sample is measured to the
closest point on the reconstruction's finely tessellated surface; the face is
`matched` when the 95th percentile of those distances is within the
tolerance (`--coverage-tol` for `compare`, `--tol` for `coverage`, 0.1 mm by
default). The same is done for the reconstruction's faces against the
reference. Per side the report gives `faces_total`, `matched`,
`area_matched_fraction`, and `unmatched`: one entry per missed face with its
id (`p1:f7`, as `re inspect` numbers it; reconstruction parts are numbered in
`show_object` order), part name, surface type and analytic parameters
(plane origin and normal, cylinder axis and radius, ...), area, centroid, and
the sampled `distance.{mean, p95, max}`, sorted by area so the largest
missing detail comes first. A forgotten chamfer therefore appears as one
plane at 45 degrees with its area, and a recess floor as a plane 1 mm under
the top, instead of as a volume. Faces on both sides must sit within the
tolerance everywhere they are sampled: a reference face the script
reproduces exactly is matched even when the script's own face is larger;
that excess is reported on the reconstruction side. Mesh mode (`.stl`)
covers the reconstruction's faces against the STL only, and distances there
include the STL's chordal error.

### Picking parts

`--ref-part NAME` restricts the reference to the assembly part(s) whose name
equals NAME or contains it case-insensitively, using the names `re inspect`
reports; `--part NAME` does the same for the script's `show_object(...,
name=...)` parts. Both are repeatable, apply to `compare` (either mode, though
an `.stl` has no parts to pick) and `coverage`, and an unknown name fails
with the available names listed. The report records what was compared under
`reference.selected_parts` and `reconstruction.selected_parts` (`null` when
everything was) next to `available_parts`; `reconstruction.step` holds only
the selected parts.

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

## Rendering pictures

`lamad render` runs a script and saves PNGs without recording a version.
Both subcommands take `--param`, `--part NAME` (repeatable, matched like
`re compare`), and `--out`; the default output sits next to the script and is
numbered rather than overwritten, and an existing `--out` is refused.

### Part views

```bash
lamad render part stand.py               # -> stand_render.png
lamad render part stand.py --n 12 --size 300
lamad render part stand.py --part lip --n 0   # just the first row
```

One sheet, three views wide. Row one is **top**, **side** (from +X, the
right view) and **bottom**. Below it come `--n` (default 6) **home** views
whose cameras are spread as far apart as possible: the smallest angle between
any two cameras is maximised (6 gives an octahedron, every camera 90 deg from
its nearest neighbour; 12 an icosahedron, 63.4 deg). Any rotation of such a set
is equally spread, so it is turned to keep every camera well away from the
axis views of row one. Each home view is labelled with its azimuth and
elevation, and the JSON lists every camera's direction and up vector plus
`home_min_angle_deg`. Parts keep their `show_object()` colors.

### Sketches

`lamad render sketch` draws planar parts as a flat 2D picture: filled faces
with their holes, edges, a millimetre grid, and the drawn size.

```python
with BuildSketch() as plate:
    RectangleRounded(60, 30, 4)
    Circle(4, mode=Mode.SUBTRACT)
show_object(plate.sketch, name="plate")      # a sketch or Face
show_object(path.line, name="path")           # a BuildLine curve works too
```

```bash
lamad render sketch plate.py             # -> plate_sketch.png
lamad render sketch plate.py --part plate --size 1600 --no-grid
```

The plane is detected from the geometry. XY, XZ and YZ sketches keep global
coordinates (the grid's darker lines are the axes) and report their offset;
any other plane is drawn in its own axes. Solids, or parts on different
planes, are an error; pick parts with `--part`.

## Web viewer

`lamad web` runs a build123d script and serves the result in the browser
viewer straight from memory: no project, no version, no STEP on disk. Each
`show_object()` part gets its own color (the script's `color=` if given,
otherwise the export palette) and a row in the viewer's scene tree, whose
visibility toggle hides the part and everything nested under it.

Parts nest like a CAD assembly. A build123d `Compound(label=..., children=[...])`
becomes a group with one row per child (unlabeled children are numbered after
their parent), and a `/` in a name nests too:

```python
base = Compound(label="base", children=[slab, bolt])   # children carry .label
show_object(Compound(children=[base, lid]), name="stand")  # stand/base/bolt, ...
show_object(knob, name="extras/knob")                   # extras/knob
```

`lamad view` nests a STEP assembly the same way.

```bash
lamad web examples/stand.py                      # opens http://localhost:8080
lamad web stand.py --param width=120 --port 9000 # same --param overrides as run
lamad web stand.py --no-browser --watch          # re-run and refresh on file change
```

One JSON object (script, params, parts with colors, url) is printed on stdout
before the server blocks; ctrl-c stops it. `lamad view` still serves recorded
versions and STEP files.
