"""Exact surface and render-state checks for the optimized chunk builder."""
from array import array
import random
import tempfile
import unittest

import test_regressions as checks


class ChunkSurfaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='disepshun-mesh-test-')
        self.world = checks.world(self.tmp.name)

    def tearDown(self):
        self.world.render.removeNode()
        self.tmp.cleanup()

    def assert_surface_matches(self, key):
        """Compare every float, triangle index, style and collider visibility.

        The reference enumerates all six faces of every logical block instead
        of using the optimized interior shortcut or quad writer.
        """
        w = self.world
        expected = {}
        stashed = {}
        for c in w.chunk_contents.get(key, ()):
            if c.isHidden():
                stashed[c] = c.isStashed()
                continue
            p = c.getPos()
            x, y, z = w.get_grid_key(p)
            visible = []
            for normal, corners in w.FACE_DATA:
                neighbor = w.cube_map.get(tuple(a+b for a,b in zip((x,y,z), normal)))
                if neighbor is None or neighbor.isHidden():
                    visible.append((normal, corners))
            stashed[c] = not visible
            if not visible:
                continue
            tint = c.getPythonTag('selection_color') if c.hasPythonTag('selection_color') else None
            appearance = (c.getTag('material'), tuple(c.getColor()), tuple(c.getColorScale()),
                          c == w.active_checkpoint_cube, tint)
            vertices, indices, owner = expected.setdefault(appearance, (array('f'), array('I'), c))
            for normal, corners in visible:
                first = len(vertices)//8
                for offset, uv in zip(corners, ((0,0), (1,0), (1,1), (0,1))):
                    vertices.extend((*[a+b for a,b in zip(p, offset)], *normal, *uv))
                indices.extend(first+i for i in (0,1,2,0,2,3))

        before = w.serialize_records()
        w.rebuild_chunk(key)
        self.assertEqual(w.serialize_records(), before)
        for c, value in stashed.items():
            self.assertEqual(c.isStashed(), value)
        if not expected:
            self.assertNotIn(key, w.chunks_visual)
            return
        node = w.chunks_visual[key].node()
        self.assertEqual(node.getNumGeoms(), len(expected))
        for i, (vertices, indices, owner) in enumerate(expected.values()):
            geom = node.getGeom(i)
            self.assertEqual(geom.getVertexData().getArray(0).getHandle().getData(), vertices.tobytes())
            self.assertEqual(geom.getPrimitive(0).getVertices().getHandle().getData(), indices.tobytes())
            style = checks.NP('reference-style')
            w.style_face(style, owner)
            style.setColorScale(owner.getColorScale())
            self.assertEqual(node.getGeomState(i), style.getState())

    def test_dense_mixed_materials_keep_every_vertex_and_style(self):
        w = self.world
        for x in range(13, 19):
            for y in range(-3, 3):
                for z in range(-2, 4):
                    c = checks.cube(w, (x,y,z+.5), str(1+(x+y+z)%5))
                    c.setColor((x%3)/2, (y%3)/2, (z%3)/2, 1)
                    if (x+y+z)%7 == 0:
                        c.setColorScale(.5,.75,.9,1)
                    if (x+y+z)%11 == 0:
                        c.setPythonTag('selection_color', (.2,.4,.8,1))
        w.active_checkpoint_cube = next(c for c in w.cubes if c.getTag('material') == '4')
        for key in tuple(w.chunk_contents):
            self.assert_surface_matches(key)
            self.assert_surface_matches(key)  # Existing stashed interiors remain correct.
        self.assertTrue(any(c.isStashed() for c in w.cubes))

    def test_hidden_off_grid_and_negative_chunk_neighbors(self):
        w = self.world
        positions = [(-17.3,-1.2,.2), (-16.3,-1.2,.2), (-15.3,-1.2,.2),
                     (-.49,.49,.5), (.51,.49,.5), (1.51,.49,.5),
                     (15.49,15.49,.5), (16.49,15.49,.5), (16.49,16.49,.5)]
        nodes = [checks.cube(w, p, '3' if i%2 else '4') for i,p in enumerate(positions)]
        nodes[1].hide()
        nodes[4].stash()
        for key in tuple(w.chunk_contents):
            self.assert_surface_matches(key)
        nodes[1].show()
        nodes[4].hide()
        for key in tuple(w.chunk_contents):
            self.assert_surface_matches(key)

    def test_neighbor_delete_move_and_conversion_reveal_the_same_faces(self):
        w = self.world
        for x in range(14,18):
            for y in range(3):
                for z in range(3):
                    checks.cube(w, (x,y,z+.5))
        for key in tuple(w.chunk_contents):
            self.assert_surface_matches(key)
        c = w.cube_map[(15,1,2)]
        w.remove_block(c)
        c = w.cube_map[(16,1,2)]
        w.convert_to_mover(c, dict(origin=c.getPos(), waypoints=[], speed=3., current_idx=0, direction=1))
        c = w.cube_map.pop((14,1,2))
        w.unregister_cube(c)
        c.setPos(-16.25,-.25,.5)
        w.cube_map[w.get_grid_key(c.getPos())] = c
        w.register_cube(c)
        for key in tuple(w.chunk_contents):
            self.assert_surface_matches(key)
        for c in tuple(w.cubes):
            w.remove_block(c)
        for key in tuple(w.chunks_visual):
            self.assert_surface_matches(key)

    def test_tall_checkpoint_column_updates_only_nearby_vertical_slices(self):
        w = self.world
        nodes = [checks.cube(w, (1,1,z+.5), '4') for z in range(1000)]
        w.active_checkpoint_cube = nodes[8]
        w.update_chunks()
        self.assertEqual(len(w.chunk_contents), 63)
        self.assertLessEqual(max(map(len, w.chunk_contents.values())), 16)
        middle = w.get_chunk_key(nodes[400].getPos())
        unchanged = w.chunks_visual[middle]
        old = w.active_checkpoint_cube
        w.active_checkpoint_cube = nodes[-8]
        w.update_cube_faces(old)
        w.update_cube_faces(w.active_checkpoint_cube)
        self.assertLessEqual(len(w.dirty_chunks), 4)
        self.assertNotIn(middle, w.dirty_chunks)
        affected = tuple(w.dirty_chunks)
        w.update_chunks()
        self.assertEqual(w.chunks_visual[middle], unchanged)
        self.assertFalse(unchanged.isEmpty())
        for key in affected: self.assert_surface_matches(key)
        checks.cube(w, (1,1,1000.5), '4')
        self.assertLessEqual(len(w.dirty_chunks), 2)
        w.update_chunks()
        self.assertEqual(w.chunks_visual[middle], unchanged)

    def test_vertical_chunk_boundaries_keep_faces_and_dirty_both_sides(self):
        w = self.world
        for bottom in (-16.5, -.5, 15.5):
            nodes = [checks.cube(w, (5,5,bottom+i), '4') for i in range(2)]
            w.update_chunks()
            keys = [w.get_chunk_key(n.getPos()) for n in nodes]
            self.assertNotEqual(keys[0], keys[1])
            for key in keys: self.assert_surface_matches(key)
            w.remove_block(nodes[0])
            self.assertIn(keys[1], w.dirty_chunks)
            w.update_chunks()
            self.assert_surface_matches(keys[1])
            w.remove_block(nodes[1])
            w.update_chunks()

    def test_off_grid_neighbours_dirty_their_actual_vertical_chunks(self):
        w = self.world
        # Rounded occupancy neighbours can span physical chunks even when the
        # removed centre is more than one unit from the chunk boundary.
        lower = checks.cube(w, (2,2,14.9))
        upper = checks.cube(w, (2,2,16.49))
        w.update_chunks()
        lower_key, upper_key = (w.get_chunk_key(n.getPos()) for n in (lower,upper))
        self.assertNotEqual(lower_key, upper_key)
        w.remove_block(lower)
        self.assertIn(upper_key, w.dirty_chunks)
        w.update_chunks()
        self.assert_surface_matches(upper_key)

    def test_chunk_invalidation_matches_logical_neighbours_for_off_grid_centres(self):
        w = self.world
        rng = random.Random(713)
        records = []
        for base in (-16,0,8,16):
            for x in range(base-2,base+3):
                for y in range(base-2,base+3):
                    for z in range(base-2,base+3):
                        pos = checks.V(x+rng.uniform(-.49,.49), y+rng.uniform(-.49,.49), z+rng.uniform(-.49,.49))
                        node = checks.cube(w,pos)
                        records.append((node,w.get_grid_key(pos)))
        # An independent all-block scan catches missed physical chunks near
        # boundaries, including neighbours whose off-grid centres cross a side.
        for node, coords in records:
            expected = {w.get_chunk_key(node.getPos())}
            for other, other_coords in records:
                if sum(abs(a-b) for a,b in zip(coords,other_coords)) == 1:
                    expected.add(w.get_chunk_key(other.getPos()))
            w.dirty_chunks.clear()
            w.request_chunk_update(node.getPos())
            self.assertEqual(w.dirty_chunks, expected)


class GlowAndMoverSearchTests(unittest.TestCase):
    def test_tall_checkpoint_column_glow_keeps_nearest_sources_across_slices(self):
        with tempfile.TemporaryDirectory(prefix='disepshun-tall-glow-') as tmp:
            w = checks.world(tmp)
            self.addCleanup(w.render.removeNode)
            for z in range(1000): checks.cube(w, (0,0,z+.5), '4')
            checks.mover(w, (1,0,16.5), '3')
            for height in (0, 15.5, 16, 511.99, 999.5, 10001):
                camera = checks.V(0,-2,height)
                expected = [c for c in w.all_blocks()
                            if (c.getPos(w.render)-camera).lengthSquared() < 225]
                expected.sort(key=lambda c: (c.getPos(w.render)-camera).lengthSquared())
                w.next_glow_scan = 0
                w.update_glow_lights(camera, now=0)
                self.assertEqual(w.glow_sources, expected[:len(w.glow_lights)])

    def test_dense_glow_ranking_keeps_distance_and_map_order_ties(self):
        with tempfile.TemporaryDirectory(prefix='disepshun-glow-test-') as tmp:
            w = checks.world(tmp)
            self.addCleanup(w.render.removeNode)
            for x in range(-8, 8):
                for y in range(-8, 8):
                    for z in range(-8, 8):
                        checks.cube(w, (x, y, z+.5), '3' if (x+y+z)%2 else '4')
            # Movers may share positions with statics; equal distances retain
            # static map order first, followed by mover map order.
            for pos in ((0,0,.5), (0,0,-.5), (1,0,.5), (-1,0,.5)):
                checks.mover(w, pos, '4')
            lights = w.glow_lights
            for camera in (checks.V(0,0,0), checks.V(-1.4,2.1,.8), checks.V(40,40,40)):
                ordered = [c for c in w.all_blocks()
                           if (c.getPos(w.render)-camera).lengthSquared() < 225]
                ordered.sort(key=lambda c: (c.getPos(w.render)-camera).lengthSquared())
                for budget in (0, 1, 4):
                    w.glow_lights = lights[:budget]
                    w.next_glow_scan = 0
                    w.update_glow_lights(camera, now=0)
                    self.assertEqual(w.glow_sources, ordered[:budget])
            # Fewer eligible sources than light slots still returns all sources.
            w.glow_lights = lights
            w.next_glow_scan = 0
            camera = checks.V(21.99, 7, 7.5)
            ordered = [c for c in w.all_blocks()
                       if (c.getPos(w.render)-camera).lengthSquared() < 225]
            ordered.sort(key=lambda c: (c.getPos(w.render)-camera).lengthSquared())
            self.assertGreater(len(ordered), 0)
            self.assertLess(len(ordered), len(lights))
            w.update_glow_lights(camera, now=0)
            self.assertEqual(w.glow_sources, ordered)

    def test_empty_mover_search_stays_empty_across_index_and_edit_states(self):
        with tempfile.TemporaryDirectory(prefix='disepshun-mover-test-') as tmp:
            w = checks.world(tmp)
            self.addCleanup(w.render.removeNode)
            bounds = (-.2, .2, -.2, .2, 0, 1.67)
            self.assertEqual(w.movers_near(*bounds), [])
            w.index_movers()
            self.assertEqual(w.movers_near(*bounds), [])
            moving = checks.mover(w)['np']
            w.index_movers()
            self.assertEqual(w.movers_near(*bounds), [(moving, moving.getPos(w.render))])
            w.remove_block(moving)
            self.assertEqual(w.movers_near(*bounds), [])
            w.index_movers()
            self.assertEqual(w.movers_near(*bounds), [])

    def test_small_mover_counts_match_exhaustive_contacts_across_index_threshold(self):
        with tempfile.TemporaryDirectory(prefix='disepshun-small-movers-') as tmp:
            w = checks.world(tmp)
            self.addCleanup(w.render.removeNode)
            p = checks.physics(w)
            rng = random.Random(511)
            nodes = []
            for count in range(1, 7):
                nodes.append(checks.mover(w, (count*1.25, .1*count, .5))['np'])
                w.index_movers()
                for i in range(80):
                    pos = checks.V(rng.uniform(0,9), rng.uniform(-.7,1), rng.uniform(-1,2))
                    height = (.9,1.67)[i%2]
                    ignored = nodes[:2] if i%3 else ()
                    expected = []
                    for node in nodes:
                        cp = node.getPos(w.render)
                        if (node not in ignored and pos.x-.2 < cp.x+.5 and pos.x+.2 > cp.x-.5 and
                                pos.y-.2 < cp.y+.5 and pos.y+.2 > cp.y-.5 and
                                pos.z < cp.z+.5 and pos.z+height > cp.z-.5):
                            expected.append(node)
                    self.assertEqual(p.get_contacts(pos,height,ignored), (False,expected))
            # Edits invalidate the old index while crossing back to the scan path.
            for node in nodes[4:]: w.remove_block(node)
            self.assertEqual([node for node,_ in w.movers_near(0,9,-1,2,-1,3)], nodes[:4])


class ColliderEditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='disepshun-collider-test-')
        self.addCleanup(self.tmp.cleanup)
        self.world = checks.world(self.tmp.name)
        self.addCleanup(self.world.render.removeNode)

    def solid_region(self):
        for x in range(3):
            for y in range(5):
                for z in range(3): checks.cube(self.world, (x,y,z+.5))
        self.world.update_chunks()
        return self.world.cube_map[(1,0,2)], self.world.cube_map[(1,1,2)]

    def pick(self, origin, direction=(0,1,0)):
        root = self.world.render
        node = checks.core.CollisionNode('collider-edit-probe')
        node.addSolid(checks.core.CollisionRay(*origin, *direction))
        node.setFromCollideMask(checks.core.BitMask32(1))
        node.setIntoCollideMask(checks.core.BitMask32.allOff())
        probe = root.attachNewNode(node)
        traverser = checks.core.CollisionTraverser()
        queue = checks.core.CollisionHandlerQueue()
        traverser.addCollider(probe, queue)
        traverser.traverse(root)
        queue.sortEntries()
        result = queue.getEntry(0).getIntoNodePath().getParent() if queue.getNumEntries() else None
        probe.removeNode()
        return result

    def test_deleting_surface_exposes_inner_collider_before_mesh_rebuild(self):
        front, inner = self.solid_region()
        self.assertTrue(inner.isStashed())
        self.assertEqual(self.pick((1,-3,1.5)), front)
        self.world.remove_block(front)
        self.assertTrue(self.world.dirty_chunks)
        self.assertFalse(inner.isStashed())
        self.assertEqual(self.pick((1,-3,1.5)), inner)

    def test_deletion_exposes_inner_collider_in_neighboring_chunk(self):
        w = self.world
        for x in range(14,17):
            for y in range(3):
                for z in range(3): checks.cube(w, (x,y,z+.5))
        w.update_chunks()
        front, inner = w.cube_map[(16,1,2)], w.cube_map[(15,1,2)]
        self.assertNotEqual(w.get_chunk_key(front.getPos()), w.get_chunk_key(inner.getPos()))
        self.assertTrue(inner.isStashed())
        self.assertEqual(self.pick((20,1,1.5), (-1,0,0)), front)
        w.remove_block(front)
        self.assertEqual(self.pick((20,1,1.5), (-1,0,0)), inner)

    def test_transforming_enclosed_block_keeps_its_collider_live(self):
        _, inner = self.solid_region()
        w = self.world
        self.assertTrue(inner.isStashed())
        w.unregister_cube(inner)
        del w.cube_map[w.get_grid_key(inner.getPos())]
        w.request_chunk_update(inner.getPos())
        inner.setPos(20,0,1.5)
        w.cube_map[w.get_grid_key(inner.getPos())] = inner
        w.register_cube(inner)
        w.request_chunk_update(inner.getPos())
        self.assertTrue(w.dirty_chunks)
        self.assertFalse(inner.isStashed())
        self.assertEqual(self.pick((20,-3,1.5)), inner)

    def test_converting_surface_to_mover_exposes_next_collider_immediately(self):
        front, inner = self.solid_region()
        self.world.convert_to_mover(front, dict(origin=front.getPos(), waypoints=[],
                                              speed=3., current_idx=0, direction=1))
        front.setPos(20,0,1.5)
        self.assertFalse(inner.isStashed())
        self.assertEqual(self.pick((1,-3,1.5)), inner)
        self.assertEqual(self.pick((20,-3,1.5)), front)

    def test_pooled_mover_reuse_retains_one_clean_cube_collider(self):
        w = self.world
        moving = checks.mover(w, material='5')['np']
        moving.setPythonTag('selection_color', (1,0,1,1))
        moving.setPythonTag('history_id', 'old')
        moving.setTag('group', 'old-group')
        moving.setTag('heading', '90')
        moving.setTag('bounciness', '2')
        moving.setTag('max_height', '5')
        self.assertFalse(moving.find('face_geom').isEmpty())
        self.assertTrue(w.remove_block(moving))
        node = w.get_cube('reused')
        self.assertEqual(node, moving)
        self.assertEqual(node.getNumChildren(), 1)
        collider = node.find('coll')
        self.assertFalse(collider.isEmpty())
        self.assertEqual(collider.node().getNumSolids(), 1)
        self.assertEqual(collider.node().getIntoCollideMask(), checks.core.BitMask32(1))
        self.assertFalse(node.hasPythonTag('selection_color'))
        self.assertFalse(node.hasPythonTag('history_id'))
        for tag in ('group','heading','bounciness','max_height','material'):
            self.assertFalse(node.getTag(tag))
        self.assertEqual(node.getPos(), checks.V(0,0,0))
        node.setPos(0,0,.5); node.setTag('material', '1')
        w.cubes.append(node); w.cube_map[w.get_grid_key(node.getPos())] = node
        w.register_cube(node)
        self.assertEqual(self.pick((0,-3,.5)), node)
        p = checks.physics(w)
        self.assertEqual(p.get_contacts(checks.V(0,0,.9),1.67), (False,[node]))
        self.assertEqual(p.get_contacts(checks.V(1,0,.9),1.67), (False,[]))


if __name__ == '__main__':
    unittest.main()
