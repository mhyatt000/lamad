"""Offscreen OpenGL renders of a TopoDS_Shape via OCCT's AIS/V3d."""

import tempfile
from pathlib import Path

from OCP.AIS import AIS_InteractiveContext, AIS_Shape
from OCP.Aspect import Aspect_DisplayConnection, Aspect_NeutralWindow
from OCP.Graphic3d import Graphic3d_MaterialAspect, Graphic3d_NameOfMaterial_Silver
from OCP.Image import Image_AlienPixMap
from OCP.OpenGl import OpenGl_GraphicDriver
from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
from OCP.TCollection import TCollection_AsciiString
from OCP.V3d import (
    V3d_AmbientLight,
    V3d_DirectionalLight,
    V3d_TypeOfOrientation_Zup_AxoRight,
    V3d_TypeOfOrientation_Zup_Bottom,
    V3d_TypeOfOrientation_Zup_Front,
    V3d_TypeOfOrientation_Zup_Left,
    V3d_TypeOfOrientation_Zup_Right,
    V3d_TypeOfOrientation_Zup_Top,
    V3d_Viewer,
)
from OCP.gp import gp_Dir

from lamad.core.export import PALETTE, parse_color

VIEWS = {
    "front": V3d_TypeOfOrientation_Zup_Front,
    "left": V3d_TypeOfOrientation_Zup_Left,
    "right": V3d_TypeOfOrientation_Zup_Right,
    "top": V3d_TypeOfOrientation_Zup_Top,
    "bottom": V3d_TypeOfOrientation_Zup_Bottom,
    "iso": V3d_TypeOfOrientation_Zup_AxoRight,
}
PREVIEW_VIEWS = ["iso", "front", "right", "top"]


def _scene(shape, parts, width, height):
    """Build one offscreen GL context with the shape displayed. Reused across views."""
    driver = OpenGl_GraphicDriver(Aspect_DisplayConnection())
    driver.ChangeOptions().contextNoAccel = True
    driver.ChangeOptions().buffersNoSwap = True

    viewer = V3d_Viewer(driver)
    for light in (
        V3d_AmbientLight(Quantity_Color(0.5, 0.5, 0.5, Quantity_TOC_RGB)),
        V3d_DirectionalLight(gp_Dir(1, -1, -1), Quantity_Color(0.8, 0.8, 0.8, Quantity_TOC_RGB)),
        V3d_DirectionalLight(gp_Dir(-1, 1, 0.5), Quantity_Color(0.4, 0.4, 0.4, Quantity_TOC_RGB)),
        V3d_DirectionalLight(gp_Dir(0, 0, 1), Quantity_Color(0.25, 0.25, 0.25, Quantity_TOC_RGB)),
    ):
        viewer.AddLight(light)
        viewer.SetLightOn(light)

    view = viewer.CreateView()
    window = Aspect_NeutralWindow()
    window.SetSize(width, height)
    view.SetWindow(window)
    view.SetBackgroundColor(Quantity_Color(0.96, 0.96, 0.96, Quantity_TOC_RGB))

    ctx = AIS_InteractiveContext(viewer)
    drawn = [p for p in (parts or []) if p.get("shape") is not None]
    if len(drawn) > 1:
        for i, p in enumerate(drawn):
            ais = AIS_Shape(p["shape"])
            ais.SetMaterial(Graphic3d_MaterialAspect(Graphic3d_NameOfMaterial_Silver))
            ais.Attributes().SetFaceBoundaryDraw(True)
            r, g, b = parse_color(p.get("color")) or PALETTE[i % len(PALETTE)]
            ais.SetColor(Quantity_Color(r, g, b, Quantity_TOC_RGB))
            ctx.Display(ais, 1, -1, False)
        ctx.UpdateCurrentViewer()
    else:
        ais = AIS_Shape(shape)
        ais.SetMaterial(Graphic3d_MaterialAspect(Graphic3d_NameOfMaterial_Silver))
        ais.Attributes().SetFaceBoundaryDraw(True)
        ctx.Display(ais, 1, -1, True)
    return view, ctx


def render_views(shape, names, out_dir, parts=None, size=512):
    """Render each named view to out_dir/<name>.png. Returns written paths."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    scale = 2  # render big, downsample: cheap antialiasing
    view, _ctx = _scene(shape, parts, size * scale, size * scale)  # keep ctx alive
    written = []
    for name in names:
        view.SetProj(VIEWS[name])
        view.FitAll(0.08)   # 8% margin, or the model touches the frame edge
        view.ZFitAll()
        view.Redraw()
        path = out_dir / f"{name}.png"
        pixmap = Image_AlienPixMap()
        view.ToPixMap(pixmap, size * scale, size * scale)
        pixmap.Save(TCollection_AsciiString(str(path)))
        written.append(path)

    from PIL import Image
    for path in written:
        with Image.open(path) as im:
            im.convert("RGB").resize((size, size), Image.Resampling.LANCZOS).save(path)
    return written


def render_preview(shape, out_path, parts=None, size=400):
    """Four labelled views in one 2x2 image — the 'look at what you built' shot."""
    from PIL import Image, ImageDraw

    with tempfile.TemporaryDirectory() as tmp:
        panels = render_views(shape, PREVIEW_VIEWS, tmp, parts=parts, size=size)
        images = [Image.open(p).convert("RGB").copy() for p in panels]

    bar = 26
    sheet = Image.new("RGB", (size * 2, (size + bar) * 2), (245, 245, 245))
    draw = ImageDraw.Draw(sheet)
    for img, label, (x, y) in zip(
        images, PREVIEW_VIEWS,
        [(0, 0), (size, 0), (0, size + bar), (size, size + bar)],
    ):
        sheet.paste(img, (x, y + bar))
        draw.text((x + 8, y + 7), label, fill=(40, 40, 40))
    draw.line([(size, 0), (size, (size + bar) * 2)], fill=(210, 210, 210))
    draw.line([(0, size + bar), (size * 2, size + bar)], fill=(210, 210, 210))

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(str(out_path))
    return out_path
