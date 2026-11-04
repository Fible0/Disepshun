"""Bounded, object-level editor history; scene nodes are never stored in entries."""
from panda3d.core import VBase3


class EditHistory:
    def __init__(self, world, limit=100):
        self.world = world
        self.limit = limit
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
                    wait_timer=motion.get('wait_timer', 0), loop=motion.get('loop',False))
            result[self.identity(node)] = state
        return result

    def begin(self, nodes):
        return self.capture(nodes), self.identity(self.world.active_checkpoint_cube)

    def finish(self, token, nodes, label):
        before, checkpoint_before = token
        after = self.capture(nodes)
        checkpoint_after = self.identity(self.world.active_checkpoint_cube)
        if before == after and checkpoint_before == checkpoint_after:
            return False
        self.undo_stack.append((before, after, checkpoint_before, checkpoint_after, label))
        del self.undo_stack[:-self.limit]
        self.redo_stack.clear()
        return True

    def _restore(self, entry, undo):
        before, after, cp_before, cp_after, _ = entry
        states = before if undo else after
        affected = before.keys() | after.keys()
        current_cp = self.identity(self.world.active_checkpoint_cube)
        live = {self.identity(c): c for c in self.world.all_blocks()}
        for identity in affected:
            if identity in live:
                self.world.remove_block(live[identity])
        for identity, state in states.items():
            node = self.world._make_block(dict(pos=VBase3(*state['pos']), mat=state['mat'],
                bounce=float(state['bounce'] or 1.3), max_h=float(state['max_h'] or 0)))
            node.setColor(*state['color'])
            node.setPythonTag('history_id', identity)
            for tag, value in (('group', state['group']), ('heading', state['heading']),
                               ('bounciness', state['bounce']), ('max_height', state['max_h'])):
                if value: node.setTag(tag,value)
                else: node.clearTag(tag)
            motion = state['motion']
            if motion is not None:
                restored = dict(motion, origin=VBase3(*motion['origin']),
                    waypoints=[VBase3(*p) for p in motion['waypoints']])
                self.world.convert_to_mover(node, restored)
            else:
                self.world.cubes.append(node)
                self.world.cube_map[self.world.get_grid_key(node.getPos())] = node
                self.world.register_cube(node)
                self.world.request_chunk_update(node.getPos())
        live = {self.identity(c): c for c in self.world.all_blocks()}
        desired_cp = cp_before if undo else cp_after
        # Restore edited/deleted checkpoints, without rolling back unrelated gameplay progress.
        if current_cp in affected or (current_cp is None and desired_cp in affected):
            active = live.get(desired_cp)
        else:
            active = live.get(current_cp)
        self.world.active_checkpoint_cube = active
        self.world.saved_checkpoint_pos = active.getPos() if active is not None else None
        restyle=set(affected)
        active_id=self.identity(active)
        if active_id!=current_cp: restyle.update((current_cp,active_id))
        for identity in restyle:
            node=live.get(identity)
            if node is not None and node.getTag('material')=='4': self.world.update_cube_faces(node)
        self.world.next_glow_scan = 0
        self.world.queue_save()

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
