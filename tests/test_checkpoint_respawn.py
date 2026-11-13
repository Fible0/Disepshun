"""Checkpoint spawn searches must not cause collision cascades or death loops."""
import builtins
import tempfile
import unittest
from unittest.mock import patch

import test_regressions as checks


class SafeCheckpointRespawnTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='disepshun-respawn-')
        self.addCleanup(tmp.cleanup)
        self.world = checks.world(tmp.name)
        self.addCleanup(self.world.render.removeNode)
        self.physics = checks.physics(self.world)

    def checkpoint(self, pos=(0,0,.5)):
        node = checks.cube(self.world, pos, '4')
        self.world.active_checkpoint_cube = node
        return node

    def test_normal_checkpoint_keeps_spawn_heading_and_standing_clearance(self):
        node = self.checkpoint()
        node.setTag('heading', '135')
        p = self.physics
        p.player.setPos(20,20,-10); p.pending_land = (.01,1,1)
        p.respawn()
        self.assertEqual(p.player.getPos(), checks.V(0,0,1.5))
        self.assertEqual(p.checkpoint, checks.V(0,0,1.5))
        self.assertEqual(p.player.getH(), 135)
        self.assertIsNone(p.pending_land)
        self.assertFalse(p.flying)
        self.assertFalse(p.spawn_recovery_flight)

    def test_tall_stack_respawns_above_it_without_intermediate_activations(self):
        w, p = self.world, self.physics
        nodes = [checks.cube(w, (0,0,z+.5), '4') for z in range(1000)]
        w.active_checkpoint_cube = nodes[0]
        with patch.object(p, 'activate_checkpoint', wraps=p.activate_checkpoint) as activate:
            p.respawn()
            self.assertEqual(p.player.getPos(), checks.V(0,0,1000))
            self.assertEqual(w.active_checkpoint_cube, nodes[0])
            self.assertEqual(activate.call_count, 0)
            self.assertFalse(p.flying)
            for _ in range(240): p.update(1/240, checks.KEYS)
            # The new supporting checkpoint may activate once on landing;
            # the other 998 blocks must never receive contact events.
            self.assertLessEqual(activate.call_count, 1)
        self.assertEqual(p.player.getZ(), 1000)
        self.assertTrue(p.ground)

    def test_stack_prefers_nearby_floor_over_a_large_vertical_teleport(self):
        bottom = self.checkpoint()
        for z in range(1,100): checks.cube(self.world, (0,0,z+.5), '4')
        checks.cube(self.world, (1,0,.5))
        self.physics.respawn()
        self.assertEqual(self.physics.player.getPos(), checks.V(1,0,1.5))
        self.assertEqual(self.world.active_checkpoint_cube, bottom)
        self.assertFalse(self.physics.flying)

    def test_lethal_ceiling_uses_safe_side_floor_and_does_not_repeat_deaths(self):
        bottom = self.checkpoint()
        hazard = checks.cube(self.world, (0,0,1.5), '3')
        checks.cube(self.world, (1,0,.5))
        p = self.physics
        with patch.object(p, 'respawn', wraps=p.respawn) as respawn:
            p.respawn()
            self.assertEqual(p.player.getPos(), checks.V(1,0,1.5))
            for _ in range(600): p.update(1/240, checks.KEYS)
            self.assertEqual(respawn.call_count, 1)
        self.assertTrue(p.ground)
        self.assertFalse(p.flying)
        self.assertEqual(self.world.active_checkpoint_cube, bottom)
        self.assertNotIn(hazard,p.get_contacts(p.player.getPos(),p.player_height)[1])

    def test_impossible_supported_spawn_enables_recovery_flight_once(self):
        self.checkpoint()
        checks.cube(self.world, (0,0,1.5), '3')
        p = self.physics
        with patch.object(p, 'respawn', wraps=p.respawn) as respawn:
            p.respawn()
            self.assertTrue(p.flying)
            self.assertTrue(p.spawn_recovery_flight)
            self.assertTrue(p._spawn_body_clear(p.player.getPos()))
            for _ in range(240): p.update(1/240,checks.KEYS)
            self.assertEqual(respawn.call_count,1)
        # The fallback changes flight, never the user's invincibility toggle.
        self.assertFalse(p.god_mode)

    def test_last_safe_spawn_is_revalidated_after_map_edits(self):
        old_floor = checks.cube(self.world)
        p = self.physics
        p.set_spawn_position(checks.V(0,0,1.5),safe=True)
        self.checkpoint((10,0,.5))
        checks.cube(self.world, (10,0,1.5), '3')
        p.respawn()
        self.assertEqual(p.player.getPos(),checks.V(0,0,1.5))
        self.assertFalse(p.flying)
        self.world.remove_block(old_floor)
        p.just_respawned = False
        p.respawn()
        self.assertNotEqual(p.player.getPos(),checks.V(0,0,1.5))
        self.assertTrue(p.flying)

    def test_legacy_checkpoint_below_fall_plane_does_not_repeat_respawns(self):
        self.checkpoint((0,0,-30.5))
        p = self.physics
        with patch.object(p,'respawn',wraps=p.respawn) as respawn:
            p.respawn()
            self.assertGreaterEqual(p.player.getZ(),-20)
            self.assertTrue(p.flying)
            for _ in range(120):
                p.update(1/60,checks.KEYS)
                if not p.god_mode and p.player.getZ() < -20: p.respawn()
            self.assertEqual(respawn.call_count,1)

    def test_moving_checkpoint_uses_its_live_position_and_heading(self):
        moving = checks.mover(self.world,(0,0,.5),'4')['np']
        self.world.active_checkpoint_cube = moving
        moving.setPos(50,-30,20.5)
        moving.setTag('heading','270')
        self.physics.respawn()
        self.assertEqual(self.physics.player.getPos(),checks.V(50,-30,21.5))
        self.assertEqual(self.physics.player.getH()%360,270)
        self.assertFalse(self.physics.flying)

    def test_enabled_god_floor_is_a_supported_spawn_below_editor_floor(self):
        w, p = self.world, self.physics
        w.visual_floor.show(); w.update_god_collision(True)
        p.god_mode = True
        p.set_spawn_position(checks.V(0,0,-20),safe=True)
        self.assertEqual(p.player.getPos(),checks.V(0,0,-20))
        self.assertFalse(p.spawn_recovery_flight)
        self.assertFalse(p.flying)

    def test_search_does_not_emit_sounds_particles_saves_or_contact_events(self):
        node = self.checkpoint()
        checks.cube(self.world, (0,0,1.5),'3')
        checks.cube(self.world, (1,0,.5))
        p, w = self.physics, self.world
        with patch.object(builtins.base,'play_sfx') as sounds, \
                patch.object(p.particles,'activate_checkpoint') as particles, \
                patch.object(w,'queue_save') as saves, \
                patch.object(p,'activate_checkpoint') as activate:
            result,recovery = p.resolve_spawn_position(checks.V(0,0,1.5))
        self.assertEqual(result,checks.V(1,0,1.5))
        self.assertFalse(recovery)
        for call in (sounds,particles,saves,activate): call.assert_not_called()
        self.assertEqual(w.active_checkpoint_cube,node)
        self.assertFalse(p.just_respawned)


if __name__ == '__main__':
    unittest.main()
