"""Headless checks for large group selection and cached checkpoint arrow transforms."""
import tempfile
import random
import unittest

import test_regressions as checks


class EditorPerformanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='disepshun-editor-')
        self.world = checks.world(self.tmp.name)
        self.app = checks.app(self.world)

    def tearDown(self):
        self.world.render.removeNode()
        self.tmp.cleanup()

    def test_large_partial_group_selection_retains_order_and_pivot(self):
        nodes = [checks.cube(self.world, (i, 0, .5)) for i in range(4096)]
        moving = checks.mover(self.world, (0, 3, .5))['np']
        for node in nodes + [moving]:
            node.setTag('group', 'large-group')
        outside = checks.cube(self.world, (0, 5, .5))
        a = self.app
        a.tool_mode = 11
        a.tool_phases[11] = 'select'
        a.selected_objects = [outside, nodes[50], nodes[0]]
        a.pick_object = lambda: nodes[-1]
        a.select_object()
        expected = ([outside, nodes[50], nodes[0]] +
                    [n for n in nodes[:-1] if n not in (nodes[50], nodes[0])] +
                    [moving, nodes[-1]])
        self.assertEqual(a.selected_objects, expected)
        self.assertEqual(len(set(a.selected_objects)), len(expected))
        self.assertEqual(a.selected_objects[-1], nodes[-1])
        self.assertTrue(all(n.hasPythonTag('selection_color') for n in expected))
        a.select_object()
        self.assertEqual(a.selected_objects, [outside])
        self.assertTrue(all(not n.hasPythonTag('selection_color') for n in nodes + [moving]))

    def test_group_material_filter_remains_selective(self):
        nodes = [checks.cube(self.world, (i, 0, .5), mat)
                 for i, mat in enumerate(('4', '5', '1', '4', '5'))]
        for node in nodes:
            node.setTag('group', 'mixed')
        a = self.app
        a.tool_mode = 9
        a.pick_object = lambda: nodes[0]
        a.select_object()
        self.assertEqual(a.selected_objects, [nodes[0], nodes[3]])
        a.select_object()
        self.assertEqual(a.selected_objects, [])
        a.tool_mode = 8
        a.pick_object = lambda: nodes[1]
        a.select_object()
        self.assertEqual(a.selected_objects, [nodes[1], nodes[4]])
        self.assertEqual(a.selected_trampolines, a.selected_objects)

    def test_idle_arrows_skip_scene_writes_and_follow_live_inputs(self):
        a = self.app
        static = checks.cube(self.world, material='4')
        moving = checks.mover(self.world, (3, 0, .5), '4')['np']
        a.tool_mode = 9
        a.selected_objects = [static, moving]
        a.draw_checkpoint_direction()

        class CountWrites:
            def __init__(self, marker):
                self.marker = marker
                self.calls = []

            def setPos(self, value):
                self.calls.append('position')
                self.marker.setPos(value)

            def setScale(self, value):
                self.calls.append('scale')
                self.marker.setScale(value)

            def setH(self, value):
                self.calls.append('heading')
                self.marker.setH(value)

            def removeNode(self):
                self.marker.removeNode()

        wrappers = {node: CountWrites(marker) for node, marker in a.checkpoint_markers.items()}
        a.checkpoint_markers = wrappers.copy()
        for _ in range(10):
            a.draw_checkpoint_direction()
        self.assertTrue(all(not w.calls for w in wrappers.values()))

        moving.setPos(5, 2, 3)
        a.draw_checkpoint_direction()
        self.assertEqual(wrappers[moving].calls, ['position', 'scale'])
        self.assertLess((wrappers[moving].marker.getPos() - checks.V(5, 2, 3.95)).length(), 1e-5)
        self.assertEqual(wrappers[static].calls, [])
        static.setTag('heading', '225')
        a.draw_checkpoint_direction()
        self.assertEqual(wrappers[static].calls, ['heading'])
        self.assertEqual(wrappers[static].marker.getH() % 360, 225)
        a.physics.camera.setPos(0, -100, 2)
        a.draw_checkpoint_direction()
        self.assertEqual(wrappers[static].calls, ['heading', 'scale'])
        self.assertEqual(wrappers[static].marker.getScale(), checks.V(3, 3, 3))

        a.selected_objects = [static]
        a.draw_checkpoint_direction()
        self.assertTrue(wrappers[moving].marker.isEmpty())
        self.assertNotIn(moving, a.checkpoint_marker_states)
        a.tool_mode = 8
        a.draw_checkpoint_direction()
        self.assertIsNone(a.selection_node)
        self.assertEqual(a.checkpoint_marker_states, {})

    def test_fill_mover_cells_match_exhaustive_overlap(self):
        a, w = self.app, self.world
        rng = random.Random(2041)
        positions = [checks.V(*(rng.uniform(-5, 5) for _ in range(3))) for _ in range(120)]
        # Include both sides of the strict .99 threshold, negative coordinates,
        # and centres on fill-grid planes. Panda3D stores these as float32.
        positions += [checks.V(x, 0, z) for x in (-1.01, -.99, -.9899, 0, .9899, .99, 1.01)
                      for z in (-.49, -.4899, .5, 1.4899, 1.49)]
        for p in positions:
            checks.mover(w, p)
        positions = [m['np'].getPos() for m in w.moving_cubes]
        static = checks.cube(w, (0, 0, .5), '4')
        a.tool_mode = 12
        a.fill_start = checks.V(-4, -4, -3.5)
        a.preview.setPos(4, 4, 4.5)
        a.physics.player.setPos(30, 30, 0)
        w.queue_save = lambda: None
        expected = {(x, y, z+1) for x in range(-4, 5) for y in range(-4, 5) for z in range(-4, 5)
                    if not any(abs(x-q.x) < .99 and abs(y-q.y) < .99 and abs(z+.5-q.z) < .99
                               for q in positions)}
        expected.add(w.get_grid_key(static.getPos()))
        a.fill_corner()
        self.assertEqual(set(w.cube_map), expected)
        self.assertIsNone(a.fill_start)
        self.assertTrue(a.history_step())
        self.assertEqual(w.all_blocks(), [static] + [m['np'] for m in w.moving_cubes])
        self.assertTrue(a.history_step(True))
        self.assertEqual(set(w.cube_map), expected)

    def test_hollow_fill_keeps_surface_order_for_flat_and_thick_regions(self):
        a, w = self.app, self.world
        a.tool_mode = 12
        a.fill_solid = False
        a.fill_material = 6
        a.physics.player.setPos(30, 30, 0)
        w.queue_save = lambda: None
        for lo, hi in [((-2, -2, 0), (2, 2, 3)), ((5, 5, 1), (8, 8, 1)),
                       ((12, 5, 0), (12, 8, 3)), ((15, 5, 0), (18, 5, 3))]:
            a.fill_start = checks.V(hi[0], hi[1], hi[2]+.5)
            a.preview.setPos(lo[0], lo[1], lo[2]+.5)
            expected = [(x, y, z+.5) for x in range(lo[0], hi[0]+1)
                        for y in range(lo[1], hi[1]+1) for z in range(lo[2], hi[2]+1)
                        if any(v == low or v == high for v, low, high in zip((x,y,z),lo,hi))]
            before = len(w.cubes)
            a.fill_corner()
            added = w.cubes[before:]
            self.assertEqual([tuple(c.getPos()) for c in added], expected)
            self.assertEqual([c.getTag('material') for c in added],
                             [str(1+((x+y+int(z-.5)) % 2)) for x,y,z in expected])


if __name__ == '__main__':
    unittest.main()
