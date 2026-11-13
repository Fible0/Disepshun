"""Landing equivalence checks for the contact reuse optimization.

Run: python -m unittest discover -s tests
"""
import math
import random
import tempfile
import unittest

import test_regressions as checks


def original_surface(world, physics, pos):
    """Independent reference: the original landing search, including tie order."""
    hw = physics.w / 2
    sx, ex = round(pos.x-hw), round(pos.x+hw)
    sy, ey = round(pos.y-hw), round(pos.y+hw)
    sz = round(pos.z+.5)
    candidates = [(m['np'], m['np'].getPos(world.render), .5)
                  for m in world.moving_cubes]
    if world.god_floor_enabled:
        candidates.append((None, world.god_collision_floor.getPos(world.render), world.FLOOR_HALF))
    candidates.extend((node, node.getPos(world.render), .5)
                      for (x, y, z), node in sorted(world.cube_map.items())
                      if sx-1 <= x < ex+2 and sy-1 <= y < ey+2 and sz-2 <= z < sz+2)
    height = -math.inf
    surface = None
    for node, cp, half in candidates:
        if node is not None and (cp.x-pos.x)**2+(cp.y-pos.y)**2+(cp.z-pos.z)**2 > 9:
            continue
        if (pos.x-hw < cp.x+half and pos.x+hw > cp.x-half and
                pos.y-hw < cp.y+half and pos.y+hw > cp.y-half and
                pos.z < cp.z+.5 and pos.z+physics.player_height > cp.z-.5 and cp.z+.5 > height):
            height, surface = cp.z+.5, node
    return height, surface


class LandingContactReuseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='disepshun-physics-')
        self.addCleanup(self.tmp.cleanup)
        self.world = checks.world(self.tmp.name)
        self.addCleanup(self.world.render.removeNode)
        self.physics = checks.physics(self.world)
        self.physics.god_mode = True

    def test_landing_matches_independent_surface_search(self):
        rng = random.Random(1047)
        world, p = self.world, self.physics
        for _ in range(180):
            pos = checks.V(*(rng.uniform(-4, 4) for _ in range(3)))
            if world.get_grid_key(pos) not in world.cube_map:
                checks.cube(world, pos)
        for _ in range(20):
            checks.mover(world, tuple(rng.uniform(-5, 5) for _ in range(3)))
        # Explicit off-grid overhead contact: the overlap query sees it, but
        # the original landing scan's narrower vertical range excludes it.
        checks.cube(world, (12, 0, 2.6))
        checks.cube(world, (9999.7, 0, .5))
        cases = [checks.V(*(rng.uniform(-5, 5) for _ in range(3))) for _ in range(800)]
        cases += [checks.V(12, 0, .99), checks.V(10000, 0, .99),
                  checks.V(0, 0, -20.01), checks.V(1001, 0, -20.01)]
        for enabled in (False, True):
            world.visual_floor.show()
            world.update_god_collision(enabled)
            for i, target in enumerate(cases):
                p.player_height = (.9, 1.23, 1.67)[i % 3]
                p.player.setPos(target+checks.V(0, 0, .125))
                # Recreate the float32 target computed by vertical_step.
                target = p.player.getPos()+checks.V(0, 0, -.125)
                p.vz = -2
                p.ground = False
                p.fall_peak_z = 20
                p.pending_land = None
                floor, hits = p.get_contacts(target, p.player_height)
                height, _ = original_surface(world, p, target)
                lands = bool(floor or hits) and height > -10000
                stopped = p.vertical_step(-.125, checks.KEYS)
                self.assertEqual(stopped, lands, (enabled, target))
                self.assertEqual(p.ground, lands, (enabled, target))
                self.assertEqual(p.vz, 0 if lands else -2)
                self.assertAlmostEqual(p.player.getZ(), height if lands else target.z, places=5)

    def test_equal_height_mover_precedes_static_trampoline(self):
        world, p = self.world, self.physics
        checks.mover(world, (-.4, 0, .5), '5')
        checks.cube(world, (.4, 0, .5), '1')
        p.player.setPos(0, 0, 1.1)
        p.vz = -8
        keys = dict(checks.KEYS, space=True)
        self.assertTrue(p.vertical_step(-.2, keys))
        self.assertAlmostEqual(p.vz, 8*1.3)
        self.assertFalse(p.ground)
        self.assertAlmostEqual(p.player.getZ(), 1.01, places=5)

    def test_floor_tie_precedes_static_trampoline(self):
        world, p = self.world, self.physics
        world.visual_floor.show()
        world.update_god_collision(True)
        checks.cube(world, (0, 0, -20.5), '5')
        p.player.setPos(0, 0, -19.9)
        p.vz = -8
        self.assertTrue(p.vertical_step(-.2, dict(checks.KEYS, space=True)))
        self.assertEqual(p.vz, 0)
        self.assertTrue(p.ground)
        self.assertEqual(p.player.getZ(), -20)

    def test_flight_directions_follow_camera_and_opposing_keys_exactly(self):
        p = self.physics
        p.flying = True
        rng = random.Random(3106)
        # The reference recalculates directions from the current camera on
        # every step; repeated orientations exercise the cached path too.
        for i in range(600):
            if i % 3 == 0:
                p.player.setH(rng.uniform(-180, 180))
                p.camera.setHpr(rng.uniform(-180, 180), rng.uniform(-89, 89), rng.uniform(-30, 30))
            p.player.setPos(1, 2, 3)
            keys = {key: bool(rng.getrandbits(1)) for key in checks.KEYS}
            dt = (1/240, 1/60, .2)[i % 3]
            q = p.camera.getQuat(self.world.render)
            f = q.getForward(); f.setZ(0); f.normalize()
            r = q.getRight(); r.setZ(0); r.normalize()
            direction = checks.V(0, 0, 0)
            if keys['w']: direction += f
            if keys['s']: direction -= f
            if keys['a']: direction -= r
            if keys['d']: direction += r
            if keys['space']: direction.z += 1
            if keys['lshift'] or keys['rshift']: direction.z -= 1
            expected = checks.V(1, 2, 3)
            if direction.lengthSquared() > 0:
                expected += direction.normalized()*p.fly_speed*min(dt, .1)
            p.update(dt, keys)
            self.assertEqual(p.player.getPos(), expected)

    def test_idle_flight_still_updates_effects_and_landing_state(self):
        p = self.physics
        p.flying = True
        p.player.setPos(2, 3, 4)
        p.pending_land = (.01, 1, 1)
        p.checkpoint_activated_this_update = True
        updates = []
        p.particles = checks.NS(update=updates.append)
        # With no movement input, camera direction cannot affect the result.
        p.camera = checks.NS(getQuat=lambda _: self.fail('idle flight requested direction'))
        p.update(1/240, checks.KEYS)
        self.assertEqual(p.player.getPos(), checks.V(2, 3, 4))
        self.assertIsNone(p.pending_land)
        self.assertFalse(p.checkpoint_activated_this_update)
        self.assertEqual(p.fall_peak_z, 4)
        self.assertEqual(updates, [1/240])

    def test_high_altitude_blocks_support_walking_and_block_horizontal_motion(self):
        w, p = self.world, self.physics
        for i, (height, moving) in enumerate(((1000, False), (2500, True), (9999, False), (10000.5, True))):
            with self.subTest(height=height, moving=moving):
                x = i*4
                checks.cube(w, (x, 0, height-.5))
                if moving:
                    wall = checks.mover(w, (x, 1, height+.5), wp=(x, 1, height+.5))['np']
                else:
                    wall = checks.cube(w, (x, 1, height+.5))
                w.index_movers()
                p.player.setPos(x, 0, height); p.vz = 0; p.ground = True
                p.curr_h = p.h_stand
                for _ in range(48): p.update(1/240, dict(checks.KEYS, w=True))
                self.assertGreater(p.player.getY(), .2)
                self.assertLessEqual(p.player.getY(), .3001)
                self.assertEqual(p.player.getZ(), height)
                self.assertTrue(p.ground)
                self.assertAlmostEqual(p.player_height, p.h_stand)
                self.assertIn(wall, p.get_contacts(checks.V(x, 1, height), p.h_stand)[1])

    def test_high_altitude_landing_retains_every_material_effect(self):
        for moving in (False, True):
            for material in ('1', '3', '4', '5'):
                with self.subTest(moving=moving, material=material):
                    w = checks.world(self.tmp.name)
                    self.addCleanup(w.render.removeNode)
                    if moving:
                        node = checks.mover(w, (0, 0, 1500.5), material, wp=(0, 0, 1500.5))['np']
                    else:
                        node = checks.cube(w, (0, 0, 1500.5), material)
                    w.index_movers()
                    p = checks.physics(w); p.player.setPos(0, 0, 1501.1); p.vz = -8
                    self.assertTrue(p.vertical_step(-.2, dict(checks.KEYS, space=material == '5')))
                    if material == '3':
                        self.assertTrue(p.just_respawned)
                        self.assertEqual(p.player.getPos(), checks.V(0, 0, 1))
                    elif material == '5':
                        self.assertGreater(p.vz, 8)
                        self.assertFalse(p.ground)
                        self.assertAlmostEqual(p.player.getZ(), 1501.01, places=3)
                    else:
                        self.assertEqual(p.player.getZ(), 1501)
                        self.assertTrue(p.ground)
                        if material == '4': self.assertEqual(w.active_checkpoint_cube, node)

    def test_checkpoint_at_maximum_saved_height_respawns_above_its_surface(self):
        w, p = self.world, self.physics
        p.god_mode = False
        checkpoint = checks.cube(w, (0, 0, w.COORD_LIMIT), '4')
        p.player.setPos(0, 0, w.COORD_LIMIT+.8); p.vz = -2
        self.assertTrue(p.vertical_step(-.4, checks.KEYS))
        self.assertEqual(w.active_checkpoint_cube, checkpoint)
        self.assertEqual(p.checkpoint, checks.V(0, 0, w.COORD_LIMIT+1))
        p.respawn()
        self.assertEqual(p.player.getZ(), w.COORD_LIMIT+1)
        landed = False
        for _ in range(120):
            p.update(1/240, checks.KEYS)
            if landed: self.assertTrue(p.ground)
            landed = landed or p.ground
        self.assertTrue(p.ground)
        self.assertEqual(p.player.getZ(), w.COORD_LIMIT+.5)
        p.update(1/240, dict(checks.KEYS, space=True))
        self.assertGreater(p.vz, 7)
        self.assertGreater(p.player.getZ(), w.COORD_LIMIT+.5)
        self.assertFalse(p.ground)

    def test_sub_float32_vertical_step_does_not_create_support_in_empty_space(self):
        p = self.physics
        p.player.setPos(0, 0, 10000); p.ground = True; p.vz = -.1
        self.assertFalse(p.vertical_step(-.0001, checks.KEYS))
        self.assertEqual(p.player.getZ(), 10000)
        self.assertFalse(p.ground)
        self.assertEqual(p.vz, -.1)

    def test_flight_outside_save_bounds_does_not_lock_horizontal_return(self):
        p = self.physics
        cases = ((checks.V(-10001, 0, 1500), 'd', 0, 1),
                 (checks.V(10001, 0, 1500), 'a', 0, -1),
                 (checks.V(0, -10001, 1500), 'w', 1, 1),
                 (checks.V(0, 10001, 1500), 's', 1, -1),
                 (checks.V(0, 0, 12000), 'w', 1, 1))
        for pos, key, axis, sign in cases:
            with self.subTest(pos=pos):
                p.player.setPos(pos); p.flying = True; p.vz = 0
                keys = dict(checks.KEYS, **{key: True})
                p.update(1/60, keys)
                after_flight = p.player.getPos()
                p.flying = False; p.curr_h = p.h_stand
                for _ in range(10): p.update(1/240, keys)
                self.assertGreater(sign*(p.player.getPos()[axis]-after_flight[axis]), .15)
                self.assertLess(p.player.getZ(), after_flight.z)
                self.assertFalse(p.was_crouching)
                self.assertEqual(p.get_contacts(pos, p.h_stand), (False, []))

    def test_nonfinite_contacts_are_rejected_without_scanning_the_world(self):
        for axis in range(3):
            for invalid in (math.nan, math.inf, -math.inf):
                pos = checks.V(0, 0, 0); pos[axis] = invalid
                self.assertEqual(self.physics.get_contacts(pos, self.physics.h_stand), (True, []))

    def test_trampoline_predictions_have_no_artificial_altitude_ceiling(self):
        w, p = self.world, self.physics
        predictions = []
        for height in (.5, 1500.5, w.COORD_LIMIT):
            node = checks.cube(w, (0, 0, height), '5')
            node.setTag('bounciness', '1.3'); node.setTag('max_height', '4')
            predictions.append(p.bounce_heights(node, 1/240))
        self.assertEqual(predictions[0], predictions[1])
        self.assertEqual(predictions[0], predictions[2])
        self.assertGreater(predictions[0][0], 0)
        # Terminal fall speed bounds the next launch even with unlimited height.
        node.setTag('bounciness', '2'); node.setTag('max_height', '0')
        first, highest = p.bounce_heights(node, 1/240)
        self.assertGreater(first, 5)
        self.assertTrue(math.isfinite(highest))
        launch = 2*p.max_fall_speed
        k = math.floor(launch/(abs(p.g)/240))
        expected = .01 + (k*launch - abs(p.g)/240*k*(k+1)/2)/240
        self.assertAlmostEqual(highest, expected)
        self.assertGreater(highest, 9000)
        # A real maximum-speed launch reaches the same apex. Use an empty
        # column so the test's other trampoline blocks cannot form a ceiling.
        p.player.setPos(4, 0, 1501.01); p.vz = launch; p.ground = False
        peak = p.player.getZ()
        while p.vz > 0:
            p.update(1/240, checks.KEYS)
            peak = max(peak, p.player.getZ())
        self.assertAlmostEqual(peak-1501, highest, delta=.1)


if __name__ == '__main__':
    unittest.main()
