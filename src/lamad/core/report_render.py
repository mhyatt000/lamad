"""Headless orthographic, depth-buffered report images using OCCT + NumPy/Pillow."""

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from lamad.core.viewer import tessellate

VIEWS = {"iso": (1, -1, 1), "front (-Y)": (0, -1, 0),
         "right (+X)": (1, 0, 0), "top (+Z)": (0, 0, 1)}
BG = np.array([247, 247, 247], dtype=np.uint8)
BLUE = (90, 145, 205)
MISSING = (220, 65, 100)
EXTRA = (25, 175, 175)


def mesh(shape, tol):
    vertices, faces = tessellate(shape, tol, 0.3)
    return vertices.astype(float), faces


def camera(meshes, direction, size):
    forward = np.array(direction, dtype=float)
    forward /= np.linalg.norm(forward)
    up = np.array([0., 1., 0.]) if abs(forward[2]) > 0.99 else np.array([0., 0., 1.])
    right = np.cross(up, forward)
    right /= np.linalg.norm(right)
    up = np.cross(forward, right)
    basis = np.column_stack((right, up, forward))
    points = np.concatenate([v for v, _ in meshes if len(v)]) @ basis
    lo, hi = points.min(axis=0), points.max(axis=0)
    scale = (size - 32) / max(float(max((hi - lo)[:2])), 1e-9)
    return basis, (lo + hi) / 2, scale


def raster(items, cam, size):
    """Items are (mesh, RGB, integer ID); larger camera Z is nearer."""
    basis, center, scale = cam
    pixels = np.broadcast_to(BG, (size, size, 3)).copy()
    depth = np.full((size, size), -np.inf)
    ids = np.full((size, size), -1, dtype=int)
    for (vertices, faces), color, identity in items:
        points = (vertices @ basis - center) * scale
        points[:, 0] += size / 2
        points[:, 1] = size / 2 - points[:, 1]
        for triangle in points[faces]:
            a, b, c = triangle
            low = np.maximum(np.floor(triangle[:, :2].min(axis=0)).astype(int), 0)
            high = np.minimum(np.ceil(triangle[:, :2].max(axis=0)).astype(int), size - 1)
            x0, y0 = low
            x1, y1 = high
            if x1 < x0 or y1 < y0:
                continue
            den = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
            if abs(den) < 1e-12:
                continue
            yy, xx = np.mgrid[y0:y1 + 1, x0:x1 + 1]
            xx, yy = xx + 0.5, yy + 0.5
            w0 = ((b[1] - c[1]) * (xx - c[0]) + (c[0] - b[0]) * (yy - c[1])) / den
            w1 = ((c[1] - a[1]) * (xx - c[0]) + (a[0] - c[0]) * (yy - c[1])) / den
            w2 = 1 - w0 - w1
            z = w0 * a[2] + w1 * b[2] + w2 * c[2]
            region = depth[y0:y1 + 1, x0:x1 + 1]
            mask = (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9) & (z > region)
            normal = np.cross(b - a, c - a)
            normal /= max(np.linalg.norm(normal), 1e-12)
            if normal[2] < 0:
                normal = -normal
            light = np.array([-0.35, -0.45, 0.82])
            shade = 0.45 + 0.55 * max(0.0, float(normal @ light))
            pixels[y0:y1 + 1, x0:x1 + 1][mask] = np.asarray(color) * shade
            region[mask] = z[mask]
            ids[y0:y1 + 1, x0:x1 + 1][mask] = identity
    return pixels, ids


def comparison_image(shapes, path, tol=0.1, size=320):
    meshes = {name: mesh(shape, tol) for name, shape in shapes.items()}
    sheet = Image.new("RGB", (size * 4, (size + 24) * 4 + 30), tuple(BG))
    draw = ImageDraw.Draw(sheet)
    draw.text((8, 8), "Missing: red | Extra: teal | Overlay: reference red, reconstruction teal", fill="black")
    for row, (view, direction) in enumerate(VIEWS.items()):
        cam = camera([meshes["reference"], meshes["reconstruction"]], direction, size)
        ref, _ = raster([(meshes["reference"], BLUE, 0)], cam, size)
        new, _ = raster([(meshes["reconstruction"], BLUE, 0)], cam, size)
        red, _ = raster([(meshes["reference"], MISSING, 0)], cam, size)
        teal, _ = raster([(meshes["reconstruction"], EXTRA, 0)], cam, size)
        overlay = ((red.astype(float) + teal.astype(float)) / 2).astype(np.uint8)
        delta, ids = raster([(meshes["missing"], MISSING, 0),
                             (meshes["extra"], EXTRA, 1)], cam, size)
        context = (ref.astype(float) * 0.15 + BG * 0.85).astype(np.uint8)
        delta[ids < 0] = context[ids < 0]
        for col, (title, pixels) in enumerate(zip(
                ("reference", "reconstruction", "overlay", "solid difference"),
                (ref, new, overlay, delta))):
            x, y = col * size, 30 + row * (size + 24)
            draw.text((x + 8, y + 6), f"{view}: {title}", fill="black")
            sheet.paste(Image.fromarray(pixels), (x, y + 24))
    sheet.save(path)


def inspection_image(items, path, tol=0.1, size=480):
    meshes = [mesh(item["shape"], tol) for item in items]
    sheet = Image.new("RGB", (size * 2, (size + 24) * 2), tuple(BG))
    draw = ImageDraw.Draw(sheet)
    palette = [(90, 145, 205), (205, 150, 90), (110, 180, 130), (180, 125, 185)]
    for index, (name, direction) in enumerate(VIEWS.items()):
        cam = camera(meshes, direction, size)
        pixels, ids = raster([(m, palette[i % len(palette)], i) for i, m in enumerate(meshes)], cam, size)
        panel = Image.fromarray(pixels)
        labels = ImageDraw.Draw(panel)
        visible, counts = np.unique(ids[ids >= 0], return_counts=True)
        occupied = []
        # Label the largest visible faces, using a pixel belonging to each face.
        for i in visible[np.argsort(-counts)[:24]]:
            yy, xx = np.where(ids == i)
            distance = (xx - xx.mean()) ** 2 + (yy - yy.mean()) ** 2
            at = np.argmin(distance)
            label = items[i]["id"]
            x, y = int(xx[at]), int(yy[at])
            # Move labels away from each other, retaining a leader to the face.
            placed = None
            for dx, dy in ((0, 0), (0, -16), (0, 16), (-45, 0), (16, 0), (0, -32), (0, 32)):
                lx, ly = max(0, min(size - 65, x + dx)), max(0, min(size - 14, y + dy))
                box = labels.textbbox((lx, ly), label)
                if all(box[2] + 3 < b[0] or box[0] > b[2] + 3 or
                       box[3] + 3 < b[1] or box[1] > b[3] + 3 for b in occupied):
                    placed = lx, ly, box
                    break
            if placed is None:
                continue
            lx, ly, box = placed
            occupied.append(box)
            if (lx, ly) != (x, y):
                labels.line((x, y, lx, ly), fill="black")
            labels.rectangle(box, fill="white")
            labels.text((lx, ly), label, fill="black")
        x, y = (index % 2) * size, (index // 2) * (size + 24)
        draw.text((x + 8, y + 6), f"{name} (up to 24 visible face IDs)", fill="black")
        sheet.paste(panel, (x, y + 24))
    sheet.save(Path(path))
