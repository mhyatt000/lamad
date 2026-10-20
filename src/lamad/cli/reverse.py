"""Reverse-engineering commands (`lamad re ...`); no project manifest required."""

from contextlib import contextmanager, redirect_stdout
from pathlib import Path
import sys
import tempfile

import click

from lamad.cli import HelpGroup, emit, fail, note
from lamad.core import export, project, runner
from lamad.core.native_io import quiet_kernel


@contextmanager
def output_directory(destination):
    """Only publish complete reports, and never replace an existing report."""
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError(f"Output already exists: {destination}. Choose a new --out directory.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".lamad-report-", dir=destination.parent) as temporary:
        work = Path(temporary) / "report"
        work.mkdir()
        yield work, destination
        if destination.exists():
            raise ValueError(f"Output already exists: {destination}.")
        work.rename(destination)


@click.group(name="re", cls=HelpGroup)
def re():
    """Reverse engineering: inspect STEP topology, compare STEP to a script."""


@re.command(name="inspect")
@click.argument("reference", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--out", type=click.Path(path_type=Path), help="New output directory; default: <reference>_inspect.")
@click.option("--preview/--no-preview", default=True, help="Write labeled orthographic views.")
@click.option("--tol", default=0.1, type=click.FloatRange(min=0, min_open=True), show_default=True,
              help="Preview tessellation deflection in mm; does not affect measurements.")
def inspect_command(reference, out, preview, tol):
    """Describe STEP assembly, solids, analytic faces, and face adjacency."""
    from lamad.core.inspection import inspect_step
    try:
        with output_directory(out or Path(f"{reference.stem}_inspect")) as (work, final):
            note("inspecting STEP topology…")
            with quiet_kernel():
                report, items = inspect_step(reference)
            report.update(command="inspect", status="success")
            report["outputs"] = {"report": str(final / "report.json")}
            if preview:
                from lamad.core.report_render import inspection_image
                note("rendering labeled views…")
                inspection_image(items, work / "preview.png", tol)
                report["outputs"]["preview"] = str(final / "preview.png")
            project.write_json(work / "report.json", report)
        emit(report)
    except Exception as exc:
        fail("inspect", f"{type(exc).__name__}: {exc}")


@re.command(name="compare")
@click.argument("reference", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("script", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--out", type=click.Path(path_type=Path), help="New output directory; default: <script>_compare.")
@click.option("--param", "params", multiple=True, metavar="K=V", help="Override a script parameter; repeatable.")
@click.option("--preview/--no-preview", default=True, help="Write aligned views, overlay, and solid differences.")
@click.option("--tol", default=0.1, type=click.FloatRange(min=0, min_open=True), show_default=True,
              help="Preview tessellation deflection in mm.")
@click.option("--boolean-tol", default=1e-6, type=click.FloatRange(min=0, min_open=True), show_default=True,
              help="OCCT boolean tolerance in mm, not a match threshold.")
def compare_command(reference, script, out, params, preview, tol, boolean_tol):
    """Compare a STEP solid model to a trusted build123d script."""
    import json
    from lamad.core.comparison import compare_shapes
    from lamad.core.inspection import shapes
    from lamad.core.step_io import load_shape
    from OCP.TopAbs import TopAbs_SOLID
    try:
        overrides = {}
        for raw in params:
            if "=" not in raw:
                raise ValueError(f"Bad --param {raw!r}; expected K=V.")
            key, value = raw.split("=", 1)
            try:
                overrides[key] = json.loads(value)
            except json.JSONDecodeError:
                overrides[key] = value
        with output_directory(out or Path(f"{script.stem}_compare")) as (work, final):
            note("loading reference and executing reconstruction…")
            source = script.read_text()
            with quiet_kernel(), redirect_stdout(sys.stderr):
                original = load_shape(reference)
                result = runner.execute(source, overrides, filename=str(script))
            if not result.ok:
                raise ValueError(result.error + ("\n" + result.traceback if result.traceback else ""))
            note("computing missing and extra material…")
            with quiet_kernel():
                report, geometry = compare_shapes(original, result.shape, boolean_tol)
            report.update(command="compare", status="success", reference_file=str(reference.resolve()),
                          script=str(script.resolve()), params=result.params)
            outputs = {"report": str(final / "report.json"),
                       "reconstruction": str(final / "reconstruction.step"),
                       "script": str(final / "script.py")}
            export.export_step(result.shape, work / "reconstruction.step", parts=result.parts)
            (work / "script.py").write_text(source)
            for name in ("missing", "extra"):
                if shapes(geometry[name], TopAbs_SOLID):
                    export.export_step(geometry[name], work / f"{name}.step")
                    outputs[name] = str(final / f"{name}.step")
            if preview:
                from lamad.core.report_render import comparison_image
                note("rendering shared-camera comparison…")
                comparison_image(geometry, work / "comparison.png", tol)
                outputs["preview"] = str(final / "comparison.png")
            report["outputs"] = outputs
            project.write_json(work / "report.json", report)
        emit(report)
    except Exception as exc:
        fail("compare", f"{type(exc).__name__}: {exc}")
