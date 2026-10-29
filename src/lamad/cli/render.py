"""`lamad render`: execute a build123d script and save pictures of it as PNG.

    lamad render sketch plate.py   # planar parts, flat 2D drawing
    lamad render part stand.py     # home, top, side, bottom views of the model
"""

from pathlib import Path

import click

from lamad.cli import HelpGroup, emit, fail, note, parse_params


def default_output(script, suffix):
    """<script dir>/<stem>_<suffix>.png, numbered rather than overwritten."""
    script = Path(script).resolve()
    out, n = script.with_name(f"{script.stem}_{suffix}.png"), 1
    while out.exists():
        n += 1
        out = script.with_name(f"{script.stem}_{suffix}_{n}.png")
    return out


def script_options(f):
    """Options every `render` subcommand shares, outermost first."""
    for opt in reversed([
        click.argument("script", type=click.Path(exists=True, dir_okay=False, path_type=Path)),
        click.option("--param", "params", multiple=True, metavar="K=V",
                     help="Override a top-level literal in the script. Repeatable."),
        click.option("--part", "part_names", multiple=True, metavar="NAME",
                     help="Draw only show_object parts whose name equals or contains NAME. "
                          "Repeatable."),
        click.option("--out", type=click.Path(dir_okay=False, path_type=Path),
                     help="New PNG path; default next to the script, numbered if taken."),
    ]):
        f = opt(f)
    return f


def load(command, script, params, part_names, out, suffix):
    """Run the script and pick parts. Returns (result, parts with 0..1 colors, out path)."""
    if script.suffix.lower() != ".py":
        fail(command, f"{script} is not a Python script.")
    if out is not None and out.exists():
        fail(command, f"Output already exists: {out}. Choose a new --out.")
    overrides = parse_params(params, command)

    import sys
    from contextlib import redirect_stdout

    from lamad.cli.reverse import _select
    from lamad.cli.web import assign_colors
    from lamad.core import runner
    from lamad.core.native_io import quiet_kernel

    note("executing script…")
    with quiet_kernel(), redirect_stdout(sys.stderr):
        result = runner.execute(script.read_text(), overrides, filename=str(script))
    if not result.ok:
        fail(command, result.error, traceback=result.traceback)

    parts = result.parts
    if part_names:
        try:
            parts = _select(parts, part_names, "--part")
        except ValueError as e:
            fail(command, str(e))
    parts = [{**p, "color": rgb} for p, rgb in zip(parts, assign_colors(parts))]
    return result, parts, (out or default_output(script, suffix)).resolve()


@click.group(cls=HelpGroup)
def render():
    """PNG pictures of a script: sketch drawings or part views."""


@render.command()
@script_options
@click.option("--size", default=1000, show_default=True, type=click.IntRange(min=100),
              help="Long side of the drawing, px.")
@click.option("--grid/--no-grid", default=True, show_default=True, help="Draw a mm grid.")
@click.option("--tol", default=0.05, show_default=True, type=click.FloatRange(min=0, min_open=True),
              help="Curve discretisation, mm.")
def sketch(script, params, part_names, out, size, grid, tol):
    """Save SCRIPT's planar parts (sketches, faces, lines) as a 2D PNG.

    show_object() a BuildSketch's `.sketch`, a Face, or a BuildLine's `.line`.
    All drawn parts must share one plane; pick parts with --part otherwise.
    Default output: <script dir>/<stem>_sketch.png.
    """
    from lamad.core import sketch as sketch_render
    from lamad.core.native_io import quiet_kernel

    result, parts, out = load("render sketch", script, params, part_names, out, "sketch")
    note("drawing…")
    try:
        with quiet_kernel():
            info = sketch_render.render(parts, out, size=size, grid=grid, tol=tol)
    except ValueError as e:
        fail("render sketch", str(e), params=result.params)

    emit({"command": "render sketch", "status": "success", "script": str(script),
          "params": result.params, "parts": [p["name"] for p in parts],
          **info, "output": str(out)})


@render.command()
@script_options
@click.option("--n", "n_home", default=6, show_default=True, type=click.IntRange(min=0),
              help="Number of home views, spread as far apart as possible.")
@click.option("--size", default=400, show_default=True, type=click.IntRange(min=100),
              help="Side of each view, px.")
def part(script, params, part_names, out, n_home, size):
    """Save top, side, bottom and N spread-out home views as one PNG.

    Row one is top, side (from +X) and bottom. Below it, N home views whose
    cameras are as far apart as possible: the smallest angle between any two
    is maximised (N=6 is an octahedron, 90 deg apart), and the set is turned
    away from the axis views. Default output: <script dir>/<stem>_render.png.
    """
    from lamad.cli.reverse import _whole
    from lamad.core import cameras
    from lamad.core import render as views
    from lamad.core.native_io import quiet_kernel

    result, parts, out = load("render part", script, params, part_names, out, "render")
    dirs = cameras.spread_directions(n_home)
    home = []
    for i, d in enumerate(dirs, 1):
        up, az, el = cameras.camera(d)
        home.append({"label": f"home {i}  az {az:.0f}  el {el:+.0f}", "direction": d, "up": up,
                     "azimuth_deg": round(az, 2), "elevation_deg": round(el, 2)})

    note(f"rendering {len(views.ORTHO_ROW) + len(home)} views…")
    shape = result.shape if not part_names else _whole(parts)
    rows = [views.ORTHO_ROW, [(h["label"], (h["direction"], h["up"])) for h in home]]
    with quiet_kernel():
        views.render_sheet(shape, out, [r for r in rows if r], parts=parts, size=size)

    emit({"command": "render part", "status": "success", "script": str(script),
          "params": result.params, "parts": [p["name"] for p in parts],
          "views": [label for label, _v in views.ORTHO_ROW],
          "home": [{"direction": [round(float(c), 6) for c in h["direction"]],
                    "up": [round(float(c), 6) for c in h["up"]],
                    "azimuth_deg": h["azimuth_deg"], "elevation_deg": h["elevation_deg"]}
                   for h in home],
          "home_min_angle_deg": round(cameras.min_angle_deg(dirs), 3) if len(dirs) > 1 else None,
          "output": str(out)})
