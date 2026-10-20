"""Run with uv run python -m unittest discover -s tests -v."""

import json
from pathlib import Path
import tempfile
import unittest

from click.testing import CliRunner
from build123d import Box, Cone, Cylinder, Pos, Sphere, Torus
from OCP.TopAbs import TopAbs_FACE

from lamad.cli import cli
from lamad.core.comparison import compare_shapes
from lamad.core.export import export_step
from lamad.core.inspection import face_report, inspect_step, shapes
from lamad.core.report_render import camera, mesh, raster, BLUE
from lamad.core.runner import _compound


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
