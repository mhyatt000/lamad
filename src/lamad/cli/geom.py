"""Geometry commands that work on any STEP/BREP file: view, measure, export."""

import webbrowser
from pathlib import Path

import click

from lamad.cli import emit, fail, note
from lamad.core import project

MESH_FORMATS = ("stl", "glb")


def serve(step_path, port=8080, tol=0.05, ang=0.3):
    """Start the viser viewer. Blocks until interrupted."""
    from lamad.core import viewer
    try:
        webbrowser.open(f"http://localhost:{port}")
        viewer.serve(step_path, tol=tol, ang=ang, port=port)
    except OSError as e:
        note(f"could not start viewer on port {port}: {e}")


@click.command()
@click.argument("ref", required=False)
@click.option("--port", default=8080, show_default=True)
@click.option("--tol", default=0.05, show_default=True, help="Linear deflection, mm.")
@click.option("--ang", default=0.3, show_default=True, help="Angular deflection, rad.")
def view(ref, port, tol, ang):
    """Serve a version in the browser. REF is a number, label, or STEP path."""
    # A path wins over a version lookup, so `lamad view parts/x.step` works
    # outside a project.
    if ref and Path(ref).suffix.lower() == ".py":
        fail("view", f"{ref} is a script, not a version or STEP file. "
             "Use `lamad web SCRIPT` to view a script directly, or "
             "`lamad run SCRIPT --label L` to record it as a version first.")
    if ref and Path(ref).suffix.lower() in (".step", ".stp"):
        if not Path(ref).exists():
            fail("view", f"{ref} not found.")
        serve(Path(ref), port, tol, ang)
        return

    try:
        root, manifest = project.load()
    except FileNotFoundError as e:
        fail("view", str(e))
    entry = project.resolve(root, manifest, ref)
    if entry is None:
        fail("view", f"No version matching {ref!r}.",
             available=[v["label"] for v in manifest["versions"]])
    step = root / entry["path"] / "output.step"
    if not step.exists():
        fail("view", f"{step} is missing. Re-run this version.")
    serve(step, port, tol, ang)


@click.command()
@click.argument("file", type=click.Path(exists=True, dir_okay=False))
def measure(file):
    """Report metrics for an existing STEP/BREP file."""
    from lamad.core import metrics as _metrics
    from lamad.core.step_io import load_shape
    try:
        shape = load_shape(file)
    except ValueError as e:
        fail("measure", str(e))
    emit({"command": "measure", "status": "success",
          "file": file, "metrics": _metrics.compute(shape)})


@click.command()
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--to", "formats", required=True,
              help="Mesh formats, comma separated: stl, glb.")
@click.option("--out", type=click.Path(file_okay=False, path_type=Path), default=None,
              help="Output directory (default: next to FILE).")
def export(file, formats, out):
    """Convert an existing STEP/BREP file to mesh formats (<stem>.stl, <stem>.glb)."""
    from lamad.core import export as _export
    from lamad.core.step_io import load_shape

    wanted = [f.strip().lower() for f in formats.split(",") if f.strip()]
    if not wanted:
        fail("export", "No formats given. Use --to stl,glb.")
    for fmt in wanted:
        if fmt not in MESH_FORMATS:
            fail("export", f"Unsupported format {fmt!r}. Supported: {', '.join(MESH_FORMATS)}.")

    try:
        shape = load_shape(file)
    except ValueError as e:
        fail("export", str(e))

    out_dir = out or file.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = {}
    for fmt in wanted:
        note(f"exporting {fmt.upper()}…")
        target = out_dir / f"{file.stem}.{fmt}"
        try:
            if fmt == "stl":
                _export.export_stl(shape, target)
            else:
                _export.export_glb(shape, target)
        except RuntimeError as e:
            fail("export", str(e), format=fmt)
        outputs[fmt] = str(target)
    emit({"command": "export", "status": "success", "file": str(file), "outputs": outputs})
