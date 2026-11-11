"""Bounded, object-level editor history; scene nodes are never stored in entries."""
from panda3d.core import VBase3


class EditHistory:
    def __init__(self, world, limit=100, max_states=100_000):
        self.world = world
        self.limit = limit
        # Each captured block state costs roughly 0.7 KB, so this keeps history near 70 MB at most.
        self.max_states = max_states
        self.next_id = 1
        self.undo_stack = []
        self.redo_stack = []

    def identity(self, node):
        if node is None or node.isEmpty():
            return None
        if not node.hasPythonTag('history_id'):
            node.setPythonTag('history_id', self.next_id)
            self.next_id += 1
        return node.getPythonTag('history_id')

    def capture(self, nodes):
        result = {}
        for node in nodes:
            motion = self.world.find_mover(node)
            state = dict(pos=tuple(node.getPos()), color=tuple(node.getColor()),
                         mat=int(node.getTag('material')), group=node.getTag('group'),
                         heading=node.getTag('heading'), bounce=node.getTag('bounciness'),
                         max_h=node.getTag('max_height'), motion=None)
            if motion is not None:
                state['motion'] = dict(origin=tuple(motion['origin']),
                    waypoints=tuple(tuple(p) for p in motion['waypoints']), speed=motion['speed'],
                    current_idx=motion['current_idx'], direction=motion.get('direction', 1),
                    loop=motion.get('loop',False))
            result[self.identity(node)] = state
        return result

    def begin(self, nodes):
        return self.capture(nodes), self.identity(self.world.active_checkpoint_cube)

    @staticmethod
    def entry_size(entry):
        return len(entry[0]) + len(entry[1])

    def finish(self, token, nodes, label):
        before, checkpoint_before = token
        after = self.capture(nodes)
        checkpoint_after = self.identity(self.world.active_checkpoint_cube)
        if before == after and checkpoint_before == checkpoint_after:
            return False
        self.redo_stack.clear()
        self.undo_stack.append((before, after, checkpoint_before, checkpoint_after, label))
        # Bound by entry count and by captured blocks, always keeping the newest entry.
        total = sum(self.entry_size(e) for e in self.undo_stack)
        drop = 0
        while len(self.undo_stack) - drop > 1 and (len(self.undo_stack) - drop > self.limit or total > self.max_states):
            total -= self.entry_size(self.undo_stack[drop]); drop += 1
        del self.undo_stack[:drop]
        return True

    @staticmethod
    def _motion(motion):
        return dict(motion, origin=VBase3(*motion['origin']), waypoints=[VBase3(*p) for p in motion['waypoints']])

    def _apply_tags(self, node, state):
        node.setTag('material', str(state['mat']))
        node.setColor(*state['color'])
        for tag, value in (('group', state['group']), ('heading', state['heading']),
                           ('bounciness', state['bounce']), ('max_height', state['max_h'])):
            if value: node.setTag(tag,value)
            else: node.clearTag(tag)

    def _restore(self, entry, undo):
        before, after, cp_before, cp_after, _ = entry
        world = self.world
        states = before if undo else after
        affected = before.keys() | after.keys()
        current_cp = self.identity(world.active_checkpoint_cube)
        live = {c.getPythonTag('history_id'): c for c in world.all_blocks() if c.hasPythonTag('history_id')}

        # Patch surviving blocks in place; only deletions, creations and mover-to-static changes rebuild nodes.
        patched = []; patched_ids = set()
        for identity in affected:
            node = live.get(identity)
            if node is None: continue
            state = states.get(identity)
            mover = world.find_mover(node)
            if state is None or (mover is not None and state['motion'] is None):
                world.remove_block(node)
            else:
                patched.append((node, state, mover)); patched_ids.add(identity)
        # Lift patched static blocks out of the grid first, so moved blocks never collide with stale entries.
        for node, _, mover in patched:
            if mover is not None: continue
            key = world.get_grid_key(node.getPos())
            if world.cube_map.get(key) == node: del world.cube_map[key]
            world.unregister_cube(node); world.request_chunk_update(node.getPos())
        for node, state, mover in patched:
            node.setPos(VBase3(*state['pos']))
            self._apply_tags(node, state)
            motion = state['motion']
            if motion is None:
                world.cube_map[world.get_grid_key(node.getPos())] = node
                world.register_cube(node); world.request_chunk_update(node.getPos())
            elif mover is not None:
                mover.update(self._motion(motion))
                world.update_cube_faces(node)
            else:
                world.convert_to_mover(node, self._motion(motion))

        for identity, state in states.items():
            if identity in patched_ids: continue
            node = world._make_block(dict(pos=VBase3(*state['pos']), mat=state['mat'],
                bounce=float(state['bounce'] or 1.3), max_h=float(state['max_h'] or 0)))
            node.setPythonTag('history_id', identity)
            self._apply_tags(node, state)
            if state['motion'] is not None:
                world.convert_to_mover(node, self._motion(state['motion']))
            else:
                world.cubes.append(node)
                world.cube_map[world.get_grid_key(node.getPos())] = node
                world.register_cube(node)
                world.request_chunk_update(node.getPos())
        world.touch()
        live = {c.getPythonTag('history_id'): c for c in world.all_blocks() if c.hasPythonTag('history_id')}
        desired_cp = cp_before if undo else cp_after
        # Restore edited/deleted checkpoints, without rolling back unrelated gameplay progress.
        if current_cp in affected or (current_cp is None and desired_cp in affected):
            active = live.get(desired_cp)
        else:
            active = live.get(current_cp)
        world.active_checkpoint_cube = active
        world.saved_checkpoint_pos = active.getPos() if active is not None else None
        restyle=set(affected)
        active_id=self.identity(active)
        if active_id!=current_cp: restyle.update((current_cp,active_id))
        for identity in restyle:
            node=live.get(identity)
            if node is not None and node.getTag('material')=='4': world.update_cube_faces(node)
        world.next_glow_scan = 0
        world.queue_save()

    def undo(self):
        if not self.undo_stack:
            return False
        entry = self.undo_stack.pop()
        self._restore(entry, True)
        self.redo_stack.append(entry)
        return True

    def redo(self):
        if not self.redo_stack:
            return False
        entry = self.redo_stack.pop()
        self._restore(entry, False)
        self.undo_stack.append(entry)
        return True
