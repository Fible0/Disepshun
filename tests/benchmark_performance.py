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
        for name in ('disepshun/editor_tools.py', 'disepshun/world_manager.py', 'disepshun/player_physics.py', 'Main.py'):
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
        w.render.removeNode()

        w = checks.world(tmp)
        for x in range(16):
            for y in range(16):
                for z in range(16):
                    checks.cube(w, (x,y,z+.5))
        measure('Mesh rebuild / solid 4,096-block chunk', lambda: w.rebuild_chunk((0,0)), 3)
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
