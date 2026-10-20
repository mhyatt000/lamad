"""Topology helpers shared by the detectors: stable ids, maps, point formatting."""

from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_VERTEX
from OCP.TopExp import TopExp
from OCP.collections import IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher

PREFIX = {TopAbs_EDGE: "e", TopAbs_FACE: "f", TopAbs_VERTEX: "v"}


def indexed(shape, kind):
    """1-based indexed map of sub-shapes of `kind`; ids are `<prefix><index>`.

    The same shape always maps in the same order, so edge ids reported by
    `edges` match the ids referenced by `corners`.
    """
    table = IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher()
    TopExp.MapShapes_s(shape, kind, table)
    return table


def entries(table):
    return [table.FindKey(i) for i in range(1, table.Extent() + 1)]


def ident(kind, index):
    return f"{PREFIX[kind]}{index}"


def xyz(point):
    return [round(point.X(), 7), round(point.Y(), 7), round(point.Z(), 7)]


def rounded(value):
    return round(float(value), 7)
