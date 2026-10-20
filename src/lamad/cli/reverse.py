"""Reverse-engineering commands (`lamad re ...`); no project manifest required."""

from contextlib import contextmanager, redirect_stdout
import json
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
    """Reverse engineering: inspect STEP topology, compare STEP to a script, detect features."""



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


MESH_SUFFIXES = (".stl",)
SOLID_SUFFIXES = (".step", ".stp", ".brep")


def _parse_overrides(params):
    overrides = {}
    for raw in params:
        if "=" not in raw:
            raise ValueError(f"Bad --param {raw!r}; expected K=V.")
        key, value = raw.split("=", 1)
        try:
            overrides[key] = json.loads(value)
        except json.JSONDecodeError:
            overrides[key] = value
    return overrides


def _run_script(script, overrides):
    source = script.read_text()
    with quiet_kernel(), redirect_stdout(sys.stderr):
        result = runner.execute(source, overrides, filename=str(script))
    if not result.ok:
        raise ValueError(result.error + ("\n" + result.traceback if result.traceback else ""))
    return source, result


def _compare_solid(reference, script, overrides, work, final, preview, tol, boolean_tol):
    """STEP/BREP reference: OCCT booleans give missing/extra volumes and IoU."""
    from lamad.core.comparison import compare_shapes
    from lamad.core.inspection import shapes
    from lamad.core.step_io import load_shape
    from OCP.TopAbs import TopAbs_SOLID
    note("loading reference and executing reconstruction…")
    with quiet_kernel():
        original = load_shape(reference)
    source, result = _run_script(script, overrides)
    note("computing missing and extra material…")
    with quiet_kernel():
        report, geometry = compare_shapes(original, result.shape, boolean_tol)
    report.update(command="compare", status="success", mode="solid",
                  reference_file=str(reference.resolve()), script=str(script.resolve()),
                  params=result.params)
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
    return report


def _compare_mesh(reference, script, overrides, work, final, preview, tol, ang, samples):
    """STL reference: sampled surface distances between two triangle meshes."""
    from lamad.core.mesh_compare import body_mesh, compare_meshes, load_mesh, render_mesh_comparison
    note("loading reference mesh and executing reconstruction…")
    original = load_mesh(reference)
    source, result = _run_script(script, overrides)
    note(f"tessellating reconstruction and sampling {samples} surface points each way…")
    with quiet_kernel():
        generated = body_mesh(result.shape, tol, ang)
        raw = compare_meshes(original, generated, samples, booleans=False)
    distances = {}
    for name, key in (("reference_to_reconstruction", "reference_to_generated"),
                      ("reconstruction_to_reference", "generated_to_reference")):
        d = raw[key]
        distances[name] = {"mean": d["mean_mm"], "p95": d["p95_mm"], "max": d["max_sampled_mm"],
                           "max_sampled_point": d["max_sampled_point_mm"],
                           "closest_point": d["closest_point_mm"]}
    both_directions = [distances[k] for k in distances]
    ref_bounds, rec_bounds = raw["reference_bounds"], raw["generated_bounds"]
    size = lambda b: [hi - lo for lo, hi in zip(b[0], b[1])]  # noqa: E731
    watertight = {"reference": raw["reference_watertight"], "reconstruction": raw["generated_watertight"]}
    volume = {"reference": raw["reference_volume_mm3"] if watertight["reference"] else None,
              "reconstruction": raw["generated_volume_mm3"] if watertight["reconstruction"] else None,
              "watertight": watertight}
    if volume["reference"] is not None and volume["reconstruction"] is not None:
        volume["difference"] = volume["reconstruction"] - volume["reference"]
        volume["relative_difference"] = (volume["difference"] / volume["reference"]
                                         if volume["reference"] else None)
    else:
        volume["unavailable"] = "Mesh volume is only reported for watertight meshes."
    report = {"command": "compare", "status": "success", "mode": "mesh",
              "method": "sampled surface distances between the STL reference and the "
                        "tessellated script result; no boolean volumes or IoU in this mode",
              "units": {"length": "mm", "volume": "mm^3"},
              "alignment": "authored coordinates; no automatic alignment or scaling",
              "tessellation": {"linear_deflection_mm": tol, "angular_deflection_rad": ang},
              "samples_each_direction": samples,
              "distance_mm": distances,
              "distance_mm_summary": {"mean": max(d["mean"] for d in both_directions),
                                      "p95": max(d["p95"] for d in both_directions),
                                      "max": max(d["max"] for d in both_directions)},
              "bounds_mm": {"reference": ref_bounds, "reconstruction": rec_bounds,
                            "reference_size": size(ref_bounds), "reconstruction_size": size(rec_bounds),
                            "size_difference": [r - o for r, o in zip(size(rec_bounds), size(ref_bounds))]},
              "volume_mm3": volume,
              "notes": ["Distances are from deterministic surface samples to the closest point on the "
                        "other mesh; they bound nothing and are not a Hausdorff distance.",
                        "Both meshes are chordal approximations: distances below roughly the sum of the "
                        "STL's export deflection and --tol are tessellation noise.",
                        "Bounds and volumes compare the meshes as given; see mode \"solid\" for OCCT "
                        "boolean occupancy differences."],
              "reference_file": str(reference.resolve()), "script": str(script.resolve()),
              "params": result.params}
    outputs = {"report": str(final / "report.json"),
               "reconstruction": str(final / "reconstruction.stl"),
               "script": str(final / "script.py")}
    generated.export(str(work / "reconstruction.stl"))
    (work / "script.py").write_text(source)
    if preview:
        note("rendering shared-camera comparison…")
        render_mesh_comparison(original, generated, work / "comparison.png")
        outputs["preview"] = str(final / "comparison.png")
    report["outputs"] = outputs
    return report


@re.command(name="compare")
@click.argument("reference", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("script", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--out", type=click.Path(path_type=Path), help="New output directory; default: <script>_compare.")
@click.option("--param", "params", multiple=True, metavar="K=V", help="Override a script parameter; repeatable.")
@click.option("--preview/--no-preview", default=True, help="Write aligned views, overlay, and differences.")
@click.option("--tol", default=0.1, type=click.FloatRange(min=0, min_open=True), show_default=True,
              help="Tessellation linear deflection in mm: preview only for .step/.brep, "
                   "the reconstruction mesh itself for .stl.")
@click.option("--ang", default=0.3, type=click.FloatRange(min=0, min_open=True), show_default=True,
              help="Mesh mode (.stl): tessellation angular deflection in radians.")
@click.option("--samples", default=4000, type=click.IntRange(min=1), show_default=True,
              help="Mesh mode (.stl): surface samples per direction.")
@click.option("--boolean-tol", default=1e-6, type=click.FloatRange(min=0, min_open=True), show_default=True,
              help="Solid mode (.step/.brep): OCCT boolean tolerance in mm, not a match threshold.")
@click.pass_context
def compare_command(ctx, reference, script, out, params, preview, tol, ang, samples, boolean_tol):
    """Compare a reference model to a trusted build123d script.

    A .step/.stp/.brep reference runs in solid mode: OCCT booleans report
    missing and extra volume and IoU. A .stl reference runs in mesh mode:
    the script result is tessellated and sampled surface distances are
    reported in both directions. The stdout JSON carries "mode".
    """
    from click.core import ParameterSource
    try:
        suffix = reference.suffix.lower()
        if suffix not in MESH_SUFFIXES + SOLID_SUFFIXES:
            raise ValueError(f"Unsupported extension {suffix!r}. Use .step/.stp/.brep or .stl.")
        mesh_mode = suffix in MESH_SUFFIXES
        if mesh_mode and ctx.get_parameter_source("boolean_tol") is ParameterSource.COMMANDLINE:
            note("warning: --boolean-tol is ignored in mesh mode (.stl reference).")
        overrides = _parse_overrides(params)
        with output_directory(out or Path(f"{script.stem}_compare")) as (work, final):
            if mesh_mode:
                report = _compare_mesh(reference, script, overrides, work, final, preview, tol, ang, samples)
            else:
                report = _compare_solid(reference, script, overrides, work, final, preview, tol, boolean_tol)
            project.write_json(work / "report.json", report)
        emit(report)
    except Exception as exc:
        fail("compare", f"{type(exc).__name__}: {exc}")


# Registered after `re` exists; the module imports the registry only (no kernel).
from lamad.cli.detect import det  # noqa: E402

re.add_command(det)
