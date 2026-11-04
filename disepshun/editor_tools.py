"""Batch editor operations. Logical blocks retain their colliders and mover paths."""
import uuid
import math
from panda3d.core import VBase3, GeomVertexData, GeomVertexFormat, GeomVertexWriter, GeomTriangles, Geom, GeomNode, NodePath, CardMaker


class EditorTools:
    TOOL_SLOTS = (7, 8, 9, 10, 11, 12)
    TOOL_NAMES = {7: 'Waypoint', 8: 'Trampoline', 9: 'Checkpoint', 10: 'Grouping', 11: 'Selection', 12: 'Fill'}

    SELECTION_COLORS = {7:(.8,.2,1,1), 8:(1,.72,.1,1), 9:(.1,.8,1,1),
                        10:(.35,1,.2,1), 11:(1,.25,.6,1), 12:(1,.85,.35,1)}

    COMBINED_TOOLS = (8, 9, 10, 12)

    def selecting(self):
        return self.tool_mode in self.COMBINED_TOOLS or (self.tool_mode in self.TOOL_SLOTS and self.tool_phases[self.tool_mode] == 'select')

    def tinkering(self):
        return not self.input_blocked() and self.tool_mode in self.TOOL_SLOTS and (self.tool_mode in self.COMBINED_TOOLS or self.tool_phases[self.tool_mode] == 'tinker')

    def toggle_tool_phase(self):
        if self.input_blocked() or self.tool_mode not in self.TOOL_SLOTS or self.tool_mode in self.COMBINED_TOOLS: return
        phase = 'tinker' if self.selecting() else 'select'
        self.tool_phases[self.tool_mode] = phase
        # A click held while switching modes must not turn into an edit.
        for key in ('mouse1','mouse3','minus','plus','z','x'):
            self.keyMap[key] = False; self.timers[key] = 0
        self.play_sfx('mode_' + phase)
        self.update_hud()

    def ensure_selected_movers(self):
        if not self.tinkering() or self.tool_mode != 7: return
        if not self.selected_objects: return
        self.selected_movers = [m for c in self.selected_objects for m in [self.world.find_mover(c)] if m]
        for c in self.selected_objects:
            if self.world.find_mover(c): continue
            ref = self.selected_movers[0] if self.selected_movers else None
            waypoints = [c.getPos()+(w-ref['origin']) for w in ref['waypoints']] if ref else []
            m = self.world.convert_to_mover(c, dict(waypoints=waypoints, speed=ref['speed'] if ref else 3.0,
                current_idx=0, wait_timer=0, origin=c.getPos(), direction=1, loop=ref.get('loop',False) if ref else False))
            self.selected_movers.append(m)

    def editor_notice(self, text):
        self.ui.fly_text.setText(text)
        self.ui.fly_text.show()
        self.ui.fly_text.setAlphaScale(1)
        self.fly_text_timer = 4

    def pick_object(self):
        self.cTrav.traverse(self.render)
        if not self.cHandler.getNumEntries(): return None
        self.cHandler.sortEntries()
        hit = self.cHandler.getEntry(0)
        node = hit.getIntoNodePath().getParent()
        return node if node.hasTag('material') and not node.getParent().isEmpty() else None

    def select_object(self):
        if self.input_blocked() or not self.selecting(): return
        node = self.pick_object()
        if node is None: return
        if self.tool_mode == 8 and node.getTag('material') != '5': return
        if self.tool_mode == 9 and node.getTag('material') != '4': return
        group = node.getTag('group')
        nodes = [c for c in self.world.all_blocks() if c.getTag('group') == group] if group else [node]
        if self.tool_mode in (8,9):
            nodes=[c for c in nodes if c.getTag('material')==('5' if self.tool_mode==8 else '4')]
        if self.tool_mode==11 and group: nodes=[c for c in nodes if c!=node]+[node]
        removing = node in self.selected_objects
        if removing:
            self.selected_objects = [c for c in self.selected_objects if c not in nodes]
        else:
            self.selected_objects.extend(c for c in nodes if c not in self.selected_objects)
        if self.tool_mode == 8:
            self.selected_trampolines = list(self.selected_objects)
            self.cur_bounce = float(node.getTag('bounciness') or 1.3)
            self.cur_h = float(node.getTag('max_height') or 0)
        if self.tool_mode == 7:
            self.selected_movers = [m for c in self.selected_objects for m in [self.world.find_mover(c)] if m]
            self.draw_wp()
        self.refresh_object_selection()
        self.play_sfx('object_deselect' if removing else 'object_select')
        self.update_hud()

    def refresh_object_selection(self):
        if not self.selected_objects and not getattr(self,'highlighted_objects',None): return
        self.selected_objects = [c for c in self.selected_objects if not c.isEmpty() and not c.getParent().isEmpty()]
        current = set(self.selected_objects)
        previous = getattr(self, 'highlighted_objects', set())
        color = self.SELECTION_COLORS.get(self.tool_mode)
        for c in current | previous:
            if c.isEmpty() or c.getParent().isEmpty(): continue
            wanted = color if c in current else None
            old = c.getPythonTag('selection_color') if c.hasPythonTag('selection_color') else None
            if old == wanted: continue
            c.clearColorScale()
            if wanted is not None: c.setPythonTag('selection_color', wanted)
            else: c.clearPythonTag('selection_color')
            self.world.update_cube_faces(c)
        self.highlighted_objects = current

    @staticmethod
    def make_checkpoint_arrow():
        data = GeomVertexData('checkpoint_arrow', GeomVertexFormat.getV3c4(), Geom.UHStatic)
        positions = GeomVertexWriter(data, 'vertex'); colors = GeomVertexWriter(data, 'color')
        triangles = GeomTriangles(Geom.UHStatic)
        count = 0
        # A solid shaft and head, with thickness so it stays visible from low angles.
        for polygon in ([(-.11,0),(.11,0),(.11,1.05),(-.11,1.05)],
                        [(-.43,1.05),(.43,1.05),(0,1.85)]):
            size = len(polygon)
            for z in (-.035,.035):
                for x,y in polygon:
                    positions.addData3(x,y,z)
                    colors.addData4(1,.95,.35,.5) if z>0 else colors.addData4(.9,.4,.02,.5)
            for i in range(1,size-1):
                triangles.addVertices(count,count+i+1,count+i)
                triangles.addVertices(count+size,count+size+i,count+size+i+1)
            for i in range(size):
                j=(i+1)%size
                triangles.addVertices(count+i,count+j,count+size+j)
                triangles.addVertices(count+i,count+size+j,count+size+i)
            count += 2*size
        geom=Geom(data); geom.addPrimitive(triangles)
        node=GeomNode('checkpoint_arrow_mesh'); node.addGeom(geom)
        arrow=NodePath(node); arrow.setTwoSided(True)
        return arrow

    def draw_checkpoint_direction(self):
        checkpoints = ([c for c in self.selected_objects if not c.isEmpty() and c.getTag('material')=='4']
                       if self.tool_mode==9 else [])
        if not checkpoints:
            if self.selection_node is not None: self.selection_node.removeNode()
            self.selection_node=None; self.checkpoint_markers={}
            return
        if not hasattr(self,'checkpoint_arrow_template'): self.checkpoint_arrow_template=self.make_checkpoint_arrow()
        if self.selection_node is None:
            self.selection_node=self.render.attachNewNode('checkpoint_directions')
            self.selection_node.setLightOff(); self.selection_node.setShaderOff()
            self.selection_node.setDepthTest(False); self.selection_node.setDepthWrite(False); self.selection_node.setBin('fixed',20)
            self.checkpoint_markers={}
        markers=self.checkpoint_markers
        for c in set(markers)-set(checkpoints): markers.pop(c).removeNode()
        camera=getattr(self,'camera',self.physics.camera)
        for c in checkpoints:
            if c not in markers:
                marker=self.selection_node.attachNewNode('checkpoint_facing')
                outline=marker.attachNewNode('arrow_outline')
                outline.setScale(1.2,1.07,1.6); outline.setColorScale(0,0,0,1); outline.setBin('fixed',19)
                self.checkpoint_arrow_template.instanceTo(outline)
                fill=marker.attachNewNode('arrow_fill'); fill.setBin('fixed',20)
                self.checkpoint_arrow_template.instanceTo(fill); markers[c]=marker
            marker=markers[c]; pos=c.getPos(self.render)
            marker.setPos(pos+VBase3(0,0,.95))
            distance=(camera.getPos(self.render)-pos).length()
            marker.setScale(max(1.0,min(3.0,distance/10))); marker.setH(float(c.getTag('heading') or 0)%360)

    def reference_point(self, positions, grid_z=False):
        center=sum((VBase3(p) for p in positions),VBase3(0,0,0))/len(positions)
        off_grid=abs(center.x-round(center.x))>.01 or abs(center.y-round(center.y))>.01
        if grid_z: off_grid=off_grid or abs(center.z-.5-round(center.z-.5))>.01
        if self.saved_settings.get('Use Last Selected as Pivot',False) or off_grid: return VBase3(positions[-1])
        return center

    @staticmethod
    def make_center_marker(parent,name,color):
        card=CardMaker(name); card.setFrame(-.1,.1,-.1,.1)
        marker=parent.attachNewNode(card.generate()); marker.setColor(*color)
        marker.setBillboardPointEye(); marker.setLightOff(); marker.setShaderOff()
        marker.setDepthTest(False); marker.setDepthWrite(False); marker.setBin('fixed',25)
        return marker

    def draw_selection_center(self):
        marker=getattr(self,'selection_center_node',None)
        if self.tool_mode!=11 or not self.selected_objects:
            if marker is not None: marker.hide()
            return
        if marker is None:
            marker=self.make_center_marker(self.render,'selection_center_pivot',(0,1,1,.5))
            self.selection_center_node=marker
        # One waypoint-style marker represents both the center and active pivot.
        self.selection_pivot_node=marker
        positions=[c.getPos(self.render) for c in self.selected_objects]
        pivot=self.reference_point(positions,grid_z=any(not self.world.find_mover(c) for c in self.selected_objects))
        marker.setPos(pivot); marker.show()

    def begin_edit(self, nodes):
        if not hasattr(self,'edit_history'):
            from disepshun.edit_history import EditHistory
            self.edit_history=EditHistory(self.world)
        return self.edit_history.begin(nodes)

    def finish_edit(self, token, nodes, label):
        return self.edit_history.finish(token,nodes,label)

    def expand_groups(self, nodes):
        nodes=list(dict.fromkeys(c for c in nodes if c is not None and not c.isEmpty()
                                 and c.hasTag('material') and not c.getParent().isEmpty()))
        groups={c.getTag('group') for c in nodes if c.getTag('group')}
        if groups:
            nodes=list(dict.fromkeys(nodes+[c for c in self.world.all_blocks() if c.getTag('group') in groups]))
        return nodes

    def delete_objects(self, nodes, label='delete'):
        nodes=self.expand_groups(nodes)
        if not nodes: return False
        token=self.begin_edit(nodes); removed=set(nodes)
        was_cp=self.world.active_checkpoint_cube in removed
        for c in nodes: self.world.remove_block(c)
        self.selected_objects=[c for c in self.selected_objects if c not in removed]
        self.selected_movers=[m for m in self.selected_movers if m['np'] not in removed]
        self.selected_trampolines=[c for c in self.selected_trampolines if c not in removed]
        if was_cp: self.physics.checkpoint=VBase3(0,0,1)
        self.refresh_object_selection(); self.draw_wp(); self.update_hud()
        self.finish_edit(token,[],label)
        return True

    def history_step(self, redo=False):
        if self.input_blocked() or not hasattr(self,'edit_history'): return False
        stack=self.edit_history.redo_stack if redo else self.edit_history.undo_stack
        if not stack: return False
        self.selected_objects=[]; self.refresh_object_selection()
        self.selected_movers=[]; self.selected_trampolines=[]; self.draw_wp()
        result=self.edit_history.redo() if redo else self.edit_history.undo()
        active=self.world.active_checkpoint_cube
        self.physics.checkpoint=active.getPos(self.render)+VBase3(0,0,1) if active is not None else VBase3(0,0,1)
        self.update_hud(); self.draw_checkpoint_direction(); self.draw_selection_center()
        if result: self.play_sfx('redo' if redo else 'undo')
        return result

    def commit_editor(self, sound, token=None, nodes=None, rate=None):
        if token is not None: self.finish_edit(token,self.selected_objects if nodes is None else nodes,sound)
        self.world.map_is_dirty = True
        self.world.save_map()
        if rate is None: self.play_sfx(sound)
        else: self.play_sfx(sound,rate)
        self.update_hud()

    def group_selection(self, ungroup=None):
        if self.input_blocked() or self.tool_mode != 10 or not self.selected_objects: return
        if ungroup is None:
            groups={c.getTag('group') for c in self.selected_objects}
            ungroup=len(groups)==1 and '' not in groups
        if not ungroup and len(set(self.selected_objects)) < 2: return
        token=self.begin_edit(self.selected_objects)
        group = uuid.uuid4().hex
        for c in self.selected_objects:
            if ungroup: c.clearTag('group')
            else: c.setTag('group', group)
        self.commit_editor('ungroup' if ungroup else 'group',token)

    def selection_command(self, command):
        if self.input_blocked() or self.tool_mode != 11: return
        if command in ('all','clear'):
            if not self.selecting(): return
            self.selected_objects = self.world.all_blocks() if command == 'all' else []
            self.refresh_object_selection(); self.play_sfx('selection_' + command); self.update_hud(); return
        if not self.tinkering(): return
        action = command
        if command in ('copy', 'cut'):
            if not self.selected_objects: return
            if command=='cut': self.selected_objects=self.expand_groups(self.selected_objects)
            self.clipboard = []
            self.clipboard_anchor = self.reference_point([c.getPos() for c in self.selected_objects], grid_z=any(not self.world.find_mover(c) for c in self.selected_objects))
            for c in self.selected_objects:
                m = self.world.find_mover(c)
                self.clipboard.append(dict(pos=VBase3(c.getPos()), mat=int(c.getTag('material')),
                    bounce=float(c.getTag('bounciness') or 1.3), max_h=float(c.getTag('max_height') or 0),
                    group=c.getTag('group'), heading=c.getTag('heading'),
                    mover=None if m is None else dict(origin=VBase3(m['origin']), speed=m['speed'], loop=m.get('loop',False),
                        waypoints=[VBase3(w) for w in m['waypoints']])))
            if command == 'copy': self.play_sfx('copy'); return
            command = 'delete'
        if command == 'delete':
            if not self.selected_objects: return
            if self.delete_objects(self.selected_objects,action): self.commit_editor(action)
        elif command == 'paste' and self.clipboard:
            anchor=self.reference_point([r['pos'] for r in self.clipboard],grid_z=any(r['mover'] is None for r in self.clipboard))
            delta = self.preview.getPos() - anchor
            positions = [r['pos'] + delta for r in self.clipboard]
            if not self.valid_positions(positions, []): return
            if not self.valid_static_grid([p for r,p in zip(self.clipboard, positions) if r['mover'] is None]): return
            paths = [p+delta for r in self.clipboard if r['mover'] for p in [r['mover']['origin']] + r['mover']['waypoints']]
            if not self.valid_paths(paths): return
            token=self.begin_edit([])
            groups = {}; nodes = []
            for rec, pos in zip(self.clipboard, positions):
                c = self.world._make_block(dict(rec, pos=pos))
                if rec['heading']: c.setTag('heading', rec['heading'])
                if rec['group']: c.setTag('group', groups.setdefault(rec['group'], uuid.uuid4().hex))
                m = rec['mover']
                if m:
                    self.world.convert_to_mover(c, dict(origin=m['origin']+delta, speed=m['speed'],
                        waypoints=[w+delta for w in m['waypoints']], current_idx=0, direction=1, wait_timer=0, loop=m.get('loop',False)))
                else:
                    self.world.cubes.append(c); self.world.cube_map[self.world.get_grid_key(pos)] = c
                    self.world.register_cube(c); self.world.request_chunk_update(pos)
                nodes.append(c)
            self.selected_objects = nodes; self.commit_editor('paste',token)

    def valid_positions(self, positions, ignored):
        ignored = set(ignored)
        # Nearby cells suffice for unit-cube overlap; avoid comparing every
        # selected block against the entire map and every earlier selection.
        occupied = {}
        for c in self.world.all_blocks():
            if c in ignored: continue
            q = c.getPos()
            key = tuple(math.floor(v) for v in q)
            occupied.setdefault(key, []).append(q)
        for p in positions:
            if any(not math.isfinite(v) or abs(v)>self.world.COORD_LIMIT for v in p) or p.z < -19.5:
                self.editor_notice('Objects must stay inside the map bounds'); return False
            x,y,z = (math.floor(v) for v in p)
            for cx in range(x-1,x+2):
                for cy in range(y-1,y+2):
                    for cz in range(z-1,z+2):
                        if any(abs(p.x-q.x)<.999 and abs(p.y-q.y)<.999 and abs(p.z-q.z)<.999
                               for q in occupied.get((cx,cy,cz), ())):
                            self.editor_notice('Edit blocked: objects would overlap'); return False
            occupied.setdefault((x,y,z), []).append(p)
        return True

    def valid_static_grid(self, positions):
        for p in positions:
            if abs(p.x-round(p.x))>.001 or abs(p.y-round(p.y))>.001 or abs((p.z-.5)-round(p.z-.5))>.001:
                self.editor_notice('Static blocks must stay on the grid'); return False
        return True

    def valid_paths(self, positions):
        if any(not math.isfinite(v) or abs(v)>self.world.COORD_LIMIT for p in positions for v in p):
            self.editor_notice('Edit blocked: a moving path would leave the map bounds'); return False
        return True

    def transform_selection(self, dx=0, dy=0, dz=0, rotate=False, to_cursor=False, rotate_axis='z'):
        if not self.tinkering() or self.tool_mode != 11 or not self.selected_objects: return
        pivot = self.reference_point([c.getPos() for c in self.selected_objects], grid_z=any(not self.world.find_mover(c) for c in self.selected_objects))
        delta = self.preview.getPos() - pivot if to_cursor else VBase3(dx,dy,dz)
        def transform(p):
            v = p-pivot
            if rotate:
                v = VBase3(v.x,-v.z,v.y) if rotate_axis=='x' else VBase3(-v.y,v.x,v.z)
            return pivot + v + delta
        positions = [transform(c.getPos()) for c in self.selected_objects]
        if not self.valid_positions(positions, self.selected_objects): return
        if not self.valid_static_grid([p for c,p in zip(self.selected_objects, positions) if not self.world.find_mover(c)]): return
        paths = [transform(p) for c in self.selected_objects for m in [self.world.find_mover(c)] if m for p in [m['origin']] + m['waypoints']]
        if not self.valid_paths(paths): return
        token=self.begin_edit(self.selected_objects)
        for c in self.selected_objects:
            if not self.world.find_mover(c):
                self.world.unregister_cube(c)
                self.world.cube_map.pop(self.world.get_grid_key(c.getPos()), None)
                self.world.request_chunk_update(c.getPos())
        for c, p in zip(self.selected_objects, positions):
            m = self.world.find_mover(c)
            if m:
                m['origin'] = transform(m['origin'])
                m['waypoints'] = [transform(w) for w in m['waypoints']]
            c.setPos(p)
            if rotate and rotate_axis=='z': c.setTag('heading', str((float(c.getTag('heading') or 0)+90)%360))
            if not m:
                self.world.cube_map[self.world.get_grid_key(p)] = c
                self.world.register_cube(c); self.world.request_chunk_update(p)
        self.commit_editor('rotate' if rotate else 'move',token)

    def adjust_checkpoint(self, direction):
        if not self.tinkering() or self.tool_mode != 9 or not self.selected_objects: return
        token=self.begin_edit(self.selected_objects)
        for c in self.selected_objects:
            c.setTag('heading', str((float(c.getTag('heading') or 0) + direction*15) % 360))
        self.commit_editor('checkpoint_turn',token,rate=1.12 if direction>0 else .88)

    def checkpoint_face_camera(self):
        if not self.tinkering() or self.tool_mode != 9 or not self.selected_objects: return
        token=self.begin_edit(self.selected_objects)
        for c in self.selected_objects: c.setTag('heading', str(self.physics.player.getH() % 360))
        self.commit_editor('checkpoint_face',token)

    def convert_legacy_maps(self):
        try:
            count = self.world.convert_maps(__import__('os').path.dirname(self.world.save_file))
            self.editor_notice(f'Converted {count} maps; skipped {len(self.world.conversion_errors)} invalid maps; originals kept')
            self.play_sfx('map_convert')
        except Exception as e: self.editor_notice(f'Conversion failed: {e}')

    FILL_NAMES = ('White', 'Gray', 'Hazard', 'Checkpoint', 'Trampoline', 'White / Gray checkers')

    def toggle_fill_solid(self):
        if self.input_blocked() or self.tool_mode != 12: return
        self.fill_solid = not getattr(self, 'fill_solid', True)
        self.play_sfx('toggle',1.12 if self.fill_solid else .88)
        self.update_hud()

    def cancel_fill(self):
        if getattr(self, 'fill_start', None) is not None:
            self.fill_start = None
            self.play_block_action(False)
            self.update_hud()

    def fill_corner(self):
        if self.input_blocked() or self.preview.getZ() < -19.5: return
        pos = VBase3(self.preview.getPos())
        first = getattr(self, 'fill_start', None)
        if first is None:
            self.fill_start = pos
            self.play_block_action(True)
            self.update_hud()
            return
        lo = [min(round(first[i] - (.5 if i == 2 else 0)), round(pos[i] - (.5 if i == 2 else 0))) for i in range(3)]
        hi = [max(round(first[i] - (.5 if i == 2 else 0)), round(pos[i] - (.5 if i == 2 else 0))) for i in range(3)]
        count = math.prod(hi[i] - lo[i] + 1 for i in range(3))
        if count > 32768:
            self.play_sfx('fill_error')
            self.editor_notice('Fill is too large (maximum 32,768 blocks). Choose a closer second corner.')
            return
        token = self.begin_edit([])
        added = []
        movers = [m['np'].getPos() for m in self.world.moving_cubes]
        pp = self.physics.player.getPos()
        mode = getattr(self, 'fill_material', 1)
        for x in range(lo[0], hi[0]+1):
            for y in range(lo[1], hi[1]+1):
                for z in range(lo[2], hi[2]+1):
                    if not getattr(self, 'fill_solid', True) and not (x in (lo[0],hi[0]) or y in (lo[1],hi[1]) or z in (lo[2],hi[2])): continue
                    p = VBase3(x, y, z+.5)
                    key = self.world.get_grid_key(p)
                    if key in self.world.cube_map: continue
                    if any(all(abs(p[i]-q[i]) < .99 for i in range(3)) for q in movers): continue
                    if abs(pp.x-x) < .9 and abs(pp.y-y) < .9 and pp.z < z+1 and pp.z+self.physics.player_height > z: continue
                    mat = 1 + ((x+y+z) % 2) if mode == 6 else mode
                    c = self.world._make_block(dict(pos=p, mat=mat, bounce=self.cur_bounce, max_h=self.cur_h))
                    self.world.cubes.append(c); self.world.cube_map[key] = c
                    self.world.register_cube(c); self.world.request_chunk_update(p)
                    added.append(c)
        if added:
            self.finish_edit(token, added, 'fill')
            self.world.queue_save()
            self.play_block_action(True)
        else:
            self.play_sfx('fill_error')
        self.fill_start = None
        self.update_hud()
