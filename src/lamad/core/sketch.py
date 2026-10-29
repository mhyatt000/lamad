"""2D PNG of planar build123d geometry (sketches, faces, lines) with Pillow.

The plane is found from the geometry itself. An axis-aligned plane keeps
global coordinates (XY: x right, y up; XZ: x right, z up; YZ: y right, z up)
so grid values read as model millimetres; any other plane gets in-plane axes
derived from global X.
"""

import math
from pathlib import Path

import numpy as np

AXIS_PLANES = {  # name: (normal axis, x axis, y axis) as global indices
    "XY": (2, 0, 1),
    "XZ": (1, 0, 2),
    "YZ": (0, 1, 2),
}
SS = 3  # supersampling: Pillow draws without antialiasing
MIN_WIDTH = 520  # px; the caption line needs about this much


def _edge_points(edge, tol):
    from build123d import GeomType

    if edge.geom_type == GeomType.LINE:
        n = 1
    else:
        n = min(512, max(24, math.ceil(edge.length / tol)))
    return np.array([tuple(p) for p in edge.positions([i / n for i in range(n + 1)])])


def collect(parts, tol=0.05, ang=0.2):
    """Per part: (color, [(tri_pts, tris)], [polyline pts]) in global coordinates.
    Raises ValueError for solids or for parts with nothing planar to draw."""
    from build123d import Compound

    out = []
    for p in parts:
        shape = Compound(p["shape"])
        if shape.solids():
            raise ValueError(f"part {p['name']!r} is a solid; `lamad render sketch` draws planar "
                             "faces and lines (show_object a sketch, face, or curve).")
        faces = []
        for f in shape.faces():
            verts, tris = f.tessellate(tol, ang)
            faces.append((np.array([tuple(v) for v in verts]), np.array(tris, dtype=int)))
        lines = [_edge_points(e, tol) for e in shape.edges()]
        if not lines:
            raise ValueError(f"part {p['name']!r} has no edges to draw.")
        out.append((p["color"], faces, lines))
    return out


def fit_plane(points):
    """(name, x_axis, y_axis, normal) for coplanar `points`; ValueError otherwise."""
    pts = np.asarray(points, dtype=float)
    c = pts.mean(axis=0)
    extent = float(np.ptp(pts, axis=0).max()) or 1.0
    _u, s, vt = np.linalg.svd(pts - c, full_matrices=False)
    if s.size < 2 or s[1] <= 1e-9 * extent * math.sqrt(len(pts)):
        normal = np.array([0.0, 0.0, 1.0])   # collinear: any plane holds it
        d = vt[0]
        if abs(d @ normal) > 0.999:
            normal = np.array([0.0, 1.0, 0.0])
    else:
        normal = vt[2]
    off = np.abs((pts - c) @ normal).max()
    if off > 1e-4 * max(1.0, extent):
        raise ValueError(f"geometry is not planar (points stray {off:.4g} mm from the best-fit "
                         "plane); draw one sketch at a time with --part.")
    for name, (n, xi, yi) in AXIS_PLANES.items():
        if abs(normal[n]) > 0.999:
            # Positive axis, so the reported offset is the plane's coordinate.
            return name, np.eye(3)[xi], np.eye(3)[yi], np.eye(3)[n]
    x = np.eye(3)[0] - normal * normal[0]
    if np.linalg.norm(x) < 1e-6:
        x = np.eye(3)[1] - normal * normal[1]
    x /= np.linalg.norm(x)
    return "custom", x, np.cross(normal, x), normal


def nice_step(span, target=10):
    """A 1/2/5 x 10^k grid step giving about `target` lines over `span`."""
    raw = span / target
    mag = 10 ** math.floor(math.log10(raw))
    return next(m * mag for m in (1, 2, 5, 10) if m * mag >= raw)


def render(parts, out_path, size=1000, grid=True, tol=0.05):
    """Draw `parts` ([{name, shape, color 0..1 rgb}]) to `out_path`. Returns a
    summary dict: plane, origin offset, axes, and the drawn extent in mm."""
    from PIL import Image, ImageDraw, ImageFont

    drawn = collect(parts, tol=tol)
    every = np.concatenate([pl for _c, _f, lines in drawn for pl in lines])
    name, xa, ya, normal = fit_plane(every)
    offset = float(every.mean(axis=0) @ normal)

    def flat(pts):
        return np.stack([pts @ xa, pts @ ya], axis=1)

    xy = flat(every)
    lo, hi = xy.min(axis=0), xy.max(axis=0)
    span = hi - lo
    pad = max(span.max() * 0.08, 1e-3)
    lo, hi = lo - pad, hi + pad
    w_mm, h_mm = hi - lo
    scale = (size - 1) / max(w_mm, h_mm)
    if w_mm * scale < MIN_WIDTH:   # room for the caption under a tall, thin sketch
        extra = (MIN_WIDTH / scale - w_mm) / 2
        lo[0], hi[0] = lo[0] - extra, hi[0] + extra
        w_mm = hi[0] - lo[0]
    W, H = max(1, round(w_mm * scale)), max(1, round(h_mm * scale))
    bar = 36
    img = Image.new("RGB", (W * SS, (H + bar) * SS), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    def px(pts2):
        u = (pts2[:, 0] - lo[0]) * scale * SS
        v = (hi[1] - pts2[:, 1]) * scale * SS
        return list(zip(u.tolist(), v.tolist()))

    step = nice_step(max(w_mm, h_mm))
    if grid:
        for k in range(math.ceil(lo[0] / step), math.floor(hi[0] / step) + 1):
            (u, _), = px(np.array([[k * step, lo[1]]]))
            draw.line([(u, 0), (u, H * SS)], fill=(150, 150, 150) if k == 0 else (232, 232, 232),
                      width=SS)
        for k in range(math.ceil(lo[1] / step), math.floor(hi[1] / step) + 1):
            (_, v), = px(np.array([[lo[0], k * step]]))
            draw.line([(0, v), (W * SS, v)], fill=(150, 150, 150) if k == 0 else (232, 232, 232),
                      width=SS)

    def mix(rgb, t):
        """Blend a 0..1 color toward white (t > 0) or black (t < 0)."""
        base = 1.0 if t > 0 else 0.0
        return tuple(round(255 * (c + (base - c) * abs(t))) for c in rgb)

    for rgb, faces, _lines in drawn:
        fill = mix(rgb, 0.65)
        for verts, tris in faces:
            pts = px(flat(verts))
            for a, b, c in tris:
                # Outline in the fill color closes hairline seams between triangles.
                draw.polygon([pts[a], pts[b], pts[c]], fill=fill, outline=fill)
    for rgb, _faces, lines in drawn:
        ink, r = mix(rgb, -0.45), 2.5 * SS
        for pl in lines:
            pts = px(flat(pl))
            draw.line(pts, fill=ink, width=2 * SS, joint="curve")
            for u, v in (pts[0], pts[-1]):
                draw.ellipse([u - r, v - r, u + r, v + r], fill=ink)

    labels = {"XY": ("x", "y"), "XZ": ("x", "z"), "YZ": ("y", "z")}.get(name, ("u", "v"))
    try:
        font = ImageFont.load_default(size=13 * SS)
    except TypeError:   # Pillow < 10.1 has a fixed-size default font
        font = ImageFont.load_default()
    plane_txt = name if name != "custom" else "custom plane"
    if abs(offset) > 1e-9:
        plane_txt += f" @ {offset:+g}"
    text = (f"{labels[0]} {span[0]:.2f} mm   {labels[1]} {span[1]:.2f} mm   "
            f"plane {plane_txt}" + (f"   grid {step:g} mm" if grid else ""))
    draw.line([(0, H * SS), (W * SS, H * SS)], fill=(210, 210, 210), width=SS)
    draw.text((10 * SS, (H + 10) * SS), text, fill=(60, 60, 60), font=font)

    img = img.resize((W, H + bar), Image.Resampling.LANCZOS)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out_path))
    return {"plane": name, "offset": round(offset, 6),
            "x_axis": [round(float(c), 6) for c in xa],
            "y_axis": [round(float(c), 6) for c in ya],
            "size_mm": [round(float(span[0]), 4), round(float(span[1]), 4)],
            "image_px": [W, H + bar]}
