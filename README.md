# lamad

CAD tooling built on [build123d](https://build123d.readthedocs.io): write a
Python script describing a part, get a STEP file, measurements, a preview
image, and a browser viewer.

## Install

As a standalone command-line tool:

```bash
uv tool install git+https://github.com/mhyatt000/lamad
lamad
```

For development:

```bash
git clone https://github.com/mhyatt000/lamad
cd lamad
uv sync
uv run lamad
```

## Python support

OCCT bindings (`cadquery-ocp`, pulled in by build123d) have no wheels for
Python 3.13+, so the project pins Python 3.11–3.12.

On Intel Macs, torch resolves to the last release that still shipped x86_64
wheels (2.2.x).

## Optional extras

```bash
uv sync --extra reverse-engineering   # trimesh, rtree, shapely
```
