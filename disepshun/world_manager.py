from disepshun.config import *
from panda3d.core import Shader, DirectionalLight, AmbientLight, CompassEffect, NodePath, PointLight, Material, VBase4
import builtins
from collections import defaultdict
import math
import shutil
import time

class WorldManager:
    FLOOR_HALF = 1000 # God floor half-size, shared by visuals, ray picking and player physics
    MAP_HEADER = "#DISEPSHUN_MAP,2"
    BOUNCE_RANGE = (0.1, 100.0); MAX_H_RANGE = (0.0, 10000.0); SPEED_RANGE = (0.01, 1000.0); COORD_LIMIT = 10000.0

    def __init__(self, render, loader):
        self.render = render
        self.loader = loader
        self.cubes = [] # Logical nodes (Collision only)
        self.cube_map = {} 
        self.moving_cubes = []
        self.save_file = os.path.join(DATA_DIR, "map_save.txt")
        self.map_is_dirty = False
        self.save_lock = threading.Lock()
        self.save_gen = 0; self.committed_gen = 0 # Snapshot order; older writers never replace newer files
        self.save_threads = []
        self.save_error = None
        self.save_blocked = False # Set when the map file could not be read, so it is never overwritten
        self.next_save_retry = 0.0
        self.load_errors = []
        self.active_checkpoint_cube = None
        self.saved_checkpoint_pos = None
        
        self.cube_pool = []
        
        self.chunk_size = 16
        self.chunks_visual = {} 
        self.chunk_contents = defaultdict(list) 
        self.dirty_chunks = set()
        
        cm = CardMaker('face')
        # Standard frame: (-0.5, 0.5) creates a card in XZ plane with normal (0, -1, 0)
        cm.setFrame(-0.5, 0.5, -0.5, 0.5)
        cm.setHasNormals(True) 
        cm.setHasUvs(True)
        self.face_node = NodePath(cm.generate())
        # Optimization: Backface Culling (Hides inside of blocks)
        self.face_node.setTwoSided(False)
        
        # --- Neon Materials ---
        self.red_glow_mat = Material()
        self.red_glow_mat.setEmission(VBase4(1, 0, 0, 1))
        
        self.lime_glow_mat = Material()
        self.lime_glow_mat.setEmission(VBase4(0, 1, 0, 1))
        
        self.cyan_glow_mat = Material()
        self.cyan_glow_mat.setEmission(VBase4(0, 0.6, 0.8, 1)) 
        
        self.setup_lights()
        self.create_sky()
        self.create_boundary_objects()
        self.create_platform()

    def setup_lights(self):
        self.alight = AmbientLight('alight')
        self.alight.setColor((0.2, 0.2, 0.2, 1)) 
        self.alnp = self.render.attachNewNode(self.alight)
        self.render.setLight(self.alnp)

        self.dlight = DirectionalLight('dlight')
        self.dlight.setColor((0.6, 0.6, 0.6, 1))
        
        self.dlnp = self.render.attachNewNode(self.dlight)
        if hasattr(builtins, 'base'):
            self.dlnp.reparentTo(builtins.base.camera)
            self.dlnp.setPos(0, 0, 0)
            self.dlnp.setEffect(CompassEffect.make(self.render, CompassEffect.PRot))
        
        self.dlnp.setHpr(45, -60, 0)
        self.render.setLight(self.dlnp)
        self.render.setShaderAuto()

    def set_shaders_enabled(self, v):
        if v:
            self.render.clearLight() 
            self.render.setLightOff(0) 
            self.render.setLight(self.alnp)
            self.render.setLight(self.dlnp)
            self.render.setShaderAuto()
        else:
            self.render.clearLight()
            self.render.clearShader()
            self.render.setLightOff(1)

    def create_sky(self):
        self.sky = self.loader.loadModel("models/misc/sphere")
        self.sky.reparentTo(self.render); self.sky.setScale(1)
        self.sky.setAttrib(CullFaceAttrib.make(CullFaceAttrib.MCullCounterClockwise))
        self.sky.setBin("background", 10); self.sky.setDepthTest(False); self.sky.setDepthWrite(False); self.sky.setLightOff()
        self.sky.setColorScale((0, 0, 0, 1))

    def create_boundary_objects(self):
        cm = CardMaker("visual_floor"); cm.setFrame(-self.FLOOR_HALF, self.FLOOR_HALF, -self.FLOOR_HALF, self.FLOOR_HALF)
        self.visual_floor = self.render.attachNewNode(cm.generate())
        self.visual_floor.setPos(0, 0, -20.0); self.visual_floor.setP(-90); self.visual_floor.setColor((1, 0, 0, 1)); self.visual_floor.hide()
        
        self.god_collision_floor = NodePath("GodCollisionFloor")
        coll = CollisionNode("god_collision_floor_coll")
        coll.addSolid(CollisionBox((-self.FLOOR_HALF, -self.FLOOR_HALF, -0.5), (self.FLOOR_HALF, self.FLOOR_HALF, 0.5)))
        coll.setIntoCollideMask(COLLIDABLE_MASK)
        self.god_collision_floor.attachNewNode(coll).reparentTo(self.god_collision_floor)
        self.god_collision_floor.reparentTo(self.render); self.god_collision_floor.setPos(0, 0, -20.5)

    def get_chunk_key(self, pos):
        return (int(pos.x) // self.chunk_size, int(pos.y) // self.chunk_size)

    def request_chunk_update(self, pos):
        key = self.get_chunk_key(pos)
        self.dirty_chunks.add(key)
        
        x, y = int(pos.x), int(pos.y)
        lx, ly = x % self.chunk_size, y % self.chunk_size
        
        if lx == 0: self.dirty_chunks.add((key[0]-1, key[1]))
        if lx == self.chunk_size - 1: self.dirty_chunks.add((key[0]+1, key[1]))
        if ly == 0: self.dirty_chunks.add((key[0], key[1]-1))
        if ly == self.chunk_size - 1: self.dirty_chunks.add((key[0], key[1]+1))

    def update_chunks(self):
        if not self.dirty_chunks: return
        for key in self.dirty_chunks:
            self.rebuild_chunk(key)
        self.dirty_chunks.clear()

    def rebuild_chunk(self, key):
        if key in self.chunks_visual:
            self.chunks_visual[key].removeNode()
            del self.chunks_visual[key]

        temp_node = NodePath(f"chunk_{key}")
        has_geom = False

        cubes_in_chunk = self.chunk_contents.get(key, [])
        
        for c in cubes_in_chunk:
            if c.isHidden(): continue
            
            pos = c.getPos()
            grid_key = self.get_grid_key(pos)
            x, y, z = grid_key
            mat = c.getTag("material")
            
            visible_faces = 0
            
            face_defs = [
                # Front (Y-): needs normal (0,-1,0). Card is (0,-1,0). Rotation: 0
                ((0, -0.5, 0), 0, 0, (x, y - 1, z)),
                # Back (Y+): needs normal (0,1,0). Card is (0,-1,0). Rotation: 180
                ((0, 0.5, 0), 180, 0, (x, y + 1, z)),
                # Left (X-): needs normal (-1,0,0). Card (0,-1,0). Rot -90 -> (-1,0,0)
                ((-0.5, 0, 0), -90, 0, (x - 1, y, z)),
                # Right (X+): needs normal (1,0,0). Card (0,-1,0). Rot 90 -> (1,0,0)
                ((0.5, 0, 0), 90, 0, (x + 1, y, z)),
                # Top (Z+): needs normal (0,0,1). Card (0,-1,0). Pitch -90 -> (0,0,1)
                ((0, 0, 0.5), 0, -90, (x, y, z + 1)),
                # Bottom (Z-): needs normal (0,0,-1). Card (0,-1,0). Pitch 90 -> (0,0,-1)
                ((0, 0, -0.5), 0, 90, (x, y, z - 1))
            ]

            for f_pos, f_h, f_p, n_key in face_defs:
                neighbor = self.cube_map.get(n_key)
                show_face = True
                
                if neighbor:
                    if not any(mc['np'] == neighbor for mc in self.moving_cubes):
                        if not neighbor.isHidden():
                            show_face = False
                
                if show_face:
                    f = self.face_node.copyTo(temp_node)
                    f.setPos(pos + VBase3(f_pos))
                    f.setHpr(f_h, f_p, 0)
                    
                    if mat in ("3", "4"): self.style_face(f, c)
                    else: f.setColor(c.getColor())
                        
                    f.setTwoSided(False)
                    has_geom = True
                    visible_faces += 1
            
            # Optimization: Stash fully occluded blocks
            if visible_faces == 0:
                if not c.isStashed():
                    c.stash()
            else:
                if c.isStashed():
                    c.unstash()

        if has_geom:
            temp_node.flattenStrong()
            temp_node.reparentTo(self.platform_holder)
            self.chunks_visual[key] = temp_node

    def register_cube(self, cube):
        k = self.get_chunk_key(cube.getPos())
        self.chunk_contents[k].append(cube)
        
    def unregister_cube(self, cube):
        k = self.get_chunk_key(cube.getPos())
        if cube in self.chunk_contents[k]:
            self.chunk_contents[k].remove(cube)

    def get_cube(self, name):
        while self.cube_pool:
            cube = self.cube_pool.pop()
            if cube.isEmpty(): continue
            try:
                cube.setName(name)
                if cube.isStashed(): cube.unstash()
                cube.show()
                cube.clearColor()
                cube.clearColorScale()
                cube.setPos(0,0,0)
                cube.setTag("material", "")
                cube.setTag("bounciness", "")
                cube.setTag("max_height", "")
                cube.getChildren().detach()
                if cube.find("**/coll").isEmpty():
                    cn = CollisionNode("coll")
                    cn.addSolid(CollisionBox((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5)))
                    cn.setIntoCollideMask(COLLIDABLE_MASK)
                    cube.attachNewNode(cn)
                return cube
            except: continue
        return self.create_new_cube_node(name)

    def recycle_cube(self, cube):
        if cube.isEmpty(): return
        self.unregister_cube(cube)
        cube.detachNode()
        self.cube_pool.append(cube)

    def create_new_cube_node(self, name):
        cube = NodePath(name)
        cn = CollisionNode("coll")
        cn.addSolid(CollisionBox((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5)))
        cn.setIntoCollideMask(COLLIDABLE_MASK)
        cube.attachNewNode(cn)
        return cube

    def get_grid_key(self, pos):
        return (math.floor(pos.x + 0.5), math.floor(pos.y + 0.5), math.floor(pos.z + 0.5))

    def style_face(self, f, cube):
        mat = cube.getTag("material")
        if mat == "3":
            f.setMaterial(self.red_glow_mat)
            f.setColor(1, 0, 0, 1)
        elif mat == "4":
            if cube == self.active_checkpoint_cube:
                f.setMaterial(self.cyan_glow_mat)
                f.setColor(0, 0.6, 0.8, 1)
            else:
                f.setMaterial(self.lime_glow_mat)
                f.setColor(0, 1, 0, 1)

    def find_mover(self, np):
        for mc in self.moving_cubes:
            if mc['np'] == np: return mc
        return None

    def update_cube_faces(self, cube):
        if self.find_mover(cube):
            geom = cube.find("face_geom")
            if geom.isEmpty():
                geom = NodePath("face_geom")
                face_data = [((0, -0.5, 0), 0, 0), ((0, 0.5, 0), 180, 0), ((-0.5, 0, 0), -90, 0), ((0.5, 0, 0), 90, 0), ((0, 0, 0.5), 0, -90), ((0, 0, -0.5), 0, 90)]
                for pos, h, p in face_data:
                    f = self.face_node.copyTo(geom)
                    f.setPos(pos); f.setHpr(h, p, 0); f.setTwoSided(False)
                geom.reparentTo(cube)
            # Restyle existing faces too, so checkpoint activation changes mover colors
            for f in geom.getChildren(): self.style_face(f, cube)
            return

        self.request_chunk_update(cube.getPos())

    def convert_to_mover(self, c, mover):
        """Turn a live static block into a mover without recycling its node."""
        k = self.get_grid_key(c.getPos())
        if self.cube_map.get(k) == c: del self.cube_map[k]
        if c in self.cubes: self.cubes.remove(c)
        self.unregister_cube(c)
        self.request_chunk_update(c.getPos())
        if c.isStashed(): c.unstash()
        if c.getParent() != self.platform_holder: c.reparentTo(self.platform_holder)
        mover['np'] = c
        self.moving_cubes.append(mover)
        self.update_cube_faces(c)
        return mover

    def remove_block(self, np):
        """Single deletion path for static and moving blocks; clears references before the node is pooled."""
        if np is None or np.isEmpty() or np == self.god_collision_floor: return False
        mc = self.find_mover(np)
        if mc: self.moving_cubes.remove(mc)
        elif np in self.cubes:
            k = self.get_grid_key(np.getPos())
            if self.cube_map.get(k) == np: del self.cube_map[k]
            self.cubes.remove(np)
            self.request_chunk_update(np.getPos())
        else: return False
        if np == self.active_checkpoint_cube: self.active_checkpoint_cube = None
        self.recycle_cube(np)
        return True

    def update_neighbor_visibility(self, key):
        pass

    def create_platform(self):
        self.platform_holder = self.render.attachNewNode("PlatformHolder")
        self.chunk_contents.clear()
        self.chunks_visual.clear()
        
        self.cubes = []; self.cube_map = {}; self.moving_cubes = []
        
        self.update_chunks()

    def _threaded_save(self, data, gen):
        with self.save_lock:
            if gen <= self.committed_gen: return # A newer snapshot is already on disk
            tmp = self.save_file + ".tmp"
            try:
                # Write a temp file and swap it in, so a failed write never truncates the last good map
                with open(tmp, "w") as f:
                    f.write(data); f.flush(); os.fsync(f.fileno())
                os.replace(tmp, self.save_file)
            except Exception as e:
                try: os.remove(tmp)
                except OSError: pass
                if gen == self.save_gen: self.map_is_dirty = True # Latest state still unsaved; retried later
                msg = f"Save failed: {e}"
                if msg != self.save_error: print(msg)
                self.save_error = msg
                return
            self.committed_gen = gen
            if gen == self.save_gen: self.save_error = None

    def serialize_map(self):
        buf = [self.MAP_HEADER + "\n"]
        movers = [m for m in self.moving_cubes if not m['np'].isEmpty()]
        ac = self.active_checkpoint_cube
        if ac is not None and not ac.isEmpty() and ac.getTag("material") == "4":
            mi = next((i for i, m in enumerate(movers) if m['np'] == ac), None)
            if mi is not None: buf.append(f"CP,M,{mi}\n")
            elif ac in self.cubes:
                p = ac.getPos(); buf.append(f"CP,S,{p.x},{p.y},{p.z}\n")
        for c in self.cubes:
            if c == self.god_collision_floor or self.find_mover(c): continue
            p = c.getPos(); m = c.getTag("material")
            if m:
                l = f"B,{p.x},{p.y},{p.z},{m}"
                if m == "5": l += f",{c.getTag('bounciness') or '1.3'},{c.getTag('max_height') or '0.0'}"
                buf.append(l + "\n")
        for m in movers:
            c = m['np']; p = m['origin']
            l = f"M,{p.x},{p.y},{p.z},{c.getTag('material')},{m['speed']},{c.getTag('bounciness') or '1.3'},{c.getTag('max_height') or '0.0'}"
            for w in m['waypoints']: l += f",{w.x},{w.y},{w.z}"
            buf.append(l + "\n")
        return "".join(buf)

    def save_map(self):
        if not self.map_is_dirty: return
        if self.save_blocked: return # Map file was unreadable at load; keep it untouched and stay dirty
        self.save_gen += 1
        data = self.serialize_map()
        self.map_is_dirty = False
        self.save_threads = [t for t in self.save_threads if t.is_alive()]
        # Non-daemon so the interpreter waits for pending writes on exit
        t = threading.Thread(target=self._threaded_save, args=(data, self.save_gen), daemon=False)
        self.save_threads.append(t); t.start()

    def retry_save(self, now):
        """Called every frame; retries a failed save every couple of seconds."""
        if self.map_is_dirty and not self.save_blocked and now >= self.next_save_retry:
            self.next_save_retry = now + 2.0
            self.save_map()

    def flush_saves(self, timeout=10.0):
        """Save any pending edit and wait for every writer. Returns True when the latest state is on disk."""
        self.save_map()
        deadline = time.monotonic() + timeout
        for t in list(self.save_threads): t.join(max(0.0, deadline - time.monotonic()))
        if any(t.is_alive() for t in self.save_threads):
            print("Save still in progress at exit; the map file may not contain the last edit.")
            return False
        if self.map_is_dirty:
            print(self.save_error or "Map has unsaved changes that could not be written.")
            return False
        return True

    def _num(self, s, lo=None, hi=None):
        v = float(s)
        if not math.isfinite(v): raise ValueError(f"non-finite number {s!r}")
        if lo is None: lo, hi = -self.COORD_LIMIT, self.COORD_LIMIT
        if not lo <= v <= hi: raise ValueError(f"{s} outside {lo}..{hi}")
        return v

    def _vec(self, parts):
        return VBase3(self._num(parts[0]), self._num(parts[1]), self._num(parts[2]))

    def _waypoints(self, parts):
        if len(parts) % 3: raise ValueError("incomplete waypoint")
        return [self._vec(parts[i:i+3]) for i in range(0, len(parts), 3)]

    def _material(self, s):
        mid = int(s)
        if not 1 <= mid <= 6: raise ValueError(f"unknown material {s!r}")
        return mid

    def parse_map(self, lines):
        """Validate every record without touching the scene. Returns (blocks, movers, checkpoint, errors)."""
        blocks = []; movers = []; cp = None; errors = []
        seen = {}
        body = [(n, l.strip()) for n, l in enumerate(lines, 1)]
        body = [(n, l) for n, l in body if l]
        v2 = bool(body) and body[0][1] == self.MAP_HEADER
        if v2: body = body[1:]
        for n, line in body:
            parts = [p.strip() for p in line.split(',')]
            try:
                if line.startswith("#"): raise ValueError("unknown header/comment")
                if parts[0] == "CP":
                    if v2 and parts[1:2] == ["M"] and len(parts) == 3: cp = ('M', int(parts[2]))
                    elif v2 and parts[1:2] == ["S"] and len(parts) == 5: cp = ('S', self._vec(parts[2:5]))
                    elif not v2 and len(parts) == 4: cp = ('P', self._vec(parts[1:4]))
                    else: raise ValueError("bad checkpoint record")
                    continue
                rec = {'bounce': 1.3, 'max_h': 0.0}
                if v2:
                    kind = parts[0]
                    if kind == "B":
                        if len(parts) not in (5, 7): raise ValueError("bad block record")
                        rec['pos'] = self._vec(parts[1:4]); rec['mat'] = self._material(parts[4])
                        if len(parts) == 7: rec['bounce'] = self._num(parts[5], *self.BOUNCE_RANGE); rec['max_h'] = self._num(parts[6], *self.MAX_H_RANGE)
                    elif kind == "M":
                        if len(parts) < 8: raise ValueError("bad mover record")
                        rec['pos'] = self._vec(parts[1:4]); rec['mat'] = self._material(parts[4])
                        rec['speed'] = self._num(parts[5], *self.SPEED_RANGE)
                        rec['bounce'] = self._num(parts[6], *self.BOUNCE_RANGE); rec['max_h'] = self._num(parts[7], *self.MAX_H_RANGE)
                        rec['waypoints'] = self._waypoints(parts[8:])
                    else: raise ValueError(f"unknown record type {kind!r}")
                else:
                    # Legacy format: movers are blocks with extra fields, except trampolines whose extra fields are bounce settings
                    if len(parts) < 4: raise ValueError("too few fields")
                    rec['pos'] = self._vec(parts[0:3]); rec['mat'] = self._material(parts[3]); extra = parts[4:]
                    if rec['mat'] == 5 and len(extra) == 2:
                        rec['bounce'] = self._num(extra[0], *self.BOUNCE_RANGE); rec['max_h'] = self._num(extra[1], *self.MAX_H_RANGE)
                    elif extra:
                        if len(extra) % 3 != 1: raise ValueError("ambiguous extra fields")
                        rec['speed'] = self._num(extra[0], *self.SPEED_RANGE); rec['waypoints'] = self._waypoints(extra[1:])
                        if rec['mat'] == 5: errors.append(f"line {n}: moving trampoline from old save format; its bounce settings were not saved, defaults used")
                if rec['mat'] == 6: continue
                if 'speed' in rec: movers.append(rec); continue
                k = self.get_grid_key(rec['pos'])
                if k in seen: raise ValueError(f"duplicate block position, line {seen[k]} kept")
                seen[k] = n; blocks.append(rec)
            except (ValueError, IndexError) as e:
                errors.append(f"line {n}: {e}: {line}")
        return blocks, movers, cp, errors

    def _make_block(self, rec):
        mid = rec['mat']
        c = self.get_cube("loaded_cube")
        c.setColor({1:(1,1,1,1), 2:(0.4,0.4,0.4,1), 3:(1,0,0,1), 4:(0,1,0,1), 5:(0,0,1,1)}[mid]); c.setTag("material", str(mid))
        if mid == 5: c.setTag("bounciness", str(rec['bounce'])); c.setTag("max_height", str(rec['max_h']))
        c.setPos(rec['pos']); c.reparentTo(self.platform_holder)
        return c

    @staticmethod
    def backup_name(path):
        stamp = time.strftime('%Y%m%d-%H%M%S'); bak = f"{path}.{stamp}.bak"; n = 1
        while os.path.exists(bak): n += 1; bak = f"{path}.{stamp}-{n}.bak"
        return bak

    def load_map(self):
        if not os.path.exists(self.save_file):
            default_map = """0.0,0.0,0.5,4
-1.0,0.0,0.5,2
0.0,-1.0,0.5,2
1.0,0.0,0.5,2
0.0,1.0,0.5,2
1.0,1.0,0.5,1
1.0,-1.0,0.5,1
-1.0,-1.0,0.5,1
-1.0,1.0,0.5,1
"""
            os.makedirs(os.path.dirname(self.save_file), exist_ok=True)
            with open(self.save_file, "w") as f:
                f.write(default_map)

        try:
            with open(self.save_file, "r") as f: lines = f.readlines()
        except (OSError, UnicodeDecodeError) as e:
            # Reject the whole load and never overwrite a file we could not read
            self.save_blocked = True
            self.save_error = f"Map file could not be read ({e}); saving is disabled so it is not overwritten."
            print(self.save_error)
            return

        blocks, movers, cp, errors = self.parse_map(lines)
        self.load_errors = errors
        if errors:
            for e in errors: print("Map load:", e)
            # Keep the original so rejected records are not lost when the cleaned map is saved
            bak = self.backup_name(self.save_file)
            try: shutil.copy2(self.save_file, bak); print(f"Map load: original file kept as {bak}")
            except OSError as e:
                self.save_blocked = True
                self.save_error = f"Map had invalid records and could not be backed up ({e}); saving is disabled."
                print(self.save_error)

        self.platform_holder.getChildren().detach()
        self.chunks_visual.clear()
        self.chunk_contents.clear()

        for c in self.cubes:
            if c != self.god_collision_floor: self.recycle_cube(c)
        for m in self.moving_cubes: self.recycle_cube(m['np'])

        self.cubes = [c for c in self.cubes if c == self.god_collision_floor]
        self.cube_map = {}; self.moving_cubes = []; self.active_checkpoint_cube = None; self.saved_checkpoint_pos = None

        for rec in blocks:
            c = self._make_block(rec)
            self.cubes.append(c); self.cube_map[self.get_grid_key(rec['pos'])] = c
            self.register_cube(c)
            self.request_chunk_update(rec['pos'])
        for rec in movers:
            c = self._make_block(rec)
            self.moving_cubes.append({'np': c, 'waypoints': rec['waypoints'], 'speed': rec['speed'], 'current_idx': 0, 'wait_timer': 0, 'origin': rec['pos'], 'direction': 1})
            self.update_cube_faces(c)

        if cp:
            kind, val = cp; c = None
            if kind == 'M':
                if 0 <= val < len(self.moving_cubes): c = self.moving_cubes[val]['np']
            else:
                c = self.cube_map.get(self.get_grid_key(val))
                if c is None and kind == 'P':
                    # Old saves stored a moving checkpoint's current position; match it by origin
                    c = next((m['np'] for m in self.moving_cubes if self.get_grid_key(m['origin']) == self.get_grid_key(val)), None)
            if c is not None and c.getTag("material") == "4":
                self.active_checkpoint_cube = c
                self.saved_checkpoint_pos = c.getPos()
                if self.find_mover(c): self.update_cube_faces(c)
            elif kind == 'P': self.saved_checkpoint_pos = val
            else: print("Map load: saved checkpoint does not match a checkpoint block; ignored")

        self.update_chunks()

    def update_god_collision(self, gm):
        if gm and not self.visual_floor.isHidden():
            if self.god_collision_floor not in self.cubes: self.cubes.append(self.god_collision_floor)
        elif self.god_collision_floor in self.cubes: self.cubes.remove(self.god_collision_floor)