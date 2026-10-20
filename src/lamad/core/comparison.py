"""Solid-set differences; all geometry remains in authored coordinates."""

from OCP.BOPAlgo import BOPAlgo_GlueFull, BOPAlgo_GlueShift
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_COMPOUND, TopAbs_COMPSOLID, TopAbs_FACE, TopAbs_SOLID
from OCP.TopoDS import TopoDS_Iterator
from OCP.collections import IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher, List_TopoDS_Shape

from lamad.core.inspection import shapes
from lamad.core.metrics import compute
from lamad.core.native_io import quiet_kernel
from lamad.core.runner import _compound

# Retried in this order when OCCT rejects a boolean (typically exactly coincident
# faces): glue modes tell the algorithm the arguments share faces, and a larger
# fuzzy value lets near-coincident geometry merge.
STRATEGIES = ("plain", "glue-shift", "glue-full", "fuzzy")


def volume(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def _attempt(kind, a, b, tolerance, strategy):
    """One boolean build; None when OCCT fails or produces invalid geometry."""
    args, tools = List_TopoDS_Shape(), List_TopoDS_Shape()
    args.Append(a)
    tools.Append(b)
    op = kind()
    op.SetArguments(args)
    op.SetTools(tools)
    op.SetNonDestructive(True)
    op.SetFuzzyValue(tolerance * 10 if strategy == "fuzzy" else tolerance)
    if strategy == "glue-shift":
        op.SetGlue(BOPAlgo_GlueShift)
    elif strategy == "glue-full":
        op.SetGlue(BOPAlgo_GlueFull)
    with quiet_kernel():
        op.Build()
    if not op.IsDone() or op.Shape().IsNull():
        return None
    result = op.Shape()
    if not BRepCheck_Analyzer(result).IsValid():
        return None
    if kind is BRepAlgoAPI_Fuse and not shapes(result, TopAbs_SOLID):
        return None  # a fuse of solids can never be empty
    return result


def boolean(kind, a, b, tolerance, used=None):
    """Run a boolean, retrying through STRATEGIES; record the one that worked in `used`."""
    for strategy in STRATEGIES:
        result = _attempt(kind, a, b, tolerance, strategy)
        if result is not None:
            if used is not None:
                used.append(strategy)
            return result
    raise ValueError("OCCT boolean failed after retrying with glue-shift, glue-full, and a 10x fuzzy "
                     "value; inspect geometry validity and --boolean-tol.")


def _top_level(shape):
    """Members of nested compounds, flattened; a bare shape is its own member."""
    if shape.ShapeType() != TopAbs_COMPOUND:
        return [shape]
    members, it = [], TopoDS_Iterator(shape)
    while it.More():
        members.extend(_top_level(it.Value()))
        it.Next()
    return members


def non_solid_count(shape):
    """Top-level members that are not solids (free faces, shells, wires, ...)."""
    return sum(m.ShapeType() not in (TopAbs_SOLID, TopAbs_COMPSOLID) for m in _top_level(shape))


def drop_non_solids(shape):
    """Keep only the solid top-level members. Returns (compound of solids, dropped count)."""
    members = _top_level(shape)
    solids = [m for m in members if m.ShapeType() in (TopAbs_SOLID, TopAbs_COMPSOLID)]
    return _compound(solids), len(members) - len(solids)


def solid_union(shape, tolerance, used=None):
    solids = shapes(shape, TopAbs_SOLID)
    if not solids or not BRepCheck_Analyzer(shape).IsValid():
        raise ValueError("Comparison requires valid solids on both sides; use inspect for surface models.")
    solid_faces = IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher()
    for solid in solids:
        for face in shapes(solid, TopAbs_FACE):
            solid_faces.Add(face)
    if any(not solid_faces.Contains(f) for f in shapes(shape, TopAbs_FACE)):
        raise ValueError("Comparison does not accept loose faces or shells alongside solids "
                         "(for a reference file, `lamad re compare --solids-only` drops them).")
    if any(volume(s) <= 0 for s in solids):
        raise ValueError("Comparison requires closed solids with positive volume.")
    result = solids[0]
    for solid in solids[1:]:
        result = boolean(BRepAlgoAPI_Fuse, result, solid, tolerance, used)
    return result


def compare_shapes(reference, reconstruction, tolerance=1e-6):
    used = []
    reference = solid_union(reference, tolerance, used)
    reconstruction = solid_union(reconstruction, tolerance, used)
    missing = boolean(BRepAlgoAPI_Cut, reference, reconstruction, tolerance, used)
    extra = boolean(BRepAlgoAPI_Cut, reconstruction, reference, tolerance, used)
    strategy = max(used, key=STRATEGIES.index)
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
                             "relative_difference": (mv + ev) / rv,
                             "boolean_strategy": strategy},
              "notes": ["Overlapping solids are fused before volume comparison.",
                        "Volumes measure solid occupancy, not feature history or maximum surface error.",
                        "Visuals are tessellated approximations; numerical differences use OCCT booleans.",
                        "boolean_strategy is the most permissive OCCT setting any boolean here needed: "
                        "plain, glue-shift, glue-full (coincident faces), or fuzzy (10x --boolean-tol)."]}
    return report, {"reference": reference, "reconstruction": reconstruction,
                    "missing": missing, "extra": extra}
