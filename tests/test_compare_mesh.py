"""`lamad re compare` with an STL reference (mesh mode) next to the STEP solid mode."""

import json
from pathlib import Path
import tempfile
import unittest

from click.testing import CliRunner
from build123d import Box, Cylinder

from lamad.cli import cli
from lamad.core.export import export_step, export_stl

TOL = 0.1          # --tol default and the fixture's export deflection
SCRIPT = "radius = {radius}\nshow_object(Box(20, 20, 10) - Cylinder(radius, 20))\n"


class MeshCompareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lamad-mesh-test-")
        self.root = Path(self.tmp.name)
        part = (Box(20, 20, 10) - Cylinder(3, 20)).wrapped
        self.stl = self.root / "fixture.stl"
        self.step = self.root / "fixture.step"
        export_stl(part, self.stl, deflection=TOL)
        export_step(part, self.step)
        self.match = self.root / "match.py"
        self.match.write_text(SCRIPT.format(radius=3))
        self.mismatch = self.root / "mismatch.py"
        self.mismatch.write_text(SCRIPT.format(radius=6))
        self.runner = CliRunner()

    def tearDown(self):
        self.tmp.cleanup()

    def invoke(self, *args):
        result = self.runner.invoke(cli, ["re", "compare", *map(str, args)])
        return result, json.loads(result.stdout)

    def test_matching_script_reports_tessellation_noise_only(self):
        out = self.root / "match"
        result, payload = self.invoke(self.stl, self.match, "--out", out, "--tol", TOL)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(payload["mode"], "mesh")
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["samples_each_direction"], 4000)
        self.assertEqual(payload["tessellation"], {"linear_deflection_mm": TOL, "angular_deflection_rad": 0.3})
        for direction in ("reference_to_reconstruction", "reconstruction_to_reference"):
            d = payload["distance_mm"][direction]
            # Both meshes approximate the same cylinder within TOL, so sampled
            # distances stay below the summed chord error.
            self.assertLess(d["p95"], TOL)
            self.assertLess(d["max"], 2 * TOL)
            self.assertLess(d["mean"], TOL / 10)
        self.assertEqual(payload["bounds_mm"]["size_difference"], [0, 0, 0])
        self.assertTrue(payload["volume_mm3"]["watertight"]["reference"])
        self.assertTrue(payload["volume_mm3"]["watertight"]["reconstruction"])
        self.assertLess(abs(payload["volume_mm3"]["relative_difference"]), 0.01)
        for key in ("iou", "intersection_over_union", "missing_volume", "extra_volume", "difference"):
            self.assertNotIn(key, payload)
        self.assertEqual(sorted(p.name for p in out.iterdir()),
                         ["comparison.png", "reconstruction.stl", "report.json", "script.py"])
        self.assertEqual(json.loads((out / "report.json").read_text()), payload)
        self.assertEqual((out / "script.py").read_text(), self.match.read_text())
        self.assertEqual(payload["params"], {"radius": 3})

    def test_mismatched_script_reports_clearly_larger_distances(self):
        out = self.root / "mismatch"
        result, payload = self.invoke(self.stl, self.mismatch, "--out", out, "--samples", "1000")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(payload["mode"], "mesh")
        self.assertEqual(payload["samples_each_direction"], 1000)
        for direction in ("reference_to_reconstruction", "reconstruction_to_reference"):
            d = payload["distance_mm"][direction]
            self.assertGreater(d["max"], 2.5)      # hole radius 3 -> 6
            self.assertGreater(d["p95"], 2.5)
            self.assertGreater(d["mean"], TOL)
        self.assertGreater(payload["distance_mm_summary"]["max"], 2.5)
        self.assertLess(payload["volume_mm3"]["relative_difference"], -0.2)
        self.assertEqual(payload["params"], {"radius": 6})

    def test_param_override_and_boolean_tol_warning(self):
        out = self.root / "override"
        result, payload = self.invoke(self.stl, self.mismatch, "--param", "radius=3",
                                      "--boolean-tol", "1e-5", "--no-preview", "--out", out)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("--boolean-tol is ignored in mesh mode", result.stderr)
        self.assertEqual(payload["params"], {"radius": 3})
        self.assertLess(payload["distance_mm_summary"]["max"], 2 * TOL)
        self.assertNotIn("preview", payload["outputs"])
        self.assertFalse((out / "comparison.png").exists())
        before = (out / "report.json").read_bytes()
        result, error = self.invoke(self.stl, self.match, "--out", out)
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(error["status"], "error")
        self.assertEqual((out / "report.json").read_bytes(), before)

    def test_solid_reference_still_reports_solid_mode(self):
        out = self.root / "solid"
        result, payload = self.invoke(self.step, self.match, "--out", out)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(payload["mode"], "solid")
        self.assertAlmostEqual(payload["difference"]["intersection_over_union"], 1)
        self.assertNotIn("distance_mm", payload)
        self.assertTrue((out / "reconstruction.step").exists())
        self.assertFalse((out / "reconstruction.stl").exists())

    def test_unsupported_extension_and_empty_mesh(self):
        bad = self.root / "fixture.obj"
        bad.write_bytes(self.stl.read_bytes())
        result, payload = self.invoke(bad, self.match, "--out", self.root / "bad")
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(payload["status"], "error")
        self.assertIn("Unsupported extension", payload["message"])
        self.assertFalse((self.root / "bad").exists())
        empty = self.root / "empty.stl"
        empty.write_text("solid empty\nendsolid empty\n")
        result, payload = self.invoke(empty, self.match, "--out", self.root / "empty")
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(payload["status"], "error")
        self.assertFalse((self.root / "empty").exists())


if __name__ == "__main__":
    unittest.main()
