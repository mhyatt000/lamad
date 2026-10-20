"""Feature detection on B-rep shapes (`lamad re det ...`).

This package is intentionally free of OCP imports so the registry below can be
read (for `--help` and `status`) without loading the CAD kernel. The detectors
in `edges`, `corners`, and `faces` import OCP when they are imported.

FEATURES is the single source of truth for what the `det` commands support:
the help epilog, the `status` command, and the STL "planned" errors are all
generated from it so they cannot drift apart.
"""

# Each row: name, group, description, step status, stl status.
# `step` covers .step/.stp/.brep input (B-rep); `stl` covers meshes.
FEATURES = [
    {"name": "edges/line", "group": "edges", "step": "done", "stl": "planned",
     "description": "Straight edges with start/end points and length."},
    {"name": "edges/circle", "group": "edges", "step": "done", "stl": "planned",
     "description": "Circular edges and arcs with center, radius, and axis."},
    {"name": "edges/ellipse", "group": "edges", "step": "done", "stl": "planned",
     "description": "Elliptical edges with center, radii, and axis."},
    {"name": "edges/freeform", "group": "edges", "step": "done", "stl": "planned",
     "description": "B-spline, Bezier, and other non-analytic edges."},
    {"name": "corners/sharp-edge", "group": "corners", "step": "done", "stl": "planned",
     "description": "Edges whose dihedral angle deviates from 180 deg; convex or concave."},
    {"name": "corners/vertex", "group": "corners", "step": "done", "stl": "planned",
     "description": "Vertices where three or more sharp edges meet."},
    {"name": "faces/plane", "group": "faces", "step": "done", "stl": "planned",
     "description": "Planar faces with origin and outward normal."},
    {"name": "faces/cylinder", "group": "faces", "step": "done", "stl": "planned",
     "description": "Cylindrical faces with axis and radius."},
    {"name": "faces/cone", "group": "faces", "step": "done", "stl": "planned",
     "description": "Conical faces with axis, reference radius, and semi-angle."},
    {"name": "faces/sphere", "group": "faces", "step": "done", "stl": "planned",
     "description": "Spherical faces with center and radius."},
    {"name": "faces/torus", "group": "faces", "step": "done", "stl": "planned",
     "description": "Toroidal faces with axis and major/minor radii."},
    {"name": "faces/freeform", "group": "faces", "step": "done", "stl": "planned",
     "description": "B-spline, Bezier, swept, and other non-analytic faces."},
    {"name": "fillet", "group": "features", "step": "planned", "stl": "planned",
     "description": "Constant-radius blends inferred from tangent cylinder/torus faces."},
    {"name": "chamfer", "group": "features", "step": "planned", "stl": "planned",
     "description": "Bevels inferred from narrow planar faces between sharp edges."},
    {"name": "hole", "group": "features", "step": "planned", "stl": "planned",
     "description": "Cylindrical cuts with axis, diameter, depth, and through/blind."},
    {"name": "boss", "group": "features", "step": "planned", "stl": "planned",
     "description": "Raised cylindrical or prismatic features on a face."},
    {"name": "pattern", "group": "features", "step": "planned", "stl": "planned",
     "description": "Linear and circular repeats of a detected feature."},
]

COLUMNS = ("feature", "step", "stl")

# Default sharp-edge threshold in degrees; mirrored here so the CLI help
# can show it without importing the OCP-backed corners module.
DEFAULT_ANGLE_TOL = 10.0


def support_matrix():
    """JSON-able copy of the registry."""
    return [dict(row) for row in FEATURES]


def rows_for(group=None):
    """Registry rows for one group (`edges`, `corners`, `faces`), or all rows."""
    return [dict(r) for r in FEATURES if group is None or r["group"] == group]


def support_table():
    """Plain-text table: feature, step, stl. One row per registry entry."""
    rows = [(r["name"], r["step"], r["stl"]) for r in FEATURES]
    widths = [max(len(c[i]) for c in rows + [COLUMNS]) for i in range(3)]
    line = "  ".join(f"{COLUMNS[i]:<{widths[i]}}" for i in range(3)).rstrip()
    rule = "  ".join("-" * w for w in widths)
    body = ["  ".join(f"{cell:<{widths[i]}}" for i, cell in enumerate(row)).rstrip() for row in rows]
    return "\n".join([line, rule, *body])
