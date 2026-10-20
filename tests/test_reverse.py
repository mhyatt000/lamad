"""Run with uv run python -m unittest discover -s tests -v."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from click.testing import CliRunner
from build123d import Box, Cone, Cylinder, GeomType, Pos, Sphere, Torus
import numpy as np
from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
from PIL import Image

from lamad.cli import cli
from lamad.core import comparison
from lamad.core.comparison import STRATEGIES, compare_shapes, drop_non_solids, non_solid_count
from lamad.core.export import export_step
from lamad.core.inspection import face_report, inspect_step, shapes
from lamad.core.report_render import BG, BLUE, EXTRA, VIEWS, camera, comparison_image, mesh, raster
from lamad.core.runner import _compound


def counterbored_plate():
    """Box(30, 30, 10) with two counterbored holes: through r=1.5, counterbore r=3 depth 3."""
    body = Box(30, 30, 10)
    for x in (-8, 8):
        body -= Pos(x, 0, 0) * Cylinder(1.5, 12)
        body -= Pos(x, 0, 5 - 1.5) * Cylinder(3, 3)
    return body


COUNTERBORE_SCRIPT = """body = Box(30, 30, 10)
for x in (-8, 8):
    body -= Pos(x, 0, 0) * Cylinder(1.5, 12)
    body -= Pos(x, 0, 5 - 1.5) * Cylinder(3, 3)
show_object(body)
"""


class GeometryTests(unittest.TestCase):
    def test_identical_and_translated(self):
        box = Box(10, 10, 10).wrapped
        equal, _ = compare_shapes(box, box)
        self.assertAlmostEqual(equal["difference"]["symmetric_difference_volume"], 0)
        self.assertAlmostEqual(equal["difference"]["intersection_over_union"], 1)
        moved = (Pos(2, 0, 0) * Box(10, 10, 10)).wrapped
        report, _ = compare_shapes(box, moved)
        self.assertAlmostEqual(report["difference"]["missing_volume"], 200)
        self.assertAlmostEqual(report["difference"]["extra_volume"], 200)
        self.assertAlmostEqual(report["difference"]["intersection_over_union"], 2 / 3)

    def test_missing_hole_and_union(self):
        box = Box(10, 10, 10)
        drilled = box - Cylinder(2, 20)
        report, _ = compare_shapes(drilled.wrapped, box.wrapped)
        self.assertAlmostEqual(report["difference"]["missing_volume"], 0)
        self.assertAlmostEqual(report["difference"]["extra_volume"], 40 * __import__("math").pi)
        overlapping = _compound([box.wrapped, (Pos(2, 0, 0) * box).wrapped])
        union, _ = compare_shapes(box.wrapped, overlapping)
        self.assertAlmostEqual(union["difference"]["reconstruction_volume"], 1200)

    def test_disjoint_and_surface_rejection(self):
        box = Box(10, 10, 10).wrapped
        report, _ = compare_shapes(box, (Pos(30, 0, 0) * Box(10, 10, 10)).wrapped)
        self.assertAlmostEqual(report["difference"]["intersection_over_union"], 0)
        face = shapes(box, TopAbs_FACE)[0]
        with self.assertRaises(ValueError):
            compare_shapes(box, face)
        with self.assertRaises(ValueError):
            compare_shapes(box, _compound([box, (Pos(30, 0, 0) * Box(1, 1, 1)).faces()[0].wrapped]))

    def test_analytic_surface_parameters(self):
        for solid, kind in [(Cylinder(2, 5), "cylinder"), (Sphere(2), "sphere"),
                            (Cone(3, 1, 5), "cone"), (Torus(5, 1), "torus")]:
            reports = [face_report(f, "f1") for f in shapes(solid.wrapped, TopAbs_FACE)]
            analytic = next(f for f in reports if f["surface"] == kind)
            self.assertEqual(analytic["axis"], [0, 0, 1])
            if kind in ("cylinder", "sphere"):
                self.assertAlmostEqual(analytic["radius"], 2)

    def test_shared_camera_preserves_displacement(self):
        import numpy as np
        a = mesh(Box(10, 10, 10).wrapped, 0.1)
        b = mesh((Pos(2, 0, 0) * Box(10, 10, 10)).wrapped, 0.1)
        cam = camera([a, b], (0, -1, 0), 160)
        _, ia = raster([(a, BLUE, 0)], cam, 160)
        _, ib = raster([(b, BLUE, 0)], cam, 160)
        self.assertGreater(np.where(ib >= 0)[1].mean(), np.where(ia >= 0)[1].mean())

    def test_boolean_strategy_ladder(self):
        box = Box(10, 10, 10).wrapped
        report, _ = compare_shapes(box, box)
        self.assertEqual(report["difference"]["boolean_strategy"], "plain")
        self.assertEqual(STRATEGIES, ("plain", "glue-shift", "glue-full", "fuzzy"))
        attempt = comparison._attempt

        def failing_before(rung):
            def wrapper(kind, a, b, tolerance, strategy):
                if STRATEGIES.index(strategy) < STRATEGIES.index(rung):
                    return None
                return attempt(kind, a, b, tolerance, strategy)
            return wrapper

        for rung in ("glue-shift", "glue-full", "fuzzy"):
            with patch.object(comparison, "_attempt", failing_before(rung)):
                report, _ = compare_shapes(box, box)
            self.assertEqual(report["difference"]["boolean_strategy"], rung)
            self.assertAlmostEqual(report["difference"]["intersection_over_union"], 1)
        with patch.object(comparison, "_attempt", lambda *a: None):
            with self.assertRaisesRegex(ValueError, "glue-shift, glue-full, and a 10x fuzzy"):
                compare_shapes(box, box)

    def test_drop_non_solids(self):
        box = Box(10, 10, 10).wrapped
        face = Cylinder(5, 10).faces().filter_by(GeomType.CYLINDER)[0].wrapped
        mixed = _compound([box, _compound([face, Box(2, 2, 2).wrapped])])
        self.assertEqual(non_solid_count(mixed), 1)
        kept, dropped = drop_non_solids(mixed)
        self.assertEqual(dropped, 1)
        self.assertEqual(len(shapes(kept, TopAbs_SOLID)), 2)
        self.assertEqual(non_solid_count(kept), 0)
        self.assertEqual(drop_non_solids(box)[1], 0)
        self.assertEqual(non_solid_count(box), 0)


class PreviewTests(unittest.TestCase):
    """The top view must show a tall feature that only the reconstruction has."""

    SIZE = 320

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lamad-preview-")

    def tearDown(self):
        self.tmp.cleanup()

    def panel(self, image, view, column):
        """Pixels of one comparison panel: rows follow VIEWS, columns reference/reconstruction/overlay/difference."""
        row = list(VIEWS).index(view)
        y = 30 + row * (self.SIZE + 24) + 24
        return image[y:y + self.SIZE, column * self.SIZE:(column + 1) * self.SIZE]

    def check_post(self, x, y):
        radius, height = 2, 40
        reference = Box(40, 40, 5).wrapped
        reconstruction = (Box(40, 40, 5) + Pos(x, y, 2.5 + height / 2) * Cylinder(radius, height)).wrapped
        _, geometry = compare_shapes(reference, reconstruction)
        path = Path(self.tmp.name) / "comparison.png"
        comparison_image(geometry, path, 0.1, self.SIZE)
        image = np.asarray(Image.open(path).convert("RGB")).astype(int)
        # Where the post's top lands in the shared top-view camera.
        meshes = [mesh(geometry[k], 0.1) for k in ("reference", "reconstruction")]
        basis, center, scale = camera(meshes, VIEWS["top (+Z)"], self.SIZE)
        top = (np.array([[x, y, 2.5 + height]]) @ basis - center) * scale
        px, py = int(top[0, 0] + self.SIZE / 2), int(self.SIZE / 2 - top[0, 1])
        reach = int(radius * scale) + 2
        reference_panel, reconstruction_panel, _, difference_panel = (
            self.panel(image, "top (+Z)", c) for c in range(4))
        # Framing: the post footprint is rendered in the reconstruction panel ...
        self.assertGreater(np.abs(reconstruction_panel[py, px] - BG).sum(), 30)
        # ... and the differences panel paints it in the "extra" colour.
        self.assertLess(np.abs(difference_panel[py, px] - EXTRA).sum(), 60)
        # Visibility: the footprint is distinguishable from the surrounding box top,
        # whose +Z face would otherwise take the same flat shade: its rim is outlined.
        box_top = reconstruction_panel[self.SIZE // 2, self.SIZE // 2]
        footprint = reconstruction_panel[py - reach:py + reach + 1, px - reach:px + reach + 1].reshape(-1, 3)
        darker = (footprint.sum(axis=1) < 0.8 * box_top.sum()).sum()
        self.assertGreaterEqual(darker, 2 * np.pi * radius * scale * 0.5)
        return reference_panel[py, px]

    def test_tall_post_inside_reference_footprint(self):
        at_post = self.check_post(15, 15)
        self.assertGreater(np.abs(at_post - BG).sum(), 30)  # reference box top is under the post

    def test_tall_post_outside_reference_bounds(self):
        at_post = self.check_post(25, 25)
        self.assertLess(np.abs(at_post - BG).sum(), 30)  # nothing of the reference there


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lamad-test-")
        self.root = Path(self.tmp.name)
        self.ref = self.root / "reference.step"
        self.script = self.root / "reconstruction.py"
        export_step(Box(10, 10, 10).wrapped, self.ref)
        self.script.write_text('width = 10\nprint("script diagnostics")\nshow_object(Box(width, 10, 10))\n')
        self.runner = CliRunner()

    def tearDown(self):
        self.tmp.cleanup()

    def invoke(self, args):
        result = self.runner.invoke(cli, ["re", *args])
        return result, json.loads(result.stdout)

    def test_inspect_adjacency_and_views(self):
        out = self.root / "inspect"
        result, payload = self.invoke(["inspect", str(self.ref), "--out", str(out)])
        self.assertEqual(result.exit_code, 0, result.output)
        part = payload["parts"][0]
        self.assertEqual(part["surface_counts"], {"plane": 6})
        self.assertTrue(all(len(f["adjacent_faces"]) == 4 for f in part["faces"]))
        self.assertTrue((out / "preview.png").exists())
        self.assertEqual(json.loads((out / "report.json").read_text()), payload)

    def test_compare_artifacts_and_parameter(self):
        out = self.root / "compare"
        result, payload = self.invoke(["compare", str(self.ref), str(self.script),
                                       "--param", "width=12", "--out", str(out)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertAlmostEqual(payload["difference"]["extra_volume"], 200)
        self.assertAlmostEqual(payload["difference"]["missing_volume"], 0)
        self.assertEqual(payload["difference"]["boolean_strategy"], "plain")
        self.assertEqual(payload["reference"]["dropped_non_solids"], 0)
        self.assertTrue((out / "extra.step").exists())
        self.assertFalse((out / "missing.step").exists())
        self.assertTrue((out / "comparison.png").exists())
        self.assertEqual(payload["params"]["width"], 12)
        self.assertEqual((out / "script.py").read_text(), self.script.read_text())
        before = (out / "report.json").read_bytes()
        result, error = self.invoke(["compare", str(self.ref), str(self.script), "--out", str(out)])
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(error["status"], "error")
        self.assertEqual((out / "report.json").read_bytes(), before)

    def test_coincident_counterbores_compare(self):
        export_step(counterbored_plate().wrapped, self.ref)
        self.script.write_text(COUNTERBORE_SCRIPT)
        out = self.root / "counterbore"
        result, payload = self.invoke(["compare", str(self.ref), str(self.script), "--no-preview",
                                       "--out", str(out)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertGreaterEqual(payload["difference"]["intersection_over_union"], 0.999)
        self.assertIn(payload["difference"]["boolean_strategy"], STRATEGIES)
        self.assertAlmostEqual(payload["difference"]["reference_volume"],
                               30 * 30 * 10 - 2 * np.pi * (1.5 ** 2 * 7 + 3 ** 2 * 3), places=3)

    def test_solids_only_drops_free_faces(self):
        face = Cylinder(5, 10).faces().filter_by(GeomType.CYLINDER)[0].wrapped
        export_step(_compound([Box(10, 10, 10).wrapped, face]), self.ref)
        out = self.root / "refused"
        result, payload = self.invoke(["compare", str(self.ref), str(self.script), "--no-preview",
                                       "--out", str(out)])
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(payload["status"], "error")
        self.assertIn("--solids-only", payload["message"])
        self.assertFalse(out.exists())
        out = self.root / "solids-only"
        result, payload = self.invoke(["compare", str(self.ref), str(self.script), "--no-preview",
                                       "--solids-only", "--out", str(out)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertAlmostEqual(payload["difference"]["intersection_over_union"], 1)
        self.assertEqual(payload["reference"]["dropped_non_solids"], 1)
        self.assertIn("dropped 1 non-solid", result.stderr)
        self.assertEqual(json.loads((out / "report.json").read_text()), payload)

    def test_default_output_sits_next_to_input(self):
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        previous = os.getcwd()
        os.chdir(elsewhere)
        try:
            result, payload = self.invoke(["inspect", str(self.ref), "--no-preview"])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(Path(payload["outputs"]["report"]),
                             (self.root / "reference_inspect" / "report.json").resolve())
            result, payload = self.invoke(["compare", str(self.ref), str(self.script), "--no-preview"])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(Path(payload["outputs"]["report"]),
                             (self.root / "reconstruction_compare" / "report.json").resolve())
        finally:
            os.chdir(previous)
        self.assertTrue((self.root / "reference_inspect" / "report.json").exists())
        self.assertTrue((self.root / "reconstruction_compare" / "report.json").exists())
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_invalid_script_leaves_no_report(self):
        self.script.write_text("not valid python !")
        out = self.root / "bad"
        result, payload = self.invoke(["compare", str(self.ref), str(self.script), "--out", str(out)])
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(payload["status"], "error")
        self.assertFalse(out.exists())

    def test_named_instances_are_preserved(self):
        a, b = Box(10, 10, 10).wrapped, (Pos(20, 0, 0) * Box(10, 10, 10)).wrapped
        export_step(_compound([a, b]), self.ref,
                    parts=[{"shape": a, "name": "repeated"}, {"shape": b, "name": "repeated"}])
        report, _ = inspect_step(self.ref)
        self.assertEqual(len(report["parts"]), 2)
        self.assertEqual(len({p["id"] for p in report["parts"]}), 2)
        self.assertTrue(all(p["name"] == "repeated" for p in report["parts"]))
        centers = sorted(p["metrics"]["center_of_mass"]["x"] for p in report["parts"])
        self.assertEqual(centers, [0, 20])

    def test_nested_assembly_locations(self):
        from OCP.STEPCAFControl import STEPCAFControl_Writer
        from OCP.STEPControl import STEPControl_AsIs
        from OCP.TCollection import TCollection_ExtendedString
        from OCP.TDocStd import TDocStd_Document
        from OCP.TopLoc import TopLoc_Location
        from OCP.XCAFDoc import XCAFDoc_DocumentTool
        from OCP.gp import gp_Trsf, gp_Vec
        doc = TDocStd_Document(TCollection_ExtendedString("nested"))
        tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
        root, sub = tool.NewShape(), tool.NewShape()
        leaf = tool.AddShape(Box(2, 4, 6).wrapped, False)

        def location(x, y, z):
            t = gp_Trsf()
            t.SetTranslation(gp_Vec(x, y, z))
            return TopLoc_Location(t)

        tool.AddComponent(sub, leaf, location(0, 20, 0))
        tool.AddComponent(root, sub, location(10, 0, 0))
        tool.AddComponent(root, sub, location(30, 0, 0))
        tool.UpdateAssemblies()
        writer = STEPCAFControl_Writer()
        self.assertTrue(writer.Transfer(doc, STEPControl_AsIs))
        writer.Write(str(self.ref))
        report, _ = inspect_step(self.ref)
        centers = sorted((p["metrics"]["center_of_mass"]["x"],
                          p["metrics"]["center_of_mass"]["y"]) for p in report["parts"])
        self.assertEqual(centers, [(10, 20), (30, 20)])
        self.assertTrue(report["assembly"][0]["children"][0]["children"])

    def test_invalid_step_and_no_preview(self):
        out = self.root / "no-preview"
        result, payload = self.invoke(["compare", str(self.ref), str(self.script),
                                       "--no-preview", "--out", str(out)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertNotIn("preview", payload["outputs"])
        self.assertAlmostEqual(payload["difference"]["symmetric_difference_volume"], 0)
        self.ref.write_text("not a STEP file")
        out = self.root / "bad-step"
        result, payload = self.invoke(["inspect", str(self.ref), "--out", str(out)])
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(payload["status"], "error")
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
