"""Geometric metrics from a TopoDS_Shape."""

from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.BRepTools import BRepTools
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SOLID
from OCP.TopExp import TopExp
from OCP.collections import IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher


def _count(shape, kind):
    m = IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher()
    TopExp.MapShapes_s(shape, kind, m)
    return m.Extent()


def compute(shape):
    """Return a JSON-serializable dict of geometric measurements."""
    # AddOptimal_s, not Add_s: Add_s derives bounds from B-spline control
    # points, which sit outside the real trimmed surface. STEP files are full
    # of NURBS, so Add_s can overstate dimensions badly. Clean_s first to drop
    # cached triangulation that AddOptimal would otherwise prefer.
    BRepTools.Clean_s(shape)
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, box)
    # OCP 8 returns Bnd_Box::Limits from Get(), which has no Python binding;
    # the corner accessors include the gap exactly as Get() did.
    lo, hi = box.CornerMin(), box.CornerMax()
    xmin, ymin, zmin, xmax, ymax, zmax = lo.X(), lo.Y(), lo.Z(), hi.X(), hi.Y(), hi.Z()

    vol = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, vol)
    com = vol.CentreOfMass()

    area = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, area)

    r = lambda v: round(v, 4)  # noqa: E731
    analyzer = BRepCheck_Analyzer(shape)
    out = {
        "bounding_box": {
            "x": [r(xmin), r(xmax)],
            "y": [r(ymin), r(ymax)],
            "z": [r(zmin), r(zmax)],
        },
        "dimensions": {"x": r(xmax - xmin), "y": r(ymax - ymin), "z": r(zmax - zmin)},
        "volume": r(vol.Mass()),
        "surface_area": r(area.Mass()),
        "center_of_mass": {"x": r(com.X()), "y": r(com.Y()), "z": r(com.Z())},
        "solid_count": _count(shape, TopAbs_SOLID),
        "face_count": _count(shape, TopAbs_FACE),
        "edge_count": _count(shape, TopAbs_EDGE),
        "is_valid": analyzer.IsValid(),
    }
    if out["volume"] < 0:
        out["warning"] = (
            "Negative volume — inverted normals. Check wire winding order "
            "(counter-clockwise in XY gives a +Z normal)."
        )
    return out
