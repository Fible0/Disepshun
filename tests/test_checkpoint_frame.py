"""Checkpoint effects and respawn work stay bounded within a rendered frame."""
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

import test_regressions as checks


class CheckpointFrameTests(unittest.TestCase):
    def test_respawn_stops_the_remaining_fixed_physics_steps(self):
        with tempfile.TemporaryDirectory(prefix='disepshun-checkpoint-frame-') as tmp:
            w = checks.world(tmp)
            self.addCleanup(w.render.removeNode)
            a = checks.app(w)
            updates = []
            def update(dt, keys):
                updates.append(dt)
                a.physics.just_respawned = True
            a.physics.update = update
            a.step_physics(.1)
            self.assertEqual(updates, [a.PHYSICS_STEP])
            self.assertEqual(a.physics_time, 0)
            a.physics.just_respawned = False
            a.step_physics(a.PHYSICS_STEP)
            self.assertEqual(updates, [a.PHYSICS_STEP]*2)

    def test_recovery_flight_notice_and_cue_are_shown_once(self):
        with tempfile.TemporaryDirectory(prefix='disepshun-checkpoint-notice-') as tmp:
            w = checks.world(tmp)
            self.addCleanup(w.render.removeNode)
            a = checks.app(w)
            a.paused = True
            a.physics.spawn_recovery_flight = True
            notices = []; sounds = []
            a.editor_notice = notices.append
            a.play_sfx = lambda name: sounds.append(name)
            a.presence = NS(tick=lambda *args: None)
            a.win = NS(getProperties=lambda: NS(getForeground=lambda: True))
            a.apply_frame_limit = lambda: None
            a.report_save_state = lambda _: None
            a.ui = NS(update_item_name=lambda _: None, update_presence_status=lambda: None,
                      fps_text=NS(setText=lambda _: None), fly_text=checks.NP('fly-text'))
            a.fly_text_timer = 0
            clock = NS(getDt=lambda: 1/60, getFrameTime=lambda: 1,
                       getAverageFrameRate=lambda: 60)
            with patch.dict(checks.G, globalClock=clock, user32=None):
                a.update(checks.TASK)
                a.update(checks.TASK)
            self.assertEqual(len(notices), 1)
            self.assertIn('flight enabled', notices[0])
            self.assertEqual(sounds, ['power_on'])
            self.assertFalse(a.physics.spawn_recovery_flight)

    def test_full_particle_pool_does_not_repeat_same_frame_scene_writes(self):
        now = [0.]
        clock = NS(getFrameTime=lambda: now[0])
        with patch.dict(checks.G, ClockObject=NS(getGlobalClock=lambda: clock)):
            particles = checks.G['ParticleSystem'](checks.NP('checkpoint-particles'), pool_size=30)
            self.addCleanup(particles.parent.removeNode)
            particles.activate_checkpoint(checks.V(0, 0, 0))
            particles.update(1/240)
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
            for p in particles.active_parts: p.node = WatchedNode(p.node)
            for _ in range(24):
                particles.activate_checkpoint(checks.V(0, 0, 0))
                particles.update(1/240)
            self.assertEqual(len(particles.active_parts), 30)
            self.assertEqual(writes, [])
            now[0] = .25
            particles.update(1/240)
            self.assertEqual(len(writes), 60)


if __name__ == '__main__':
    unittest.main()
