"""STEP / GLB / STL writers operating on raw TopoDS_Shape."""

import math

from OCP.BRep import BRep_Builder
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.IFSelect import IFSelect_RetDone
from OCP.Message import Message_ProgressRange
from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
from OCP.RWGltf import RWGltf_CafWriter
from OCP.Interface import Interface_Static
from OCP.STEPCAFControl import STEPCAFControl_Writer
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
from OCP.StlAPI import StlAPI_Writer
from OCP.TCollection import TCollection_AsciiString, TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label
from OCP.TDocStd import TDocStd_Document
from OCP.TopAbs import TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Compound
from OCP.XCAFApp import XCAFApp_Application
from OCP.XCAFDoc import XCAFDoc_ColorSurf, XCAFDoc_DocumentTool
from OCP.collections import (
    IndexedDataMap_TCollection_AsciiString_TCollection_AsciiString,
    Sequence_TDF_Label,
)
from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf

from lamad.core.native_io import quiet_kernel

PALETTE = [
    (0.33, 0.55, 0.80), (0.90, 0.35, 0.30), (0.30, 0.69, 0.31),
    (0.95, 0.70, 0.20), (0.61, 0.35, 0.71), (0.00, 0.59, 0.53),
    (0.95, 0.50, 0.13), (0.85, 0.44, 0.57), (0.47, 0.33, 0.28),
]

NAMED_COLORS = {
    "red": (1, 0, 0), "green": (0, .5, 0), "blue": (0, 0, 1),
    "yellow": (1, 1, 0), "orange": (1, .55, 0), "purple": (.5, 0, .5),
    "gray": (.5, .5, .5), "grey": (.5, .5, .5), "white": (1, 1, 1),
    "black": (0, 0, 0), "brown": (.55, .27, .07), "pink": (1, .41, .71),
    "teal": (0, .5, .5), "gold": (1, .84, 0), "silver": (.75, .75, .75),
    "cyan": (0, 1, 1), "steelblue": (.27, .51, .71),
}


def parse_color(value):
    """Accept a name, #rrggbb, or an (r,g,b) 0..1 triple. None if unparseable."""
    if isinstance(value, str):
        v = value.strip().lower()
        if v in NAMED_COLORS:
            return NAMED_COLORS[v]
        if v.startswith("#") and len(v) == 7:
            try:
                return tuple(int(v[i:i + 2], 16) / 255 for i in (1, 3, 5))
            except ValueError:
                return None
    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            rgb = tuple(float(c) for c in value)
        except (TypeError, ValueError):
            return None
        if all(0 <= c <= 1 for c in rgb):
            return rgb
    return None


def export_step(shape, path, parts=None):
    """Write STEP. With `parts`, writes a named, colored assembly.

    A bare STEPControl_Writer flattens everything into one anonymous blob, so
    any assembly-aware reader (the viewer, other CAD tools) sees a single
    unnamed lump. STEPCAFControl_Writer keeps one named label per part and
    carries the colors, which is what makes them come back on import.
    """
    if not parts:
        with quiet_kernel():
            writer = STEPControl_Writer()
            if writer.Transfer(shape, STEPControl_AsIs) != IFSelect_RetDone:
                raise RuntimeError("STEP transfer failed")
            if writer.Write(str(path)) != IFSelect_RetDone:
                raise RuntimeError("STEP write failed")
        return

    doc = TDocStd_Document(TCollection_ExtendedString("XmlXCAF"))
    XCAFApp_Application.GetApplication_s().InitDocument(doc)
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    color_tool = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())

    # One assembly root with components, not N loose free shapes. Given loose
    # free shapes the CAF writer transfers each separately and only the first
    # one's color survives the write.
    compound = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(compound)
    for part in parts:
        builder.Add(compound, part["shape"])

    root = shape_tool.AddShape(compound, True)   # makeAssembly -> child labels
    components = Sequence_TDF_Label()
    shape_tool.GetComponents_s(root, components)

    for i, part in enumerate(parts):
        if i >= components.Length():
            break
        label = components.Value(i + 1)
        referred = TDF_Label()
        target = referred if shape_tool.GetReferredShape_s(label, referred) else label
        name = TCollection_ExtendedString(str(part.get("name") or f"part{i+1}"))
        r, g, b = parse_color(part.get("color")) or PALETTE[i % len(PALETTE)]
        color = Quantity_Color(r, g, b, Quantity_TOC_RGB)
        # Write to both the instance and the prototype: readers differ on
        # which one they consult.
        for lab in (label, target):
            TDataStd_Name.Set_s(lab, name)
            color_tool.SetColor(lab, color, XCAFDoc_ColorSurf)

    with quiet_kernel():
        # Colors and names need AP214 or AP242; the default AP203 drops them.
        Interface_Static.SetCVal_s("write.step.schema", "AP214IS")
        writer = STEPCAFControl_Writer()
        writer.SetColorMode(True)
        writer.SetNameMode(True)
        if not writer.Transfer(doc, STEPControl_AsIs):
            raise RuntimeError("STEP assembly transfer failed")
        if writer.Write(str(path)) != IFSelect_RetDone:
            raise RuntimeError("STEP write failed")


def export_stl(shape, path, deflection=0.1):
    BRepMesh_IncrementalMesh(shape, deflection)
    with quiet_kernel():
        if StlAPI_Writer().Write(shape, str(path)) is False:
            raise RuntimeError("STL write failed")


def _y_up(shape):
    """glTF is Y-up; OCCT/build123d are Z-up. Rotate -90 deg about X."""
    t = gp_Trsf()
    t.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(1, 0, 0)), -math.pi / 2)
    return BRepBuilderAPI_Transform(shape, t, True).Shape()


def export_glb(shape, path, parts=None, deflection=0.1):
    """Write binary glTF, one colored node per part (or per solid)."""
    shape = _y_up(shape)
    BRepMesh_IncrementalMesh(shape, deflection)

    doc = TDocStd_Document(TCollection_ExtendedString("XmlXCAF"))
    XCAFApp_Application.GetApplication_s().InitDocument(doc)
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    color_tool = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())

    items = []
    for i, p in enumerate(parts or []):
        if p.get("shape") is None:
            continue
        s = _y_up(p["shape"])
        BRepMesh_IncrementalMesh(s, deflection)
        items.append((s, p.get("name") or f"part_{i}", parse_color(p.get("color"))))

    if not items:
        solids = []
        exp = TopExp_Explorer(shape, TopAbs_SOLID)
        while exp.More():
            solids.append(TopoDS.Solid(exp.Current()))
            exp.Next()
        items = [(s, f"solid_{i}", None) for i, s in enumerate(solids)] or [(shape, "shape", None)]

    for i, (s, name, color) in enumerate(items):
        label = shape_tool.AddShape(s)
        TDataStd_Name.Set_s(label, TCollection_ExtendedString(str(name)))
        r, g, b = color or PALETTE[i % len(PALETTE)]
        color_tool.SetColor(label, Quantity_Color(r, g, b, Quantity_TOC_RGB), XCAFDoc_ColorSurf)

    with quiet_kernel():
        writer = RWGltf_CafWriter(TCollection_AsciiString(str(path)), True)
        writer.Perform(doc, IndexedDataMap_TCollection_AsciiString_TCollection_AsciiString(),
                       Message_ProgressRange())
