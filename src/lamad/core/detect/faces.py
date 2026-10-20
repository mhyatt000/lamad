"""Per-face type plane | cylinder | cone | sphere | torus | freeform.

Classification and analytic parameters come from
`lamad.core.inspection.face_report`, so `re inspect` and `re det faces` can
never disagree about a surface; this module only relabels non-analytic kinds
as `freeform` and uses the detector id scheme (f1..fN).
"""

from collections import Counter

from OCP.TopAbs import TopAbs_FACE

from lamad.core.detect.common import entries, ident, indexed

ANALYTIC = ("plane", "cylinder", "cone", "sphere", "torus")
TYPES = (*ANALYTIC, "freeform")


def face_summary(face, fid):
    from lamad.core.inspection import face_report
    report = face_report(face, fid)
    kind = report.pop("surface")
    report.pop("uv_bounds", None)
    result = {"id": fid, "type": kind if kind in ANALYTIC else "freeform", "surface": kind}
    result.update(report)
    return result


def detect_faces(shape):
    """Returns (summary, faces) for every face of `shape`, ids f1..fN."""
    table = indexed(shape, TopAbs_FACE)
    reports = [face_summary(f, ident(TopAbs_FACE, i)) for i, f in enumerate(entries(table), start=1)]
    counts = Counter(f["type"] for f in reports)
    summary = {"total": len(reports), "by_type": {t: counts.get(t, 0) for t in TYPES},
               "area": round(sum(f["area"] for f in reports), 7)}
    return summary, reports
