"""Compare STL occupancy and sampled surface distances to a build123d body."""

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
import trimesh

from lamad.core.report_render import BG, BLUE, EXTRA, MISSING, VIEWS, camera, raster
from lamad.core.viewer import tessellate


def body_mesh(body, tolerance=0.05, angular_tolerance=0.3):
    """Mesh using absolute linear deflection in mm, angular deflection in radians.

    build123d's export_stl/Shape.tessellate use relative deflection in the
    installed version. Use the viewer's explicit absolute mode consistently.
    Deflection settings are numerical targets, not certified distance bounds.
    """
    v, f = tessellate(body.wrapped if hasattr(body, "wrapped") else body,
                      tolerance, angular_tolerance)
    result = trimesh.Trimesh(v, f, process=True)
    # At a fillet pole OCCT may emit a collapsed triangle. After vertex merging
    # it has repeated indices and zero area, but its self-edge makes a closed
    # surface appear non-manifold. Remove only these exact degeneracies: never
    # weld nearby boundaries or discard finite-area thin triangles here.
    faces = result.faces
    distinct = ((faces[:,0] != faces[:,1]) & (faces[:,1] != faces[:,2])
                & (faces[:,2] != faces[:,0]))
    result.metadata["degenerate_triangles_removed"] = int((~distinct).sum())
    if not distinct.all():
        result.update_faces(distinct)
    return result


def compare_meshes(reference, generated, samples=4000):
    """Numerical report. Sampling is deterministic, not a Hausdorff certificate."""
    report = {"units": "mm", "reference_watertight": bool(reference.is_watertight),
              "generated_watertight": bool(generated.is_watertight),
              "reference_volume_mm3": float(reference.volume),
              "generated_volume_mm3": float(generated.volume),
              "reference_bounds": reference.bounds.tolist(), "generated_bounds": generated.bounds.tolist(),
              "sample_count_each_direction": samples}
    for name, a, b in (("reference_to_generated", reference, generated),
                       ("generated_to_reference", generated, reference)):
        points, _ = trimesh.sample.sample_surface(a, samples, seed=123)
        closest, distances, _ = trimesh.proximity.closest_point(b, points)
        worst = int(np.argmax(distances))
        report[name] = {"mean_mm": float(distances.mean()), "max_sampled_mm": float(distances.max()),
                        "p95_mm": float(np.quantile(distances, 0.95)),
                        "max_sampled_point_mm": points[worst].tolist(),
                        "closest_point_mm": closest[worst].tolist()}
    if reference.is_volume and generated.is_volume:
        missing = trimesh.boolean.difference([reference, generated], engine="manifold")
        extra = trimesh.boolean.difference([generated, reference], engine="manifold")
        mv, ev = abs(float(missing.volume)), abs(float(extra.volume))
        report.update(missing_volume_mm3=mv, extra_volume_mm3=ev,
                      relative_symmetric_difference=(mv + ev) / reference.volume,
                      intersection_over_union=max(0, reference.volume - mv) / (reference.volume + ev))
    else:
        report["boolean_unavailable"] = "Both meshes must be watertight, consistently oriented volumes."
    return report


def render_mesh_comparison(reference, generated, path, size=320, title="STL reference / build123d reconstruction"):
    meshes = [(np.asarray(m.vertices), np.asarray(m.faces)) for m in (reference, generated)]
    sheet = Image.new("RGB", (size * 4, 35 + 4 * (size + 24)), tuple(BG))
    draw = ImageDraw.Draw(sheet)
    draw.text((8, 10), title, fill="black")
    for row, (name, direction) in enumerate(VIEWS.items()):
        cam = camera(meshes, direction, size)
        ref, ri = raster([(meshes[0], BLUE, 0)], cam, size)
        new, ni = raster([(meshes[1], BLUE, 0)], cam, size)
        red, _ = raster([(meshes[0], MISSING, 0)], cam, size)
        teal, _ = raster([(meshes[1], EXTRA, 0)], cam, size)
        overlay = ((red.astype(float) + teal.astype(float)) / 2).astype(np.uint8)
        delta = np.broadcast_to(BG, ref.shape).copy()
        delta[(ri >= 0) & (ni < 0)] = MISSING
        delta[(ni >= 0) & (ri < 0)] = EXTRA
        delta[(ni >= 0) & (ri >= 0)] = (210, 213, 216)
        for col, (label, pixels) in enumerate(zip(
            ("source STL", "build123d", "overlay: red / teal", "silhouette difference"), (ref, new, overlay, delta))):
            x, y = col * size, 35 + row * (size + 24)
            draw.text((x + 5, y + 6), f"{name}: {label}", fill="black")
            sheet.paste(Image.fromarray(pixels), (x, y + 24))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)
