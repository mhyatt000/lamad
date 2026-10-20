"""viser web viewer for a STEP assembly. Driven by `lamad view`.

    lamad view                 # latest recorded version
    lamad view 2               # by version number, or by label
    lamad view parts/x.step    # any STEP file

Depends only on OCP + viser (no build123d), so it survives whatever the
project's CAD kernel wrapper happens to be.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import viser
from OCP.BRep import BRep_Tool
from OCP.BRepGProp import BRepGProp
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.GProp import GProp_GProps
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label
from OCP.TDocStd import TDocStd_Document
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED, TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS
from OCP.Quantity import Quantity_Color
from OCP.XCAFDoc import (
    XCAFDoc_ColorCurv,
    XCAFDoc_ColorGen,
    XCAFDoc_ColorSurf,
    XCAFDoc_DocumentTool,
)
from OCP.collections import Sequence_TDF_Label

PALETTE = [
    (86, 149, 232), (232, 143, 74), (108, 196, 134),
    (214, 108, 158), (196, 176, 84), (140, 128, 220),
]


def load_parts(path: Path):
    """[(name, TopoDS_Shape)] for each leaf part, placed in global coordinates.

    GetShape_s(label) places a component relative to its IMMEDIATE parent, so
    nested parts need TopLoc_Location accumulated down the tree. The document
    must outlive every label read from it -- keep `doc` referenced.
    """
    doc = TDocStd_Document(TCollection_ExtendedString("d"))
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    reader.SetColorMode(True)
    if reader.ReadFile(str(path)) != IFSelect_RetDone:
        raise SystemExit(f"cannot read {path}")
    reader.Transfer(doc)
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    ct = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())

    def color(label: TDF_Label):
        """The part's authored color as 0-255 RGB, or None to fall back."""
        c = Quantity_Color()
        for kind in (XCAFDoc_ColorSurf, XCAFDoc_ColorGen, XCAFDoc_ColorCurv):
            if ct.GetColor_s(label, kind, c):
                return (round(c.Red() * 255), round(c.Green() * 255), round(c.Blue() * 255))
        return None

    def name(label: TDF_Label) -> str:
        attr = TDataStd_Name()
        if label.FindAttribute(TDataStd_Name.GetID_s(), attr):
            return attr.Get().ToExtString()
        return "unnamed"

    def children(label: TDF_Label) -> list[TDF_Label]:
        ref = TDF_Label()
        target = ref if st.IsReference_s(label) and st.GetReferredShape_s(label, ref) else label
        seq = Sequence_TDF_Label()
        st.GetComponents_s(target, seq)
        return [seq.Value(i) for i in range(1, seq.Length() + 1)]

    out = []

    def proto(label: TDF_Label) -> TDF_Label:
        """The prototype a component points at. XCAF assemblies are always
        instance -> prototype, so a part's name and color usually sit on the
        instance while the geometry sits one level below under a generic
        name like 'SOLID'."""
        ref = TDF_Label()
        return ref if st.GetReferredShape_s(label, ref) else label

    GENERIC = {"unnamed", "?", "SOLID", "COMPOUND", "SHELL", "ASSEMBLY", ""}

    def real_name(label) -> str | None:
        nm = name(label)
        return None if nm in GENERIC or nm.startswith("=>") else nm

    def walk(label, loc, inherited_name=None, inherited_color=None):
        kids = children(label)
        src = proto(label)
        nm = real_name(label) or real_name(src) or inherited_name
        rgb = color(label) or color(src) or inherited_color
        if not kids:
            out.append((nm or "part", st.GetShape_s(label).Moved(loc), rgb))
            return
        nxt = loc.Multiplied(st.GetLocation_s(label)) if st.IsReference_s(label) else loc
        for kid in kids:
            walk(kid, nxt, nm, rgb)

    roots = Sequence_TDF_Label()
    st.GetFreeShapes(roots)
    for i in range(1, roots.Length() + 1):
        walk(roots.Value(i), TopLoc_Location())
    if not out:
        raise SystemExit(f"no parts found in {path}")
    return doc, out


def tessellate(shape, lin: float, ang: float):
    """Triangulate every face and concatenate into one indexed mesh."""
    BRepMesh_IncrementalMesh(shape, lin, False, ang, True)
    verts: list[tuple[float, float, float]] = []
    tris: list[tuple[int, int, int]] = []
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        face = TopoDS.Face(exp.Current())
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        if tri is not None:
            trsf = loc.Transformation()
            off = len(verts)
            for i in range(1, tri.NbNodes() + 1):
                p = tri.Node(i).Transformed(trsf)
                verts.append((p.X(), p.Y(), p.Z()))
            flip = face.Orientation() == TopAbs_REVERSED
            for i in range(1, tri.NbTriangles() + 1):
                a, b, c = tri.Triangle(i).Get()
                if flip:
                    b, c = c, b
                tris.append((a - 1 + off, b - 1 + off, c - 1 + off))
        exp.Next()
    return (np.array(verts, dtype=np.float32).reshape(-1, 3),
            np.array(tris, dtype=np.uint32).reshape(-1, 3))


def volume_cm3(shape) -> float:
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass() / 1000.0


def count_solids(shape) -> int:
    exp, n = TopExp_Explorer(shape, TopAbs_SOLID), 0
    while exp.More():
        n += 1
        exp.Next()
    return n


def serve(step: Path, tol: float = 0.05, ang: float = 0.3, port: int = 8080,
          block: bool = True) -> None:
    """Tessellate `step` and serve it. Blocks until interrupted."""
    class args:  # noqa: N801 - keeps the body below unchanged
        pass
    args.step, args.tol, args.ang, args.port = Path(step), tol, ang, port

    print(f"reading {args.step} ...", file=sys.stderr)
    _doc, parts = load_parts(args.step)

    server = viser.ViserServer(port=args.port)
    server.scene.set_up_direction("+z")

    handles, meta, allv = {}, [], []
    for i, (nm, shape, rgb) in enumerate(parts):
        v, f = tessellate(shape, args.tol, args.ang)
        allv.append(v)
        # viser works in metres, CAD in millimetres -> scale on the node.
        handles[nm] = server.scene.add_mesh_simple(
            f"/{nm}", v, f, color=rgb or PALETTE[i % len(PALETTE)],
            scale=0.001, side="double",
        )
        meta.append((nm, volume_cm3(shape), count_solids(shape), len(f)))
        print(f"  {nm:<24} {meta[-1][1]:6.1f} cm3  {len(f):>7} tris", file=sys.stderr)

    pts = np.concatenate(allv)
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    ctr, size = (lo + hi) / 2, hi - lo

    with server.gui.add_folder("Parts"):
        for nm, vol, _nsol, _ntri in meta:
            cb = server.gui.add_checkbox(f"{nm} ({vol:.1f} cm3)", True)

            @cb.on_update
            def _(event, nm=nm):
                handles[nm].visible = event.target.value

    with server.gui.add_folder("Display"):
        opacity = server.gui.add_slider("opacity", 0.1, 1.0, 0.05, 1.0)

        @opacity.on_update
        def _(_event):
            for h in handles.values():
                h.opacity = opacity.value

        wire = server.gui.add_checkbox("wireframe", False)

        @wire.on_update
        def _(_event):
            for h in handles.values():
                h.wireframe = wire.value

        reset = server.gui.add_button("reset view")

        @reset.on_click
        def _(event):
            frame(event.client)

    server.gui.add_markdown(
        f"**{args.step.name}**\n\n"
        f"{len(parts)} parts &middot; {sum(m[2] for m in meta)} solids &middot; "
        f"{sum(m[3] for m in meta):,} tris\n\n"
        f"bbox `{size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f}` mm\n\n"
        f"total `{sum(m[1] for m in meta):.1f}` cm3"
    )

    def frame(client: viser.ClientHandle) -> None:
        d = float(np.linalg.norm(size)) / 1000.0
        c = ctr / 1000.0
        client.camera.position = (c[0] - d * 0.5, c[1] - d, c[2] + d * 0.5)
        client.camera.look_at = tuple(float(x) for x in c)

    @server.on_client_connect
    def _(client: viser.ClientHandle) -> None:
        frame(client)

    print(f"\nserving http://localhost:{args.port}   (ctrl-c to stop)", file=sys.stderr)
    if not block:
        return
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
