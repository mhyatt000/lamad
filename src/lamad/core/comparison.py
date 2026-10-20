"""Solid-set differences; all geometry remains in authored coordinates."""

from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
from OCP.collections import IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher, List_TopoDS_Shape

from lamad.core.inspection import shapes
from lamad.core.metrics import compute
from lamad.core.native_io import quiet_kernel


def volume(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def boolean(kind, a, b, tolerance):
    args, tools = List_TopoDS_Shape(), List_TopoDS_Shape()
    args.Append(a)
    tools.Append(b)
    op = kind()
    op.SetArguments(args)
    op.SetTools(tools)
    op.SetNonDestructive(True)
    op.SetFuzzyValue(tolerance)
    with quiet_kernel():
        op.Build()
    if not op.IsDone() or op.Shape().IsNull():
        raise ValueError("OCCT boolean failed; inspect geometry validity and tolerance.")
    result = op.Shape()
    if not BRepCheck_Analyzer(result).IsValid():
        raise ValueError("OCCT boolean produced invalid geometry.")
    return result


def solid_union(shape, tolerance):
    solids = shapes(shape, TopAbs_SOLID)
    if not solids or not BRepCheck_Analyzer(shape).IsValid():
        raise ValueError("Comparison requires valid solids on both sides; use inspect for surface models.")
    solid_faces = IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher()
    for solid in solids:
        for face in shapes(solid, TopAbs_FACE):
            solid_faces.Add(face)
    if any(not solid_faces.Contains(f) for f in shapes(shape, TopAbs_FACE)):
        raise ValueError("Comparison does not accept loose faces alongside solids.")
    if any(volume(s) <= 0 for s in solids):
        raise ValueError("Comparison requires closed solids with positive volume.")
    result = solids[0]
    for solid in solids[1:]:
        result = boolean(BRepAlgoAPI_Fuse, result, solid, tolerance)
    return result


def compare_shapes(reference, reconstruction, tolerance=1e-6):
    reference = solid_union(reference, tolerance)
    reconstruction = solid_union(reconstruction, tolerance)
    missing = boolean(BRepAlgoAPI_Cut, reference, reconstruction, tolerance)
    extra = boolean(BRepAlgoAPI_Cut, reconstruction, reference, tolerance)
    rv, cv = volume(reference), volume(reconstruction)
    mv, ev = max(0.0, volume(missing)), max(0.0, volume(extra))
    shared = max(0.0, min(rv, cv, rv - mv))
    union = rv + ev
    report = {"units": {"length": "mm", "volume": "mm^3"},
              "alignment": "authored coordinates; no automatic alignment or scaling",
              "boolean_tolerance_mm": tolerance,
              "reference": compute(reference), "reconstruction": compute(reconstruction),
              "difference": {"missing_volume": mv, "extra_volume": ev,
                             "symmetric_difference_volume": mv + ev,
                             "reference_volume": rv, "reconstruction_volume": cv,
                             "intersection_volume": shared, "union_volume": union,
                             "intersection_over_union": shared / union if union else 1.0,
                             "relative_difference": (mv + ev) / rv},
              "notes": ["Overlapping solids are fused before volume comparison.",
                        "Volumes measure solid occupancy, not feature history or maximum surface error.",
                        "Visuals are tessellated approximations; numerical differences use OCCT booleans."]}
    return report, {"reference": reference, "reconstruction": reconstruction,
                    "missing": missing, "extra": extra}
