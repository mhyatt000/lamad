"""Project manifest and versioned output directories."""

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

MANIFEST = "lamad.json"
_VDIR = re.compile(r"^v(\d+)(?:_|$)")


def write_json(path, payload):
    """Write via temp file + rename so a crash never leaves half a manifest."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def find_root(start=None):
    """Nearest directory at or above `start` holding a manifest."""
    base = Path(start or Path.cwd()).resolve()
    for d in [base, *base.parents]:
        if (d / MANIFEST).exists():
            return d
    return None


def load(start=None):
    """Return (root, manifest). Raises FileNotFoundError if uninitialized."""
    root = find_root(start)
    if root is None:
        raise FileNotFoundError(f"No {MANIFEST} here or above. Run `lamad init` first.")
    return root, json.loads((root / MANIFEST).read_text())


def init(root, name):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / MANIFEST
    if path.exists():
        raise FileExistsError(f"{path} already exists")
    manifest = {"name": name, "current": None, "versions": []}
    write_json(path, manifest)
    return manifest


def next_version(root, manifest):
    """Highest version seen on disk or in the manifest, plus one."""
    used = {v["version"] for v in manifest["versions"]}
    for child in Path(root).iterdir():
        m = _VDIR.match(child.name) if child.is_dir() else None
        if m:
            used.add(int(m.group(1)))
    return max(used, default=0) + 1


def record(root, manifest, *, version, label, dir_name, metrics, params, script):
    entry = {
        "version": version,
        "label": label,
        "path": dir_name,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "script": script,
        "params": params,
        "metrics": metrics,
    }
    manifest["versions"] = [v for v in manifest["versions"] if v["version"] != version]
    manifest["versions"].append(entry)
    manifest["versions"].sort(key=lambda v: v["version"])
    manifest["current"] = label
    write_json(Path(root) / MANIFEST, manifest)
    return entry


def resolve(root, manifest, ref):
    """Look up a version by number ('3', 'v3'), label, or 'latest'."""
    versions = manifest["versions"]
    if not versions:
        return None
    if ref in (None, "latest"):
        return versions[-1]
    key = str(ref).lstrip("v")
    if key.isdigit():
        return next((v for v in versions if v["version"] == int(key)), None)
    return next((v for v in versions if v["label"] == ref), None)
