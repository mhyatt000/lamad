"""Assembly selection, native prototype isolation, and interface propagation."""
import importlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
from build123d import Solid

_PROJECT = Path(__file__).resolve().parents[1] / "projects/orca-v1"
if not _PROJECT.exists():
    raise unittest.SkipTest("requires projects/orca-v1 (ORCA project sources are not shipped with lamad)")
PROJECT = Path(__file__).resolve().parents[1] / 'projects/orca-v1'
sys.path.insert(0, str(PROJECT))
assembly = importlib.import_module('assembly')
registry = importlib.import_module('build')


class AssemblyTests(unittest.TestCase):
    def fixture(self):
        finger = SimpleNamespace(SOURCE='ORCA_Fingers/DP.stl',
                                 build=Mock(side_effect=lambda p: Solid.make_box(1, 2, 3)))
        context = SimpleNamespace(SOURCE='ORCA_Tower/Context.stl',
                                  build=Mock(side_effect=lambda p: Solid.make_box(2, 2, 2)))
        instances = [assembly.Instance('first', 'orca_fingers__dp', 'p1', 'first'),
                     assembly.Instance('second', 'orca_fingers__dp', 'p2', 'second'),
                     assembly.Instance('context', 'orca_tower__context', 'p3', 'base')]
        poses = {}
        for index, instance in enumerate(instances):
            matrix = np.eye(4)
            matrix[0, 3] = index * 10
            poses[instance.name] = {'matrix': matrix.tolist()}
        return finger, context, instances, poses

    def build_fixture(self, fingers_only):
        finger, context, instances, poses = self.fixture()
        with patch.object(assembly, 'INSTANCES', instances), \
             patch.object(assembly, 'placements', return_value=poses), \
             patch.object(registry, 'modules', return_value=iter((finger, context))):
            body = assembly.build(fingers_only=fingers_only)
        return body, finger, context

    def test_finger_only_omits_context_and_builds_repeated_recipe_once(self):
        body, finger, context = self.build_fixture(True)
        self.assertTrue(body.is_valid)
        self.assertEqual(len(body.solids()), 2)
        self.assertEqual([child.label for child in body.children], ['first', 'second'])
        finger.build.assert_called_once_with({})
        context.build.assert_not_called()

    def test_repeated_instances_have_independent_placements(self):
        body, _, _ = self.build_fixture(True)
        first, second = body.children
        self.assertAlmostEqual(first.bounding_box().min.X, 0)
        self.assertAlmostEqual(second.bounding_box().min.X, 10)
        self.assertAlmostEqual(first.volume, second.volume)

    def test_full_assembly_default_keeps_context(self):
        body, finger, context = self.build_fixture(False)
        self.assertEqual(len(body.solids()), 3)
        finger.build.assert_called_once()
        context.build.assert_called_once()

    def test_step_component_names_survive_shared_native_prototypes(self):
        from build123d import export_step
        from verify_finger_assembly import read_step_instances
        body, _, _ = self.build_fixture(True)
        with tempfile.TemporaryDirectory(prefix='mycad-assembly-names-') as folder:
            path = Path(folder) / 'assembly.step'
            export_step(body, path)
            instances = read_step_instances(path)
        self.assertEqual(set(instances), {'first', 'second'})
        self.assertAlmostEqual(instances['first'].bounding_box().min.X, 0)
        self.assertAlmostEqual(instances['second'].bounding_box().min.X, 10)

    def test_right_hand_catalog_mapping_and_rigid_placements(self):
        selected = [i for i in assembly.INSTANCES if i.asset.startswith('orca_fingers__')]
        self.assertEqual(len(selected), 20)
        self.assertFalse(any(i.asset.startswith('orca_fingers__l_') for i in selected))
        poses = assembly.placements(False)
        for instance in selected:
            with self.subTest(instance=instance.name):
                pose = poses[instance.name]
                self.assertEqual(pose['step_id'], instance.step_id)
                self.assertEqual(registry.asset_name(pose['source']), instance.asset)
                matrix = np.asarray(pose['matrix'])
                self.assertTrue(np.allclose(matrix[3], (0, 0, 0, 1)))
                self.assertTrue(np.allclose(matrix[:3, :3].T @ matrix[:3, :3], np.eye(3)))
                self.assertAlmostEqual(np.linalg.det(matrix[:3, :3]), 1, places=8)

    def test_pp_spacing_propagates_to_correct_descendants(self):
        from validate_kinematics import verify_spacing
        self.assertEqual(len(verify_spacing()), 3)

    def test_default_datum_axes_match_measured_bearings(self):
        datums = json.loads((PROJECT / 'reports/finger_datum_placements.json').read_text())
        poses = assembly.placements(False)
        joints = {joint.name: joint for joint in assembly.JOINTS}
        for name, datum in datums['placements'].items():
            matrix = np.asarray(poses[name]['matrix'])
            for check in datum['joint_checks']:
                with self.subTest(instance=name, joint=check['joint']):
                    joint = joints[check['joint']]
                    point = matrix[:3, :3] @ check['local_point_mm'] + matrix[:3, 3]
                    axis = matrix[:3, :3] @ check['local_axis']
                    self.assertLess(np.linalg.norm(np.cross(point - joint.origin_mm, joint.axis)), 1e-6)
                    self.assertLess(np.linalg.norm(np.cross(axis, joint.axis)), 1e-7)

    def test_fixed_tip_pin_and_tongue_align_in_ip_frame(self):
        from part.finger_dp import DEFAULTS
        angle = np.radians(DEFAULTS['tongue_angle'])
        u = np.array([np.cos(angle), -np.sin(angle), 0])
        v = np.array([np.sin(angle), np.cos(angle), 0])
        center = DEFAULTS['bore_station'] * u + [0, 0, DEFAULTS['height'] / 2]
        poses = assembly.placements(False)
        for finger in ('index', 'middle', 'ring', 'pinky'):
            with self.subTest(finger=finger):
                relative = np.linalg.inv(poses[finger + '_ip']['matrix']) @ poses[finger + '_dp']['matrix']
                point = relative[:3, :3] @ center + relative[:3, 3]
                self.assertTrue(np.allclose(point, (3.354562710476, 0, 16), atol=1e-6, rtol=0))
                self.assertTrue(np.allclose(abs(relative[:3, :3] @ v), (1, 0, 0), atol=1e-7))
                self.assertTrue(np.allclose(relative[:3, :3] @ u, (0, 0, -1), atol=1e-7))

    def test_diagnostic_rotation_preserves_pivot_and_siblings(self):
        from render_assembly import forward_kinematics
        joint = next(j for j in assembly.joints() if j.name == 'thumb_mcp')
        transforms = forward_kinematics({joint.name: .2})
        pivot = np.r_[joint.origin_mm, 1]
        self.assertTrue(np.allclose(transforms['thumb_pp'] @ pivot, pivot))
        self.assertTrue(np.allclose(transforms['thumb_dp'], transforms['thumb_pp']))
        self.assertTrue(np.allclose(transforms['index_pp'], np.eye(4)))

    def test_unsupported_ap_spacing_and_twist_fail_explicitly(self):
        import param
        cases = [('R-AP.stl', {'joint_spacing': 22}),
                 ('R-T-AP.stl', {'joint_spacing': 32}),
                 ('R-T-AP.stl', {'twist_angle': 25})]
        for source, overrides in cases:
            with self.subTest(source=source, overrides=overrides), \
                 patch.dict(param.PART_OVERRIDES, {'ORCA_Fingers/' + source: overrides}, clear=True):
                with self.assertRaisesRegex(ValueError, 'assembly reanchoring'):
                    assembly.placements(True)

    def test_unsupported_fixed_tip_datum_edit_fails_explicitly(self):
        import param
        with patch.dict(param.PART_OVERRIDES, {'ORCA_Fingers/DP.stl': {'height': 14}}, clear=True):
            with self.assertRaisesRegex(ValueError, 'assembly reanchoring'):
                assembly.joints()

    def test_explicit_default_interface_values_are_allowed(self):
        import param
        with patch.dict(param.PART_OVERRIDES, {'ORCA_Fingers/R-T-AP.stl':
                                             {'joint_spacing': 30, 'twist_angle': 20}}, clear=True):
            self.assertEqual(len(assembly.placements(True)), len(assembly.placements(False)))


if __name__ == '__main__':
    unittest.main()
