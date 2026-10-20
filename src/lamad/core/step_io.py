"""Load STEP / BREP into a TopoDS_Shape, with honest errors."""

from pathlib import Path

from OCP.BRep import BRep_Builder
from OCP.BRepTools import BRepTools
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_Reader
from OCP.TopAbs import TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS_Shape

from lamad.core.native_io import quiet_kernel


def _empty(shape):
    return not any(TopExp_Explorer(shape, t).More()
                   for t in (TopAbs_SOLID, TopAbs_SHELL, TopAbs_FACE))


def load_shape(path):
    p = Path(path)
    suffix = p.suffix.lower()
    try:
        with quiet_kernel():
            if suffix in (".step", ".stp"):
                reader = STEPControl_Reader()
                if reader.ReadFile(str(p)) != IFSelect_RetDone:
                    raise ValueError(f"Could not read {p.name} as STEP.")
                reader.TransferRoots()
                shape = reader.OneShape()
            elif suffix == ".brep":
                shape = TopoDS_Shape()
                if not BRepTools.Read_s(shape, str(p), BRep_Builder()):
                    raise ValueError(f"Could not read {p.name} as BREP.")
            else:
                raise ValueError(f"Unsupported extension {suffix!r}. Use .step/.stp/.brep.")
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Could not parse {p.name}: {e}") from e

    if shape is None or shape.IsNull():
        raise ValueError(f"{p.name} parsed to a null shape — likely truncated.")
    if _empty(shape):
        raise ValueError(
            f"{p.name} parsed but holds no solids, shells, or faces. "
            "Often an assembly that references children it doesn't include, "
            "or a surfaces-only export."
        )
    return shape
