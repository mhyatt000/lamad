"""Tests for `lamad web`. Run with uv run python -m unittest discover -s tests -v.

The viewer is mocked so no port is bound; the script itself really executes.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from click.testing import CliRunner

from lamad.cli import cli
from lamad.cli.web import assign_colors, split_solids
from lamad.core.viewer import unique_paths
from lamad.core.export import PALETTE

STAND = Path(__file__).resolve().parent.parent / "examples" / "stand.py"


def run_web(*args):
    """Invoke `lamad web` with the server mocked out. Returns (result, parsed JSON or None)."""
    with mock.patch("lamad.core.viewer.serve_parts") as serve_parts, \
            mock.patch("lamad.core.viewer.wait") as wait, \
            mock.patch("webbrowser.open") as browser:
        # A stand-in Scene that reports the port it was asked for.
        serve_parts.side_effect = lambda *a, **kw: mock.Mock(port=kw["port"])
        result = CliRunner().invoke(cli, ["web", *args])
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = None
    return result, payload, serve_parts, wait, browser


class WebCommandTests(unittest.TestCase):
    def test_stand_three_distinct_colors(self):
        result, payload, serve_parts, wait, browser = run_web(str(STAND), "--no-browser")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["command"], "web")
        self.assertEqual([p["name"] for p in payload["parts"]], ["wedge", "floor", "lip"])
        colors = [p["color"] for p in payload["parts"]]
        self.assertEqual(len(set(colors)), 3)
        for c in colors:
            self.assertRegex(c, r"^#[0-9a-f]{6}$")
        self.assertEqual(payload["url"], "http://localhost:8080")
        self.assertEqual(payload["params"]["width"], 80)
        serve_parts.assert_called_once()
        wait.assert_called_once()
        browser.assert_not_called()
        # Only the JSON object goes to stdout.
        self.assertEqual(json.loads(result.stdout)["command"], "web")

    def test_param_override_and_port(self):
        result, payload, serve_parts, *_ = run_web(
            str(STAND), "--no-browser", "--param", "width=120", "--port", "9999")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(payload["params"]["width"], 120)
        self.assertEqual(payload["url"], "http://localhost:9999")
        self.assertEqual(serve_parts.call_args.kwargs["port"], 9999)

    def test_browser_opens_by_default(self):
        result, _payload, _s, _w, browser = run_web(str(STAND), "--port", "9001")
        self.assertEqual(result.exit_code, 0, result.output)
        browser.assert_called_once_with("http://localhost:9001")

    def test_script_error_is_json(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "bad.py"
            bad.write_text("x = 1\nshow_object(Box(10, 10, 10) / 0)\n")
            result, payload, serve_parts, *_ = run_web(str(bad), "--no-browser")
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(payload["status"], "error")
        self.assertIn("TypeError", payload["message"])
        self.assertIn("Traceback", payload["traceback"])
        serve_parts.assert_not_called()

    def test_non_python_argument_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            for ext in (".stl", ".step"):
                f = Path(d) / f"part{ext}"
                f.write_text("solid x\nendsolid x\n")
                result, payload, serve_parts, *_ = run_web(str(f), "--no-browser")
                self.assertEqual(result.exit_code, 1, ext)
                self.assertEqual(payload["status"], "error")
                self.assertIn("not a Python script", payload["message"])
                serve_parts.assert_not_called()

    def test_single_compound_is_split_per_solid(self):
        with tempfile.TemporaryDirectory() as d:
            script = Path(d) / "two.py"
            script.write_text(
                "a = Box(10, 10, 10)\nb = Pos(30, 0, 0) * Box(5, 5, 5)\n"
                "show_object(Compound(children=[a, b]), name='pair')\n")
            result, payload, *_ = run_web(str(script), "--no-browser")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual([p["name"] for p in payload["parts"]], ["pair/pair_1", "pair/pair_2"])
        self.assertEqual(len({p["color"] for p in payload["parts"]}), 2)

    def test_assembly_children_nest_by_label_and_keep_placement(self):
        with tempfile.TemporaryDirectory() as d:
            script = Path(d) / "asm.py"
            script.write_text(
                "bolt = Pos(10, 0, 0) * Cylinder(1, 5)\nbolt.label = 'bolt'\n"
                "slab = Box(20, 20, 2)\nslab.label = 'slab'\nslab.color = Color('red')\n"
                "base = Compound(label='base', children=[slab, bolt])\n"
                "stand = Pos(100, 0, 0) * Compound(children=[base, Box(5, 5, 5)])\n"
                "show_object(stand, name='stand')\n"
                "show_object(Sphere(3), name='extras/ball')\n")
            result, payload, serve_parts, *_ = run_web(str(script), "--no-browser")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual([p["name"] for p in payload["parts"]],
                         ["stand/base/slab", "stand/base/bolt", "stand/stand_2", "extras/ball"])
        self.assertEqual(payload["parts"][0]["color"], "#ff0000")
        # Children are stored relative to their parent; the leaf must carry
        # the assembly's +100 x move.
        from build123d import Compound
        served = {p["name"]: p for p in serve_parts.call_args.args[0]}
        bb = Compound(served["stand/base/bolt"]["shape"]).bounding_box()
        self.assertAlmostEqual(bb.min.X, 109.0, places=3)
        self.assertAlmostEqual(bb.max.X, 111.0, places=3)


class ColorHelperTests(unittest.TestCase):
    def test_explicit_kept_missing_filled_without_duplicates(self):
        parts = [{"name": "a", "color": "red"}, {"name": "b"}, {"name": "c", "color": PALETTE[0]},
                 {"name": "d", "color": None}]
        colors = assign_colors(parts)
        self.assertEqual(colors[0], (1, 0, 0))
        self.assertEqual(colors[2], PALETTE[0])
        self.assertEqual(colors[1], PALETTE[1])   # PALETTE[0] is taken by "c"
        self.assertEqual(colors[3], PALETTE[2])
        self.assertEqual(len(set(colors)), 4)

    def test_full_palette_without_duplicates(self):
        parts = [{"name": f"p{i}"} for i in range(len(PALETTE))]
        colors = assign_colors(parts)
        self.assertEqual(colors, list(PALETTE))
        self.assertEqual(len(set(colors)), len(PALETTE))

    def test_cycles_beyond_palette(self):
        parts = [{"name": f"p{i}"} for i in range(len(PALETTE) + 2)]
        colors = assign_colors(parts)
        self.assertEqual(colors[len(PALETTE)], PALETTE[0])
        self.assertEqual(colors[len(PALETTE) + 1], PALETTE[1])

    def test_split_leaves_multi_part_results_alone(self):
        from build123d import Box
        parts = [{"path": ("a",), "shape": Box(1, 1, 1).wrapped, "color": None},
                 {"path": ("b",), "shape": Box(2, 2, 2).wrapped, "color": None}]
        self.assertEqual([p["path"] for p in split_solids(parts)], [("a",), ("b",)])
        self.assertEqual([p["path"] for p in split_solids(parts[:1])], [("a",)])

    def test_unique_paths_join_and_number_repeats(self):
        parts = [{"path": ("a", "b")}, {"path": ("a", "b")}, {"path": ("x/y",)}]
        self.assertEqual([p["name"] for p in unique_paths(parts)], ["a/b", "a/b_2", "x_y"])


class StepHierarchyTests(unittest.TestCase):
    def test_load_parts_keeps_assembly_path(self):
        from build123d import Box, Compound, Cylinder, Pos, export_step
        from lamad.core.viewer import load_parts
        bolt = Pos(10, 0, 0) * Cylinder(1, 5)
        bolt.label = "bolt"
        slab = Box(20, 20, 2)
        slab.label = "slab"
        top = Box(5, 5, 5)
        top.label = "top"
        stand = Compound(label="stand", children=[Compound(label="base", children=[slab, bolt]), top])
        with tempfile.TemporaryDirectory() as d:
            export_step(stand, Path(d) / "asm.step")
            _doc, loaded = load_parts(Path(d) / "asm.step")
        self.assertEqual([p for p, _s, _c in loaded],
                         [("stand", "base", "slab"), ("stand", "base", "bolt"), ("stand", "top")])

    def test_flat_lamad_step_stays_flat(self):
        from lamad.core import export, runner
        from lamad.core.viewer import load_parts
        r = runner.execute(STAND.read_text())
        with tempfile.TemporaryDirectory() as d:
            export.export_step(r.shape, Path(d) / "s.step", parts=r.parts)
            _doc, loaded = load_parts(Path(d) / "s.step")
        self.assertEqual([p for p, _s, _c in loaded], [("wedge",), ("floor",), ("lip",)])


if __name__ == "__main__":
    unittest.main()
