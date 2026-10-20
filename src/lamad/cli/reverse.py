"""Reverse-engineering commands (`lamad re ...`); no project manifest required."""

from contextlib import contextmanager, redirect_stdout
from dataclasses import dataclass
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
@click.option("--out", type=click.Path(path_type=Path), help="New output directory; default: <reference dir>/<stem>_inspect/.")
@click.option("--preview/--no-preview", default=True, help="Write labeled orthographic views.")
@click.option("--tol", default=0.1, type=click.FloatRange(min=0, min_open=True), show_default=True,
              help="Preview tessellation deflection in mm; does not affect measurements.")
def inspect_command(reference, out, preview, tol):
    """Describe STEP assembly, solids, analytic faces, and face adjacency."""
    from lamad.core.inspection import inspect_step
    try:
        with output_directory(out or reference.parent / f"{reference.stem}_inspect") as (work, final):
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


def _select(parts, names, flag):
    """Parts whose name equals a NAME, else contains it case-insensitively; order kept, no repeats."""
    chosen = []
    for wanted in names:
        hits = ([p for p in parts if p["name"] == wanted]
                or [p for p in parts if wanted.lower() in p["name"].lower()])
        if not hits:
            available = ", ".join(repr(p["name"]) for p in parts)
            raise ValueError(f"{flag} {wanted!r} matches no part. Available: {available}")
        chosen.extend(h for h in hits if not any(h is c for c in chosen))
    return chosen


def _summary(parts):
    return [{"id": p["id"], "name": p["name"]} for p in parts] if parts is not None else None


def _whole(parts):
    from lamad.core.runner import _compound
    return parts[0]["shape"] if len(parts) == 1 else _compound([p["shape"] for p in parts])


@dataclass
class Reference:
    shape: object          # what the booleans compare: selected parts, non-solids dropped
    faces: object          # coverage side: parts with `re inspect` ids, or the bare shape
    selected: list | None
    available: list | None
    dropped: int

    def section(self):
        return {"selected_parts": _summary(self.selected), "available_parts": _summary(self.available),
                "dropped_non_solids": self.dropped}


@dataclass
class Reconstruction:
    source: str
    result: object         # runner.Result (params, every show_object part)
    shape: object          # the selected parts, or the whole model
    parts: list            # selected [{id, name, color, shape}]; ids p1.. follow show_object order
    selected: list | None

    def section(self):
        return {"selected_parts": _summary(self.selected),
                "available_parts": [{"id": f"p{i}", "name": p["name"]}
                                    for i, p in enumerate(self.result.parts, start=1)]}


def _load_reference(reference, ref_parts, solids_only):
    """STEP/BREP reference: assembly parts give `re inspect` face ids and --ref-part names."""
    from lamad.core.comparison import drop_non_solids, non_solid_count
    from lamad.core.inspection import read_assembly, shapes
    from lamad.core.step_io import load_shape
    from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
    parts = None
    if reference.suffix.lower() in (".step", ".stp"):
        try:
            with quiet_kernel():
                _, parts = read_assembly(reference)
        except ValueError as exc:
            if ref_parts:
                raise ValueError(f"--ref-part needs a readable STEP assembly: {exc}") from exc
            note(f"warning: assembly names unavailable ({exc}); face ids follow `re det faces`.")
    elif ref_parts:
        raise ValueError("--ref-part needs a STEP assembly; a .brep reference carries no part names.")
    selected = _select(parts, ref_parts, "--ref-part") if ref_parts else None
    chosen = selected if selected is not None else parts
    if chosen is not None:
        shape = _whole(chosen)
    else:
        with quiet_kernel():
            shape = load_shape(reference)
    dropped = 0
    if solids_only:
        shape, dropped = drop_non_solids(shape)
        note(f"--solids-only: dropped {dropped} non-solid shape(s) from the reference.")
        if not shapes(shape, TopAbs_SOLID):
            raise ValueError(f"{reference.name} has no solids once its {dropped} non-solid shape(s) "
                             "are dropped; use inspect for surface models.")
        if chosen is not None:
            chosen = [dict(p, faces=shapes(drop_non_solids(p["shape"])[0], TopAbs_FACE)) for p in chosen]
    elif non_solid_count(shape):
        raise ValueError(f"{reference.name} holds {non_solid_count(shape)} non-solid shape(s) "
                         "(free faces, shells, or wires) next to its solids; pass --solids-only "
                         "to drop them and compare the solids.")
    return Reference(shape, chosen if chosen is not None else shape, selected, parts, dropped)


def _load_reconstruction(script, overrides, part_names):
    """Run the script; --part keeps only the named show_object parts."""
    source, result = _run_script(script, overrides)
    parts = [{"id": f"p{i}", **p} for i, p in enumerate(result.parts, start=1)]
    selected = _select(parts, part_names, "--part") if part_names else None
    chosen = selected if selected is not None else parts
    shape = result.shape if selected is None else _whole(chosen)
    return Reconstruction(source, result, shape, chosen, selected)


def _note_coverage(coverage):
    for side in ("reference", "reconstruction"):
        s = coverage.get(side)
        if s:
            fraction = s["area_matched_fraction"]
            area = f", {100 * fraction:.1f}% of area" if fraction is not None else ""
            note(f"coverage: {side} {s['matched']}/{s['faces_total']} faces matched within "
                 f"{coverage['tol_mm']} mm{area}.")


def _compare_solid(reference, rec, work, final, preview, tol, boolean_tol, coverage_tol):
    """STEP/BREP reference: OCCT booleans give missing/extra volumes and IoU."""
    from lamad.core.comparison import compare_shapes
    from lamad.core.inspection import shapes
    from OCP.TopAbs import TopAbs_SOLID
    note("computing missing and extra material…")
    with quiet_kernel():
        report, geometry = compare_shapes(reference.shape, rec.shape, boolean_tol)
    report["reference"].update(reference.section())
    report["reconstruction"].update(rec.section())
    if coverage_tol:
        from lamad.core.coverage import face_coverage
        note("sampling face coverage both ways…")
        with quiet_kernel():
            report["coverage"] = face_coverage(reference.faces, rec.parts, coverage_tol)
        _note_coverage(report["coverage"])
    outputs = {"report": str(final / "report.json"),
               "reconstruction": str(final / "reconstruction.step"),
               "script": str(final / "script.py")}
    export.export_step(rec.shape, work / "reconstruction.step", parts=rec.parts)
    (work / "script.py").write_text(rec.source)
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


def _compare_mesh(original, rec, work, final, preview, tol, ang, samples, coverage_tol):
    """STL reference: sampled surface distances between two triangle meshes."""
    from lamad.core.mesh_compare import body_mesh, compare_meshes, render_mesh_comparison
    note(f"tessellating reconstruction and sampling {samples} surface points each way…")
    with quiet_kernel():
        generated = body_mesh(rec.shape, tol, ang)
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
              "reference": {"selected_parts": None, "available_parts": None},
              "reconstruction": rec.section(),
              "notes": ["Distances are from deterministic surface samples to the closest point on the "
                        "other mesh; they bound nothing and are not a Hausdorff distance.",
                        "Both meshes are chordal approximations: distances below roughly the sum of the "
                        "STL's export deflection and --tol are tessellation noise.",
                        "Bounds and volumes compare the meshes as given; see mode \"solid\" for OCCT "
                        "boolean occupancy differences."]}
    if coverage_tol:
        from lamad.core.coverage import mesh_coverage
        note("sampling reconstruction faces against the reference mesh…")
        with quiet_kernel():
            report["coverage"] = mesh_coverage(rec.parts, original, coverage_tol)
        _note_coverage(report["coverage"])
    outputs = {"report": str(final / "report.json"),
               "reconstruction": str(final / "reconstruction.stl"),
               "script": str(final / "script.py")}
    generated.export(str(work / "reconstruction.stl"))
    (work / "script.py").write_text(rec.source)
    if preview:
        note("rendering shared-camera comparison…")
        render_mesh_comparison(original, generated, work / "comparison.png")
        outputs["preview"] = str(final / "comparison.png")
    report["outputs"] = outputs
    return report


def _finish(report, command, reference, script, rec):
    report.update(command=command, status="success", reference_file=str(reference.resolve()),
                  script=str(script.resolve()), params=rec.result.params)
    return report


def _check_suffix(reference):
    suffix = reference.suffix.lower()
    if suffix not in MESH_SUFFIXES + SOLID_SUFFIXES:
        raise ValueError(f"Unsupported extension {suffix!r}. Use .step/.stp/.brep or .stl.")
    return suffix in MESH_SUFFIXES


def _part_options(command):
    for option in (
        click.option("--part", "part_names", multiple=True, metavar="NAME",
                     help="Compare only the show_object part(s) named NAME (exact, else case-insensitive "
                          "substring); repeatable. An unknown name lists the available parts."),
        click.option("--ref-part", "ref_parts", multiple=True, metavar="NAME",
                     help="Solid mode (.step): use only the reference assembly part(s) named NAME "
                          "(exact, else case-insensitive substring); repeatable."),
    ):
        command = option(command)
    return command


@re.command(name="compare")
@click.argument("reference", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("script", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--out", type=click.Path(path_type=Path), help="New output directory; default: <script dir>/<stem>_compare/.")
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
@click.option("--solids-only", is_flag=True,
              help="Solid mode (.step/.brep): drop free faces, shells, and wires from the reference "
                   "(e.g. cosmetic thread surfaces) instead of refusing it.")
@click.option("--coverage/--no-coverage", default=True, show_default=True,
              help="Face coverage: list the reference faces the script misses and vice versa "
                   "(solid mode both ways; mesh mode reconstruction faces only).")
@click.option("--coverage-tol", default=0.1, type=click.FloatRange(min=0, min_open=True), show_default=True,
              help="Face coverage match tolerance in mm: a face is matched when the 95th percentile "
                   "of its sampled distances to the other side is within it.")
@_part_options
@click.pass_context
def compare_command(ctx, reference, script, out, params, preview, tol, ang, samples, boolean_tol,
                    solids_only, coverage, coverage_tol, part_names, ref_parts):
    """Compare a reference model to a trusted build123d script.

    A .step/.stp/.brep reference runs in solid mode: OCCT booleans report
    missing and extra volume and IoU, and face coverage lists which
    reference faces the script does not reproduce (and which script faces
    the reference lacks). A .stl reference runs in mesh mode: the script
    result is tessellated and sampled surface distances are reported in
    both directions. The stdout JSON carries "mode".
    """
    from click.core import ParameterSource
    try:
        mesh_mode = _check_suffix(reference)
        if mesh_mode and ctx.get_parameter_source("boolean_tol") is ParameterSource.COMMANDLINE:
            note("warning: --boolean-tol is ignored in mesh mode (.stl reference).")
        if mesh_mode and solids_only:
            note("warning: --solids-only is ignored in mesh mode (.stl reference).")
        if mesh_mode and ref_parts:
            note("warning: --ref-part is ignored in mesh mode (an .stl has no parts).")
        overrides = _parse_overrides(params)
        coverage_tol = coverage_tol if coverage else None
        with output_directory(out or script.parent / f"{script.stem}_compare") as (work, final):
            note("loading reference and executing reconstruction…")
            if mesh_mode:
                from lamad.core.mesh_compare import load_mesh
                original = load_mesh(reference)
                rec = _load_reconstruction(script, overrides, part_names)
                report = _compare_mesh(original, rec, work, final, preview, tol, ang, samples, coverage_tol)
            else:
                original = _load_reference(reference, ref_parts, solids_only)
                rec = _load_reconstruction(script, overrides, part_names)
                report = _compare_solid(original, rec, work, final, preview, tol, boolean_tol, coverage_tol)
                report["mode"] = "solid"
            _finish(report, "compare", reference, script, rec)
            project.write_json(work / "report.json", report)
        emit(report)
    except Exception as exc:
        fail("compare", f"{type(exc).__name__}: {exc}")


@re.command(name="coverage")
@click.argument("reference", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("script", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--out", type=click.Path(path_type=Path), help="New output directory; default: <script dir>/<stem>_coverage/.")
@click.option("--param", "params", multiple=True, metavar="K=V", help="Override a script parameter; repeatable.")
@click.option("--tol", default=0.1, type=click.FloatRange(min=0, min_open=True), show_default=True,
              help="Match tolerance in mm: a face is matched when the 95th percentile of its "
                   "sampled distances to the other side is within it.")
@click.option("--solids-only", is_flag=True,
              help="Solid mode (.step/.brep): drop free faces, shells, and wires from the reference.")
@_part_options
def coverage_command(reference, script, out, params, tol, solids_only, part_names, ref_parts):
    """List the reference faces a build123d script does not reproduce, and vice versa.

    Only the face-coverage section of `re compare`, without booleans or
    previews: each unmatched face carries its surface type, analytic
    parameters, area, centroid, and sampled distances, largest area first.
    A .stl reference covers the reconstruction's faces only.
    """
    try:
        mesh_mode = _check_suffix(reference)
        if mesh_mode and solids_only:
            note("warning: --solids-only is ignored for an .stl reference.")
        if mesh_mode and ref_parts:
            note("warning: --ref-part is ignored for an .stl reference (no parts).")
        overrides = _parse_overrides(params)
        with output_directory(out or script.parent / f"{script.stem}_coverage") as (work, final):
            note("loading reference and executing reconstruction…")
            if mesh_mode:
                from lamad.core.coverage import mesh_coverage
                from lamad.core.mesh_compare import load_mesh
                original = load_mesh(reference)
                rec = _load_reconstruction(script, overrides, part_names)
                note("sampling reconstruction faces against the reference mesh…")
                with quiet_kernel():
                    section = mesh_coverage(rec.parts, original, tol)
                reference_section = {"selected_parts": None, "available_parts": None}
            else:
                from lamad.core.coverage import face_coverage
                original = _load_reference(reference, ref_parts, solids_only)
                rec = _load_reconstruction(script, overrides, part_names)
                note("sampling face coverage both ways…")
                with quiet_kernel():
                    section = face_coverage(original.faces, rec.parts, tol)
                reference_section = original.section()
            _note_coverage(section)
            report = {"mode": "mesh" if mesh_mode else "solid",
                      "reference": reference_section, "reconstruction": rec.section(),
                      "coverage": section, "outputs": {"report": str(final / "report.json")}}
            _finish(report, "coverage", reference, script, rec)
            project.write_json(work / "report.json", report)
        emit(report)
    except Exception as exc:
        fail("coverage", f"{type(exc).__name__}: {exc}")


# Registered after `re` exists; the module imports the registry only (no kernel).
from lamad.cli.detect import det  # noqa: E402

re.add_command(det)
