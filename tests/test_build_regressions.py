"""Build-boundary, batch-validation and high trampoline preview regressions."""
import tempfile
import unittest

import test_regressions as checks


class BuildRegressions(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='disepshun-build-')
        self.addCleanup(tmp.cleanup)
        self.world = checks.world(tmp.name)
        self.addCleanup(self.world.render.removeNode)
        self.app = checks.app(self.world)
        self.app.physics.player.setPos(50, 50, 1)
        self.notices = []
        self.app.editor_notice = self.notices.append

    def test_placement_rejects_unsavable_coordinates_and_keeps_top_grid_row(self):
        a, w = self.app, self.world
        for pos in ((10001, 0, .5), (-10001, 0, .5), (0, 0, 10000.5)):
            a.preview.setPos(*pos)
            a.place()
            self.assertEqual(w.all_blocks(), [])
            self.assertEqual(a.spawned_cube_count, 0)
            self.assertFalse(w.map_is_dirty)
        a.preview.setPos(10000, 0, 9999.5)
        a.place()
        self.assertEqual(len(w.cubes), 1)
        checks.save(w)
        w.load_map()
        self.assertEqual(w.load_errors, [])
        self.assertEqual([tuple(c.getPos()) for c in w.cubes], [(10000, 0, 9999.5)])

    def test_fill_rejects_invalid_corners_without_partial_changes(self):
        a, w = self.app, self.world
        a.tool_mode = 12
        a.preview.setPos(0, 0, 10000.5)
        a.fill_corner()
        self.assertIsNone(getattr(a, 'fill_start', None))
        a.preview.setPos(0, 0, 9999.5)
        a.fill_corner()
        a.preview.setPos(0, 0, 10000.5)
        a.fill_corner()
        self.assertEqual(w.all_blocks(), [])
        self.assertEqual(a.fill_start, checks.V(0, 0, 9999.5))
        self.assertFalse(w.map_is_dirty)
        a.preview.setPos(1, 0, 9999.5)
        a.fill_corner()
        self.assertEqual(len(w.cubes), 2)
        checks.save(w)
        w.load_map()
        self.assertEqual(w.load_errors, [])
        self.assertEqual(len(w.cubes), 2)

    def test_attaching_to_a_mover_validates_the_entire_offset_path(self):
        a, w = self.app, self.world
        m = checks.mover(w, (9998, 0, .5), wp=(10000, 0, .5))
        checks.hit(a, m['np'])
        a.preview.setPos(9999, 0, .5)
        a.place()
        self.assertEqual(len(w.moving_cubes), 1)
        self.assertEqual(a.spawned_cube_count, 0)
        self.assertFalse(w.map_is_dirty)
        self.assertTrue(self.notices)
        # An offset path whose furthest point is exactly at the limit remains valid.
        m['waypoints'] = [checks.V(9999, 0, .5)]
        a.place()
        self.assertEqual(len(w.moving_cubes), 2)
        self.assertEqual(w.moving_cubes[-1]['waypoints'], [checks.V(10000, 0, .5)])
        checks.save(w)
        w.load_map()
        self.assertEqual(w.load_errors, [])
        self.assertEqual(len(w.moving_cubes), 2)

    def test_high_bounce_ghosts_keep_finite_positions(self):
        a = self.app
        a.tool_mode = 8
        a.selected_trampolines = [checks.cube(self.world, (0, 0, 1500.5), '5')]
        a.bounce_ghosts = []
        a.make_ghost = lambda color: self.world.render.attachNewNode('ghost')
        a.physics.bounce_heights = lambda c, dt: (3., 9.)
        a.update_bounce_ghosts()
        first, top = a.bounce_ghosts[0]
        self.assertEqual(first.getZ(), 1504)
        self.assertEqual(top.getZ(), 1510)
        self.assertFalse(first.isHidden())
        self.assertFalse(top.isHidden())
        a.physics.bounce_heights = lambda c, dt: (3., float('inf'))
        a.update_bounce_ghosts()
        self.assertFalse(first.isHidden())
        self.assertTrue(top.isHidden())
        self.assertEqual(top.getZ(), 1510)

    def test_waypoint_bounds_are_checked_before_converting_any_selected_blocks(self):
        a, w = self.app, self.world
        nodes = [checks.cube(w, (x, 0, .5)) for x in (9998, 10000)]
        a.tool_mode = 7
        a.selected_objects = nodes
        a.preview.setPos(10000, 0, .5)
        a.handle_place_wp()
        self.assertEqual(list(w.cubes), nodes)
        self.assertFalse(w.moving_cubes)
        self.assertFalse(w.map_is_dirty)
        a.preview.setPos(9999, 0, .5)
        a.handle_place_wp()
        self.assertEqual(len(w.moving_cubes), 2)
        self.assertEqual([m['waypoints'] for m in w.moving_cubes],
                         [[checks.V(9998, 0, .5)], [checks.V(10000, 0, .5)]])
        checks.save(w)
        w.load_map()
        self.assertEqual(w.load_errors, [])
        self.assertEqual(len(w.moving_cubes), 2)

    def test_empty_map_batch_validation_still_detects_overlaps(self):
        a = self.app
        positions = [checks.V(x*2, y*2, .5) for x in range(64) for y in range(64)]
        self.assertTrue(a.valid_positions(positions, ()))
        self.assertFalse(a.valid_positions(positions + [checks.V(0, 0, .5)], ()))
        checks.mover(self.world)
        self.assertFalse(a.valid_positions([checks.V(.5, 0, .5)], ()))


if __name__ == '__main__':
    unittest.main()
