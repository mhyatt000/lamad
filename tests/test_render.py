"""Tests for `lamad render sketch` and `lamad render part`. Run with uv run python -m unittest discover -s tests -v."""

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from click.testing import CliRunner
from PIL import Image

from lamad.cli import cli
from lamad.core.cameras import camera, min_angle_deg, spread_directions
from lamad.core.sketch import fit_plane, nice_step

PLATE = """
width = 60
with BuildSketch() as plate:
    Rectangle(width, 30)
    Circle(5, mode=Mode.SUBTRACT)
show_object(plate.sketch, name="plate")
with BuildLine() as path:
    Polyline((-30, 20), (0, 28), (30, 20))
show_object(path.line, name="path", color="red")
"""


def run_sketch(source, *args, name="s.py", command="sketch"):
    """Write `source` to a temp dir and run `lamad render sketch` on it.
    Returns (exit code, payload, script path, temp dir handle)."""
    tmp = tempfile.TemporaryDirectory()
    script = Path(tmp.name) / name
    script.write_text(source)
    result = CliRunner().invoke(cli, ["render", command, str(script), *args])
    return result.exit_code, json.loads(result.stdout), script, tmp


class SketchCommandTests(unittest.TestCase):
    def test_xy_sketch_and_curve_drawn_next_to_script(self):
        code, payload, script, tmp = run_sketch(PLATE)
        with tmp:
            self.assertEqual(code, 0, payload)
            self.assertEqual(payload["plane"], "XY")
            self.assertEqual(payload["parts"], ["plate", "path"])
            self.assertEqual(payload["size_mm"], [60.0, 43.0])
            out = Path(payload["output"])
            self.assertEqual(out, script.with_name("s_sketch.png").resolve())
            with Image.open(out) as im:
                self.assertEqual(list(im.size), payload["image_px"])
                rgb = np.asarray(im.convert("RGB"))
            # Drawn extent is x -30..30, y -15..28 plus 8% of 60 mm padding.
            pad = 0.08 * 60
            mm = (rgb.shape[1] - 1) / (60 + 2 * pad)

            def pixel(x, y):
                return rgb[round((28 + pad - y) * mm), round((x + 30 + pad) * mm)]

            # Inside the hole (off the grid's axis lines) is white; the plate is tinted.
            self.assertTrue((pixel(2, 2) > 245).all(), pixel(2, 2))
            self.assertFalse((pixel(20, 2) > 245).all(), pixel(20, 2))

    def test_default_output_is_numbered_not_overwritten(self):
        code, first, script, tmp = run_sketch(PLATE)
        with tmp:
            again = json.loads(CliRunner().invoke(cli, ["render", "sketch", str(script)]).stdout)
            self.assertEqual(Path(again["output"]).name, "s_sketch_2.png")
            taken = CliRunner().invoke(cli, ["render", "sketch", str(script), "--out", first["output"]])
            self.assertEqual(taken.exit_code, 1)
            self.assertIn("already exists", json.loads(taken.stdout)["message"])

    def test_xz_plane_keeps_global_axes_and_offset(self):
        code, payload, _s, tmp = run_sketch(
            "with BuildSketch(Plane.XZ.offset(-5)) as s:\n    Rectangle(40, 10)\n"
            "show_object(s.sketch)\n")
        with tmp:
            self.assertEqual(code, 0, payload)
            self.assertEqual(payload["plane"], "XZ")
            self.assertAlmostEqual(payload["offset"], 5.0)   # XZ's normal is -Y
            self.assertEqual(payload["size_mm"], [40.0, 10.0])

    def test_part_selection(self):
        code, payload, _s, tmp = run_sketch(PLATE, "--part", "path", "--no-grid")
        with tmp:
            self.assertEqual(code, 0, payload)
            self.assertEqual(payload["parts"], ["path"])
            self.assertEqual(payload["size_mm"], [60.0, 8.0])

    def test_solid_rejected(self):
        code, payload, _s, tmp = run_sketch("show_object(Box(1, 1, 1), name='cube')\n")
        with tmp:
            self.assertEqual(code, 1)
            self.assertIn("solid", payload["message"])

    def test_two_planes_rejected(self):
        code, payload, _s, tmp = run_sketch(
            "show_object(Rectangle(10, 10))\n"
            "show_object(Pos(0, 0, 5) * Rot(90, 0, 0) * Rectangle(10, 10))\n")
        with tmp:
            self.assertEqual(code, 1)
            self.assertIn("not planar", payload["message"])

    def test_render_group_lists_both_commands(self):
        self.assertIn("render", CliRunner().invoke(cli, []).output)
        result = CliRunner().invoke(cli, ["render"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("sketch", result.output)
        self.assertIn("part", result.output)


class RenderPartTests(unittest.TestCase):
    SCRIPT = ("show_object(Box(40, 20, 10), name='base', color='red')\n"
              "show_object(Pos(0, 0, 10) * Cylinder(5, 10), name='post')\n")

    def test_ortho_row_then_six_spread_home_views(self):
        code, payload, script, tmp = run_sketch(self.SCRIPT, "--size", "150", command="part")
        with tmp:
            self.assertEqual(code, 0, payload)
            self.assertEqual(payload["views"], ["top", "side", "bottom"])
            self.assertEqual(len(payload["home"]), 6)
            self.assertAlmostEqual(payload["home_min_angle_deg"], 90.0, places=1)
            self.assertEqual(payload["parts"], ["base", "post"])
            out = Path(payload["output"])
            self.assertEqual(out, script.with_name("s_render.png").resolve())
            with Image.open(out) as im:
                self.assertEqual(im.size, (450, 3 * 176))   # 3 columns, 3 rows of 150 px + bar
                rgb = np.asarray(im.convert("RGB"))
            # Something other than background was drawn in every cell.
            for r in range(3):
                for c in range(3):
                    cell = rgb[r * 176 + 26:(r + 1) * 176, c * 150:(c + 1) * 150]
                    drawn = (np.abs(cell.astype(int) - cell[2, 2]).sum(-1) > 30).mean()
                    self.assertGreater(drawn, 0.02, (r, c))

    def test_n_sets_home_view_count_and_rows(self):
        for n, rows in ((0, 1), (8, 4)):
            code, payload, _s, tmp = run_sketch(self.SCRIPT, "--n", str(n), "--size", "100",
                                                command="part")
            with tmp:
                self.assertEqual(code, 0, payload)
                self.assertEqual(len(payload["home"]), n)
                with Image.open(payload["output"]) as im:
                    self.assertEqual(im.size, (300, rows * 126))

    def test_part_selection(self):
        code, payload, _s, tmp = run_sketch(self.SCRIPT, "--part", "post", "--size", "120",
                                            command="part")
        with tmp:
            self.assertEqual(code, 0, payload)
            self.assertEqual(payload["parts"], ["post"])


class CameraSpreadTests(unittest.TestCase):
    def test_known_optimal_spreads(self):
        # Tammes optima: octahedron, square antiprism, icosahedron.
        for n, best in ((4, 109.471), (6, 90.0), (8, 74.858), (12, 63.435)):
            self.assertAlmostEqual(min_angle_deg(spread_directions(n)), best, delta=0.05, msg=n)

    def test_unit_deterministic_and_off_the_axis_views(self):
        a, b = spread_directions(6), spread_directions(6)
        np.testing.assert_allclose(a, b)
        np.testing.assert_allclose(np.linalg.norm(a, axis=1), 1.0)
        nearest_axis = np.degrees(np.arccos(np.abs(a @ np.eye(3)).max()))
        self.assertGreater(nearest_axis, 30)
        self.assertTrue((np.diff(a[:, 2]) <= 1e-6).all())   # ordered top-down

    def test_camera_up_is_perpendicular_and_upright(self):
        for d in ((1, -1, 1), (0, 0, 1), (0.3, 0.2, -0.9)):
            up, _az, el = camera(d)
            d = np.array(d) / np.linalg.norm(d)
            self.assertAlmostEqual(float(up @ d), 0.0)
            self.assertAlmostEqual(float(np.linalg.norm(up)), 1.0)
            if abs(d[2]) < 0.99:
                self.assertGreater(up[2], 0)
            self.assertAlmostEqual(el, np.degrees(np.arcsin(d[2])))


class PlaneHelperTests(unittest.TestCase):
    def test_tilted_plane_is_custom_and_orthonormal(self):
        n = np.array([0.0, 1.0, 1.0]) / np.sqrt(2)
        u = np.array([1.0, 0.0, 0.0])
        v = np.cross(n, u)
        pts = [a * u + b * v for a, b in ((0, 0), (5, 0), (0, 3), (4, 4))]
        name, x, y, normal = fit_plane(pts)
        self.assertEqual(name, "custom")
        self.assertAlmostEqual(abs(normal @ n), 1.0)
        self.assertAlmostEqual(x @ y, 0.0)
        self.assertAlmostEqual(abs(x @ u), 1.0)

    def test_nice_step(self):
        self.assertEqual(nice_step(60), 10)
        self.assertEqual(nice_step(43), 5)
        self.assertEqual(nice_step(1.5), 0.2)


if __name__ == "__main__":
    unittest.main()
