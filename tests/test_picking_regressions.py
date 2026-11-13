"""Real collision queries for visible-face aiming and bounded editor picking."""
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import test_regressions as checks


class PickingRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='disepshun-picking-')
        self.addCleanup(self.tmp.cleanup)
        self.world = checks.world(self.tmp.name)
        self.addCleanup(self.world.render.removeNode)
        self.app = checks.app(self.world)
        self.app.camera = self.world.render.attachNewNode('camera')
        self.app.setup_ray()

    def nearest(self, length=None):
        a = self.app
        a.traverse_pick(length)
        if not a.cHandler.getNumEntries(): return None
        a.cHandler.sortEntries()
        return a.cHandler.getEntry(0)

    def test_outside_aim_reports_front_face_at_every_build_distance(self):
        w, a = self.world, self.app
        block = checks.cube(w)
        center = block.getPos(w.render)
        # A long CollisionSegment used to report the exit face when the block
        # occupied the segment's first half, making the preview jump behind it.
        for direction in (checks.V(1,0,0), checks.V(-1,0,0), checks.V(0,1,0),
                          checks.V(0,-1,0), checks.V(0,0,1), checks.V(0,0,-1)):
            a.camera.setPos(center-direction*2)
            a.camera.lookAt(center)
            for length in (2, 5, 20, a.PICK_FAR):
                entry = self.nearest(length)
                self.assertIsNotNone(entry)
                self.assertEqual(entry.getIntoNodePath().getParent(), block)
                self.assertLess((entry.getSurfacePoint(w.render)-(center-direction*.5)).length(), 1e-5)
                self.assertLess((entry.getSurfaceNormal(w.render)+direction).length(), 1e-5)

    def test_nearest_static_or_moving_block_occludes_blocks_behind(self):
        w, a = self.world, self.app
        a.camera.setPos(0, -2, .5)
        near = checks.cube(w)
        moving = checks.mover(w, (0, 3, .5))['np']
        far = checks.cube(w, (0, 6, .5))
        self.assertEqual(a.pick_object(), near)
        w.remove_block(near)
        self.assertEqual(a.pick_object(), moving)
        moving.setX(2)
        self.assertEqual(a.pick_object(), far)
        # A prior long-range query must not leak into the next short query.
        self.assertIsNone(self.nearest(1))
        self.assertEqual(a.cHandler.getNumEntries(), 0)

    def test_reach_rejects_conservative_bounds_false_positives(self):
        w, a = self.world, self.app
        a.camera.setPos(0, 0, .5)
        block = checks.cube(w, (0, 5.75, .5))
        # The block's sphere overlaps reach 5, but its front face is at 5.25.
        self.assertIsNone(self.nearest(5))
        entry = self.nearest(5.25)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.getIntoNodePath().getParent(), block)
        self.assertEqual(entry.getSurfacePoint(w.render), checks.core.Point3(0, 5.25, .5))
        self.assertIsNone(self.nearest(5))

    def test_block_preview_stays_on_the_visible_side(self):
        w, a = self.world, self.app
        checks.cube(w)
        a.camera.setPos(0, -2, .5)
        a.presence = SimpleNamespace(tick=lambda *args: None)
        a.win = SimpleNamespace(getProperties=lambda: SimpleNamespace(getForeground=lambda: True))
        a.apply_frame_limit = lambda: None
        a.report_save_state = lambda _: None
        a.step_physics = lambda _: None
        a.mouseWatcherNode = SimpleNamespace(hasMouse=lambda: False)
        a.ui = SimpleNamespace(update_item_name=lambda _: None, update_presence_status=lambda: None,
                               fps_text=SimpleNamespace(setText=lambda _: None), fly_text=checks.NP('fly-text'))
        a.fly_text_timer = 0
        a.preview_enabled = True
        a.keyMap.update(dict.fromkeys(('br_l', 'br_r'), False))
        a.timers.update(dict.fromkeys(('br_l', 'br_r'), 0))
        a.refresh_selection_if_changed = lambda: None
        a.draw_checkpoint_direction = lambda: None
        a.update_bounce_ghosts = lambda: None
        clock = SimpleNamespace(getDt=lambda: 1/60, getFrameTime=lambda: 1,
                                getAverageFrameRate=lambda: 60)
        with patch.dict(checks.G, globalClock=clock, user32=None):
            a.update(checks.TASK)
        self.assertEqual(a.preview.getPos(), checks.core.Point3(0, -1, .5))
        self.assertFalse(a.preview.isHidden())


if __name__ == '__main__':
    unittest.main()
