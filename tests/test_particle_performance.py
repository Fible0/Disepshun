"""Particle appearance and same-frame updates, without a window or user saves."""
import math
import random
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import test_regressions as checks


class ParticlePerformanceTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        clock = SimpleNamespace(getFrameTime=lambda: self.now)
        self.globals = patch.dict(checks.G, ClockObject=SimpleNamespace(getGlobalClock=lambda: clock),
                                  random=random.Random(42))
        self.globals.start()
        self.addCleanup(self.globals.stop)
        self.particles = checks.G['ParticleSystem'](checks.NP('particle-test'))
        self.addCleanup(self.particles.parent.removeNode)

    def test_repeated_physics_steps_do_not_rewrite_particle_transforms(self):
        self.particles.activate_checkpoint(checks.V(1, 2, 3))
        self.now = .25
        self.particles.update(1/240)
        nodes = [p.node for p in self.particles.active_parts]
        states = [(n.getTransform(), n.getState()) for n in nodes]
        # Wrappers count writes to real Panda3D nodes.
        writes = []

        class WatchedNode:
            def __init__(self, node): self.node = node
            def __getattr__(self, name):
                value = getattr(self.node, name)
                if name not in ('setPos', 'setColorScale'): return value
                def write(*args):
                    writes.append(name)
                    return value(*args)
                return write

        for p in self.particles.active_parts: p.node = WatchedNode(p.node)
        for _ in range(8): self.particles.update(1/240)
        self.assertEqual(writes, [])
        self.assertEqual(states, [(n.getTransform(), n.getState()) for n in nodes])
        self.now = .5
        self.particles.update(1/240)
        self.assertEqual(len(writes), 2*len(nodes))
        for p in self.particles.active_parts:
            self.assertAlmostEqual(p.node.getZ(), 3.6 + p.vz*.5, places=5)
            color = p.node.getColorScale()
            for actual, expected in zip(color, (0, .84, .32, .6)):
                # Panda3D quantizes render-state colours to 1/1024 increments.
                self.assertAlmostEqual(actual, expected, delta=1/1024)

    def test_bursts_between_physics_steps_appear_in_the_same_frame(self):
        self.particles.activate_checkpoint(checks.V(0, 0, 0))
        self.now = .25
        self.particles.update(1/240)
        self.particles.activate_checkpoint(checks.V(2, 3, 4))
        self.particles.update(1/240)
        self.assertEqual(len(self.particles.active_parts), 60)
        for p in self.particles.active_parts[30:]:
            self.assertEqual(p.node.getColorScale(), checks.core.Vec4(0, 1, 0, 1))
        self.particles.explode(checks.V(4, 5, 6))
        self.particles.update(1/240)
        swirls = [p for p in self.particles.active_parts if p.p_type == 0]
        self.assertEqual(len(swirls), 60)
        for p in swirls:
            self.assertEqual(p.node.getColorScale(), checks.core.Vec4(0, 1, 1, 1))
        self.now = .5
        self.particles.update(1/240)
        for p in swirls:
            angle = p.angle + p.angular_vel*.25
            expected = checks.V(4 + math.cos(angle)*p.radius,
                                5 + math.sin(angle)*p.radius, 6 + p.height + p.vz*.25)
            self.assertLess((p.node.getPos()-expected).length(), 1e-5)
        self.now = 2
        self.particles.update(1/240)
        self.assertEqual(self.particles.active_parts, [])
        self.assertEqual(self.particles.parent.getNumChildren(), 0)
        # A later burst still updates after the system has become empty.
        self.particles.activate_checkpoint(checks.V(0, 0, 0))
        self.particles.update(1/240)
        self.assertEqual(self.particles.active_parts[0].node.getColorScale(), checks.core.Vec4(0, 1, 0, 1))


if __name__ == '__main__':
    unittest.main()
