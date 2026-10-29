# Handoff

State of `lamad` as of 2026-10-19, for the next agent picking it up.

## What this is

A CLI for scripted CAD on build123d: run a script, get a versioned STEP with
metrics and a preview, view it in viser, and reverse-engineer vendor STEP/STL
files against a script. It is the successor to `../mycad` (same author) and
diverges from it; do not edit mycad.

It serves the parent repo `davincisi`, where another agent reverse-engineers
vendor parts and reports tool gaps. Expect feature requests to arrive as
pasted reports from that agent.

## Repo and environment

- Own git repo at this directory (nested inside `davincisi`, which has its own
  repo; never run git against the parent). Branch `main`, 9 commits, nothing
  pushed, no remote yet. The intended remote is
  `https://github.com/mhyatt000/lamad`.
- Commit each verified milestone separately with a descriptive message. End
  commit messages with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
  Never push.
- uv project, `uv_build` backend, src layout. Python pinned to 3.11–3.12 because
  OCCT bindings have no 3.13+ wheels. Venv at `.venv`; run things with `uv run`.
- The user has it installed as an editable uv tool: `~/.local/bin/lamad` points
  at this `src/`. Keep the package importable at all times (no half-written
  modules on disk). After dependency changes, the user must run
  `uv tool install --reinstall -e /Users/matthewhyatt/repo/davincisi/lamad`.
- Dev machine is an Intel Mac. torch resolves to 2.2.x there (platform marker in
  `pyproject.toml`) and its NumPy bridge is broken under NumPy 2, which
  build123d requires. Nothing in `src/` may import torch; a test asserts
  `import lamad.cli` leaves `torch` out of `sys.modules`.
- OCP is cadquery-ocp 8.0.1. Templated collections live in `OCP.collections`
  (`List_TopoDS_Shape`, `Sequence_TDF_Label`,
  `IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher`, ...), `TopoDS` casts have
  no `_s` suffix, `Bnd_Box.Get()` is gone (use `CornerMin/CornerMax`),
  `BRepTopAdaptor_FClass2d` is not bound. mycad was written for OCP 7.9.3; any
  code copied from it needs these renames.
- Shell quirk: a `lamad web`/`view` started with a trailing `&` ignores ctrl-c
  because zsh masks SIGINT for background jobs. Use SIGTERM or `subprocess`.
- Agent tooling note: the Bash permission classifier occasionally fails
  transiently. Read-only tools still work; retry once, then move on.

## Layout

```
src/lamad/
  __init__.py          main() -> cli.cli (lazy import)
  cli/
    __init__.py        root HelpGroup (bare group prints help, exit 0),
                       emit/fail/note/parse_params
    project.py         init, run, versions {list, show}
    geom.py            view, measure, export; serve() helper
    web.py             web (script -> viser, per-part colours, --watch)
    reverse.py         re {inspect, compare, coverage}; shared loaders
                       _load_reference / _load_reconstruction; output_directory
    detect.py          re det {edges, corners, faces, all, status}
  core/
    runner.py          execute(source, overrides, filename) -> ok/shape/parts/params
    project.py         lamad.json manifest, vN_label dirs, resolve()
    metrics.py export.py render.py viewer.py step_io.py native_io.py
    inspection.py      read_assembly, face_report (surface type + params)
    comparison.py      compare_shapes, boolean retry ladder, drop_non_solids
    coverage.py        face_coverage, mesh_coverage
    mesh_compare.py    STL comparison by point sampling (trimesh + rtree)
    mesh_native.py     mesh helpers used by tests
    report_render.py   comparison_image / inspection_image (outlined previews)
    detect/            registry (__init__), common, edges, corners, faces
tests/                 unittest; fixtures are built with build123d in temp dirs
examples/stand.py      three named, coloured parts
```

## Contracts to preserve

- Every command prints exactly one JSON object on stdout; progress and
  warnings go to stderr with a `[lamad]` prefix; failures emit a JSON error
  and exit 1. `native_io.quiet_kernel` flushes C stdio before swapping fds so
  OCCT banners cannot land after the JSON. Verify with a real shell pipe, not
  only CliRunner.
- Bare `lamad`, `lamad versions`, `lamad re`, `lamad re det` print help with
  the subcommand list and exit 0 (click 8.5 would exit 2; `HelpGroup`
  overrides that). Every command has a one-line docstring.
- Heavy imports (OCP, viser, trimesh) stay inside commands so `--help` is fast.
- Output directories for inspect/compare/coverage default next to the input
  (reference for inspect, script for the others) and are never overwritten.
- `re det` support table is generated from `core/detect/__init__.py`
  FEATURES; update the registry when a feature lands, never the help text.
- Face ids: `f<i>` for a bare shape, `p<i>:f<j>` for assembly parts, shared by
  `re inspect`, `re det faces`, and coverage.

## Verification routine

```bash
uv run python -m unittest discover -s tests -v     # 0 failures, 0 skips
uv run python -c "import sys, lamad.cli; print('torch' in sys.modules)"  # False
~/.local/bin/lamad                                  # lists all commands, exit 0
```

New fixtures: build the shape with build123d, export with
`lamad.core.export.export_step` / `export_stl` into a temp dir, assert on
computed facts (counts, angles, areas), and drive the CLI through
`click.testing.CliRunner` parsing stdout as JSON. Tests must not bind ports;
mock `viewer.serve_parts` and `viewer.wait`.

## Known caveats and open items

1. Coincident-face booleans. The parent agent reported OCCT cuts returning
   not-done when reconstruction faces coincide exactly with the vendor's. A
   retry ladder (plain, glue-shift, glue-full, fuzzy) now exists and records
   `difference.boolean_strategy`, but the failure could not be reproduced on
   this OCCT with any fixture tried; the ladder is tested by forcing lower
   rungs to fail. Waiting on the parent agent to retry the real vendor file.
   If it still fails, get that STEP and script.
2. Dihedral convention (documented in `core/detect/corners.py`): a through-hole
   rim is convex like an outer box edge; a boss base is concave. Hole vs boss
   must come from cylinder orientation, not edge sign.
3. Coverage reads: a missing cut feature shows as its own faces (floor, walls)
   in `reference.unmatched`, and as an oversized face on the reconstruction
   side; the face it was cut from can still be matched. Both lists matter.
4. Non-assembly STEPs name their single part after the product string
   (e.g. `"Open CASCADE STEP translator 8.0 1"`). Kept for id consistency.
5. viser moves to the next free port silently; `web` reports the bound port.
6. The `reverse-engineering` extra now holds only `shapely`, which nothing
   imports. Drop the extra or use it.
7. `lamad export foo.step --to glb` writes `foo.glb` next to the input.

## Planned next

- `re det` on STEP: fillet, chamfer, hole, boss, pattern (registry rows exist
  as `planned`). Sharp edges, cylinder faces, and the adjacency graph from
  inspection.py are the inputs.
- `re det` on STL: sharp edges (dihedral), flat facets (trimesh facets),
  corners, then line/circle edge chains, then cylinder/sphere/cone fitting.
  Test STL fixtures are already exported alongside the STEP ones in
  `tests/test_detect.py`. Tolerances must scale with mesh resolution.
- README has install, commands, reverse engineering, feature detection, and
  web viewer sections; keep it current when commands change.
