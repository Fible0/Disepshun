"""Repeatable CPU benchmarks, using temporary headless scenes and no user data.

Run: python tests/benchmark_performance.py
An optional --source-root PATH measures a saved copy of the original sources.
Timings cover individual CPU workloads, not rendered frame rates.
"""
import argparse
import ast
from pathlib import Path
import runpy
import statistics
import tempfile
import time

import test_regressions as checks


def measure(label, action, iterations=1):
    action()
    samples = []
    for _ in range(5):
        started = time.perf_counter()
        for _ in range(iterations):
            action()
        samples.append((time.perf_counter()-started)*1000/iterations)
    print(f'{label}: {statistics.median(samples):.4f} ms/call')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path)
    args = parser.parse_args()
    root = args.source_root or checks.ROOT
    if args.source_root:
        for name in ('disepshun/editor_tools.py', 'disepshun/particle_system.py',
                     'disepshun/world_manager.py', 'disepshun/player_physics.py', 'Main.py'):
            path = root/name
            tree = ast.parse(path.read_text(), filename=str(path))
            tree.body = [n for n in tree.body if isinstance(n, ast.ClassDef)]
            exec(compile(tree, str(path), 'exec'), checks.G)
        checks.World, checks.Physics, checks.App = (checks.G[n] for n in
                                                  ('WorldManager', 'PlayerPhysics', 'Disepshun'))
    print(f'Sources: {root}')
    with tempfile.TemporaryDirectory(prefix='disepshun-benchmark-') as tmp:
        w = checks.world(tmp)
        for x in range(-80, 80):
            for y in range(-50, 50):
                checks.cube(w, (x*2, y*2, .5), '3' if (x+y)%4 == 0 else '1')
        p = checks.physics(w)
        measure('Contacts / 16,000 static blocks', lambda: p.get_contacts(checks.V(.1,.1,.95), 1.67), 1000)

        def glow():
            w.next_glow_scan = 0
            w.update_glow_lights(checks.V(0,0,2), now=0)
        measure('Glow source scan / 16,000 blocks', glow, 10)
        a = checks.app(w)
        positions = [checks.V(x*2,0,5.5) for x in range(256)]
        measure('Validate 256-block edit / 16,000 blocks', lambda: a.valid_positions(positions, ()))
        a.camera = a.physics.camera; a.setup_ray()
        a.camera.setPos(w.render, 0, -5, 2); a.camera.lookAt(w.render, checks.V(0, 0, .5))
        measure('Picking / 16,000 blocks, five-unit reach', lambda: a.traverse_pick(5), 100)
        w.render.removeNode()

        w = checks.world(tmp)
        a = checks.app(w)
        positions = [checks.V(x*2, y*2, .5) for x in range(64) for y in range(64)]
        measure('Validate 4,096-block edit / empty map', lambda: a.valid_positions(positions, ()))
        w.render.removeNode()

        w = checks.world(tmp)
        for x in range(16):
            for y in range(16):
                for z in range(16):
                    checks.cube(w, (x,y,z+.5))
        chunk = w.get_chunk_key(checks.V(0, 0, .5))
        measure('Mesh rebuild / solid 4,096-block chunk', lambda: w.rebuild_chunk(chunk), 3)
        w.render.removeNode()

        w = checks.world(tmp)
        for i in range(200):
            node = checks.NP('mover'); node.reparentTo(w.platform_holder)
            node.setPos(i*2, 0, .5)
            w.moving_cubes.append(dict(np=node, origin=checks.V(i*2,0,.5),
                waypoints=[checks.V(i*2,j*2,(j%3)+.5) for j in range(1,33)],
                speed=3., current_idx=1, direction=1, loop=True))
        a = checks.app(w); a.physics.flying = True
        measure('Mover update / 200 movers, 32 waypoints each', lambda: a.update_world(checks.TASK), 100)
        w.render.removeNode()

        w = checks.world(tmp)
        for x in range(-5, 6):
            for y in range(-5, 6): checks.cube(w, (x, y, .5))
        p = checks.physics(w); p.ground = True
        measure('Grounded physics / 240 Hz step', lambda: p.update(1/240, checks.KEYS), 1000)
        w.index_movers()
        measure('Grounded physics / indexed scene, no movers', lambda: p.update(1/240, checks.KEYS), 1000)
        p.flying = True
        measure('Idle flight / 240 Hz step', lambda: p.update(1/240, checks.KEYS), 1000)
        flight_keys = dict(checks.KEYS, w=True)
        measure('Moving flight / unchanged view', lambda: p.update(1/240, flight_keys), 1000)
        w.render.removeNode()

        w = checks.world(tmp)
        nodes = [checks.cube(w, (i*2, 0, .5)) for i in range(4000)]
        for node in nodes: node.setTag('group', 'benchmark-group')
        a = checks.app(w); a.tool_mode = 11; a.tool_phases[11] = 'select'
        a.pick_object = lambda: nodes[-1]
        def toggle_group():
            a.select_object(); a.select_object()
        measure('Select and deselect / 4,000-block group', toggle_group, 2)
        w.render.removeNode()

        w = checks.world(tmp)
        a = checks.app(w); a.tool_mode = 9
        a.selected_objects = [checks.cube(w, (i*2, 0, .5), '4') for i in range(1000)]
        measure('Checkpoint arrows / 1,000 unchanged markers', a.draw_checkpoint_direction, 20)
        w.render.removeNode()

        w = checks.world(tmp)
        for x in range(-8, 9):
            for y in range(-8, 9):
                for z in range(-8, 9): checks.cube(w, (x, y, z+.5), '3')
        def dense_glow():
            w.next_glow_scan = 0
            w.update_glow_lights(checks.V(0, 0, 2), now=0)
        measure('Glow source scan / 4,913 nearby glowing blocks', dense_glow, 10)
        w.render.removeNode()

        w = checks.world(tmp)
        checks.mover(w, (100, 100, .5)); checks.mover(w, (100, 102, .5))
        a = checks.app(w); a.tool_mode = 12; a.physics.player.setPos(50, 50, 1)
        w.queue_save = lambda: None
        def fill_and_undo():
            a.fill_start = checks.V(0, 0, .5); a.preview.setPos(15, 15, 15.5)
            a.fill_corner()
            if not a.history_step(): raise AssertionError('Fill undo failed')
        measure('Fill and undo / 4,096 blocks, two distant movers', fill_and_undo)
        w.render.removeNode()

        for height in (1000, 5000):
            w = checks.world(tmp)
            checkpoints = [checks.cube(w, (0, 0, z+.5), '4') for z in range(height)]
            w.update_chunks(); p = checks.physics(w)
            p.activate_checkpoint(checkpoints[0]); w.update_chunks()
            def checkpoint_switch():
                target = checkpoints[-1] if w.active_checkpoint_cube == checkpoints[0] else checkpoints[0]
                p.activate_checkpoint(target); w.update_chunks()
            measure(f'Checkpoint switch and mesh / {height}-block stack', checkpoint_switch)
            w.render.removeNode()

    clock = checks.NS(frame_time=0.0)
    clock.getFrameTime = lambda: clock.frame_time
    with checks.patch.dict(checks.G, ClockObject=checks.NS(getGlobalClock=lambda: clock)):
        particles = checks.G['ParticleSystem'](checks.NP('benchmark-particles'))
        for _ in range(10): particles.activate_checkpoint(checks.V(0, 0, 0))
        def particle_frame():
            # Four 240 Hz physics steps share one frame time at 60 rendered FPS.
            # Advance only slightly so particles survive the benchmark's samples.
            clock.frame_time += .0001
            for _ in range(4): particles.update(1/240)
        measure('Particles / 300 particles, four physics steps per frame', particle_frame, 100)
        def full_checkpoint_frame():
            clock.frame_time += .0001
            for _ in range(4):
                particles.activate_checkpoint(checks.V(0, 0, 0))
                particles.update(1/240)
        measure('Full checkpoint particle pool / four physics steps per frame', full_checkpoint_frame, 100)
        particles.parent.removeNode()

    bloom = runpy.run_path(str(root/'disepshun/bloom.py'))['NeonBloom']
    effect = bloom.__new__(bloom)
    effect.input_sizes = {}
    effect.passes = []
    for i in range(12):
        texture = checks.core.Texture(f'buffer-{i}')
        texture.setup2dTexture(256,128,checks.core.Texture.TUnsignedByte,checks.core.Texture.FRgba)
        effect.passes.append((checks.NP(f'pass-{i}'), {'src':texture}))
    measure('Bloom inputs / unchanged buffers', effect.update, 1000)


if __name__ == '__main__':
    main()
