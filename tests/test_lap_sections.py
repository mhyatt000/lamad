"""Basic signed-area checks for the cross-section diagnostic (not CAD fidelity)."""
import importlib.util
from pathlib import Path
import unittest

import trimesh


_PROJECT = Path(__file__).resolve().parents[1] / "projects/orca-v1"
if not _PROJECT.exists():
    raise unittest.SkipTest("requires projects/orca-v1 (ORCA project sources are not shipped with lamad)")
PATH = Path(__file__).resolve().parents[1]/"projects/orca-v1/analysis/lap_section_diff.py"
spec = importlib.util.spec_from_file_location("lap_section_diagnostic",PATH)
diagnostic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostic)


class SectionDifferenceTests(unittest.TestCase):
    def test_identical_cube_sections_have_zero_difference(self):
        cube = trimesh.creation.box(extents=(10,10,10))
        for axis in range(3):
            a = diagnostic.section(cube,axis,0)
            b = diagnostic.section(cube.copy(),axis,0)
            self.assertFalse(a["notes"])
            self.assertAlmostEqual(a["area"].area,100)
            self.assertAlmostEqual(a["area"].symmetric_difference(b["area"]).area,0)

    def test_translated_cube_has_equal_missing_and_extra_section_area(self):
        source = trimesh.creation.box(extents=(10,10,10))
        shifted = source.copy().apply_translation((2,0,0))
        a = diagnostic.section(source,2,0)["area"]
        b = diagnostic.section(shifted,2,0)["area"]
        self.assertAlmostEqual(a.difference(b).area,20)
        self.assertAlmostEqual(b.difference(a).area,20)

    def test_nested_closed_sections_preserve_void(self):
        outer = trimesh.creation.box(extents=(10,10,10))
        inner = trimesh.creation.box(extents=(4,4,4))
        inner.invert()
        shell = trimesh.util.concatenate([outer,inner])
        section = diagnostic.section(shell,2,0)
        self.assertFalse(section["notes"])
        self.assertAlmostEqual(section["area"].area,84)

    def test_plane_coincident_with_face_is_flagged(self):
        cube = trimesh.creation.box(extents=(10,10,10))
        section = diagnostic.section(cube,2,5)
        self.assertGreater(section["coplanar"],0)
        self.assertTrue(any("coplanar" in note for note in section["notes"]))


if __name__ == "__main__":
    unittest.main()
