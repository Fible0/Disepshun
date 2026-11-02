from disepshun.config import *
from disepshun.world_manager import WorldManager
from disepshun.player_physics import PlayerPhysics
from disepshun.game_ui import GameUI
from disepshun.editor_tools import EditorTools
from disepshun.presence import DiscordPresence
import traceback
import json
import math
import shutil

class Disepshun(EditorTools, ShowBase):
    def __init__(self):
        ShowBase.__init__(self)
        ClockObject.getGlobalClock().setMode(ClockObject.MNormal)
        
        wp = WindowProperties()
        wp.setOrigin(0, 0)
        wp.setSize(w, h-1 if user32 else h)
        wp.setUndecorated(True)
        wp.setZOrder(WindowProperties.Z_top)
        wp.setCursorHidden(True)
        self.win.requestProperties(wp)
        if not user32: self.set_x11_icon()
        self.center_mouse()
        self.win.setClearColor((0, 0, 0, 1))
        
        self.cam.node().getLens().setNear(0.1)
        self.cam.node().getLens().setFov(90)
        self.cam.node().getLens().setFar(1000)
        
        self.settings_file = os.path.join(DATA_DIR, "settings.json")
        self.saved_settings = {}
        self.load_settings()
        
        self.sfx = {}
        for filename in sorted(os.listdir(SOUND_DIR)):
            if not filename.endswith('.mp3'): continue
            self.sfx[filename[:-4]] = self.loader.loadSfx(Filename.fromOsSpecific(os.path.join(SOUND_DIR, filename)))
        self.presence = DiscordPresence(self.saved_settings)
        self.world = WorldManager(self.render, self.loader)
        self.physics = PlayerPhysics(self.render, self.camera, self.world)
        
        self.mouse_sensitivity = 1.0
        self.keyMap = {k: False for k in ["w","s","a","d","space","lshift","rshift","lcontrol","rcontrol","mouse1","mouse3","minus","plus","br_l","br_r","z","x"]}
        self.timers = {k: 0 for k in self.keyMap}; self.repeats = {k: 0 for k in self.keyMap}
        self.tool_phases = {tool:'select' for tool in self.TOOL_SLOTS}
        self.tool_mode = 1; self.build_material = 1; self.build_dist = 5
        self.hotbar_page = 0 # 0 = Blocks, 1 = Tools
        
        self.selected_objects = []; self.clipboard = []; self.selection_node = None; self.highlighted_objects = set()
        self.selected_movers = []; self.selected_trampolines = []
        self.wp_node = None; self.wp_markers = []; self.bounce_ghosts = []
        self.gpu_notice_open = False
        self.is_focused = True; self.menu_open = False; self.paused = False
        self.preview_enabled = True; self.preview_shading = True; self.cur_bounce = 1.3; self.cur_h = 0.0
        self.fly_text_timer = 0.0
        self.spawned_cube_count = 0
        self.ctrl_group_tap_pending = False
        self.ignore_mouse_input = False
        self.shown_save_error = None
        
        self.sound_enabled = self.saved_settings.get("Sound", True)
        self.particles_enabled = self.saved_settings.get("Particles", True)
        self.fly_text_enabled = self.saved_settings.get("Fly Speed Text", True)
        
        self.create_preview()
        
        self.set_preview_enabled(self.saved_settings.get("Block Preview", True))
        self.toggle_preview_shading(self.saved_settings.get("Preview Shading", True))
        self.set_visual_floor_visible(self.saved_settings.get("Visual Floor", False))
        self.toggle_shaders(self.saved_settings.get("Shaders", True))
        
        self.setup_ray()
        self.setup_input()
        
        self.world.load_map()
        
        self.world.sky.reparentTo(self.camera)
        if self.world.saved_checkpoint_pos:
            self.physics.checkpoint = self.world.saved_checkpoint_pos + VBase3(0, 0, 1)
            self.physics.player.setPos(self.physics.checkpoint)
            ac = self.world.active_checkpoint_cube
            if ac is not None: self.physics.player.setH(float(ac.getTag("heading") or 0))
        
        self.taskMgr.add(self.update, "update")
        self.taskMgr.add(self.update_world, "worldUpdate")
        
        self.ui = GameUI(self)
        self.set_tool(0)
        
        self.center_mouse()
        self.check_startup_gpu()

    BOOL_SETTINGS = ["Hide Low Power GPU Warning", "Discord Rich Presence", "Discord Show Activity", "Discord Show Block Count", "Discord Show Time", "Discord Show Icon", "Sound", "Particles", "Fly Speed Text", "Block Preview", "Preview Shading", "Visual Floor", "Use Last Selected as Pivot", "Relative Waypoints", "Shaders"]

    def load_settings(self):
        try:
            with open(self.settings_file, 'r') as f:
                data = json.load(f)
        except FileNotFoundError:
            data = {}
        except Exception as e:
            print(f"Settings: could not read {self.settings_file} ({e}); using defaults")
            data = {}
        if not isinstance(data, dict):
            print(f"Settings: {self.settings_file} is not a JSON object; using defaults")
            try: shutil.copy2(self.settings_file, self.settings_file + ".bad")
            except OSError: pass
            data = {}
        for k in self.BOOL_SETTINGS:
            if k in data and not isinstance(data[k], bool):
                print(f"Settings: ignoring {k}={data[k]!r} (expected true/false)")
                del data[k]
        if 'Use Last Selected as Pivot' not in data and 'Relative Waypoints' in data:
            data['Use Last Selected as Pivot']=data['Relative Waypoints']
        data.pop('Relative Waypoints',None)
        data.pop('Discord Application ID',None)
        self.saved_settings = data

    def save_setting(self, key, value):
        self.saved_settings[key] = value
        try:
            os.makedirs(os.path.dirname(self.settings_file), exist_ok=True)
            with open(self.settings_file, 'w') as f:
                json.dump(self.saved_settings, f, indent=4)
        except: pass

    def set_x11_icon(self):
        # Panda3D's X11 window ignores icon-filename, so set _NET_WM_ICON directly
        try:
            import ctypes.util
            x11 = ctypes.CDLL(ctypes.util.find_library("X11"))
            x11.XOpenDisplay.restype = ctypes.c_void_p
            x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
            x11.XInternAtom.restype = ctypes.c_ulong
            x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
            x11.XChangeProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
            x11.XFlush.argtypes = x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
            img = PNMImage(Filename.fromOsSpecific(os.path.join(ROOT_DIR, "assets", "icon.png")))
            iw, ih = img.getXSize(), img.getYSize()
            data = [iw, ih] + [(img.getAlphaVal(x, y) << 24) | (img.getRedVal(x, y) << 16) | (img.getGreenVal(x, y) << 8) | img.getBlueVal(x, y)
                               for y in range(ih) for x in range(iw)]
            arr = (ctypes.c_ulong * len(data))(*data)  # format-32 X properties are C longs
            dpy = x11.XOpenDisplay(None)
            if not dpy: return
            win = self.win.getWindowHandle().getIntHandle()
            x11.XChangeProperty(dpy, win, x11.XInternAtom(dpy, b"_NET_WM_ICON", 0), 6, 32, 0, arr, len(data))  # 6 = CARDINAL, 0 = replace
            x11.XFlush(dpy); x11.XCloseDisplay(dpy)
        except Exception:
            traceback.print_exc()

    def center_mouse(self):
        cx, cy = self.win.getXSize() // 2, self.win.getYSize() // 2
        self.win.movePointer(0, cx, cy)

    CUBE_FACES = [((0, -0.5, 0), 180, 0), ((0, 0.5, 0), 0, 0), ((-0.5, 0, 0), -90, 0), ((0.5, 0, 0), 90, 0), ((0, 0, 0.5), 0, -90), ((0, 0, -0.5), 0, 90)]
    GHOST_FIRST = (1, 0.7, 0.15); GHOST_MAX = (0.7, 0.35, 1) # Amber: first bounce, violet: highest bounce

    def create_preview(self):
        self.preview = NodePath("preview")
        self.preview.reparentTo(self.render)

        for pos, h, p in self.CUBE_FACES:
            f = self.world.face_node.copyTo(self.preview)
            f.setPos(pos); f.setHpr(h, p, 0); f.setTwoSided(True)
            
        self.preview.setTransparency(TransparencyAttrib.MAlpha)
        self.preview.setColorScale(1, 1, 1, 0.5)
        self.preview.setDepthOffset(1)
        # Lighting/Shader state set by toggle_preview_shading
        self.preview.hide()

    def make_ghost(self, color):
        """Bottom half of the player's hitbox, feet at the node's origin: see-through faces with solid edges."""
        w = self.physics.w; h = self.physics.h_stand / 2
        g = self.render.attachNewNode("bounce_ghost")
        body = g.attachNewNode("body"); body.setScale(w, w, h); body.setZ(h / 2)
        for pos, hh, p in self.CUBE_FACES:
            f = self.world.face_node.copyTo(body)
            f.setPos(pos); f.setHpr(hh, p, 0); f.setTwoSided(True)
        body.setColor(*color, 0.25); body.setDepthWrite(False)
        ls = LineSegs(); ls.setColor(*color, 0.85); ls.setThickness(2.0)
        x, y = w / 2, w / 2
        for z in (0, h):
            ls.moveTo(-x, -y, z); ls.drawTo(x, -y, z); ls.drawTo(x, y, z); ls.drawTo(-x, y, z); ls.drawTo(-x, -y, z)
        for cx, cy in ((-x, -y), (x, -y), (x, y), (-x, y)): ls.moveTo(cx, cy, 0); ls.drawTo(cx, cy, h)
        g.attachNewNode(ls.create())
        g.setTransparency(TransparencyAttrib.MAlpha); g.setBin("transparent", 0)
        g.setLightOff(1); g.setShaderOff(1); g.setTextureOff(1)
        return g

    def update_bounce_ghosts(self):
        ts = [t for t in self.selected_trampolines if not t.isEmpty()] if self.tool_mode == 8 else []
        fps = globalClock.getAverageFrameRate(); dt = 1 / round(fps) if fps >= 1 else 1 / 60
        while len(self.bounce_ghosts) < len(ts): self.bounce_ghosts.append((self.make_ghost(self.GHOST_FIRST), self.make_ghost(self.GHOST_MAX)))
        for i, (first, top) in enumerate(self.bounce_ghosts):
            if i >= len(ts): first.hide(); top.hide(); continue
            fh, mh = self.physics.bounce_heights(ts[i], dt)
            base = ts[i].getPos(self.render) + VBase3(0, 0, 0.5)
            first.setPos(base + VBase3(0, 0, fh)); first.show()
            # When the first bounce is already the highest, one ghost marks both
            top.setPos(base + VBase3(0, 0, mh))
            if mh - fh > 0.01: top.show()
            else: top.hide()

    def setup_ray(self):
        self.cTrav = CollisionTraverser(); self.cHandler = CollisionHandlerQueue()
        r = CollisionRay(); r.setFromLens(self.camNode, 0, 0)
        n = CollisionNode('mRay'); n.addSolid(r); n.setFromCollideMask(COLLIDABLE_MASK)
        self.picker = self.camera.attachNewNode(n); self.cTrav.addCollider(self.picker, self.cHandler)

    def setup_input(self):
        map_key = lambda k, v: self.accept(k, self.update_k, [v, True]) or self.accept(k+"-up", self.update_k, [v, False])
        for k in ["w","s","a","d","space","lshift","rshift","lcontrol","rcontrol","z","x"]: map_key("raw-"+k, k)
        for k in ["mouse1","mouse3"]: map_key(k, k)
        map_key("raw-minus", "minus"); map_key("raw-equal", "plus"); map_key("-", "minus"); map_key("=", "plus")
        map_key("raw-[", "br_l"); map_key("raw-]", "br_r")
        
        for i in range(1, 6): self.accept(str(i), self.handle_slot, [i])
        self.accept("q", self.toggle_hotbar)
        self.accept("tab", self.toggle_tool_phase)
        
        self.accept("wheel_up", self.adj_dist, [1]); self.accept("wheel_down", self.adj_dist, [-1])
        self.accept("r", self.undo_wp); self.accept("f", self.toggle_fly); self.accept("g", self.toggle_god); self.accept("escape", self.toggle_menu)
        for key,cmd in [('control-c','copy'),('control-x','cut'),('control-v','paste'),('control-a','all'),('control-d','clear')]:
            self.accept(key,self.left_ctrl_shortcut,[self.selection_command,cmd])
        self.accept('delete',self.selection_command,['delete'])
        self.accept('control-z',self.left_ctrl_shortcut,[self.history_step])
        self.accept('control-y',self.left_ctrl_shortcut,[self.history_step,True])
        events={'editor-button-down'}
        for thrower in (getattr(self,'buttonThrowers',None) or []):
            event=thrower.node().getButtonDownEvent()
            if not event: event='editor-button-down'; thrower.node().setButtonDownEvent(event)
            events.add(event)
        for event in events: self.accept(event,self.note_control_chord)
        for key, delta in [('arrow_left',(-1,0,0)), ('arrow_right',(1,0,0)), ('arrow_up',(0,1,0)), ('arrow_down',(0,-1,0)), ('page_up',(0,0,1)), ('page_down',(0,0,-1))]:
            self.accept(key, self.transform_selection, list(delta))
        self.accept('e', self.transform_selection, [0,0,0,True])
        self.accept('enter', self.checkpoint_face_camera)
        self.disableMouse()

    def note_control_chord(self, button):
        if str(button).split('-')[-1] not in ('control','lcontrol','rcontrol'):
            self.ctrl_group_tap_pending=False

    def left_ctrl_shortcut(self, callback, *args):
        self.ctrl_group_tap_pending=False
        if self.input_blocked() or not self.keyMap.get('lcontrol') or self.keyMap.get('rcontrol'): return
        return callback(*args)

    def update_k(self, k, s):
        if k in ('lcontrol','rcontrol'):
            was=self.keyMap.get(k,False); tap=getattr(self,'ctrl_group_tap_pending',False)
            self.keyMap[k]=s
            if k=='rcontrol': self.ctrl_group_tap_pending=False; return
            if s and not was:
                self.ctrl_group_tap_pending=(self.tool_mode==10 and not self.input_blocked()
                    and not any(value for key,value in self.keyMap.items() if key!='lcontrol'))
                for key in ('mouse1','mouse3','z','x','minus','plus'): self.keyMap[key]=False
            elif not s:
                self.ctrl_group_tap_pending=False
                if was and tap and not self.keyMap.get('rcontrol') and not self.input_blocked(): self.group_selection()
            return
        if s and (self.keyMap.get('lcontrol') or self.keyMap.get('rcontrol')):
            self.ctrl_group_tap_pending=False
            self.keyMap[k]=s if k in ('lshift','rshift') else False
        else: self.keyMap[k]=s
    def input_blocked(self): return self.paused or self.menu_open or getattr(self,"gpu_notice_open",False) or not self.is_focused

    def userExit(self):
        # Write the last edit before the process ends
        self.presence.close()
        if getattr(self, 'glow_filters', None) is not None: self.glow_filters.cleanup()
        self.world.flush_saves()
        ShowBase.userExit(self)

    def toggle_menu(self):
        if getattr(self,"gpu_notice_open",False):
            self.ui.close_gpu_notice(); return
        self.menu_open = not self.menu_open; self.paused = self.menu_open
        self.play_sfx("menu_open" if self.menu_open else "menu_close")
        for k in self.keyMap: self.keyMap[k] = False
        self.ctrl_group_tap_pending=False
        self.ui.set_menu_visible(self.menu_open)
        wp = WindowProperties(); wp.setCursorHidden(not self.menu_open); self.win.requestProperties(wp)
        if not self.menu_open: self.center_mouse()

    def check_startup_gpu(self):
        if self.saved_settings.get('Hide Low Power GPU Warning',False): return
        gsg = self.win.getGsg()
        if gsg is None: return
        from disepshun.gpu_advice import check_renderer
        recommendation = check_renderer(gsg.getDriverRenderer())
        if recommendation is not None: self.ui.show_gpu_notice(recommendation)

    def toggle_fly(self):
        if self.input_blocked(): return
        self.physics.flying = not self.physics.flying; self.physics.vz = 0; self.physics.ground = False
        self.play_sfx("power_on" if self.physics.flying else "power_off")
    def toggle_god(self):
        if self.input_blocked(): return
        self.physics.god_mode = not self.physics.god_mode; self.world.update_god_collision(self.physics.god_mode)
        self.play_sfx("power_on" if self.physics.god_mode else "power_off")
    
    def set_visual_floor_visible(self, v): 
        self.world.visual_floor.show() if v else self.world.visual_floor.hide()
        self.world.update_god_collision(self.physics.god_mode)

    def toggle_shaders(self, v):
        self.world.set_shaders_enabled(v)
        self.set_glow_enabled(v)

    def set_glow_enabled(self, enabled):
        from direct.filter.CommonFilters import CommonFilters
        filters = getattr(self, 'glow_filters', None)
        if not enabled:
            if filters is not None: filters.cleanup()
            self.glow_filters = None
            return
        if filters is not None: return
        # Windowless verification has no post-processing target.
        if not hasattr(self.win, 'getGsg') or self.win.getGsg() is None: return
        filters = CommonFilters(self.win, self.cam)
        if filters.setBloom(blend=(0,0,0,1), mintrigger=.05, maxtrigger=.6,
                            desat=0, intensity=3.0, size='large'):
            self.glow_filters = filters
            # Keep strong, broad halos from washing the glowing faces into pastels.
            vertex = """#version 120
uniform mat4 p3d_ModelViewProjectionMatrix;
attribute vec4 p3d_Vertex;
varying vec2 uv;
void main() {
    gl_Position=p3d_ModelViewProjectionMatrix*p3d_Vertex;
    uv=p3d_Vertex.xz*.5+.5;
}
"""
            fragment = """#version 120
uniform sampler2D scene;
uniform sampler2D halo;
uniform vec2 scene_scale;
uniform vec2 halo_scale;
varying vec2 uv;
void main() {
    vec4 base=texture2D(scene,uv*scene_scale);
    float core=smoothstep(.55,.85,base.a);
    vec3 surface=clamp(base.rgb*mix(1.0,1.15,core),0.0,1.0);
    vec3 glow=clamp(texture2D(halo,uv*halo_scale).rgb*.5,0.0,1.0);
    float pureRed=step(max(glow.g,glow.b)*3.0+.005,glow.r);
    glow.r=min(1.0,glow.r*mix(1.0,2.0,pureRed));
    vec3 combined=1.0-(1.0-glow)*(1.0-surface);
    gl_FragColor=vec4(mix(combined,surface,core),1.0);
}
"""
            filters.finalQuad.setShader(Shader.make(Shader.SL_GLSL,vertex=vertex,fragment=fragment))
            filters.finalQuad.setShaderInput('scene',filters.textures['color'])
            filters.finalQuad.setShaderInput('halo',filters.textures['bloom3'])
            for name,key in (('scene','color'),('halo','bloom3')):
                scale=filters.textures[key].getTexScale()
                filters.finalQuad.setShaderInput(name+'_scale',Vec2(scale.x,scale.y))
        else:
            filters.cleanup()
            self.glow_filters = None
            print('Glow bloom could not be enabled on this graphics device.')

    def toggle_preview_shading(self, v):
        self.preview_shading = v
        if v:
            self.preview.clearLight()
            self.preview.setLightOff(0)
            self.preview.setLight(self.world.dlnp)
            self.preview.setLight(self.world.alnp)
            self.preview.setShaderAuto()
        else:
            self.preview.clearLight()
            self.preview.clearShader()
            self.preview.setLightOff(1)

    def toggle_sound(self, v): 
        self.sound_enabled = v

    def play_sfx(self, name, rate=1.0, volume=1.0):
        s = self.sfx.get(name)
        if not s or not self.sound_enabled: return
        # Preserve checkpoint playback; other cues vary subtly on every play.
        if name != 'checkpoint':
            rate *= random.uniform(.95,1.05)
            volume *= random.uniform(.94,1.0)
        s.stop(); s.setPlayRate(rate); s.setVolume(volume); s.play()

    def play_adjustment(self, name, direction):
        self.play_sfx(name,1.12 if direction>0 else .88)

    def toggle_particles(self, v): 
        self.particles_enabled = v

    def toggle_fly_text(self, v): 
        self.fly_text_enabled = v

    def set_preview_enabled(self, v): 
        self.preview_enabled = v
        self.preview.hide() if not v else None
    
    def toggle_hotbar(self):
        if self.input_blocked(): return
        self.hotbar_page = 1 - self.hotbar_page
        self.ui.update_hotbar_layout(self.hotbar_page)
        self.set_tool(0) # Deselect current tool when switching context

    def handle_slot(self, i):
        if self.input_blocked(): return
        if self.hotbar_page == 0:
            self.set_tool(i)
        elif self.hotbar_page == 1:
            # Tool slots are independent from block material IDs.
            self.set_tool(self.TOOL_SLOTS[i-1])

    def set_tool(self, m):
        if self.tool_mode == m: m = 0
        self.tool_mode = m
        self.selected_objects = []
        self.refresh_object_selection()
        self.deselect_movers(); self.deselect_trampolines()
        self.build_material = m if 1 <= m <= 5 else 0
        self.preview.hide()
        self.play_sfx('tool_equip' if m else 'tool_unequip')
        self.update_hud()

        # Color mapping for preview
        c = {
            1: (1, 1, 1, 1),
            2: (0.4, 0.4, 0.4, 1), # Updated Gray
            3: (1, 0, 0, 1),
            4: (0, 1, 0, 1),
            5: (0, 0, 1, 1)
        }.get(m, (1, 0, 1, 1))
        
        if m != 0: self.preview.setColorScale(*c) # Alpha handled in setColorScale
        self.preview.setTransparency(TransparencyAttrib.MAlpha)
        self.preview.setAlphaScale(0.5)
        
        # Unshaded preview for Movement Tool (7)
        if m == 7:
            self.preview.setLightOff(1)
            self.preview.clearShader()
        else:
            # Respect setting for other blocks
            self.toggle_preview_shading(self.preview_shading)

        v_idx = -1
        if self.hotbar_page == 0:
            if 1 <= m <= 5: v_idx = m - 1
        else:
            if m in self.TOOL_SLOTS: v_idx = self.TOOL_SLOTS.index(m)
        
        self.ui.update_selection(v_idx)
        name = self.TOOL_NAMES.get(m, {1:'White',2:'Gray',3:'Hazard',4:'Checkpoint',5:'Trampoline'}.get(m, ''))
        self.ui.show_item_name(name + (' Tool' if m in self.TOOL_SLOTS else ''))

    def adj_dist(self, d): 
        if not self.is_focused: return
        if self.menu_open:
            self.ui.scroll_menu(d)
        elif not self.paused:
            self.build_dist = max(1, min(20, self.build_dist + d))
    
    def adj_val(self, d):
        if not self.tinkering(): return
        if self.tool_mode==9: return self.adjust_checkpoint(d)
        if self.tool_mode==7:
            nodes=self.selected_objects or [m['np'] for m in self.selected_movers]
            if not nodes: return
            token=self.begin_edit(nodes); self.ensure_selected_movers()
            for m in self.selected_movers: m['speed']=min(1000.0,max(.5,round(m['speed']+d*.5,1)))
            self.finish_edit(token,[m['np'] for m in self.selected_movers],'mover_speed')
            self.update_hud(); self.world.map_is_dirty=True; self.world.save_map(); self.play_adjustment('mover_speed',d)
        elif self.tool_mode==8 and self.selected_trampolines:
            token=self.begin_edit(self.selected_trampolines)
            self.cur_bounce=min(100,max(.1,round(self.cur_bounce+d*.1,1)))
            for t in self.selected_trampolines: t.setTag('bounciness',str(self.cur_bounce))
            self.finish_edit(token,self.selected_trampolines,'trampoline_bounce')
            self.world.map_is_dirty=True; self.world.save_map(); self.play_adjustment('trampoline_bounce',d); self.update_hud()

    def adj_h(self, d):
        if not self.tinkering(): return
        if self.tool_mode==8 and self.selected_trampolines:
            token=self.begin_edit(self.selected_trampolines)
            self.cur_h=min(10000,max(0,round(self.cur_h+d*.5,1)))
            for t in self.selected_trampolines: t.setTag('max_height',str(self.cur_h))
            self.finish_edit(token,self.selected_trampolines,'trampoline_height')
            self.world.map_is_dirty=True; self.world.save_map(); self.play_adjustment('trampoline_height',d); self.update_hud()

    def adj_fly(self, d):
        previous = self.physics.fly_speed
        self.physics.fly_speed = max(1.0, round(previous + d, 1))
        if self.physics.fly_speed != previous: self.play_adjustment('flight_speed',self.physics.fly_speed-previous)
        if not self.ui.gui_hidden and self.fly_text_enabled:
            self.ui.fly_text.setText(f"Fly Speed: {self.ui.format_number(self.physics.fly_speed)}"); self.ui.fly_text.show(); self.ui.fly_text.setAlphaScale(1.0); self.fly_text_timer = 3.0

    def handle_sel(self, mode):
        if mode == 7: return self.select_object()

    def handle_place_wp(self):
        if not self.tinkering() or self.tool_mode != 7: return
        if self.preview.getZ() < -19.5: return # Same world-height rule as block placement; visibility is only a display setting
        nodes=self.selected_objects or [m['np'] for m in self.selected_movers]
        if not nodes: return
        token=self.begin_edit(nodes)
        self.ensure_selected_movers()
        pos = self.preview.getPos(); c = len(self.selected_movers)
        if c > 0:
            ref = self.reference_point([m['origin'] for m in self.selected_movers])

            off = pos - ref
            for m in self.selected_movers: m['waypoints'].append(m['origin'] + off)
            self.finish_edit(token,[m['np'] for m in self.selected_movers],'waypoint_add')
            self.draw_wp(); self.world.map_is_dirty = True; self.world.save_map(); self.play_sfx("waypoint_add")

    def deselect_movers(self):
        for m in self.selected_movers: m['np'].clearColorScale()
        self.selected_movers = []; self.draw_wp()

    def deselect_trampolines(self):
        for t in self.selected_trampolines: 
            t.clearColorScale(); t.setColor(0,0,1,1)
            self.world.request_chunk_update(t.getPos())
        self.selected_trampolines = []

    def undo_wp(self):
        if not self.tinkering(): return
        if self.tool_mode == 7 and self.selected_movers:
            token=self.begin_edit([m['np'] for m in self.selected_movers])
            for m in self.selected_movers:
                if m['waypoints']: 
                    m['waypoints'].pop()
            self.finish_edit(token,[m['np'] for m in self.selected_movers],'waypoint_remove')
            self.draw_wp(); self.world.map_is_dirty = True; self.world.save_map(); self.play_sfx("waypoint_remove")

    def draw_wp(self):
        if self.wp_node: self.wp_node.removeNode(); self.wp_node = None
        for m in self.wp_markers: m.removeNode()
        self.wp_markers = []
        if not self.selected_movers: return
        ls = LineSegs(); ls.setColor(1,0,1,1); ls.setThickness(2.0)
        cm = CardMaker('m'); cm.setFrame(-0.1, 0.1, -0.1, 0.1); mg = cm.generate()
        for mc in self.selected_movers:
            pts = [mc['origin']] + mc['waypoints']
            if len(pts) > 1:
                ls.moveTo(pts[0])
                for p in pts[1:]: ls.drawTo(p)
                if len(pts) > 2: ls.drawTo(pts[0])
            for p in pts:
                np = self.render.attachNewNode(mg); np.setPos(p); np.setBillboardPointEye(); np.setColor(1,0,1,1); np.setDepthTest(False); np.setBin("fixed", 1); self.wp_markers.append(np)
        self.wp_node = self.render.attachNewNode(ls.create()); self.wp_node.setDepthTest(False); self.wp_node.setBin("fixed", 1)

    def update_hud(self):
        if self.tool_mode not in self.TOOL_SLOTS:
            self.ui.tool_text.setText(''); return
        fmt = self.ui.format_number
        combined = self.tool_mode in self.COMBINED_TOOLS
        phase = self.tool_phases[self.tool_mode]
        count = len(self.selected_objects)
        mode_hint = '' if combined else f" | {phase.upper()} [Tab]"
        header = f"{self.TOOL_NAMES[self.tool_mode].upper()} TOOL{mode_hint}\nSelected: {count}\n"
        self.ui.tool_text.setFg(self.SELECTION_COLORS[self.tool_mode])
        if not combined and phase == 'select':
            body = '[L-Click] Select / deselect'
            if self.tool_mode == 11: body += '\n[LCtrl+A/D] Select all / Clear'
            body += '\n[Tab] Tinker with selection'
        elif self.tool_mode == 7:
            speed = self.selected_movers[-1]['speed'] if self.selected_movers else 3.0
            body = f'Speed: {fmt(speed)} [-/+]\n[R-Click] Add waypoint | [R] Undo waypoint'
        elif self.tool_mode == 8:
            body = f'[L-Click] Select / deselect\nBounce: {fmt(self.cur_bounce)} [-/+]\nMax H: {fmt(self.cur_h)} [Z/X]'
        elif self.tool_mode == 9:
            heading = float(self.selected_objects[-1].getTag('heading') or 0) if self.selected_objects else 0
            body = f'[L-Click] Select / deselect\nFacing: {heading:.0f}\n[-/+] Turn 15 degrees | [Enter] Face camera'
        elif self.tool_mode == 10:
            body = '[L-Click] Select / deselect\n[LCtrl] Group / Ungroup'
        else:
            body = ('[R-Click] Move here | [Arrows / PgUp/PgDn] Move\n'
                    '[E] Rotate | [Delete] Delete\n[LCtrl+C/X/V] Copy / Cut / Paste')
        if self.tool_mode==11: body+='\nCyan point: center / pivot'
        self.ui.tool_text.setText(header + body)

    def repeat(self, k, t, f):
        if self.keyMap[k]:
            if self.timers[k] == 0: f(1 if k in ["plus","br_r","x"] else -1); self.timers[k] = t; self.repeats[k] = t + 0.5
            elif t >= self.repeats[k]: f(1 if k in ["plus","br_r","x"] else -1); self.repeats[k] = t + 0.1
        else: self.timers[k] = 0

    def update(self, task):
        filters=getattr(self,'glow_filters',None)
        if filters is not None:
            for name,key in (('scene','color'),('halo','bloom3')):
                scale=filters.textures[key].getTexScale()
                filters.finalQuad.setShaderInput(name+'_scale',Vec2(scale.x,scale.y))
        self.presence.tick('In settings' if self.menu_open else self.TOOL_NAMES.get(self.tool_mode, 'Building' if self.build_material else 'Exploring'), len(self.world.cubes)+len(self.world.moving_cubes)-int(self.physics.god_mode and not self.world.visual_floor.isHidden()))
        foc = (self.win.getWindowHandle().getIntHandle() == user32.GetForegroundWindow()) if user32 else self.win.getProperties().getForeground()
        if foc != self.is_focused:
            self.is_focused = foc; wp = WindowProperties()
            if not foc:
                self.ctrl_group_tap_pending=False
                for key in self.keyMap: self.keyMap[key]=False
            wp.setCursorHidden(False if self.menu_open or getattr(self,"gpu_notice_open",False) or not foc else True); wp.setZOrder(WindowProperties.Z_top if foc else WindowProperties.Z_normal); self.win.requestProperties(wp)
            if self.is_focused and not self.menu_open and not getattr(self,"gpu_notice_open",False):
                self.center_mouse()
                self.ignore_mouse_input = True
        
        if not foc: return task.cont
        dt = globalClock.getDt(); t = globalClock.getFrameTime()
        self.ui.update_item_name(dt)
        self.ui.update_presence_status()
        self.ui.fps_text.setText(f"FPS: {round(globalClock.getAverageFrameRate())}")
        
        if self.fly_text_timer > 0 and not self.paused:
            self.fly_text_timer -= dt
            if not self.ui.gui_hidden and self.fly_text_enabled: self.ui.fly_text.show(); self.ui.fly_text.setAlphaScale(min(1.0, self.fly_text_timer))
            else: self.ui.fly_text.hide()
        elif self.fly_text_timer <= 0: self.ui.fly_text.hide()

        if self.paused: return task.cont

        if self.keyMap["mouse3"]:
            if self.timers["mouse3"] == 0: self.place(); self.timers["mouse3"] = t; self.repeats["mouse3"] = t + 0.5
            elif t >= self.repeats["mouse3"] and self.tool_mode not in self.TOOL_SLOTS: self.place(); self.repeats["mouse3"] = t + 0.1
        else: self.timers["mouse3"] = 0
        
        if self.keyMap["mouse1"]:
            if self.timers["mouse1"] == 0: self.delete(); self.timers["mouse1"] = t; self.repeats["mouse1"] = t + 0.5
            elif t >= self.repeats["mouse1"] and self.tool_mode not in self.TOOL_SLOTS: self.delete(); self.repeats["mouse1"] = t + 0.1
        else: self.timers["mouse1"] = 0

        self.repeat("minus", t, self.adj_val); self.repeat("plus", t, self.adj_val)
        self.repeat("br_l", t, self.adj_fly); self.repeat("br_r", t, self.adj_fly)
        self.repeat("z", t, self.adj_h); self.repeat("x", t, self.adj_h)

        if self.mouseWatcherNode.hasMouse():
            md = self.win.getPointer(0); x = md.getX(); y = md.getY(); cx = self.win.getXSize()//2; cy = self.win.getYSize()//2
            if x != cx or y != cy:
                if self.ignore_mouse_input:
                    self.ignore_mouse_input = False
                    self.win.movePointer(0, cx, cy)
                else:
                    self.physics.player.setH(self.physics.player.getH() - (x - cx) * 0.1 * self.mouse_sensitivity)
                    self.camera.setP(max(-89, min(89, self.camera.getP() - (y - cy) * 0.1 * self.mouse_sensitivity)))
                    self.win.movePointer(0, cx, cy)

        self.physics.update(dt, self.keyMap)
        if not self.physics.god_mode and self.physics.player.getZ() < -20: self.physics.respawn()

        if ((self.tool_mode in (7, 11) and self.tinkering()) or self.build_material != 0):
            self.cTrav.traverse(self.render)
            pl = VBase3(); ok = False
            if self.cHandler.getNumEntries() > 0:
                self.cHandler.sortEntries(); e = self.cHandler.getEntry(0); hp = e.getSurfacePoint(self.render)
                if (hp - self.camera.getPos(self.render)).length() <= self.build_dist:
                    p = e.getIntoNodePath().getParent()
                    if p.getName().startswith("chunk_") or p in self.world.cubes or p.hasTag("material") or any(mc['np'] == p for mc in self.world.moving_cubes):
                        if p == self.world.god_collision_floor: pl.set(round(hp.x), round(hp.y), -19.5)
                        else:
                            n = e.getSurfaceNormal(self.render)
                            if p in self.world.cubes or p.hasTag("material"):
                                cp = p.getPos(self.render)
                            elif any(mc['np'] == p for mc in self.world.moving_cubes):
                                cp = p.getPos(self.render)
                            else: 
                                center = hp - n * 0.5
                                cp = VBase3(math.floor(center.x + 0.5), math.floor(center.y + 0.5), math.floor(center.z + 0.5) - 0.5)

                            an = VBase3(abs(n.x), abs(n.y), abs(n.z))
                            if an.x > an.y and an.x > an.z: pl = cp + VBase3(round(n.x), 0, 0)
                            elif an.y > an.x and an.y > an.z: pl = cp + VBase3(0, round(n.y), 0)
                            else: pl = cp + VBase3(0, 0, round(n.z))
                            
                            pl = VBase3(math.floor(pl.x + 0.5), math.floor(pl.y + 0.5), math.floor(pl.z) + 0.5)
                        ok = True
            if ok: 
                self.preview.setPos(pl)
            else:
                tp = self.camera.getPos(self.render) + self.camera.getQuat(self.render).getForward() * self.build_dist
                self.preview.setPos(VBase3(math.floor(tp.x + 0.5), math.floor(tp.y + 0.5), math.floor(tp.z) + 0.5))
            
            if self.preview_enabled and self.preview.getZ() >= -19.5:
                self.preview.show()
            else:
                self.preview.hide()
        else: 
            self.preview.hide()

        self.refresh_object_selection()
        self.draw_checkpoint_direction()
        self.update_bounce_ghosts()
        self.world.update_chunks(budget_seconds=.0025)
        self.world.update_glow_lights(self.camera.getPos(self.render))
        self.world.retry_save(t)
        if self.world.save_error != self.shown_save_error:
            self.shown_save_error = self.world.save_error
            if self.shown_save_error:
                self.ui.fly_text.setText(self.shown_save_error); self.ui.fly_text.show(); self.ui.fly_text.setAlphaScale(1.0); self.fly_text_timer = 5.0
        return task.cont

    def update_world(self, task):
        if self.paused or (self.is_focused is not None and not self.is_focused): return task.cont
        dt = globalClock.getDt()
        carry = None; carry_top = -float('inf'); moved = {}
        pp = self.physics.player.getPos()
        for m in self.world.moving_cubes:
            pts = [m['origin']] + m['waypoints']
            if not pts: continue
            
            m['current_idx'] = m['current_idx'] % len(pts)
            tgt = pts[m['current_idx']]
            curr = m['np'].getPos(); d = (tgt - curr).length(); s = m['speed'] * dt

            # Support is decided from the platform's position before it moves
            if not self.physics.flying and abs(pp.x - curr.x) < 0.8 and abs(pp.y - curr.y) < 0.8 and curr.z + 0.45 <= pp.z <= curr.z + 0.6 and curr.z > carry_top:
                carry = m; carry_top = curr.z
            
            if d <= s:
                m['np'].setPos(tgt)
                if len(pts) > 1:
                    di = m.get('direction', 1)
                    nxt = m['current_idx'] + di
                    if nxt >= len(pts):
                        m['direction'] = -1
                        nxt = len(pts) - 2
                    elif nxt < 0:
                        m['direction'] = 1
                        nxt = 1
                    m['current_idx'] = nxt
                else:
                     m['current_idx'] = 0
            else: 
                m['np'].setPos(curr + (tgt - curr) / d * s)
            moved[id(m)] = m['np'].getPos() - curr

        if carry is not None:
            move = moved[id(carry)]
            if move.lengthSquared() > 0:
                # Blocks moving in lockstep with the carrier can't block the rider
                same = [m['np'] for m in self.world.moving_cubes if id(m) in moved and (moved[id(m)] - move).lengthSquared() < 1e-10]
                self.physics.carry(move, ignore=same)
        self.draw_selection_center()
        return task.cont

    def place(self):
        if self.input_blocked(): return
        if self.tool_mode == 11: return self.transform_selection(to_cursor=True)
        if self.tool_mode == 10: return
        if self.tool_mode in (8, 9): return
        if self.tool_mode == 7: return self.handle_place_wp()
        if self.build_material == 0: return
        if self.preview.getZ() < -19.5: return
        pos = self.preview.getPos()
        
        k = self.world.get_grid_key(pos)
        if k in self.world.cube_map: return

        for mc in self.world.moving_cubes:
            mp = mc['np'].getPos()
            if abs(mp.x - pos.x) < 0.99 and abs(mp.y - pos.y) < 0.99 and abs(mp.z - pos.z) < 0.99:
                return

        # Find the targeted block before adding the new one, so the ray can't hit the new block
        target = None
        self.cTrav.traverse(self.render)
        if self.cHandler.getNumEntries() > 0:
            self.cHandler.sortEntries(); target = self.world.find_mover(self.cHandler.getEntry(0).getIntoNodePath().getParent())

        token=self.begin_edit([])
        self.spawned_cube_count += 1
        c = self.world.get_cube(f"c_{self.spawned_cube_count}")
        mat = self.build_material
        col = {1:(1,1,1,1), 2:(0.4,0.4,0.4,1), 3:(1,0,0,1), 4:(0,1,0,1), 5:(0,0,1,1)}.get(mat)
        c.setColor(col); c.setTag("material", str(mat))
        if mat == 5: c.setTag("bounciness", str(self.cur_bounce)); c.setTag("max_height", str(self.cur_h))
        c.setPos(pos); c.reparentTo(self.world.platform_holder)

        if target:
            # Attach: the new block joins the targeted mover's path in lockstep; no other mover is touched
            mc = target; mp = mc['np'].getPos(); off = pos - mp
            off = VBase3(math.floor(off.x+0.5), math.floor(off.y+0.5), math.floor(off.z+0.5))
            no = mc['origin'] + off
            c.setPos(mp + off)
            nw = [no + (w - mc['origin']) for w in mc['waypoints']]
            self.world.convert_to_mover(c, {'waypoints': nw, 'speed': mc['speed'], 'current_idx': mc['current_idx'], 'wait_timer': 0, 'origin': no, 'direction': mc.get('direction', 1)})
        else:
            self.world.cubes.append(c); self.world.cube_map[k] = c
            self.world.register_cube(c)
            self.world.request_chunk_update(pos)
        self.finish_edit(token,[c],'place')
        self.world.queue_save()
        self.play_sfx("place", random.uniform(0.95, 1.05))

        pos = c.getPos(); pp = self.physics.player.getPos()
        if abs(pp.x - pos.x) < 0.9 and abs(pp.y - pos.y) < 0.9 and pp.z < pos.z + 0.5 and pp.z + self.physics.player_height > pos.z - 0.5:
            self.physics.player.setZ(pos.z + 0.5); self.physics.vz = 0; self.physics.ground = True

    def delete(self):
        if self.input_blocked(): return
        if self.tool_mode == 7: return self.handle_sel(7)
        elif self.tool_mode in (8, 9, 10, 11): return self.select_object()
        self.cTrav.traverse(self.render)
        if self.cHandler.getNumEntries() > 0:
            self.cHandler.sortEntries(); np = self.cHandler.getEntry(0).getIntoNodePath(); p = np.getParent()
            
            target = p
            if p.getName().startswith("chunk_"):
                hp = self.cHandler.getEntry(0).getSurfacePoint(self.render)
                n = self.cHandler.getEntry(0).getSurfaceNormal(self.render)
                center = hp - n * 0.5
                k = self.world.get_grid_key(center)
                if k in self.world.cube_map:
                    target = self.world.cube_map[k]

            if self.delete_objects([target]):
                self.world.map_is_dirty=True; self.world.save_map()
                self.play_sfx('break',random.uniform(.95,1.05))

try:
    app = Disepshun()
    app.run()
except Exception: traceback.print_exc()