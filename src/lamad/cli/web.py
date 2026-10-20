"""`lamad web`: execute a build123d script and serve its parts in the browser.

No project manifest, no version directory, no STEP on disk: the shapes that
`show_object()` collected go straight into the viser scene, one colored mesh
per part.
"""

import webbrowser
from pathlib import Path

import click

from lamad.cli import emit, fail, note, parse_params


def assign_colors(parts, palette=None):
    """One (r, g, b) 0..1 triple per part.

    A part's own color (name, #rrggbb, or triple) is kept. Parts without one
    take palette entries in order, skipping any entry an explicit color
    already uses, so up to len(palette) parts never share a color. Beyond
    that the palette cycles.
    """
    from lamad.core.export import PALETTE, parse_color

    palette = list(palette or PALETTE)
    explicit = [parse_color(p.get("color")) for p in parts]
    used = {c for c in explicit if c is not None}
    pool = [c for c in palette if c not in used] or palette
    colors, k = [], 0
    for c in explicit:
        if c is None:
            c = pool[k % len(pool)]
            k += 1
        colors.append(c)
    return colors


def split_solids(parts):
    """A single part made of several solids becomes one part per solid, so a
    script that calls show_object() once on a compound still gets distinct
    colors and checkboxes. Multi-part results are left alone."""
    if len(parts) != 1:
        return list(parts)
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer

    solids, exp = [], TopExp_Explorer(parts[0]["shape"], TopAbs_SOLID)
    while exp.More():
        solids.append(exp.Current())
        exp.Next()
    if len(solids) < 2:
        return list(parts)
    base = parts[0]["name"]
    return [{"name": f"{base}_{i}", "shape": s, "color": parts[0].get("color")}
            for i, s in enumerate(solids, 1)]


def unique_names(parts):
    """Scene node paths are keyed by name, so repeats get a numeric suffix."""
    seen, out = {}, []
    for p in parts:
        nm = str(p["name"]).replace("/", "_")
        seen[nm] = seen.get(nm, 0) + 1
        out.append({**p, "name": nm if seen[nm] == 1 else f"{nm}_{seen[nm]}"})
    return out


def prepare(parts):
    """Scene-ready parts: split, uniquely named, every color a 0-255 tuple."""
    from lamad.core.export import parse_color

    parts = unique_names(split_solids(parts))
    for p in parts:
        if p.get("color") is not None and parse_color(p["color"]) is None:
            note(f"unknown color {p['color']!r} for {p['name']}; using the palette")
    for p, rgb in zip(parts, assign_colors(parts)):
        p["color"] = tuple(round(c * 255) for c in rgb)
    return parts


def hex_color(rgb255):
    return "#%02x%02x%02x" % tuple(rgb255)


@click.command()
@click.argument("script", type=click.Path(exists=True, dir_okay=False))
@click.option("--param", "params", multiple=True, metavar="K=V",
              help="Override a top-level literal in the script. Repeatable.")
@click.option("--port", default=8080, show_default=True)
@click.option("--tol", default=0.05, show_default=True, help="Linear deflection, mm.")
@click.option("--ang", default=0.3, show_default=True, help="Angular deflection, rad.")
@click.option("--no-browser", is_flag=True, help="Do not open a browser tab.")
@click.option("--watch", is_flag=True,
              help="Re-run SCRIPT and refresh the scene whenever the file changes.")
def web(script, params, port, tol, ang, no_browser, watch):
    """Execute SCRIPT and serve its parts in the viewer. Blocks until ctrl-c.

    Nothing is written: no version, no STEP. Each show_object() part gets its
    own color and visibility checkbox.
    """
    path = Path(script)
    if path.suffix.lower() != ".py":
        fail("web", f"{script} is not a Python script. `lamad web` runs .py scripts; "
                    "use `lamad view` for STEP files.")
    overrides = parse_params(params, "web")

    from lamad.core import runner, viewer

    def build():
        note("executing script…")
        return runner.execute(path.read_text(), overrides, filename=script)

    result = build()
    if not result.ok:
        fail("web", result.error, traceback=result.traceback)
    parts = prepare(result.parts)

    try:
        scene = viewer.serve_parts(parts, path.name, tol=tol, ang=ang, port=port,
                                   block=False, verbose=False)
    except OSError as e:
        fail("web", f"could not start viewer on port {port}: {e}")
    # viser falls through to the next free port when `port` is taken.
    if scene.port != port:
        note(f"port {port} is in use; serving on {scene.port} instead")
    url = f"http://localhost:{scene.port}"

    emit({"command": "web", "status": "success", "script": str(script),
          "params": result.params,
          "parts": [{"name": p["name"], "color": hex_color(p["color"])} for p in parts],
          "url": url, "watch": watch})
    if not no_browser:
        webbrowser.open(url)

    poll = None
    if watch:
        state = {"mtime": path.stat().st_mtime}

        def poll():
            try:
                mtime = path.stat().st_mtime
            except OSError:
                return None
            if mtime == state["mtime"]:
                return None
            state["mtime"] = mtime
            res = build()
            if not res.ok:
                note(f"script error, keeping the previous scene: {res.error}")
                return None
            note(f"{path.name} changed, reloading")
            return prepare(res.parts)

    try:
        viewer.wait(scene, poll=poll)
    except KeyboardInterrupt:
        pass
    scene.stop()
    note("stopped")
