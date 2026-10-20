"""Feature detection commands (`lamad re det ...`).

Every command prints exactly one JSON object on stdout; progress goes to
stderr. The help epilog and the `status` command are generated from
`lamad.core.detect.FEATURES`, so the printed support table cannot drift from
what the detectors implement. Kernel-heavy imports stay inside the commands.
"""

import json
from pathlib import Path

import click

from lamad.cli import HelpGroup, emit, fail, note
from lamad.core.detect import DEFAULT_ANGLE_TOL, rows_for, support_matrix, support_table

B_REP = (".step", ".stp", ".brep")


class TableGroup(HelpGroup):
    """HelpGroup whose epilog is written verbatim (click would re-wrap a table)."""

    def format_epilog(self, ctx, formatter):
        if self.epilog:
            formatter.write_paragraph()
            with formatter.indentation():
                for line in self.epilog.splitlines():
                    formatter.write(" " * formatter.current_indent + line + "\n")


@click.group(name="det", cls=TableGroup, epilog="Feature support (step = .step/.stp/.brep):\n\n" + support_table())
def det():
    """Detect edges, corners, and faces in a STEP/BREP file. STL is planned."""


def check_input(command, path, group=None):
    """Reject inputs the detectors cannot read yet with the matching registry rows."""
    suffix = path.suffix.lower()
    if suffix == ".stl":
        fail(command, "STL feature detection is planned; mesh input is not supported yet. "
                      "Convert to STEP/BREP or wait for the stl column to read 'done'.",
             file=str(path.resolve()), support=rows_for(group))
    if suffix not in B_REP:
        fail(command, f"Unsupported extension {suffix!r}. Use .step/.stp/.brep.",
             file=str(path.resolve()))


def load(path):
    from lamad.core.native_io import quiet_kernel
    from lamad.core.step_io import load_shape
    note(f"loading {path.name}…")
    with quiet_kernel():
        return load_shape(path)


def finish(payload, out):
    if out:
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2) + "\n")
        payload["outputs"] = {"json": str(out.resolve())}
    emit(payload)


file_argument = click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
out_option = click.option("--out", type=click.Path(path_type=Path), help="Also write the JSON to this file.")
angle_option = click.option("--angle-tol", default=DEFAULT_ANGLE_TOL, show_default=True,
                            type=click.FloatRange(min=0, max=180),
                            help="Edges whose outward normals differ by more than this (degrees) are sharp.")


@det.command(name="edges")
@file_argument
@out_option
def edges_command(file, out):
    """Classify every edge: line, circle, ellipse, or freeform."""
    command = "det.edges"
    check_input(command, file, "edges")
    try:
        from lamad.core.detect.edges import detect_edges
        from lamad.core.native_io import quiet_kernel
        shape = load(file)
        note("classifying edges…")
        with quiet_kernel():
            summary, items = detect_edges(shape)
        finish({"command": command, "status": "success", "file": str(file.resolve()),
                "summary": summary, "edges": items}, out)
    except Exception as exc:
        fail(command, f"{type(exc).__name__}: {exc}")


@det.command(name="corners")
@file_argument
@angle_option
@out_option
def corners_command(file, angle_tol, out):
    """Find sharp edges (convex/concave dihedral angle) and corner vertices."""
    command = "det.corners"
    check_input(command, file, "corners")
    try:
        from lamad.core.detect.corners import detect_corners
        from lamad.core.native_io import quiet_kernel
        shape = load(file)
        note("measuring dihedral angles…")
        with quiet_kernel():
            summary, sharp, corners = detect_corners(shape, angle_tol)
        finish({"command": command, "status": "success", "file": str(file.resolve()),
                "summary": summary, "sharp_edges": sharp, "corners": corners}, out)
    except Exception as exc:
        fail(command, f"{type(exc).__name__}: {exc}")


@det.command(name="faces")
@file_argument
@out_option
def faces_command(file, out):
    """Classify every face: plane, cylinder, cone, sphere, torus, or freeform."""
    command = "det.faces"
    check_input(command, file, "faces")
    try:
        from lamad.core.detect.faces import detect_faces
        from lamad.core.native_io import quiet_kernel
        shape = load(file)
        note("classifying faces…")
        with quiet_kernel():
            summary, items = detect_faces(shape)
        finish({"command": command, "status": "success", "file": str(file.resolve()),
                "summary": summary, "faces": items}, out)
    except Exception as exc:
        fail(command, f"{type(exc).__name__}: {exc}")


@det.command(name="all")
@file_argument
@angle_option
@out_option
def all_command(file, angle_tol, out):
    """Run edges, corners, and faces detection in one pass."""
    command = "det.all"
    check_input(command, file)
    try:
        from lamad.core.detect.corners import detect_corners
        from lamad.core.detect.edges import detect_edges
        from lamad.core.detect.faces import detect_faces
        from lamad.core.native_io import quiet_kernel
        shape = load(file)
        note("detecting edges, corners, and faces…")
        with quiet_kernel():
            edge_summary, edges = detect_edges(shape)
            corner_summary, sharp, corners = detect_corners(shape, angle_tol)
            face_summary, faces = detect_faces(shape)
        finish({"command": command, "status": "success", "file": str(file.resolve()),
                "summary": {"edges": edge_summary, "corners": corner_summary, "faces": face_summary},
                "edges": edges, "sharp_edges": sharp, "corners": corners, "faces": faces}, out)
    except Exception as exc:
        fail(command, f"{type(exc).__name__}: {exc}")


@det.command(name="status")
def status_command():
    """Print the feature support matrix (step and stl columns) as JSON."""
    emit({"command": "det.status", "status": "success", "columns": ["feature", "step", "stl"],
          "features": support_matrix()})
