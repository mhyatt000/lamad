"""Measured STEP topology for reconstructing editable build123d models."""

from collections import Counter
from pathlib import Path

from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label
from OCP.TDocStd import TDocStd_Document
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_REVERSED, TopAbs_SOLID
from OCP.TopExp import TopExp
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.collections import IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher, Sequence_TDF_Label

from lamad.core.metrics import compute
from lamad.core.native_io import quiet_kernel
from lamad.core.runner import _compound


def shapes(shape, kind):
    table = IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher()
    TopExp.MapShapes_s(shape, kind, table)
    return [table.FindKey(i) for i in range(1, table.Extent() + 1)]


def xyz(point):
    return [round(point.X(), 7), round(point.Y(), 7), round(point.Z(), 7)]


def read_assembly(path):
    """Return a named tree and globally positioned leaves, including instances."""
    doc = TDocStd_Document(TCollection_ExtendedString("lamad-inspect"))
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    with quiet_kernel():
        if reader.ReadFile(str(path)) != IFSelect_RetDone or not reader.Transfer(doc):
            raise ValueError(f"Could not read {path} as STEP.")
    tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    parts = []

    def name(label):
        attr = TDataStd_Name()
        nm = attr.Get().ToExtString() if label.FindAttribute(TDataStd_Name.GetID_s(), attr) else None
        if nm in (None, "", "?", "SOLID", "SHELL", "COMPOUND", "ASSEMBLY") or nm.startswith("=>"):
            return None
        return nm

    def walk(label, location, inherited=None):
        ref = TDF_Label()
        target = ref if tool.GetReferredShape_s(label, ref) else label
        nm = name(label) or name(target) or inherited or "unnamed"
        seq = Sequence_TDF_Label()
        tool.GetComponents_s(target, seq)
        node = {"name": nm, "children": []}
        if seq.Length():
            location = location.Multiplied(tool.GetLocation_s(label))
            node["children"] = [walk(seq.Value(i), location, nm)
                                for i in range(1, seq.Length() + 1)]
        else:
            shape = tool.GetShape_s(label).Moved(location)
            if shape.IsNull() or not shapes(shape, TopAbs_FACE):
                raise ValueError(f"Part {nm!r} contains no faces.")
            pid = f"p{len(parts) + 1}"
            node["part_id"] = pid
            parts.append({"id": pid, "name": nm, "shape": shape})
        return node

    roots = Sequence_TDF_Label()
    tool.GetFreeShapes(roots)
    tree = [walk(roots.Value(i), TopLoc_Location()) for i in range(1, roots.Length() + 1)]
    if not parts:
        raise ValueError("STEP contains no geometric parts.")
    return tree, parts


def face_report(face, fid):
    face = TopoDS.Face(face)
    surface = BRepAdaptor_Surface(face, True)
    kind = surface.GetType().name.removeprefix("GeomAbs_").lower()
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    result = {"id": fid, "surface": kind, "area": round(props.Mass(), 7),
              "centroid": xyz(props.CentreOfMass()),
              "orientation": "reversed" if face.Orientation() == TopAbs_REVERSED else "forward"}
    if kind == "plane":
        plane = surface.Plane()
        normal = plane.Axis().Direction()
        if face.Orientation() == TopAbs_REVERSED:
            normal.Reverse()
        result.update(origin=xyz(plane.Location()), normal=xyz(normal))
    elif kind in ("cylinder", "cone", "sphere", "torus"):
        analytic = getattr(surface, kind.title())()
        result.update(origin=xyz(analytic.Location()), axis=xyz(analytic.Position().Direction()))
        if kind in ("cylinder", "sphere"):
            result["radius"] = round(analytic.Radius(), 7)
        elif kind == "cone":
            result.update(reference_radius=round(analytic.RefRadius(), 7),
                          semi_angle_radians=round(analytic.SemiAngle(), 7))
        else:
            result.update(major_radius=round(analytic.MajorRadius(), 7),
                          minor_radius=round(analytic.MinorRadius(), 7))
    result["uv_bounds"] = [surface.FirstUParameter(), surface.LastUParameter(),
                           surface.FirstVParameter(), surface.LastVParameter()]
    return result


def inspect_step(path):
    tree, parts = read_assembly(path)
    report_parts, render_items = [], []
    for part in parts:
        shape, pid = part["shape"], part["id"]
        faces = shapes(shape, TopAbs_FACE)
        face_map = IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher()
        TopExp.MapShapes_s(shape, TopAbs_FACE, face_map)
        reports = [face_report(f, f"{pid}:f{i + 1}") for i, f in enumerate(faces)]
        edge_map = IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher()
        TopExp.MapShapes_s(shape, TopAbs_EDGE, edge_map)
        owners = {}
        for i, face in enumerate(faces):
            for edge in shapes(face, TopAbs_EDGE):
                owners.setdefault(edge_map.FindIndex(edge), set()).add(i)
        neighbors = [set() for _ in faces]
        for indices in owners.values():
            for i in indices:
                neighbors[i].update(indices - {i})
        for i, item in enumerate(reports):
            item["adjacent_faces"] = [reports[j]["id"] for j in sorted(neighbors[i])]
            render_items.append({"shape": faces[i], "id": item["id"]})
        report_parts.append({"id": pid, "name": part["name"], "metrics": compute(shape),
                             "surface_counts": dict(Counter(f["surface"] for f in reports)),
                             "solids": [{"id": f"{pid}:s{i + 1}", "metrics": compute(s),
                                         "face_ids": [f"{pid}:f{face_map.FindIndex(f)}"
                                                      for f in shapes(s, TopAbs_FACE)]}
                                        for i, s in enumerate(shapes(shape, TopAbs_SOLID))],
                             "faces": reports})
    report = {"file": str(Path(path).resolve()), "units": {"length": "mm", "area": "mm^2", "volume": "mm^3"},
              "metrics": compute(_compound([p["shape"] for p in parts])),
              "assembly": tree, "parts": report_parts,
              "notes": ["Face and part IDs identify this import; they are not stable across STEP revisions.",
                        "Analytic surfaces are measurements, not inferred holes, bosses, or feature history.",
                        "Origins and axes describe the underlying surfaces; uv_bounds delimit the trimmed faces."]}
    return report, render_items
