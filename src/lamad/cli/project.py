"""Project commands: init, run, and the `versions` group."""

from pathlib import Path

import click

from lamad.cli import HelpGroup, emit, fail, note, parse_params
from lamad.core import export, project, render, runner


@click.command()
@click.option("--name", default=None, help="Project name (default: directory name).")
def init(name):
    """Create lamad.json in the current directory."""
    root = Path.cwd()
    try:
        manifest = project.init(root, name or root.name)
    except FileExistsError as e:
        fail("init", str(e))
    emit({"command": "init", "status": "success",
          "project": manifest["name"], "root": str(root)})


@click.command()
@click.argument("script", type=click.Path(exists=True, dir_okay=False))
@click.option("--label", required=True, help="Short name for this version.")
@click.option("--param", "params", multiple=True, metavar="K=V",
              help="Override a top-level literal in the script. Repeatable.")
@click.option("--export", "formats", default=None,
              help="Extra mesh formats, comma separated: stl, glb.")
@click.option("--preview/--no-preview", default=True, help="Render the 4-view PNG.")
@click.option("--view/--no-view", "open_view", default=False,
              help="Serve the result in the viewer afterwards (blocks).")
@click.option("--dry-run", is_flag=True, help="Report metrics without writing a version.")
def run(script, label, params, formats, preview, open_view, dry_run):
    """Execute SCRIPT and record the result as a new version."""
    try:
        root, manifest = project.load()
    except FileNotFoundError as e:
        fail("run", str(e))

    overrides = parse_params(params, "run")
    source = Path(script).read_text()

    note("executing script…")
    result = runner.execute(source, overrides, filename=script)
    if not result.ok:
        fail("run", result.error, traceback=result.traceback)

    note("computing metrics…")
    from lamad.core import metrics as _metrics
    measured = _metrics.compute(result.shape)

    payload = {
        "command": "run", "status": "success", "label": label,
        "parts": [p["name"] for p in result.parts],
        "params": result.params, "metrics": measured,
    }

    if dry_run:
        payload["dry_run"] = True
        emit(payload)
        return

    version = project.next_version(root, manifest)
    out = root / f"v{version}_{label}"
    out.mkdir()

    note("exporting STEP…")
    export.export_step(result.shape, out / "output.step", parts=result.parts)
    (out / "script.py").write_text(source)
    outputs = {"step": f"{out.name}/output.step", "script": f"{out.name}/script.py"}

    for fmt in [f.strip().lower() for f in (formats or "").split(",") if f.strip()]:
        if fmt not in ("stl", "glb"):
            fail("run", f"Unsupported format {fmt!r}. Supported: stl, glb.")
        note(f"exporting {fmt.upper()}…")
        target = out / f"output.{fmt}"
        if fmt == "stl":
            export.export_stl(result.shape, target)
        else:
            export.export_glb(result.shape, target, parts=result.parts)
        outputs[fmt] = f"{out.name}/{target.name}"

    if preview:
        note("rendering preview…")
        render.render_preview(result.shape, out / "preview.png", parts=result.parts)
        outputs["preview"] = f"{out.name}/preview.png"

    meta = {"version": version, "label": label, "metrics": measured,
            "params": result.params, "parts": [p["name"] for p in result.parts]}

    project.record(root, manifest, version=version, label=label, dir_name=out.name,
                   metrics=measured, params=result.params, script=str(script))
    project.write_json(out / "meta.json", meta)

    payload.update(version=version, outputs=outputs)
    emit(payload)
    if open_view:
        # After the JSON, because this blocks until you ctrl-c.
        from lamad.cli.geom import serve
        serve(out / "output.step", port=8080)


@click.group(cls=HelpGroup)
def versions():
    """Inspect recorded versions of this project."""


@versions.command(name="list")
def list_versions():
    """List recorded versions."""
    try:
        _root, manifest = project.load()
    except FileNotFoundError as e:
        fail("list", str(e))
    emit({"command": "list", "status": "success", "project": manifest["name"],
          "current": manifest["current"],
          "versions": [{"version": v["version"], "label": v["label"],
                        "path": v["path"], "created": v["created"],
                        "dimensions": v["metrics"]["dimensions"],
                        "volume": v["metrics"]["volume"]}
                       for v in manifest["versions"]]})


@versions.command(name="show")
@click.argument("ref", required=False)
def show_version(ref):
    """Print a version's meta.json. REF is a number or label; default latest."""
    import json

    try:
        root, manifest = project.load()
    except FileNotFoundError as e:
        fail("show", str(e))
    entry = project.resolve(root, manifest, ref)
    if entry is None:
        fail("show", f"No version matching {ref!r}.",
             available=[v["label"] for v in manifest["versions"]])
    meta_path = root / entry["path"] / "meta.json"
    if not meta_path.exists():
        fail("show", f"{meta_path} is missing. Re-run this version.")
    try:
        meta = json.loads(meta_path.read_text())
    except json.JSONDecodeError as e:
        fail("show", f"{meta_path} is not valid JSON: {e}")
    emit({"command": "show", "status": "success", "path": entry["path"], **meta})
