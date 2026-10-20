"""Face coverage (`re coverage`, the `coverage` section of `re compare`) and part selection."""

import json
from pathlib import Path
import tempfile
import unittest

from click.testing import CliRunner
from build123d import Axis, Box, Pos, chamfer

from lamad.cli import cli
from lamad.core.coverage import face_coverage
from lamad.core.export import export_step, export_stl
from lamad.core.runner import _compound

TOL = 0.1


def chamfer_recess():
    """Box(40, 30, 10): 2 mm chamfers on the four top edges, a 1 mm-deep 10x8 recess in the top."""
    part = Box(40, 30, 10)
    part = chamfer(part.faces().sort_by(Axis.Z)[-1].edges(), 2)
    return part - Pos(0, 0, 4.5) * Box(10, 8, 1)


EXACT_SCRIPT = """part = Box(40, 30, 10)
part = chamfer(part.faces().sort_by(Axis.Z)[-1].edges(), 2)
part -= Pos(0, 0, 4.5) * Box(10, 8, 1)
show_object(part)
"""
PLAIN_SCRIPT = "show_object(Box(40, 30, 10))\n"
TWO_PART_SCRIPT = ('show_object(Box(40, 30, 10), name="base")\n'
                   'show_object(Pos(0, 0, 10) * Box(20, 20, 10), name="cap")\n')

# What the plain box lacks, as reference face areas in mm^2: the chamfer
# trapezoids (width 2*sqrt(2), parallel edges 40/36 and 30/26), the recess
# floor (10x8), and its walls (10x1 and 8x1). Largest first.
LONG_CHAMFER, SHORT_CHAMFER = 2 * 2 ** 0.5 * 38, 2 * 2 ** 0.5 * 28
MISSING_AREAS = sorted([LONG_CHAMFER] * 2 + [80.0] + [SHORT_CHAMFER] * 2 + [10.0] * 2 + [8.0] * 2,
                       reverse=True)


class FaceCoverageTests(unittest.TestCase):
    def setUp(self):
        self.reference = chamfer_recess().wrapped

    def test_exact_reproduction_matches_every_face(self):
        report = face_coverage(self.reference, chamfer_recess().wrapped, TOL)
        self.assertEqual(report["tol_mm"], TOL)
        for side in ("reference", "reconstruction"):
            self.assertEqual(report[side]["faces_total"], 15)
            self.assertEqual(report[side]["matched"], 15)
            self.assertEqual(report[side]["unmatched"], [])
            self.assertAlmostEqual(report[side]["area_matched_fraction"], 1.0)

    def test_plain_box_lists_chamfers_and_recess(self):
        report = face_coverage(self.reference, Box(40, 30, 10).wrapped, TOL)
        ref = report["reference"]
        # Matched: bottom, four sides, and the top face itself. Every sample of
        # the reference's top face lies on the plain box's top plane (the recess
        # is a hole in that face, so nothing is sampled there), so the top face
        # counts as matched even though the box top is oversized; that excess
        # shows up on the reconstruction side instead.
        self.assertEqual(ref["faces_total"], 15)
        self.assertEqual(ref["matched"], 6)
        self.assertEqual(ref["unmatched_count"], 9)
        self.assertAlmostEqual(ref["area_matched_fraction"], 1 - sum(MISSING_AREAS) / ref["area_total"], places=5)
        areas = [f["area"] for f in ref["unmatched"]]
        self.assertEqual(areas, sorted(areas, reverse=True))
        for got, want in zip(areas, MISSING_AREAS):
            self.assertAlmostEqual(got, want, places=4)
        self.assertTrue(all(f["surface"] == "plane" for f in ref["unmatched"]))
        self.assertTrue(all(f["id"].startswith("f") for f in ref["unmatched"]))
        first = ref["unmatched"][0]                                   # a long chamfer: 45 degrees
        self.assertAlmostEqual(abs(first["normal"][2]), 2 ** -0.5, places=5)
        self.assertAlmostEqual(first["distance"]["mean"], 0.5, places=3)
        floor = next(f for f in ref["unmatched"] if f["area"] == 80.0)
        self.assertEqual(floor["normal"], [0, 0, 1])
        self.assertEqual(floor["centroid"][2], 4)                      # 1 mm under the box top
        self.assertAlmostEqual(floor["distance"]["p95"], 1.0, places=5)
        self.assertEqual(sum(f["area"] in (8.0, 10.0) for f in ref["unmatched"]), 4)  # recess walls
        # The reconstruction's bottom is the only face the reference fully
        # covers. Its top hangs over the chamfers and the recess, and the top
        # 2 mm of each side (a fifth of its samples) sits where the chamfer
        # removed material, so the p95 distance of all five exceeds TOL.
        rec = report["reconstruction"]
        self.assertEqual(rec["faces_total"], 6)
        self.assertEqual(rec["matched"], 1)
        self.assertEqual([f["area"] for f in rec["unmatched"]], [1200.0, 400.0, 400.0, 300.0, 300.0])
        top = rec["unmatched"][0]
        self.assertEqual(top["normal"], [0, 0, 1])
        self.assertEqual(top["centroid"][2], 5)
        self.assertGreater(top["distance"]["p95"], TOL)
        self.assertAlmostEqual(top["distance"]["max"], 1.0, places=5)

    def test_samples_per_face_and_part_ids(self):
        parts = [{"id": "p1", "name": "plate", "shape": Box(40, 30, 10).wrapped}]
        report = face_coverage(self.reference, parts, TOL, samples_per_face=4)
        rec = report["reconstruction"]
        self.assertTrue(all(f["samples"] == 4 for f in rec["unmatched"]))
        self.assertTrue(all(f["part"] == "plate" and f["id"].startswith("p1:f") for f in rec["unmatched"]))
        self.assertEqual(report["samples_per_face"], 4)


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lamad-coverage-")
        self.root = Path(self.tmp.name)
        self.ref = self.root / "reference.step"
        export_step(chamfer_recess().wrapped, self.ref)
        self.exact = self.root / "exact.py"
        self.exact.write_text(EXACT_SCRIPT)
        self.plain = self.root / "plain.py"
        self.plain.write_text(PLAIN_SCRIPT)
        base, cap = Box(40, 30, 10).wrapped, (Pos(0, 0, 10) * Box(20, 20, 10)).wrapped
        self.assembly = self.root / "assembly.step"
        export_step(_compound([base, cap]), self.assembly,
                    parts=[{"name": "base", "shape": base}, {"name": "cap", "shape": cap}])
        self.two = self.root / "two.py"
        self.two.write_text(TWO_PART_SCRIPT)
        self.runner = CliRunner()

    def tearDown(self):
        self.tmp.cleanup()

    def invoke(self, args):
        result = self.runner.invoke(cli, ["re", *map(str, args)])
        return result, json.loads(result.stdout)

    def test_compare_carries_coverage_section(self):
        out = self.root / "compare"
        result, payload = self.invoke(["compare", self.ref, self.plain, "--no-preview", "--out", out])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(payload["mode"], "solid")
        self.assertIn("difference", payload)
        coverage = payload["coverage"]
        self.assertEqual(coverage["tol_mm"], 0.1)
        self.assertEqual((coverage["reference"]["faces_total"], coverage["reference"]["matched"]), (15, 6))
        self.assertEqual((coverage["reconstruction"]["faces_total"], coverage["reconstruction"]["matched"]), (6, 1))
        # Reference face ids follow `re inspect` (<part>:f<i>), reconstruction parts show_object order.
        self.assertRegex(coverage["reference"]["unmatched"][0]["id"], r"^p1:f\d+$")
        self.assertEqual(coverage["reconstruction"]["unmatched"][0]["id"].split(":")[0], "p1")
        self.assertEqual(coverage["reconstruction"]["unmatched"][0]["part"], "part1")
        self.assertIn("coverage: reference 6/15 faces matched", result.stderr)
        self.assertEqual(json.loads((out / "report.json").read_text()), payload)
        self.assertIsNone(payload["reference"]["selected_parts"])
        self.assertIsNone(payload["reconstruction"]["selected_parts"])
        self.assertEqual(payload["reconstruction"]["available_parts"], [{"id": "p1", "name": "part1"}])

    def test_no_coverage_omits_section(self):
        out = self.root / "nocov"
        result, payload = self.invoke(["compare", self.ref, self.plain, "--no-preview", "--no-coverage",
                                       "--out", out])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertNotIn("coverage", payload)
        self.assertNotIn("coverage", json.loads((out / "report.json").read_text()))
        self.assertNotIn("coverage:", result.stderr)

    def test_coverage_command_writes_report(self):
        out = self.root / "cov"
        result, payload = self.invoke(["coverage", self.ref, self.exact, "--out", out, "--tol", "0.05"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(payload["command"], "coverage")
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["reference_file"], str(self.ref.resolve()))
        self.assertEqual(payload["script"], str(self.exact.resolve()))
        self.assertEqual(payload["params"], {})
        self.assertEqual(payload["coverage"]["tol_mm"], 0.05)
        for side in ("reference", "reconstruction"):
            self.assertEqual(payload["coverage"][side]["unmatched"], [])
            self.assertAlmostEqual(payload["coverage"][side]["area_matched_fraction"], 1.0)
        for absent in ("difference", "distance_mm", "missing", "extra"):
            self.assertNotIn(absent, payload)
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["report.json"])
        self.assertEqual(json.loads((out / "report.json").read_text()), payload)
        # Default output sits next to the script and is never overwritten.
        result, payload = self.invoke(["coverage", self.ref, self.exact])
        self.assertEqual(result.exit_code, 0, result.output)
        default = self.root / "exact_coverage" / "report.json"
        self.assertEqual(Path(payload["outputs"]["report"]), default.resolve())
        self.assertTrue(default.exists())
        result, payload = self.invoke(["coverage", self.ref, self.exact])
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(payload["status"], "error")

    def test_part_selection_compares_only_named_parts(self):
        out = self.root / "cap"
        result, payload = self.invoke(["compare", self.assembly, self.two, "--ref-part", "cap", "--part", "cap",
                                       "--no-preview", "--out", out])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertAlmostEqual(payload["difference"]["intersection_over_union"], 1.0)
        self.assertAlmostEqual(payload["difference"]["reference_volume"], 20 * 20 * 10)
        self.assertEqual(payload["reference"]["selected_parts"], [{"id": "p2", "name": "cap"}])
        self.assertEqual(payload["reconstruction"]["selected_parts"], [{"id": "p2", "name": "cap"}])
        self.assertEqual([p["name"] for p in payload["reference"]["available_parts"]], ["base", "cap"])
        self.assertEqual([p["name"] for p in payload["reconstruction"]["available_parts"]], ["base", "cap"])
        for side in ("reference", "reconstruction"):
            self.assertEqual(payload["coverage"][side]["faces_total"], 6)
            self.assertEqual(payload["coverage"][side]["unmatched"], [])
        self.assertTrue((out / "reconstruction.step").exists())
        # Case-insensitive substrings select too, and the standalone command records the choice.
        out = self.root / "substring"
        result, payload = self.invoke(["coverage", self.assembly, self.two, "--ref-part", "CA", "--part", "Cap",
                                       "--out", out])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(payload["reference"]["selected_parts"], [{"id": "p2", "name": "cap"}])
        self.assertEqual(payload["reconstruction"]["selected_parts"], [{"id": "p2", "name": "cap"}])
        self.assertEqual(payload["coverage"]["reference"]["matched"], 6)
        # Without selection the whole assembly is covered against both script parts.
        out = self.root / "all"
        result, payload = self.invoke(["coverage", self.assembly, self.two, "--out", out])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(payload["coverage"]["reference"]["faces_total"], 12)
        self.assertEqual(payload["coverage"]["reference"]["unmatched"], [])

    def test_unknown_part_lists_available_names(self):
        for flag, command in (("--ref-part", "compare"), ("--part", "compare"), ("--part", "coverage"),
                              ("--ref-part", "coverage")):
            out = self.root / f"bad-{command}-{flag.strip('-')}"
            result, payload = self.invoke([command, self.assembly, self.two, flag, "lid", "--out", out])
            self.assertEqual(result.exit_code, 1, result.output)
            self.assertEqual(payload["status"], "error")
            self.assertIn(f"{flag} 'lid' matches no part", payload["message"])
            self.assertIn("'base', 'cap'", payload["message"])
            self.assertFalse(out.exists())

    def test_mesh_mode_covers_reconstruction_only(self):
        stl = self.root / "reference.stl"
        export_stl(chamfer_recess().wrapped, stl, deflection=TOL)   # all planar: the STL is exact
        out = self.root / "mesh"
        result, payload = self.invoke(["compare", stl, self.plain, "--no-preview", "--ref-part", "x",
                                       "--out", out])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(payload["mode"], "mesh")
        self.assertIn("--ref-part is ignored", result.stderr)
        coverage = payload["coverage"]
        self.assertIsNone(coverage["reference"])
        self.assertEqual((coverage["reconstruction"]["faces_total"], coverage["reconstruction"]["matched"]), (6, 1))
        self.assertEqual(coverage["reconstruction"]["unmatched"][0]["area"], 1200.0)
        self.assertEqual(payload["reconstruction"]["selected_parts"], None)


if __name__ == "__main__":
    unittest.main()
