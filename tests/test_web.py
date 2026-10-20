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
        self.assertEqual([p["name"] for p in payload["parts"]], ["pair_1", "pair_2"])
        self.assertEqual(len({p["color"] for p in payload["parts"]}), 2)


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
        parts = [{"name": "a", "shape": Box(1, 1, 1).wrapped, "color": None},
                 {"name": "b", "shape": Box(2, 2, 2).wrapped, "color": None}]
        self.assertEqual([p["name"] for p in split_solids(parts)], ["a", "b"])
        self.assertEqual([p["name"] for p in split_solids(parts[:1])], ["a"])


if __name__ == "__main__":
    unittest.main()
