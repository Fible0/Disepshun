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
        self.save_file = os.path.join(DATA_DIR, "map_save.dmf")
        self.default_map_file = os.path.join(ROOT_DIR, "assets", "default_map.dmf")
        self.map_is_dirty = False
        self.save_lock = threading.Lock()
        self.save_gen = 0; self.committed_gen = 0 # Snapshot order; older writers never replace newer files
        self.save_threads = []
        self.save_error = None
        self.save_blocked = False # Set when the map file could not be read, so it is never overwritten
        self.next_save_retry = 0.0
        self.pending_save_at = None
        self.load_errors = []
        self.active_checkpoint_cube = None
        self.saved_checkpoint_pos = None
        
        self.cube_pool = []
        
        self.chunk_size = 16
        self.chunks_visual = {}
        self.collision_chunks = {}
        self.chunk_format = GeomVertexFormat.getV3n3t2()
        self.chunk_contents = defaultdict(list) 
        self.static_cube_order = {}
        self.next_cube_order = 0
        self.dirty_chunks = set()
        self.god_floor_enabled = False
        
        cm = CardMaker('face')
        # Standard frame: (-0.5, 0.5) creates a card in XZ plane with normal (0, -1, 0)
        cm.setFrame(-0.5, 0.5, -0.5, 0.5)
        cm.setHasNormals(True) 
        cm.setHasUvs(True)
        self.face_node = NodePath(cm.generate())
        # Optimization: Backface Culling (Hides inside of blocks)
        self.face_node.setTwoSided(False)
        
        # Emission keeps the neon visible; diffuse lighting gives each face depth.
        self.red_glow_mat = self.make_glow_material((1,0,0,1))
        self.lime_glow_mat = self.make_glow_material((0,1,0,1))
        self.cyan_glow_mat = self.make_glow_material((0,.6,.8,1))
        self.selection_glow_mats = {}
        self.glow_stage = TextureStage('neon_glow')
        self.glow_stage.setMode(TextureStage.MGlow)
        mask = PNMImage(1,1,4)
        mask.fill(0,0,0); mask.alphaFill(1.0)
        self.glow_texture = Texture('neon_glow_mask')
        self.glow_texture.load(mask)

        self.glow_lights = []; self.glow_sources = []; self.next_glow_scan = 0.0
        self.shaders_enabled = True
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
        # A fixed small pool avoids adding a light (and a shader cost) per block.
        for i in range(4):
            light=PointLight(f'neon_spill_{i}')
            light.setColor((0,0,0,1)); light.setAttenuation((1,0,1.8))
            node=self.render.attachNewNode(light); self.render.setLight(node)
            self.glow_lights.append((light,node))

    def update_glow_lights(self, camera_pos, now=None):
        if not self.shaders_enabled: return
        now = time.monotonic() if now is None else now
        if now >= self.next_glow_scan:
            self.next_glow_scan = now+.2
            nearby=[]
            # Only nearby static chunks can contribute within the 15-unit radius.
            # Preserve map order for equal distances, including static/mover ties.
            radius = 15
            cs = self.chunk_size
            for x in range(math.floor((camera_pos.x-radius-1)/cs), math.floor((camera_pos.x+radius+1)/cs)+1):
                for y in range(math.floor((camera_pos.y-radius-1)/cs), math.floor((camera_pos.y+radius+1)/cs)+1):
                    for c in self.chunk_contents.get((x,y), ()):
                        if c.getTag('material') not in ('3','4'): continue
                        d=(c.getPos(self.render)-camera_pos).lengthSquared()
                        if d < 225: nearby.append((d,self.static_cube_order[c],c))
            for i,m in enumerate(self.moving_cubes):
                c=m['np']
                if c.getTag('material') not in ('3','4'): continue
                d=(c.getPos(self.render)-camera_pos).lengthSquared()
                if d < 225: nearby.append((d,self.next_cube_order+i,c))
            nearby.sort(key=lambda item:(item[0],item[1]))
            self.glow_sources=[c for _,_,c in nearby[:len(self.glow_lights)]]
        for i,(light,node) in enumerate(self.glow_lights):
            c=self.glow_sources[i] if i<len(self.glow_sources) else None
            if c is None or c.isEmpty() or c.getParent().isEmpty() or c.getTag('material') not in ('3','4'):
                light.setColor((0,0,0,1)); continue
            color = ((1,0,0,1) if c.getTag('material')=='3' else
                     (0,.6,.8,1) if c==self.active_checkpoint_cube else (0,1,0,1))
            if c.hasPythonTag('selection_color'): color=c.getPythonTag('selection_color')
            strength=2.0 if c.getTag('material')=='3' else 1.6
            light.setColor(tuple(v*strength for v in color[:3])+(1,))
            node.setPos(c.getPos(self.render))

    def set_shaders_enabled(self, v):
        self.shaders_enabled = bool(v)
        if v:
            self.render.clearLight() 
            self.render.setLightOff(0) 
            self.render.setLight(self.alnp)
            self.render.setLight(self.dlnp)
            for _,node in self.glow_lights: self.render.setLight(node)
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

    def update_chunks(self, budget_seconds=None):
        if not self.dirty_chunks: return
        started=time.perf_counter()
        for key in list(self.dirty_chunks):
            self.rebuild_chunk(key)
            self.dirty_chunks.discard(key)
            if budget_seconds is not None and time.perf_counter()-started >= budget_seconds: break

    # Counter-clockwise vertices viewed from outside, with matching outward normals.
    FACE_DATA = (
        ((0,-1,0), ((-.5,-.5,-.5),(.5,-.5,-.5),(.5,-.5,.5),(-.5,-.5,.5))),
        ((0,1,0), ((.5,.5,-.5),(-.5,.5,-.5),(-.5,.5,.5),(.5,.5,.5))),
        ((-1,0,0), ((-.5,.5,-.5),(-.5,-.5,-.5),(-.5,-.5,.5),(-.5,.5,.5))),
        ((1,0,0), ((.5,-.5,-.5),(.5,.5,-.5),(.5,.5,.5),(.5,-.5,.5))),
        ((0,0,1), ((-.5,-.5,.5),(.5,-.5,.5),(.5,.5,.5),(-.5,.5,.5))),
        ((0,0,-1), ((-.5,.5,-.5),(.5,.5,-.5),(.5,-.5,-.5),(-.5,-.5,-.5))),
    )

    def rebuild_chunk(self, key):
        from array import array
        batches={}
        for c in self.chunk_contents.get(key, ()):
            if c.isHidden(): continue
            pos=c.getPos(); x,y,z=self.get_grid_key(pos)
            appearance=None
            visible=0
            for normal,corners in self.FACE_DATA:
                nx,ny,nz=normal
                neighbor=self.cube_map.get((x+nx,y+ny,z+nz))
                if neighbor is not None and not neighbor.isHidden(): continue
                # Interior blocks need no material/selection state or vertex data.
                if appearance is None:
                    color=tuple(c.getColor()); scale=tuple(c.getColorScale())
                    tint=c.getPythonTag('selection_color') if c.hasPythonTag('selection_color') else None
                    appearance=(c.getTag('material'),color,scale,c==self.active_checkpoint_cube,tint)
                if appearance not in batches: batches[appearance]=(array('f'),array('I'),c)
                vertices,indices,_=batches[appearance]; first=len(vertices)//8
                for (dx,dy,dz),(u,v) in zip(corners,((0,0),(1,0),(1,1),(0,1))):
                    vertices.extend((pos.x+dx,pos.y+dy,pos.z+dz,nx,ny,nz,u,v))
                indices.extend((first,first+1,first+2,first,first+2,first+3)); visible+=1
            if visible==0:
                if not c.isStashed(): c.stash()
            elif c.isStashed(): c.unstash()
        node=GeomNode(f'chunk_{key}'); node.setIntoCollideMask(BitMask32.allOff())
        for vertices,indices,c in batches.values():
            data=GeomVertexData('chunk_faces',self.chunk_format,Geom.UHStatic)
            data.modifyArray(0).modifyHandle().setData(vertices.tobytes())
            triangles=GeomTriangles(Geom.UHStatic); triangles.setIndexType(Geom.NTUint32)
            triangles.modifyVertices().modifyHandle().setData(indices.tobytes())
            geom=Geom(data); geom.addPrimitive(triangles)
            style=NodePath('chunk_style'); self.style_face(style,c); style.setColorScale(c.getColorScale())
            node.addGeom(geom,style.getState())
        old=self.chunks_visual.pop(key,None)
        if old is not None: old.removeNode()
        if batches: self.chunks_visual[key]=self.platform_holder.attachNewNode(node)

    def register_cube(self, cube):
        key=self.get_chunk_key(cube.getPos())
        self.chunk_contents[key].append(cube)
        if cube not in self.static_cube_order:
            self.static_cube_order[cube] = self.next_cube_order
            self.next_cube_order += 1
        # Spatial bounds let the picking ray skip whole regions of colliders.
        if key not in self.collision_chunks:
            self.collision_chunks[key]=self.platform_holder.attachNewNode(f'chunk_colliders_{key}')
        cube.reparentTo(self.collision_chunks[key])

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
                cube.clearPythonTag("selection_color")
                cube.clearPythonTag("history_id")
                cube.clearTag("group")
                cube.clearTag("heading")
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
        self.static_cube_order.pop(cube, None)
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

    @staticmethod
    def make_glow_material(color):
        material = Material()
        material.setEmission(VBase4(*(v*.45 for v in color[:3]), 1))
        material.setDiffuse(VBase4(*(v*.55 for v in color[:3]), 1))
        material.setAmbient(VBase4(*(v*.55 for v in color[:3]), 1))
        material.setSpecular(VBase4(.08,.08,.08,1))
        material.setShininess(20)
        return material

    def style_face(self, f, cube):
        mat = cube.getTag('material')
        color = tuple(cube.getColor())
        material = None
        if mat == '3': color = (1,0,0,1); material = self.red_glow_mat
        elif mat == '4':
            active = cube == self.active_checkpoint_cube
            color = (0,.6,.8,1) if active else (0,1,0,1)
            material = self.cyan_glow_mat if active else self.lime_glow_mat
        if cube.hasPythonTag('selection_color'):
            color = cube.getPythonTag('selection_color')
            if material is not None:
                key=(mat,color)
                if key not in self.selection_glow_mats:
                    self.selection_glow_mats[key] = self.make_glow_material(color)
                material = self.selection_glow_mats[key]
        f.clearMaterial()
        f.clearTexture(self.glow_stage)
        if material is not None:
            f.setMaterial(material)
            f.setTexture(self.glow_stage, self.glow_texture)
        f.setColor(*color)

    def find_mover(self, np):
        for mc in self.moving_cubes:
            if mc['np'] == np: return mc
        return None

    @staticmethod
    def mover_path(m):
        """Reuse path geometry until an editor operation changes it."""
        cached = m.get('_path_cache')
        waypoints = m['waypoints']; loop = m.get('loop', False)
        if (cached is None or cached[0] != m['origin'] or cached[1] is not waypoints
                or cached[2] != len(waypoints) or cached[3] != loop):
            pts = [m['origin']] + waypoints
            length = sum((b-a).length() for a,b in zip(pts,pts[1:]))
            circuit = length + (pts[-1]-pts[0]).length() if loop else 2*length
            cached = (VBase3(m['origin']), waypoints, len(waypoints), loop, pts, circuit)
            m['_path_cache'] = cached
        return cached[4], cached[5]

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
        self.static_cube_order.pop(c, None)
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
        self.static_cube_order.clear()
        self.next_cube_order = 0
        self.chunks_visual.clear()
        self.collision_chunks.clear()
        
        self.cubes = []; self.cube_map = {}; self.moving_cubes = []
        self.god_floor_enabled = False
        
        self.update_chunks()

    def _threaded_save(self, data, gen):
        with self.save_lock:
            if gen <= self.committed_gen: return # A newer snapshot is already on disk
            tmp = self.save_file + ".tmp"
            try:
                if isinstance(data,tuple):
                    import gzip
                    data=b'DMAP3\n'+gzip.compress(data[0],mtime=0)
                # Write a temp file and swap it in, so a failed write never truncates the last good map
                with open(tmp, "wb") as f:
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

    def serialize_records(self):
        buf = [self.MAP_HEADER + "\n"]
        movers = [m for m in self.moving_cubes if not m['np'].isEmpty()]
        ac = self.active_checkpoint_cube
        if ac is not None and not ac.isEmpty() and ac.getTag("material") == "4":
            mi = next((i for i, m in enumerate(movers) if m['np'] == ac), None)
            if mi is not None: buf.append(f"CP,M,{mi}\n")
            elif ac in self.cubes:
                p = ac.getPos(); buf.append(f"CP,S,{p.x},{p.y},{p.z}\n")
        mover_nodes = {m['np'] for m in movers}
        for c in self.cubes:
            if c == self.god_collision_floor or c in mover_nodes: continue
            p = c.getPos(); m = c.getTag("material")
            if m:
                l = f"B,{p.x},{p.y},{p.z},{m}"
                if m == "5": l += f",{c.getTag('bounciness') or '1.3'},{c.getTag('max_height') or '0.0'}"
                buf.append(l + "\n")
        for m in movers:
            c = m['np']; p = m['origin']
            kind = "L" if m.get("loop",False) else "M"
            l = f"{kind},{p.x},{p.y},{p.z},{c.getTag('material')},{m['speed']},{c.getTag('bounciness') or '1.3'},{c.getTag('max_height') or '0.0'}"
            for w in m['waypoints']: l += f",{w.x},{w.y},{w.z}"
            buf.append(l + "\n")
        return "".join(buf)

    def all_blocks(self):
        return [c for c in self.cubes if c != self.god_collision_floor] + [m['np'] for m in self.moving_cubes]

    def serialize_map(self, compress=True):
        """Capture scene values now; save writers can compress the immutable byte snapshot."""
        import gzip, json
        nodes = self.all_blocks()
        payload = {"version": 3, "records": self.serialize_records(),
                   "properties": [[c.getTag("group"), float(c.getTag("heading") or 0)] for c in nodes]}
        raw=json.dumps(payload,separators=(',',':')).encode('utf8')
        return b'DMAP3\n'+gzip.compress(raw,mtime=0) if compress else (raw,)

    def read_map(self, path):
        import gzip, json, io
        with open(path, "rb") as f: data = f.read()
        props = None
        if data.startswith(b"DMAP3\n"):
            with gzip.GzipFile(fileobj=io.BytesIO(data[6:])) as f:
                raw = f.read(64 * 1024 * 1024 + 1)
            if len(raw) > 64 * 1024 * 1024: raise ValueError("map exceeds 64 MiB")
            obj = json.loads(raw)
            if not isinstance(obj, dict): raise ValueError('invalid map container')
            if obj.get('version') != 3: raise ValueError("unsupported map version")
            if not isinstance(obj['records'], str): raise ValueError('invalid map records')
            lines = obj['records'].splitlines()
            props = obj['properties']
            if not isinstance(props, list): raise ValueError("invalid map properties")
            for group, heading in props:
                if not isinstance(group, str) or len(group) > 128: raise ValueError("invalid group")
                self._num(heading, -360, 360)
        else: lines = data.decode('utf-8-sig').splitlines()
        return lines, props

    def convert_maps(self, directory):
        """Convert valid legacy maps without replacing the originals."""
        import gzip, json
        converted = 0
        self.conversion_errors = []
        import zlib
        for name in sorted(os.listdir(directory), key=lambda name: not name.lower().endswith('.dmap')):
            if not name.lower().endswith(('.txt', '.dmap')): continue
            source = os.path.join(directory, name)
            target = os.path.splitext(source)[0] + '.dmf'
            if os.path.exists(target) or not os.path.isfile(source): continue
            try:
                lines, props = self.read_map(source)
                blocks, movers, cp, errors = self.parse_map(lines)
                if errors or (props is not None and len(props) != len(blocks)+len(movers)):
                    raise ValueError('invalid records or properties')
            except (OSError, ValueError, KeyError, TypeError, EOFError, zlib.error) as e:
                self.conversion_errors.append(f'{name}: {e}')
                continue
            records = [self.MAP_HEADER]
            if cp:
                kind, value = cp
                if kind == 'M': records.append(f'CP,M,{value}')
                else:
                    mi = next((i for i, r in enumerate(movers) if r['pos'] == value), None)
                    if kind == 'P' and mi is not None: records.append(f'CP,M,{mi}')
                    else: records.append('CP,S,' + ','.join(map(str, value)))
            for r in blocks + movers:
                moving = 'speed' in r
                fields = [('L' if r.get('loop',False) else 'M') if moving else 'B', *r['pos'], r['mat']]
                if moving: fields += [r['speed'], r['bounce'], r['max_h'], *[v for w in r['waypoints'] for v in w]]
                elif r['mat'] == 5: fields += [r['bounce'], r['max_h']]
                records.append(','.join(map(str, fields)))
            payload = dict(version=3, records='\n'.join(records)+'\n', properties=props or [['', 0] for _ in blocks+movers])
            data = b'DMAP3\n' + gzip.compress(json.dumps(payload, separators=(',', ':')).encode('utf8'), mtime=0)
            with open(target + '.tmp', 'wb') as f: f.write(data)
            os.replace(target + '.tmp', target)
            converted += 1
        return converted

    def queue_save(self):
        """Coalesce rapid placements and checkpoint changes, without delaying exit saves."""
        self.map_is_dirty = True
        if self.pending_save_at is None: self.pending_save_at = time.monotonic()+.35

    def save_map(self):
        if not self.map_is_dirty: return
        if self.save_blocked: return # Map file was unreadable at load; keep it untouched and stay dirty
        self.pending_save_at = None
        self.save_gen += 1
        data = self.serialize_map(compress=False)
        self.map_is_dirty = False
        self.save_threads = [t for t in self.save_threads if t.is_alive()]
        # Non-daemon so the interpreter waits for pending writes on exit
        t = threading.Thread(target=self._threaded_save, args=(data, self.save_gen), daemon=False)
        self.save_threads.append(t); t.start()

    def retry_save(self, now):
        """Called every frame; retries a failed save every couple of seconds."""
        if self.pending_save_at is not None:
            if time.monotonic() < self.pending_save_at: return
            self.pending_save_at = None
            self.save_map()
            return
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
                    elif kind in ("M", "L"):
                        rec['loop'] = kind == "L"
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

    def load_map(self, migrate=True):
        legacy = os.path.splitext(self.save_file)[0] + '.txt'
        previous = os.path.splitext(self.save_file)[0] + '.dmap'
        if not os.path.exists(self.save_file) and os.path.exists(previous):
            source = previous
        elif not os.path.exists(self.save_file) and os.path.exists(legacy):
            source = legacy
        else: source = self.save_file
        fresh = None
        if not os.path.exists(source):
            # No save yet: start from the bundled default map
            try:
                os.makedirs(os.path.dirname(self.save_file), exist_ok=True)
                shutil.copyfile(self.default_map_file, self.save_file)
            except OSError as e:
                print(f"Default map could not be copied ({e}); starting with an empty map")
                fresh = ([self.MAP_HEADER], [])
            source = self.save_file

        import zlib
        try:
            lines, properties = fresh or self.read_map(source)
        except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError, EOFError, zlib.error) as e:
            # Reject the whole load and never overwrite a file we could not read
            self.save_blocked = True
            self.save_error = f"Map file could not be read ({e}); saving is disabled so it is not overwritten."
            print(self.save_error)
            return

        blocks, movers, cp, errors = self.parse_map(lines)
        if properties is not None and len(properties) != len(blocks) + len(movers):
            self.save_blocked = True
            self.save_error = "Map properties do not match its objects; saving disabled."
            return
        self.load_errors = errors
        if errors:
            for e in errors: print("Map load:", e)
            # Keep the original so rejected records are not lost when the cleaned map is saved
            bak = self.backup_name(source)
            try: shutil.copy2(source, bak); print(f"Map load: original file kept as {bak}")
            except OSError as e:
                self.save_blocked = True
                self.save_error = f"Map had invalid records and could not be backed up ({e}); saving is disabled."
                print(self.save_error)

        self.platform_holder.getChildren().detach()
        self.chunks_visual.clear()
        self.collision_chunks.clear()
        self.chunk_contents.clear()

        for c in self.cubes:
            if c != self.god_collision_floor: self.recycle_cube(c)
        for m in self.moving_cubes: self.recycle_cube(m['np'])

        self.cubes = [c for c in self.cubes if c == self.god_collision_floor]
        self.static_cube_order.clear()
        self.next_cube_order = 0
        self.cube_map = {}; self.moving_cubes = []; self.active_checkpoint_cube = None; self.saved_checkpoint_pos = None

        for rec in blocks:
            c = self._make_block(rec)
            self.cubes.append(c); self.cube_map[self.get_grid_key(rec['pos'])] = c
            self.register_cube(c)
            self.request_chunk_update(rec['pos'])
        for rec in movers:
            c = self._make_block(rec)
            self.moving_cubes.append({'np': c, 'waypoints': rec['waypoints'], 'speed': rec['speed'], 'current_idx': 0, 'wait_timer': 0, 'origin': rec['pos'], 'direction': 1, 'loop': rec.get('loop',False)})
            self.update_cube_faces(c)

        if properties is not None:
            for c, (group, heading) in zip(self.all_blocks(), properties):
                if group: c.setTag('group', group)
                c.setTag('heading', str(heading))

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
        if migrate and (properties is None or source != self.save_file) and not errors and not self.save_blocked:
            try:
                shutil.copy2(source, self.backup_name(source))
                self.map_is_dirty = True
                self.save_map()
            except OSError as e:
                self.save_error = f"Map conversion backup failed: {e}"
                self.save_blocked = True

    def update_god_collision(self, gm):
        if gm and not self.visual_floor.isHidden():
            if self.god_collision_floor not in self.cubes: self.cubes.append(self.god_collision_floor)
        elif self.god_collision_floor in self.cubes: self.cubes.remove(self.god_collision_floor)
        self.god_floor_enabled = bool(gm and not self.visual_floor.isHidden())
