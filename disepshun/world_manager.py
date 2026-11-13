from disepshun.config import *
from panda3d.core import Shader, DirectionalLight, AmbientLight, CompassEffect, NodePath, PointLight, Material, VBase4
import builtins
import math
import shutil
import time


class NodeList:
    """Insertion-ordered set of block nodes with the list operations the game uses.
    Membership and removal are O(1); the map keeps its save order."""
    __slots__ = ('_items', '_seq')

    def __init__(self, items=()):
        self._items = dict.fromkeys(items); self._seq = None

    def _sequence(self):
        if self._seq is None: self._seq = tuple(self._items)
        return self._seq

    def append(self, node): self._items[node] = None; self._seq = None
    def extend(self, nodes):
        for node in nodes: self.append(node)

    def remove(self, node):
        try: del self._items[node]
        except KeyError: raise ValueError('node not in list') from None
        self._seq = None

    def __contains__(self, node): return node in self._items
    def __iter__(self): return iter(self._sequence())  # A snapshot, so removal while iterating is safe
    def __len__(self): return len(self._items)
    def __bool__(self): return bool(self._items)
    def __getitem__(self, index):
        seq = self._sequence()
        return list(seq[index]) if isinstance(index, slice) else seq[index]
    def __eq__(self, other):
        if isinstance(other, (list, tuple, NodeList)): return list(self) == list(other)
        return NotImplemented
    __hash__ = None
    def __repr__(self): return f'NodeList({list(self)!r})'


class MoverList:
    """Moving-block records in map order, indexed by node so lookups and removals are O(1)."""
    __slots__ = ('_by_node', '_seq')

    def __init__(self, movers=()):
        self._by_node = {}; self._seq = None
        for m in movers: self.append(m)

    def _sequence(self):
        if self._seq is None: self._seq = tuple(self._by_node.values())
        return self._seq

    def append(self, mover): self._by_node[mover['np']] = mover; self._seq = None

    def remove(self, mover):
        if self._by_node.get(mover['np']) is not mover: raise ValueError('mover not in list')
        del self._by_node[mover['np']]; self._seq = None

    def find(self, node): return self._by_node.get(node)
    def __contains__(self, mover):
        return isinstance(mover, dict) and self._by_node.get(mover.get('np')) is mover
    def __iter__(self): return iter(self._sequence())
    def __len__(self): return len(self._by_node)
    def __bool__(self): return bool(self._by_node)
    def __getitem__(self, index):
        seq = self._sequence()
        return list(seq[index]) if isinstance(index, slice) else seq[index]
    def __eq__(self, other):
        if isinstance(other, (list, tuple, MoverList)): return list(self) == list(other)
        return NotImplemented
    __hash__ = None
    def __repr__(self): return f'MoverList({list(self)!r})'


class WorldManager:
    FLOOR_HALF = 1000 # God floor half-size, shared by visuals, ray picking and player physics
    MAP_HEADER = "#DISEPSHUN_MAP,2"
    BOUNCE_RANGE = (0.1, 100.0); MAX_H_RANGE = (0.0, 10000.0); SPEED_RANGE = (0.01, 1000.0); COORD_LIMIT = 10000.0

    def __init__(self, render, loader):
        self.render = render
        self.loader = loader
        self.cubes = NodeList() # Static block nodes (collision only), in save order
        self.cube_map = {}
        self.moving_cubes = MoverList()
        self.block_version = 0 # Bumped whenever blocks are added, removed, converted or edited
        self.mover_index = None # Movers bucketed by cell for this frame's collision queries
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
        self.chunk_contents = {} # 3D chunk key -> insertion-ordered {block node: None}
        self.static_cube_order = {}
        self.next_cube_order = 0
        self.dirty_chunks = set()
        self.empty_chunks = set() # Chunks whose last block left; their collider holders are pruned next frame
        self.god_floor_enabled = False
        
        cm = CardMaker('face')
        # Standard frame: (-0.5, 0.5) creates a card in XZ plane with normal (0, -1, 0)
        cm.setFrame(-0.5, 0.5, -0.5, 0.5)
        cm.setHasNormals(True) 
        cm.setHasUvs(True)
        self.face_node = NodePath(cm.generate())
        # Optimization: Backface Culling (Hides inside of blocks)
        self.face_node.setTwoSided(False)
        # One 24-vertex cube shared by every mover, preview and ghost: one draw call each.
        self.cube_geom = self.make_cube_geom()

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
                    for z in range(math.floor((camera_pos.z-radius-1)/cs), math.floor((camera_pos.z+radius+1)/cs)+1):
                        for c in self.chunk_contents.get((x,y,z), ()):
                            if c.getTag('material') not in ('3','4'): continue
                            d=(c.getPos(self.render)-camera_pos).lengthSquared()
                            if d < 225: nearby.append((d,self.static_cube_order[c],c))
            for i,m in enumerate(self.moving_cubes):
                c=m['np']
                if c.getTag('material') not in ('3','4'): continue
                d=(c.getPos(self.render)-camera_pos).lengthSquared()
                if d < 225: nearby.append((d,self.next_cube_order+i,c))
            # The fixed light budget needs only the nearest few sources. The
            # unique map-order field retains the full sort's tie breaking.
            from heapq import nsmallest
            self.glow_sources=[c for _,_,c in nsmallest(len(self.glow_lights),nearby)]
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
        # Bound rebuilding work vertically too: a tall checkpoint column must
        # not remesh its full height after every placement or activation.
        cs = self.chunk_size
        return (math.floor(pos.x/cs), math.floor(pos.y/cs), math.floor(pos.z/cs))

    def request_chunk_update(self, pos):
        key = self.get_chunk_key(pos)
        self.dirty_chunks.add(key)
        # Mesh faces use rounded logical neighbours, including legacy blocks
        # off the build grid. Dirty their actual chunks on all six sides.
        x,y,z = self.get_grid_key(pos)
        cs = self.chunk_size
        if (2 <= x-key[0]*cs <= cs-2 and 2 <= y-key[1]*cs <= cs-2 and
                2 <= z-key[2]*cs <= cs-2): return
        contents = self.chunk_contents.get(key, ())
        for (nx,ny,nz),_ in self.FACE_DATA:
            neighbor = self.cube_map.get((x+nx,y+ny,z+nz))
            if neighbor is not None and neighbor not in contents:
                self.dirty_chunks.add(self.get_chunk_key(neighbor.getPos()))

    def update_chunks(self, budget_seconds=None):
        if self.empty_chunks: self.prune_chunks()
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

    def make_cube_geom(self):
        """A unit cube centred on its origin, with outward normals and per-face UVs."""
        from array import array
        vertices = array('f'); indices = array('I')
        for (nx,ny,nz),corners in self.FACE_DATA:
            first = len(vertices)//8
            for (dx,dy,dz),(u,v) in zip(corners,((0,0),(1,0),(1,1),(0,1))):
                vertices.extend((dx,dy,dz,nx,ny,nz,u,v))
            indices.extend((first,first+1,first+2,first,first+2,first+3))
        data = GeomVertexData('cube_faces',self.chunk_format,Geom.UHStatic)
        data.modifyArray(0).modifyHandle().setData(vertices.tobytes())
        triangles = GeomTriangles(Geom.UHStatic); triangles.setIndexType(Geom.NTUint32)
        triangles.modifyVertices().modifyHandle().setData(indices.tobytes())
        geom = Geom(data); geom.addPrimitive(triangles)
        node = GeomNode('cube'); node.addGeom(geom)
        return NodePath(node)

    def rebuild_chunk(self, key):
        from array import array
        batches={}
        records=[]; occupied=set()
        for c in self.chunk_contents.get(key, ()):
            if c.isHidden(): continue
            pos=c.getPos(); coords=self.get_grid_key(pos)
            # Snapshot local visibility once. Interior blocks need no per-face
            # traversal, and surface blocks can reuse these neighbor checks.
            if self.cube_map.get(coords) == c: occupied.add(coords)
            records.append((c,pos,coords))
        lookup=self.cube_map.get
        for c,pos,(x,y,z) in records:
            if ((x,y-1,z) in occupied and (x,y+1,z) in occupied and
                (x-1,y,z) in occupied and (x+1,y,z) in occupied and
                (x,y,z+1) in occupied and (x,y,z-1) in occupied):
                if not c.isStashed(): c.stash()
                continue
            appearance=None
            visible=0
            for normal,corners in self.FACE_DATA:
                nx,ny,nz=normal
                neighbor_key=(x+nx,y+ny,z+nz)
                if neighbor_key in occupied: continue
                neighbor=lookup(neighbor_key)
                if neighbor is not None and not neighbor.isHidden(): continue
                # Interior blocks need no material/selection state or vertex data.
                if appearance is None:
                    px,py,pz=pos
                    color=tuple(c.getColor()); scale=tuple(c.getColorScale())
                    tint=c.getPythonTag('selection_color') if c.hasPythonTag('selection_color') else None
                    appearance=(c.getTag('material'),color,scale,c==self.active_checkpoint_cube,tint)
                if appearance not in batches: batches[appearance]=(array('f'),array('I'),c)
                vertices,indices,_=batches[appearance]; first=len(vertices)//8
                (dx0,dy0,dz0),(dx1,dy1,dz1),(dx2,dy2,dz2),(dx3,dy3,dz3)=corners
                vertices.extend((px+dx0,py+dy0,pz+dz0,nx,ny,nz,0,0,
                                 px+dx1,py+dy1,pz+dz1,nx,ny,nz,1,0,
                                 px+dx2,py+dy2,pz+dz2,nx,ny,nz,1,1,
                                 px+dx3,py+dy3,pz+dz3,nx,ny,nz,0,1))
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
        self.chunk_contents.setdefault(key, {})[cube] = None
        if cube not in self.static_cube_order:
            self.static_cube_order[cube] = self.next_cube_order
            self.next_cube_order += 1
        # Spatial bounds let the picking ray skip whole regions of colliders.
        if key not in self.collision_chunks:
            self.collision_chunks[key]=self.platform_holder.attachNewNode(f'chunk_colliders_{key}')
        cube.reparentTo(self.collision_chunks[key])

    def unregister_cube(self, cube):
        k = self.get_chunk_key(cube.getPos())
        contents = self.chunk_contents.get(k)
        if contents is None or cube not in contents: return
        del contents[cube]
        # An edit can expose previously enclosed blocks before the budgeted mesh
        # rebuild runs. Their logical colliders must become pickable immediately.
        if cube.isStashed(): cube.unstash()
        x,y,z = self.get_grid_key(cube.getPos())
        for (nx,ny,nz),_ in self.FACE_DATA:
            neighbor = self.cube_map.get((x+nx,y+ny,z+nz))
            if neighbor is not None and neighbor.isStashed(): neighbor.unstash()
        if contents: return
        # Drop empty chunk bookkeeping so long sessions do not accumulate it. The collider holder may
        # still parent blocks mid-edit, so it is removed by prune_chunks once the edit has moved them.
        del self.chunk_contents[k]
        self.empty_chunks.add(k)

    def prune_chunks(self):
        for k in self.empty_chunks:
            holder = self.collision_chunks.get(k)
            if k not in self.chunk_contents and holder is not None and holder.getNumChildren() == 0:
                del self.collision_chunks[k]; holder.removeNode()
        self.empty_chunks.clear()

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
                coll = cube.find("coll")
                for child in cube.getChildren():
                    if child != coll: child.detachNode()
                if coll.isEmpty():
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
        movers = self.moving_cubes
        if isinstance(movers, MoverList): return movers.find(np)
        return next((mc for mc in movers if mc['np'] == np), None)

    def touch(self):
        """Record that blocks were added, removed or edited: selection caches and the mover index refresh."""
        self.block_version += 1
        self.mover_index = None

    def index_movers(self, positions=None):
        """Bucket mover positions (in map order; read now when not given) by cell, for this frame's collision queries."""
        if positions is None: positions = [m['np'].getPos(self.render) for m in self.moving_cubes]
        cells = {}; floor = math.floor
        for i, (m, p) in enumerate(zip(self.moving_cubes, positions)):
            try: key = (floor(p.x), floor(p.y), floor(p.z))
            except (OverflowError, ValueError): self.mover_index = None; return
            if (bucket := cells.get(key)) is None: cells[key] = [(i, m['np'], p)]
            else: bucket.append((i, m['np'], p))
        self.mover_index = (self.block_version, len(self.moving_cubes), cells)

    def movers_near(self, min_x, max_x, min_y, max_y, min_z, max_z):
        """(node, position) of movers whose unit cube can overlap the box, in map order."""
        count = len(self.moving_cubes)
        if not count: return []
        index = self.mover_index
        # For a handful of movers, checking them directly costs less than
        # constructing and probing every spatial cell in the query box.
        if count > 4 and index is not None and index[0] == self.block_version and index[1] == count:
            try:
                xs = range(math.floor(min_x-.5), math.floor(max_x+.5)+1)
                ys = range(math.floor(min_y-.5), math.floor(max_y+.5)+1)
                zs = range(math.floor(min_z-.5), math.floor(max_z+.5)+1)
            except (OverflowError, ValueError): xs = ys = zs = None
            if xs is not None and len(xs)*len(ys)*len(zs) <= 512:
                cells = index[2]; found = []
                for x in xs:
                    for y in ys:
                        for z in zs:
                            if (bucket := cells.get((x, y, z))): found.extend(bucket)
                if len(found) > 1: found.sort(key=lambda item: item[0])
                return [(node, p) for _, node, p in found]
        return [(m['np'], m['np'].getPos(self.render)) for m in self.moving_cubes]

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
                # The copy shares the cube's vertex data; only the node and its style are per mover.
                geom = self.cube_geom.copyTo(cube); geom.setName("face_geom")
            # Restyle existing faces too, so checkpoint activation changes mover colors
            self.style_face(geom, cube)
            return

        # Appearance changes do not expose neighbouring faces. Only geometry
        # edits need the six-sided invalidation in request_chunk_update().
        self.dirty_chunks.add(self.get_chunk_key(cube.getPos()))

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
        self.touch()
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
        self.touch()
        return True

    def create_platform(self):
        self.platform_holder = self.render.attachNewNode("PlatformHolder")
        self.chunk_contents.clear()
        self.static_cube_order.clear()
        self.next_cube_order = 0
        self.chunks_visual.clear()
        self.collision_chunks.clear()
        
        self.cubes = NodeList(); self.cube_map = {}; self.moving_cubes = MoverList()
        self.god_floor_enabled = False; self.touch()
        
        self.update_chunks()

    def _threaded_save(self, data, gen):
        with self.save_lock:
            # A newer snapshot is already on disk, or queued behind this one and will be written anyway
            if gen <= self.committed_gen or gen < self.save_gen: return
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
        return self._serialize()[0]

    def _serialize(self):
        """Map records and their parallel (group, heading) properties, one entry per block or mover record."""
        buf = [self.MAP_HEADER + "\n"]; props = []
        prop = lambda c: props.append([c.getTag("group"), float(c.getTag("heading") or 0)])
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
                buf.append(l + "\n"); prop(c)
        for m in movers:
            c = m['np']; p = m['origin']
            kind = "L" if m.get("loop",False) else "M"
            l = f"{kind},{p.x},{p.y},{p.z},{c.getTag('material')},{m['speed']},{c.getTag('bounciness') or '1.3'},{c.getTag('max_height') or '0.0'}"
            for w in m['waypoints']: l += f",{w.x},{w.y},{w.z}"
            buf.append(l + "\n"); prop(c)
        return "".join(buf), props

    def all_blocks(self):
        return [c for c in self.cubes if c != self.god_collision_floor] + [m['np'] for m in self.moving_cubes]

    def serialize_map(self, compress=True):
        """Capture scene values now; save writers can compress the immutable byte snapshot."""
        import gzip, json
        records, props = self._serialize()
        payload = {"version": 3, "records": records, "properties": props}
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
                if errors or (props is not None and len(props) != self.parsed_record_count):
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
            props = [props[r['index']] for r in blocks+movers] if props is not None else [['', 0] for _ in blocks+movers]
            payload = dict(version=3, records='\n'.join(records)+'\n', properties=props)
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
        self.parsed_record_count = 0 # Block and mover records, valid or not: the length of a v3 properties list
        for n, line in body:
            parts = [p.strip() for p in line.split(',')]
            index = None
            if v2 and parts[0] in ("B", "M", "L"):
                index = self.parsed_record_count; self.parsed_record_count += 1
            try:
                if line.startswith("#"): raise ValueError("unknown header/comment")
                if parts[0] == "CP":
                    if v2 and parts[1:2] == ["M"] and len(parts) == 3: cp = ('M', int(parts[2]))
                    elif v2 and parts[1:2] == ["S"] and len(parts) == 5: cp = ('S', self._vec(parts[2:5]))
                    elif not v2 and len(parts) == 4: cp = ('P', self._vec(parts[1:4]))
                    else: raise ValueError("bad checkpoint record")
                    continue
                rec = {'bounce': 1.3, 'max_h': 0.0, 'index': index}
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
        if properties is not None and len(properties) != self.parsed_record_count:
            # Keep the blocks; the original file is backed up below because errors is not empty
            errors.append(f"map has {len(properties)} properties for {self.parsed_record_count} records; groups and headings were not loaded")
            properties = None
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

        self.cubes = NodeList(c for c in self.cubes if c == self.god_collision_floor)
        self.static_cube_order.clear()
        self.next_cube_order = 0
        self.cube_map = {}; self.moving_cubes = MoverList(); self.active_checkpoint_cube = None; self.saved_checkpoint_pos = None
        self.touch()

        def apply_properties(c, rec):
            # Each record carries its own properties index, so rejected records drop only their own entry.
            if properties is None or rec.get('index') is None: return
            group, heading = properties[rec['index']]
            if group: c.setTag('group', group)
            c.setTag('heading', str(heading))

        for rec in blocks:
            c = self._make_block(rec)
            self.cubes.append(c); self.cube_map[self.get_grid_key(rec['pos'])] = c
            self.register_cube(c)
            self.request_chunk_update(rec['pos'])
            apply_properties(c, rec)
        for rec in movers:
            c = self._make_block(rec)
            self.moving_cubes.append({'np': c, 'waypoints': rec['waypoints'], 'speed': rec['speed'], 'current_idx': 0, 'origin': rec['pos'], 'direction': 1, 'loop': rec.get('loop',False)})
            self.update_cube_faces(c)
            apply_properties(c, rec)

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
