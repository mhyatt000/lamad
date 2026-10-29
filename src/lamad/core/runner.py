"""Execute a build123d script and capture whatever it shows."""

import ast
import traceback
from dataclasses import dataclass, field
from typing import Any

from OCP.BRep import BRep_Builder
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS_Compound, TopoDS_Shape


@dataclass
class Result:
    ok: bool
    shape: Any = None                      # TopoDS_Shape (the whole model)
    parts: list = field(default_factory=list)   # [{name, color, shape, leaves}]
    params: dict = field(default_factory=dict)
    error: str | None = None
    traceback: str | None = None


def discover_params(source):
    """Top-level `name = <literal>` assignments are the script's knobs."""
    return {
        n.targets[0].id: n.value.value
        for n in ast.parse(source).body
        if isinstance(n, ast.Assign)
        and len(n.targets) == 1
        and isinstance(n.targets[0], ast.Name)
        and isinstance(n.value, ast.Constant)
    }


def _override(source, values):
    """Rewrite literal assignments in place; keeps line numbers stable."""
    tree = ast.parse(source)
    for n in tree.body:
        if (isinstance(n, ast.Assign) and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Name)
                and n.targets[0].id in values):
            n.value = ast.Constant(value=values[n.targets[0].id])
    ast.fix_missing_locations(tree)
    return ast.unparse(tree)


def _topods(obj):
    from build123d import Shape
    if isinstance(obj, Shape):
        return obj.wrapped
    if isinstance(obj, TopoDS_Shape):
        return obj
    raise TypeError(f"expected a build123d Shape, got {type(obj).__name__}")


def _is_empty(shape):
    """True when a shape holds no geometry — what a boolean that removed
    everything returns. It is still a valid Shape, so it exports and measures
    as a silent zero instead of failing. Edges count, so a BuildLine curve is
    not empty."""
    return not any(TopExp_Explorer(shape, t).More()
                   for t in (TopAbs_SOLID, TopAbs_SHELL, TopAbs_FACE, TopAbs_EDGE))


def _rgb(color):
    """A build123d Color as an (r, g, b) 0..1 triple, or None."""
    return None if color is None else tuple(float(c) for c in tuple(color)[:3])


def _leaves(obj, stem):
    """[(labels, TopoDS_Shape, rgb)] for each leaf of a build123d assembly (a
    Compound with children), placed in global coordinates. None for a plain
    shape.

    A child's shape is stored relative to its parent, so the parents'
    locations are accumulated on the way down. An unlabeled child is named
    after its parent (`stem` at the root) with a 1-based index; a color is
    inherited downwards.
    """
    from OCP.TopLoc import TopLoc_Location

    if not getattr(obj, "children", None):
        return None
    out = []

    def walk(node, labels, loc, rgb):
        rgb = _rgb(node.color) or rgb
        if not node.children:
            out.append((labels, node.wrapped.Moved(loc), rgb))
            return
        nxt = loc.Multiplied(node.wrapped.Location())
        parent = labels[-1] if labels else stem
        for i, kid in enumerate(node.children, 1):
            label = str(kid.label or f"{parent}_{i}").replace("/", "_")
            walk(kid, labels + (label,), nxt, rgb)

    walk(obj, (), TopLoc_Location(), None)
    return out


def _compound(shapes):
    c = TopoDS_Compound()
    b = BRep_Builder()
    b.MakeCompound(c)
    for s in shapes:
        b.Add(c, s)
    return c


def execute(source, params=None, filename="<script>"):
    """Run `source` with the build123d API preloaded. No imports needed."""
    import build123d as b3d
    from build123d import Shape, ShapeList

    found = discover_params(source)
    if params:
        unknown = set(params) - set(found)
        if unknown:
            avail = ", ".join(sorted(found)) or "(none)"
            return Result(False, error=(
                f"Unknown parameter(s): {', '.join(sorted(unknown))}. Available: {avail}"
            ))
        source = _override(source, params)

    captured = []

    def show_object(obj, name=None, color=None, **_):
        # `a - b` can yield a ShapeList when the result falls apart into
        # pieces. Unwrap the single-piece case; make the rest loud rather
        # than silently exporting only the first piece.
        if isinstance(obj, ShapeList):
            if len(obj) == 1:
                obj = obj[0]
            elif not obj:
                raise TypeError(
                    "show_object() got an empty result — the boolean removed "
                    "everything. Check that your cut actually intersects the base."
                )
            else:
                raise TypeError(
                    f"show_object() got {len(obj)} disconnected pieces. Call it "
                    "once per piece, or join them with Compound(children=list(x))."
                )
        if not isinstance(obj, (Shape, TopoDS_Shape)):
            raise TypeError(
                f"show_object() expects a build123d Shape, got {type(obj).__name__}"
            )
        topo = _topods(obj)
        if _is_empty(topo):
            raise TypeError(
                f"show_object() got an empty shape for {name or 'this part'!r}. "
                "A boolean removed everything - check that your cutter is not "
                "larger than, or fully overlapping, the base solid."
            )
        name = name or f"part{len(captured) + 1}"
        leaves = _leaves(obj, str(name).rsplit("/", 1)[-1])
        captured.append({"name": name, "color": color, "shape": topo, "leaves": leaves})

    g = {"__name__": "__lamad__", "__file__": filename, "show_object": show_object}
    for attr in getattr(b3d, "__all__", dir(b3d)):
        if not attr.startswith("_"):
            g[attr] = getattr(b3d, attr)

    try:
        exec(compile(source, filename, "exec"), g)
    except Exception as e:
        return Result(False, params={**found, **(params or {})},
                      error=f"{type(e).__name__}: {e}", traceback=traceback.format_exc())

    if not captured:
        return Result(False, params={**found, **(params or {})},
                      error="Script produced nothing. Did you call show_object()?")

    shapes = [p["shape"] for p in captured]
    whole = shapes[0] if len(shapes) == 1 else _compound(shapes)
    return Result(True, shape=whole, parts=captured, params={**found, **(params or {})})
