"""Classify every edge of a shape as line | circle | ellipse | freeform."""

from collections import Counter
import math

from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_EDGE
from OCP.TopExp import TopExp
from OCP.TopoDS import TopoDS

from lamad.core.detect.common import entries, ident, indexed, rounded, xyz

ANALYTIC = {"line": "line", "circle": "circle", "ellipse": "ellipse"}
TYPES = ("line", "circle", "ellipse", "freeform")


def curve_kind(adaptor):
    """Raw GeomAbs name in lower case: line, circle, ellipse, bsplinecurve, ..."""
    return adaptor.GetType().name.removeprefix("GeomAbs_").lower()


def edge_report(edge, eid):
    """Describe one edge. Returns None for degenerate edges (no 3D curve)."""
    edge = TopoDS.Edge(edge)
    if BRep_Tool.Degenerated_s(edge):
        return None
    curve = BRepAdaptor_Curve(edge)
    kind = curve_kind(curve)
    first, last = curve.FirstParameter(), curve.LastParameter()
    props = GProp_GProps()
    BRepGProp.LinearProperties_s(edge, props)
    closed = TopExp.FirstVertex_s(edge).IsSame(TopExp.LastVertex_s(edge))
    result = {"id": eid, "type": ANALYTIC.get(kind, "freeform"), "curve": kind,
              "length": rounded(props.Mass()),
              "start": xyz(curve.Value(first)), "end": xyz(curve.Value(last)),
              "closed": bool(closed)}
    if kind == "circle":
        circ = curve.Circle()
        center, normal = circ.Location(), circ.Axis().Direction()
        result.update(center=xyz(center), radius=rounded(circ.Radius()), normal=xyz(normal),
                      axis={"origin": xyz(center), "direction": xyz(normal)},
                      sweep_degrees=rounded(math.degrees(last - first)))
    elif kind == "ellipse":
        ell = curve.Ellipse()
        center, normal = ell.Location(), ell.Axis().Direction()
        result.update(center=xyz(center), major_radius=rounded(ell.MajorRadius()),
                      minor_radius=rounded(ell.MinorRadius()), normal=xyz(normal),
                      major_axis=xyz(ell.XAxis().Direction()),
                      axis={"origin": xyz(center), "direction": xyz(normal)},
                      sweep_degrees=rounded(math.degrees(last - first)))
    elif kind == "line":
        result["direction"] = xyz(curve.Line().Direction())
    return result


def detect_edges(shape):
    """All non-degenerate edges of `shape` with stable ids e1..eN.

    Returns (summary, edges). Degenerate edges (sphere poles, cone apexes)
    carry no 3D curve and are counted in summary["degenerate_skipped"].
    """
    table = indexed(shape, TopAbs_EDGE)
    reports, skipped = [], 0
    for i, edge in enumerate(entries(table), start=1):
        item = edge_report(edge, ident(TopAbs_EDGE, i))
        if item is None:
            skipped += 1
        else:
            reports.append(item)
    counts = Counter(e["type"] for e in reports)
    summary = {"total": len(reports), "by_type": {t: counts.get(t, 0) for t in TYPES},
               "closed": sum(1 for e in reports if e["closed"]), "degenerate_skipped": skipped}
    return summary, reports
