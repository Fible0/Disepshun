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
        
        self.settings_file = os.path.join(DATA_DIR, "settings.json.gz")
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
        
        if self.world.saved_checkpoint_pos:
            self.physics.checkpoint = self.world.saved_checkpoint_pos + VBase3(0, 0, 1)
            self.physics.set_spawn_position(self.physics.checkpoint)
            ac = self.world.active_checkpoint_cube
            if ac is not None: self.physics.player.setH(float(ac.getTag("heading") or 0))
        
        self.taskMgr.add(self.update, "update")
        self.taskMgr.add(self.update_world, "worldUpdate", sort=-10)
        
        self.ui = GameUI(self)
        self.set_tool(0)
        
        self.center_mouse()
        self.check_startup_gpu()

    DEFAULT_SETTINGS = dict.fromkeys([
        "Crosshair", "FPS Counter", "Tool Info", "Inventory", "Sound", "Particles",
        "Fly Speed Text", "Block Preview", "Preview Shading", "Shaders",
        "Discord Rich Presence", "Discord Show Activity", "Discord Show Block Count",
        "Discord Show Time", "Discord Show Icon"], True)
    DEFAULT_SETTINGS.update(dict.fromkeys([
        "Visual Floor", "Use Last Selected as Pivot", "GPU Notice Shown",
        "Cap Frame Rate"], False))
    BOOL_SETTINGS = list(DEFAULT_SETTINGS) + ["Relative Waypoints"]

    def load_settings(self):
        import gzip
        source = self.settings_file
        legacy = source[:-3] if source.endswith('.gz') else None
        if not os.path.exists(source) and legacy and os.path.exists(legacy): source = legacy
        try:
            with open(source, 'rb') as f: raw = f.read()
            data = json.loads(gzip.decompress(raw) if raw.startswith(b'\x1f\x8b') else raw)
        except FileNotFoundError:
            data = {}
        except Exception as e:
            print(f"Settings: could not read {source} ({e}); using defaults")
            data = {}
        if not isinstance(data, dict):
            print(f"Settings: {source} is not a JSON object; using defaults")
            try: shutil.copy2(source, source + ".bad")
            except OSError: pass
            data = {}
        for k in self.BOOL_SETTINGS:
            if k in data and not isinstance(data[k], bool):
                print(f"Settings: ignoring {k}={data[k]!r} (expected true/false)")
                del data[k]
        if 'Use Last Selected as Pivot' not in data and 'Relative Waypoints' in data:
            data['Use Last Selected as Pivot']=data['Relative Waypoints']
        self.saved_settings = {k:v for k,v in data.items()
                               if k in self.DEFAULT_SETTINGS and v != self.DEFAULT_SETTINGS[k]}
        if legacy and source == legacy:
            if self.write_settings():
                try: os.remove(legacy)
                except OSError: pass

    def write_settings(self):
        import gzip
        tmp = self.settings_file + '.tmp'
        try:
            os.makedirs(os.path.dirname(self.settings_file), exist_ok=True)
            raw = json.dumps(self.saved_settings, separators=(',',':')).encode('utf8')
            with open(tmp, 'wb') as f: f.write(gzip.compress(raw, mtime=0))
            os.replace(tmp, self.settings_file)
            return True
        except OSError as e:
            print(f"Settings: could not save {self.settings_file} ({e})")
            return False

    def save_setting(self, key, value):
        if key not in self.DEFAULT_SETTINGS: return
        if value == self.DEFAULT_SETTINGS[key]: self.saved_settings.pop(key, None)
        else: self.saved_settings[key] = value
        self.write_settings()

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
        # The warp can be dropped (e.g. XWayland ignores it while the cursor is still visible,
        # and the hide request only applies next frame) while Panda caches the pointer as
        # centred. The next real motion then reports the old menu position, so discard the
        # first off-centre reading and re-centre instead of turning the camera with it.
        self.ignore_mouse_input = True

    GHOST_FIRST = (1, 0.7, 0.15); GHOST_MAX = (0.7, 0.35, 1) # Amber: first bounce, violet: highest bounce

    def create_preview(self):
        self.preview = NodePath("preview")
        self.preview.reparentTo(self.render)
        self.world.cube_geom.copyTo(self.preview).setTwoSided(True)
            
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
        self.world.cube_geom.copyTo(body).setTwoSided(True)
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
        dt = self.PHYSICS_STEP # Physics runs on a fixed step, so bounces are the same at any frame rate
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

    PICK_FAR = 1000.0 # Camera far plane: selection and deletion reach anything visible

    def setup_ray(self):
        self.cTrav = CollisionTraverser(); self.cHandler = CollisionHandlerQueue()
        # A segment along the view axis; its length is set per query, so build previews skip distant blocks.
        self.pick_segment = CollisionSegment(0, 0, 0, 0, self.PICK_FAR, 0)
        n = CollisionNode('mRay'); n.addSolid(self.pick_segment); n.setFromCollideMask(COLLIDABLE_MASK)
        self.picker = self.camera.attachNewNode(n); self.cTrav.addCollider(self.picker, self.cHandler)

    def traverse_pick(self, length=None):
        """Collect blocks hit along the view axis, up to length (the camera far plane by default)."""
        segment = getattr(self, 'pick_segment', None)
        if segment is not None:
            length = self.PICK_FAR if length is None else float(length)
            if segment.getPointB().y != length: segment.setPointB(0, length, 0)
        self.cTrav.traverse(self.render)

    def setup_input(self):
        def bind_action(event, callback, args=None):
            self.accept(event, callback, [] if args is None else args)
            # Panda prefixes ordinary button events with Shift while crouching.
            if event.startswith('control-'):
                for prefix in ('control-shift-','shift-control-'):
                    self.accept(prefix+event[len('control-'):], callback, [] if args is None else args)
            else:
                self.accept('shift-'+event, callback, [] if args is None else args)
        def map_key(key, value):
            bind_action(key, self.update_k, [value, True])
            bind_action(key+'-up', self.update_k, [value, False])
        for k in ["w","s","a","d","space","lshift","rshift","lcontrol","rcontrol","z","x"]: map_key("raw-"+k, k)
        for k in ["mouse1","mouse3"]: map_key(k, k)
        map_key("raw-minus", "minus"); map_key("raw-equal", "plus"); map_key("-", "minus"); map_key("=", "plus")
        map_key("raw-[", "br_l"); map_key("raw-]", "br_r")
        
        for i in range(1, 7): bind_action(str(i), self.handle_slot, [i])
        bind_action("q", self.toggle_hotbar)
        bind_action("tab", self.toggle_tool_phase)
        bind_action("h", self.toggle_fill_solid)
        bind_action("l", self.toggle_mover_loop)
        
        bind_action("wheel_up", self.adj_dist, [1]); bind_action("wheel_down", self.adj_dist, [-1])
        bind_action("f", self.toggle_fly); bind_action("g", self.toggle_god); bind_action("escape", self.toggle_menu)
        for key,cmd in [('control-c','copy'),('control-x','cut'),('control-v','paste'),('control-a','all'),('control-d','clear')]:
            bind_action(key,self.left_ctrl_shortcut,[self.selection_command,cmd])
        bind_action('delete',self.selection_command,['delete'])
        bind_action('control-z',self.left_ctrl_shortcut,[self.history_step])
        bind_action('control-y',self.left_ctrl_shortcut,[self.history_step,True])
        events={'editor-button-down'}
        for thrower in (getattr(self,'buttonThrowers',None) or []):
            event=thrower.node().getButtonDownEvent()
            if not event: event='editor-button-down'; thrower.node().setButtonDownEvent(event)
            events.add(event)
        for event in events: bind_action(event,self.note_control_chord)
        for key, delta in [('arrow_left',(-1,0,0)), ('arrow_right',(1,0,0)), ('arrow_up',(0,1,0)), ('arrow_down',(0,-1,0)), ('page_up',(0,0,1)), ('page_down',(0,0,-1))]:
            bind_action(key, self.transform_selection, list(delta))
        bind_action('e', self.transform_selection, [0,0,0,True])
        bind_action('t', self.transform_selection, [0,0,0,True,False,'x'])
        bind_action('enter', self.checkpoint_face_camera)
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
        # The notice explains Windows' per-app GPU setting; other platforms have no equivalent to point to.
        if os.name != 'nt' or self.saved_settings.get('GPU Notice Shown',False): return
        gsg = self.win.getGsg()
        if gsg is None: return
        from disepshun.gpu_advice import renderer_info
        info = renderer_info(gsg.getDriverRenderer())
        self.ui.show_gpu_notice(info)
        self.save_setting('GPU Notice Shown', True)

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
        from disepshun.bloom import NeonBloom
        filters = getattr(self, 'glow_filters', None)
        if not enabled:
            if filters is not None: filters.cleanup()
            self.glow_filters = None
            return
        if filters is not None: return
        # Windowless verification has no post-processing target.
        if not hasattr(self.win, 'getGsg') or self.win.getGsg() is None: return
        filters = NeonBloom(self.win, self.cam)
        if filters.ok:
            self.glow_filters = filters
        else:
            filters.cleanup()
            self.glow_filters = None
            print('Glow bloom could not be enabled on this graphics device.')

    def toggle_preview_shading(self, v):
        self.preview_shading = v
        if v and self.tool_mode not in self.TOOL_SLOTS:
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

    def play_sfx(self, name, rate=1.0, volume=1.0, start=0.0):
        s = self.sfx.get(name)
        if not s or not self.sound_enabled: return
        # Preserve checkpoint playback; other cues vary subtly on every play.
        if name != 'checkpoint':
            rate *= random.uniform(.95,1.05)
            volume *= random.uniform(.94,1.0)
        s.stop(); s.setPlayRate(rate); s.setVolume(volume)
        if start: s.setTime(start)
        s.play()

    def play_block_action(self, right_click):
        self.play_sfx('place' if right_click else 'break', random.uniform(.95,1.05))

    def play_adjustment(self, direction):
        self.play_sfx('checkpoint_turn',1.12 if direction>0 else .88)

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
        self.set_tool(0, play_sound=False) # Deselect when switching context
        self.play_sfx('hotbar_tools' if self.hotbar_page else 'hotbar_blocks')

    def handle_slot(self, i):
        if self.input_blocked(): return
        if self.hotbar_page == 0:
            if i > 5: return
            self.set_tool(i)
        elif self.hotbar_page == 1:
            # Tool slots are independent from block material IDs.
            self.set_tool(self.TOOL_SLOTS[i-1])

    def set_tool(self, m, play_sound=True):
        if self.tool_mode == m: m = 0
        self.tool_mode = m
        self.fill_start = None
        self.selected_objects = []
        self.refresh_object_selection()
        self.deselect_movers(); self.deselect_trampolines()
        self.build_material = m if 1 <= m <= 5 else 0
        self.preview.hide()
        if play_sound: self.play_sfx('tool_equip' if m else 'tool_unequip')
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
        
        # All tools share the Waypoint preview; block previews follow the setting.
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
        if self.tool_mode==12:
            self.fill_material = (getattr(self, 'fill_material', 1)-1+d) % 6+1
            self.play_sfx('toggle', 1.12 if d > 0 else .88); self.update_hud(); return
        if self.tool_mode==9: return self.adjust_checkpoint(d)
        if self.tool_mode==7:
            nodes=self.selected_objects or [m['np'] for m in self.selected_movers]
            if not nodes: return
            token=self.begin_edit(nodes); self.ensure_selected_movers()
            for m in self.selected_movers: m['speed']=min(1000.0,max(.5,round(m['speed']+d*.5,1)))
            self.finish_edit(token,[m['np'] for m in self.selected_movers],'mover_speed')
            self.update_hud(); self.world.touch(); self.world.queue_save(); self.play_adjustment(d)
        elif self.tool_mode==8 and self.selected_trampolines:
            token=self.begin_edit(self.selected_trampolines)
            self.cur_bounce=min(100,max(.1,round(self.cur_bounce+d*.1,1)))
            for t in self.selected_trampolines: t.setTag('bounciness',str(self.cur_bounce))
            self.finish_edit(token,self.selected_trampolines,'trampoline_bounce')
            self.world.queue_save(); self.play_adjustment(d); self.update_hud()

    def adj_h(self, d):
        if not self.tinkering(): return
        if self.tool_mode==8 and self.selected_trampolines:
            token=self.begin_edit(self.selected_trampolines)
            self.cur_h=min(10000,max(0,round(self.cur_h+d*.5,1)))
            for t in self.selected_trampolines: t.setTag('max_height',str(self.cur_h))
            self.finish_edit(token,self.selected_trampolines,'trampoline_height')
            self.world.queue_save(); self.play_adjustment(d); self.update_hud()

    def adj_fly(self, d):
        previous = self.physics.fly_speed
        self.physics.fly_speed = max(1.0, round(previous + d, 1))
        if self.physics.fly_speed != previous: self.play_adjustment(self.physics.fly_speed-previous)
        if not self.ui.gui_hidden and self.fly_text_enabled:
            self.ui.fly_text.setText(f"Fly Speed: {self.ui.format_number(self.physics.fly_speed)}"); self.ui.fly_text.show(); self.ui.fly_text.setAlphaScale(1.0); self.fly_text_timer = 3.0

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
            self.draw_wp(); self.world.touch(); self.world.queue_save(); self.play_block_action(True)

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
        if self.tool_mode == 7 and any(m['waypoints'] for m in self.selected_movers):
            token=self.begin_edit([m['np'] for m in self.selected_movers])
            for m in self.selected_movers:
                if m['waypoints']: 
                    m['waypoints'].pop()
            self.finish_edit(token,[m['np'] for m in self.selected_movers],'waypoint_remove')
            self.draw_wp(); self.world.touch(); self.world.queue_save(); self.play_block_action(False)

    def toggle_mover_loop(self):
        if self.tool_mode != 7 or not self.tinkering(): return
        nodes = self.selected_objects or [m['np'] for m in self.selected_movers]
        if not nodes: return
        token = self.begin_edit(nodes)
        self.ensure_selected_movers()
        loop = not all(m.get('loop', False) for m in self.selected_movers)
        for m in self.selected_movers:
            m['loop'] = loop
            m['direction'] = 1
        self.finish_edit(token, [m['np'] for m in self.selected_movers], 'waypoint_loop')
        self.play_sfx('toggle',1.12 if loop else .88)
        self.world.touch(); self.world.queue_save()
        self.draw_wp(); self.update_hud()

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
                if mc.get('loop', False) and len(pts) > 2: ls.drawTo(pts[0])
            for p in pts:
                np = self.render.attachNewNode(mg); np.setPos(p); np.setBillboardPointEye(); np.setColor(1,0,1,1); np.setDepthTest(False); np.setBin("fixed", 1); self.wp_markers.append(np)
        self.wp_node = self.render.attachNewNode(ls.create()); self.wp_node.setDepthTest(False); self.wp_node.setBin("fixed", 1)

    def update_hud(self):
        if self.tool_mode not in self.TOOL_SLOTS:
            self.ui.tool_text.setText(''); return
        if self.tool_mode == 12:
            first = getattr(self, 'fill_start', None)
            corner = 'Choose first corner' if first is None else f'First: {tuple(first)} | Choose second corner'
            self.ui.tool_text.setFg(self.SELECTION_COLORS[12])
            self.ui.tool_text.setText(f"FILL TOOL\n{self.FILL_NAMES[getattr(self, 'fill_material', 1)-1]} [-/+]\n{'Solid' if getattr(self, 'fill_solid', True) else 'Hollow'} [H]\n{corner}\n[R-Click] Set corner / Fill | [L-Click] Cancel\nOccupied blocks and player space are skipped")
            return
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
            mode = 'Loop' if self.selected_movers and all(m.get('loop',False) for m in self.selected_movers) else 'Back and forth'
            body = f'Speed: {fmt(speed)} [-/+]\nPath: {mode} [L]\n[R-Click] Add waypoint | [L-Click] Delete last waypoint'
        elif self.tool_mode == 8:
            body = f'[L-Click] Select / deselect\nBounce: {fmt(self.cur_bounce)} [-/+]\nMax H: {fmt(self.cur_h)} [Z/X]'
        elif self.tool_mode == 9:
            heading = float(self.selected_objects[-1].getTag('heading') or 0) if self.selected_objects else 0
            body = f'[L-Click] Select / deselect\nFacing: {heading:.0f}\n[-/+] Turn 15 degrees | [Enter] Face camera'
        elif self.tool_mode == 10:
            body = '[L-Click] Select / deselect\n[LCtrl] Group / Ungroup'
        else:
            body = ('[R-Click] Move here | [Arrows / PgUp/PgDn] Move\n'
                    '[E] Rotate horizontally | [T] Rotate vertically | [Delete] Delete\n[LCtrl+C/X/V] Copy / Cut / Paste')
        if self.tool_mode==11: body+='\nCyan point: center / pivot'
        self.ui.tool_text.setText(header + body)

    def repeat(self, k, t, f):
        if self.keyMap[k]:
            if self.timers[k] == 0: f(1 if k in ["plus","br_r","x"] else -1); self.timers[k] = t; self.repeats[k] = t + 0.5
            elif t >= self.repeats[k]: f(1 if k in ["plus","br_r","x"] else -1); self.repeats[k] = t + 0.1
        else: self.timers[k] = 0

    PHYSICS_STEP = 1/240 # Fixed player-physics step: jump and bounce heights do not depend on frame rate
    MAX_PHYSICS_STEPS = 24 # At most 0.1 s of simulation per frame, as before
    PAUSED_FPS = 60; UNFOCUSED_FPS = 20

    def display_refresh_rate(self):
        try:
            info = self.pipe.getDisplayInformation(); mode = info.getCurrentDisplayModeIndex()
            rate = info.getDisplayModeRefreshRate(mode) if mode >= 0 else 0
        except Exception: rate = 0
        return rate if 24 <= rate <= 1000 else 144

    def apply_frame_limit(self):
        """Render at most the refresh rate when capped, and slower while paused or in the background."""
        if not self.is_focused: limit = self.UNFOCUSED_FPS
        elif self.paused: limit = self.PAUSED_FPS
        elif self.saved_settings.get('Cap Frame Rate', False):
            if getattr(self, 'refresh_rate', None) is None: self.refresh_rate = self.display_refresh_rate()
            limit = self.refresh_rate
        else: limit = 0
        if limit == getattr(self, 'frame_limit', None): return
        self.frame_limit = limit
        clock = ClockObject.getGlobalClock()
        if limit: clock.setMode(ClockObject.MLimited); clock.setFrameRate(limit)
        else: clock.setMode(ClockObject.MNormal)

    def step_physics(self, dt):
        """Advance player physics in fixed steps; leftover time carries into the next frame."""
        step = self.PHYSICS_STEP
        self.physics_time = min(getattr(self, 'physics_time', 0.0) + dt, step * self.MAX_PHYSICS_STEPS)
        while self.physics_time >= step:
            self.physics_time -= step
            self.physics.update(step, self.keyMap)

    def report_save_state(self, t):
        # Runs while paused or in the background too, so a queued or failed save is not held back.
        self.world.retry_save(t)
        if self.world.save_error != self.shown_save_error:
            self.shown_save_error = self.world.save_error
            if self.shown_save_error:
                self.ui.fly_text.setText(self.shown_save_error); self.ui.fly_text.show(); self.ui.fly_text.setAlphaScale(1.0); self.fly_text_timer = 5.0

    def update(self, task):
        filters=getattr(self,'glow_filters',None)
        if filters is not None: filters.update()
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
        
        self.apply_frame_limit()
        dt = globalClock.getDt(); t = globalClock.getFrameTime()
        self.report_save_state(t)
        if not foc: return task.cont
        self.ui.update_item_name(dt)
        self.ui.update_presence_status()
        fps = round(globalClock.getAverageFrameRate())
        if fps != getattr(self, '_last_fps', None):
            self.ui.fps_text.setText(f"FPS: {fps}")
            self._last_fps = fps
        
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

        self.step_physics(dt)
        if not self.physics.god_mode and self.physics.player.getZ() < -20: self.physics.respawn()
        self.world.mover_index = None # Built for this frame's positions; later edits must not use it

        if ((self.tool_mode in (7, 11, 12) and self.tinkering()) or self.build_material != 0):
            self.traverse_pick(self.build_dist)
            pl = VBase3(); ok = False
            if self.cHandler.getNumEntries() > 0:
                self.cHandler.sortEntries(); e = self.cHandler.getEntry(0); hp = e.getSurfacePoint(self.render)
                if (hp - self.camera.getPos(self.render)).length() <= self.build_dist:
                    p = e.getIntoNodePath().getParent()
                    if p.hasTag("material") or p == self.world.god_collision_floor:
                        if p == self.world.god_collision_floor: pl.set(round(hp.x), round(hp.y), -19.5)
                        else:
                            n = e.getSurfaceNormal(self.render)
                            cp = p.getPos(self.render)
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

        self.refresh_selection_if_changed()
        self.draw_checkpoint_direction()
        self.update_bounce_ghosts()
        self.world.update_chunks(budget_seconds=.0025)
        self.world.update_glow_lights(self.camera.getPos(self.render))
        return task.cont

    def update_world(self, task):
        if self.paused or (self.is_focused is not None and not self.is_focused): return task.cont
        dt = globalClock.getDt()
        carry = None; carry_top = -float('inf'); moved = {}; positions = []
        pp = self.physics.player.getPos()
        for m in self.world.moving_cubes:
            pts, circuit = self.world.mover_path(m)
            if not pts: positions.append(m['np'].getPos()); continue
            
            m['current_idx'] %= len(pts)
            curr = m['np'].getPos()

            # Decide support before movement, then carry before player physics runs.
            if not self.physics.flying and self.physics.vz <= 0 and abs(pp.x - curr.x) < 0.7 and abs(pp.y - curr.y) < 0.7 and curr.z + 0.45 <= pp.z <= curr.z + 0.6 and curr.z > carry_top:
                carry = m; carry_top = curr.z

            remaining = m['speed'] * min(dt, .1)
            pos = VBase3(curr)
            # Remove complete circuits to keep large steps and duplicate points bounded.
            if circuit > 0: remaining %= circuit
            for _ in range(2*len(pts)+1):
                tgt = pts[m['current_idx']]
                delta = tgt-pos; distance = delta.length()
                if distance > remaining:
                    pos += delta * (remaining/distance)
                    break
                pos = VBase3(tgt); remaining -= distance
                if len(pts) == 1: break
                if m.get('loop',False):
                    m['current_idx'] = (m['current_idx']+1) % len(pts)
                else:
                    nxt = m['current_idx'] + m.get('direction',1)
                    if nxt >= len(pts): m['direction'] = -1; nxt = len(pts)-2
                    elif nxt < 0: m['direction'] = 1; nxt = 1
                    m['current_idx'] = nxt
                if remaining <= 0: break
            m['np'].setPos(pos)
            new = m['np'].getPos(); positions.append(new)
            moved[id(m)] = new - curr

        # Collision queries until the end of this frame look up movers by cell instead of scanning them all.
        # Movers sit directly under the untransformed platform holder, so local positions are world positions.
        self.world.index_movers(positions)
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
        if self.tool_mode == 12: return self.fill_corner()
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

        # Find the targeted block before adding the new one, so the ray can't hit the new block.
        # Only a hit within build range is the block the preview is against.
        target = None
        self.traverse_pick(self.build_dist)
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
            self.world.convert_to_mover(c, {'waypoints': nw, 'speed': mc['speed'], 'current_idx': mc['current_idx'], 'wait_timer': 0, 'origin': no, 'direction': mc.get('direction', 1), 'loop': mc.get('loop', False)})
        else:
            self.world.cubes.append(c); self.world.cube_map[k] = c
            self.world.register_cube(c)
            self.world.request_chunk_update(pos)
            self.world.touch()
        self.finish_edit(token,[c],'place')
        self.world.queue_save()
        self.play_block_action(True)

        pos = c.getPos(); pp = self.physics.player.getPos()
        if abs(pp.x - pos.x) < 0.9 and abs(pp.y - pos.y) < 0.9 and pp.z < pos.z + 0.5 and pp.z + self.physics.player_height > pos.z - 0.5:
            self.physics.player.setZ(pos.z + 0.5); self.physics.vz = 0; self.physics.ground = True

    def delete(self):
        if self.input_blocked(): return
        if self.tool_mode == 12:
            self.cancel_fill(); return
        if self.tool_mode == 7:
            return self.undo_wp() if self.tinkering() else self.select_object()
        elif self.tool_mode in (8, 9, 10, 11): return self.select_object()
        self.traverse_pick()
        if self.cHandler.getNumEntries() > 0:
            self.cHandler.sortEntries(); target = self.cHandler.getEntry(0).getIntoNodePath().getParent()
            if self.delete_objects([target]):
                self.world.queue_save()
                self.play_block_action(False)


def write_crash_log(text):
    """The packaged build has no console, so keep the traceback where players can find it."""
    path = os.path.join(DATA_DIR, 'crash.log')
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(path, 'a', encoding='utf-8') as f:
            f.write(f"--- {__import__('time').strftime('%Y-%m-%d %H:%M:%S')} ---\n{text}\n")
        return path
    except OSError:
        return None


def main():
    import builtins
    try:
        Disepshun().run()
    except Exception:
        text = traceback.format_exc(); print(text, end='')
        path = write_crash_log(text)
        if path: print(f"Crash details written to {path}")
    finally:
        # Write any edit still waiting in the save debounce or marked for retry.
        world = getattr(getattr(builtins, 'base', None), 'world', None)
        if world is not None: world.flush_saves()


if __name__ == '__main__':
    main()
