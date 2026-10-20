"""Feature detection (`lamad re det`). Run with uv run python -m unittest discover -s tests -v.

Fixtures are built with build123d once per test class and exported to STEP
(the input under test) and STL (ready for the planned mesh detectors; only
the STL "planned" error path is exercised here).
"""

from collections import Counter
import json
from pathlib import Path
import tempfile
import unittest

from click.testing import CliRunner
from build123d import Box, Circle, Cylinder, Plane, Pos, Rectangle, Sphere, chamfer, fillet, loft

from lamad.cli import cli
from lamad.core.detect import FEATURES, rows_for, support_matrix, support_table
from lamad.core.detect.corners import detect_corners
from lamad.core.detect.edges import detect_edges
from lamad.core.detect.faces import detect_faces
from lamad.core.export import export_step, export_stl
from lamad.core.step_io import load_shape

FIXTURES = {
    "box": lambda: Box(20, 30, 40),
    "cylinder": lambda: Cylinder(5, 20),
    "hole": lambda: Box(20, 30, 40) - Cylinder(4, 50),
    "boss": lambda: Box(20, 30, 10) + Pos(0, 0, 10) * Cylinder(4, 10),
    "fillet": lambda: fillet(Box(20, 30, 40).edges(), 2),
    "chamfer": lambda: chamfer(Box(20, 30, 40).edges(), 2),
    "sphere": lambda: Sphere(5),
    "loft": lambda: loft([Circle(5), Plane.XY.offset(20) * Rectangle(8, 8)]),
}


class FixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="lamad-detect-")
        cls.root = Path(cls.tmp.name)
        cls.step, cls.stl = {}, {}
        for name, build in FIXTURES.items():
            shape = build().wrapped
            cls.step[name] = cls.root / f"{name}.step"
            cls.stl[name] = cls.root / f"{name}.stl"
            export_step(shape, cls.step[name])
            export_stl(shape, cls.stl[name])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def shape(self, name):
        return load_shape(self.step[name])

    def detect(self, name, angle_tol=10.0):
        shape = self.shape(name)
        _, edges = detect_edges(shape)
        _, faces = detect_faces(shape)
        _, sharp, corners = detect_corners(shape, angle_tol)
        return edges, faces, sharp, corners


class LibraryTests(FixtureTests):
    def test_registry_is_consistent(self):
        names = [r["name"] for r in FEATURES]
        self.assertEqual(len(names), len(set(names)))
        for required in ("edges/line", "edges/circle", "edges/ellipse", "edges/freeform",
                         "corners/sharp-edge", "corners/vertex", "faces/plane", "faces/cylinder",
                         "faces/cone", "faces/sphere", "faces/torus", "faces/freeform",
                         "fillet", "chamfer", "hole", "boss", "pattern"):
            self.assertIn(required, names)
        for row in FEATURES:
            self.assertIn(row["step"], ("done", "planned"))
            self.assertEqual(row["stl"], "planned")
        self.assertTrue(all(r["step"] == "done" for r in rows_for("edges") + rows_for("corners") + rows_for("faces")))
        table = support_table()
        self.assertIn("feature", table.splitlines()[0])
        self.assertEqual(len(table.splitlines()), len(FEATURES) + 2)
        self.assertEqual([r["name"] for r in support_matrix()], names)
        json.dumps(support_matrix())

    def test_box(self):
        edges, faces, sharp, corners = self.detect("box")
        self.assertEqual(Counter(e["type"] for e in edges), {"line": 12})
        self.assertEqual(Counter(f["type"] for f in faces), {"plane": 6})
        self.assertEqual(len(sharp), 12)
        self.assertTrue(all(e["convexity"] == "convex" and abs(e["angle"] - 90) < 1e-6 for e in sharp))
        self.assertEqual(len(corners), 8)
        self.assertTrue(all(len(c["sharp_edges"]) == 3 for c in corners))
        self.assertEqual(sorted({tuple(abs(x) for x in c["position"]) for c in corners}), [(10, 15, 20)])
        self.assertEqual({e["id"] for e in edges}, {f"e{i}" for i in range(1, 13)})
        ids = {e["id"] for e in sharp}
        for c in corners:
            self.assertTrue(set(c["sharp_edges"]) <= ids)

    def test_cylinder(self):
        edges, faces, sharp, corners = self.detect("cylinder")
        circles = [e for e in edges if e["type"] == "circle"]
        self.assertEqual(len(circles), 2)
        for c in circles:
            self.assertAlmostEqual(c["radius"], 5)
            self.assertTrue(c["closed"])
            self.assertEqual([abs(x) for x in c["normal"]], [0, 0, 1])
        self.assertEqual(sorted(c["center"] for c in circles), [[0, 0, -10], [0, 0, 10]])
        self.assertLessEqual(Counter(e["type"] for e in edges)["line"], 1)
        self.assertEqual(Counter(f["type"] for f in faces), {"plane": 2, "cylinder": 1})
        self.assertEqual(sorted(e["id"] for e in sharp), sorted(c["id"] for c in circles))
        self.assertEqual(corners, [])

    def test_through_hole_edges_are_convex_like_outer_edges(self):
        """A through-hole rim is a 90 deg material wedge: convex, same as the box."""
        edges, faces, sharp, corners = self.detect("hole")
        circles = [e for e in edges if e["type"] == "circle"]
        self.assertEqual(len(circles), 2)
        self.assertTrue(all(abs(c["radius"] - 4) < 1e-6 for c in circles))
        self.assertEqual(Counter(f["type"] for f in faces), {"plane": 6, "cylinder": 1})
        self.assertAlmostEqual(next(f for f in faces if f["type"] == "cylinder")["radius"], 4)
        by_id = {e["id"]: e for e in sharp}
        hole = [by_id[c["id"]] for c in circles]
        outer = [e for e in sharp if e["id"] not in {c["id"] for c in circles}]
        self.assertEqual(len(hole), 2)
        self.assertEqual(len(outer), 12)
        self.assertEqual({e["convexity"] for e in outer}, {"convex"})
        self.assertEqual({e["convexity"] for e in hole}, {"convex"})
        self.assertEqual(len(corners), 8)

    def test_boss_base_is_concave(self):
        """Material added on top of a face makes a 270 deg (concave) edge."""
        edges, _, sharp, _ = self.detect("boss")
        by_id = {e["id"]: e for e in sharp}
        circles = sorted((e for e in edges if e["type"] == "circle"), key=lambda e: e["center"][2])
        base, top = by_id[circles[0]["id"]], by_id[circles[1]["id"]]
        self.assertEqual(base["convexity"], "concave")
        self.assertAlmostEqual(base["angle"], 270)
        self.assertEqual(top["convexity"], "convex")
        self.assertAlmostEqual(top["angle"], 90)
        self.assertEqual(sum(1 for e in sharp if e["convexity"] == "concave"), 1)

    def test_filleted_box_has_no_sharp_edges(self):
        edges, faces, sharp, corners = self.detect("fillet")
        self.assertEqual(sharp, [])
        self.assertEqual(corners, [])
        kinds = Counter(f["type"] for f in faces)
        self.assertEqual(kinds["plane"], 6)
        self.assertEqual(kinds["cylinder"], 12)
        self.assertEqual(kinds["sphere"] + kinds["torus"], 8)
        self.assertEqual(kinds["freeform"], 0)
        for f in faces:
            if f["type"] == "cylinder":
                self.assertAlmostEqual(f["radius"], 2)
        arcs = [e for e in edges if e["type"] == "circle"]
        self.assertEqual(len(arcs), 24)
        self.assertTrue(all(abs(e["radius"] - 2) < 1e-6 and abs(e["sweep_degrees"] - 90) < 1e-6 for e in arcs))

    def test_chamfered_box(self):
        edges, faces, sharp, corners = self.detect("chamfer")
        self.assertEqual(Counter(f["type"] for f in faces), {"plane": 26})
        self.assertEqual(Counter(e["type"] for e in edges), {"line": 48})
        self.assertEqual(len(sharp), 48)
        self.assertEqual({e["convexity"] for e in sharp}, {"convex"})
        angles = Counter(round(e["angle"], 3) for e in sharp)
        self.assertEqual(angles[135.0], 24)           # original face <-> chamfer face
        self.assertEqual(angles[144.736], 24)         # chamfer face <-> corner triangle
        self.assertEqual(len(corners), 24)            # 8 corner triangles x 3 vertices
        self.assertTrue(all(len(c["sharp_edges"]) == 4 for c in corners))
        self.assertEqual(len(self.detect("chamfer", angle_tol=50)[2]), 0)

    def test_sphere(self):
        edges, faces, sharp, corners = self.detect("sphere")
        self.assertEqual(Counter(f["type"] for f in faces), {"sphere": 1})
        self.assertAlmostEqual(faces[0]["radius"], 5)
        self.assertEqual(sharp, [])
        self.assertEqual(corners, [])
        self.assertTrue(all(e["type"] == "circle" for e in edges))

    def test_loft_is_freeform(self):
        edges, faces, _, _ = self.detect("loft")
        self.assertGreaterEqual(Counter(f["type"] for f in faces)["freeform"], 1)
        self.assertGreaterEqual(Counter(e["type"] for e in edges)["freeform"], 1)
        self.assertTrue(all(f["surface"] not in ("plane", "cylinder") for f in faces if f["type"] == "freeform"))

    def test_edge_geometry_fields(self):
        edges, _, _, _ = self.detect("box")
        for e in edges:
            self.assertAlmostEqual(e["length"], abs(sum(a - b for a, b in zip(e["start"], e["end"]))), places=6)
            self.assertIn("direction", e)
            self.assertFalse(e["closed"])
        summary, _ = detect_edges(self.shape("box"))
        self.assertEqual(summary["by_type"], {"line": 12, "circle": 0, "ellipse": 0, "freeform": 0})
        summary, _, _ = detect_corners(self.shape("box"))
        self.assertEqual((summary["sharp_edges"], summary["convex"], summary["concave"], summary["corners"]),
                         (12, 12, 0, 8))
        summary, _ = detect_faces(self.shape("box"))
        self.assertEqual(summary["by_type"]["plane"], 6)
        self.assertAlmostEqual(summary["area"], 2 * (20 * 30 + 30 * 40 + 20 * 40))


class CommandTests(FixtureTests):
    def setUp(self):
        self.runner = CliRunner()

    def invoke(self, *args):
        result = self.runner.invoke(cli, ["re", "det", *args])
        return result, json.loads(result.stdout)

    def test_bare_and_help_print_support_table(self):
        for args in ([], ["--help"]):
            result = self.runner.invoke(cli, ["re", "det", *args])
            self.assertEqual(result.exit_code, 0, result.output)
            for line in support_table().splitlines():
                self.assertIn(line, result.output)
            for name in ("edges", "corners", "faces", "all", "status"):
                self.assertIn(f"  {name}", result.output)
        result = self.runner.invoke(cli, ["re"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("det", result.output)

    def test_status_matrix(self):
        result, payload = self.invoke("status")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(payload["command"], "det.status")
        self.assertEqual(payload["features"], support_matrix())
        self.assertEqual(payload["columns"], ["feature", "step", "stl"])

    def test_edges_command(self):
        result, payload = self.invoke("edges", str(self.step["cylinder"]))
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(payload["command"], "det.edges")
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["summary"]["by_type"]["circle"], 2)
        self.assertEqual(len(payload["edges"]), payload["summary"]["total"])

    def test_corners_command_with_tolerance(self):
        result, payload = self.invoke("corners", str(self.step["chamfer"]))
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(payload["summary"]["sharp_edges"], 48)
        self.assertEqual(payload["summary"]["corners"], 24)
        result, payload = self.invoke("corners", str(self.step["chamfer"]), "--angle-tol", "50")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(payload["summary"]["sharp_edges"], 0)
        self.assertEqual(payload["summary"]["angle_tol_degrees"], 50)

    def test_faces_command(self):
        result, payload = self.invoke("faces", str(self.step["fillet"]))
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(payload["summary"]["by_type"]["cylinder"], 12)
        self.assertEqual(payload["summary"]["by_type"]["freeform"], 0)

    def test_all_command_and_out_file(self):
        out = self.root / "reports" / "hole.json"
        result, payload = self.invoke("all", str(self.step["hole"]), "--out", str(out))
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(payload["command"], "det.all")
        self.assertEqual(payload["summary"]["faces"]["by_type"]["cylinder"], 1)
        self.assertEqual(payload["summary"]["corners"]["corners"], 8)
        self.assertEqual(payload["summary"]["edges"]["by_type"]["circle"], 2)
        self.assertEqual(payload["outputs"]["json"], str(out.resolve()))
        written = json.loads(out.read_text())
        self.assertEqual(written["summary"], payload["summary"])
        self.assertEqual(written["edges"], payload["edges"])

    def test_stl_is_planned(self):
        for command, group in (("edges", "edges"), ("corners", "corners"), ("faces", "faces"), ("all", None)):
            result, payload = self.invoke(command, str(self.stl["box"]))
            self.assertEqual(result.exit_code, 1)
            self.assertEqual(payload["status"], "error")
            self.assertEqual(payload["command"], f"det.{command}")
            self.assertIn("STL", payload["message"])
            self.assertIn("planned", payload["message"])
            self.assertEqual(payload["support"], rows_for(group))
            self.assertTrue(all(r["stl"] == "planned" for r in payload["support"]))

    def test_bad_input_is_json_error(self):
        bad = self.root / "broken.step"
        bad.write_text("not a STEP file")
        result, payload = self.invoke("edges", str(bad))
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(payload["status"], "error")
        result = self.runner.invoke(cli, ["re", "det", "faces", str(self.root / "missing.step")])
        self.assertNotEqual(result.exit_code, 0)


if __name__ == "__main__":
    unittest.main()
