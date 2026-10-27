from disepshun.config import *
from disepshun.world_manager import WorldManager
from disepshun.player_physics import PlayerPhysics
from disepshun.game_ui import GameUI
import traceback
import json
import math
import shutil

class Disepshun(ShowBase):
    def __init__(self):
        ShowBase.__init__(self)
        
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
        for n in ["walk", "jump", "bounce", "toggle", "place", "break"]:
            try: self.sfx[n] = self.loader.loadSfx(Filename.fromOsSpecific(os.path.join(SOUND_DIR, n + ".mp3")))
            except Exception: pass

        self.world = WorldManager(self.render, self.loader)
        self.physics = PlayerPhysics(self.render, self.camera, self.world)
        
        self.mouse_sensitivity = 1.0
        self.keyMap = {k: False for k in ["w","s","a","d","space","lcontrol","mouse1","mouse3","minus","plus","br_l","br_r","z","x"]}
        self.timers = {k: 0 for k in self.keyMap}; self.repeats = {k: 0 for k in self.keyMap}
        self.tool_mode = 1; self.build_material = 1; self.build_dist = 5
        self.hotbar_page = 0 # 0 = Blocks, 1 = Tools
        
        self.selected_movers = []; self.selected_trampolines = []
        self.wp_node = None; self.wp_markers = []; self.bounce_ghosts = []
        self.is_focused = True; self.menu_open = False; self.paused = False
        self.preview_enabled = True; self.preview_shading = True; self.cur_bounce = 1.3; self.cur_h = 0.0
        self.fly_text_timer = 0.0
        self.spawned_cube_count = 0
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
        
        self.taskMgr.add(self.update, "update")
        self.taskMgr.add(self.update_world, "worldUpdate")
        
        self.ui = GameUI(self)
        self.set_tool(0)
        
        self.center_mouse()

    BOOL_SETTINGS = ["Sound", "Particles", "Fly Speed Text", "Block Preview", "Preview Shading", "Visual Floor", "Relative Waypoints", "Shaders"]

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
        ts = [t for t in self.selected_trampolines if not t.isEmpty()] if self.tool_mode == 5 else []
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
        for k in ["w","s","a","d","space","lcontrol","z","x"]: map_key("raw-"+k, k)
        for k in ["mouse1","mouse3"]: map_key(k, k)
        map_key("raw-minus", "minus"); map_key("raw-equal", "plus"); map_key("-", "minus"); map_key("=", "plus")
        map_key("raw-[", "br_l"); map_key("raw-]", "br_r")
        
        for i in range(1, 6): self.accept(str(i), self.handle_slot, [i])
        self.accept("q", self.toggle_hotbar)
        
        self.accept("wheel_up", self.adj_dist, [1]); self.accept("wheel_down", self.adj_dist, [-1])
        self.accept("r", self.undo_wp); self.accept("f", self.toggle_fly); self.accept("g", self.toggle_god); self.accept("escape", self.toggle_menu)
        self.disableMouse()

    def update_k(self, k, s): self.keyMap[k] = s
    def input_blocked(self): return self.paused or self.menu_open or not self.is_focused

    def userExit(self):
        # Write the last edit before the process ends
        self.world.flush_saves()
        ShowBase.userExit(self)

    def toggle_menu(self):
        self.menu_open = not self.menu_open; self.paused = self.menu_open
        self.ui.set_menu_visible(self.menu_open)
        wp = WindowProperties(); wp.setCursorHidden(not self.menu_open); self.win.requestProperties(wp)
        if not self.menu_open: self.center_mouse()

    def toggle_fly(self):
        if self.input_blocked(): return
        self.physics.flying = not self.physics.flying; self.physics.vz = 0; self.physics.ground = False
    def toggle_god(self):
        if self.input_blocked(): return
        self.physics.god_mode = not self.physics.god_mode; self.world.update_god_collision(self.physics.god_mode)
    
    def set_visual_floor_visible(self, v): 
        self.world.visual_floor.show() if v else self.world.visual_floor.hide()
        self.world.update_god_collision(self.physics.god_mode)

    def toggle_shaders(self, v):
        self.world.set_shaders_enabled(v)

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
        s.stop(); s.setPlayRate(rate); s.setVolume(volume); s.play()

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
            # Map slot 1 to Movement Tool (ID 7)
            if i == 1: self.set_tool(7)

    def set_tool(self, m):
        if self.tool_mode == m: m = 0
        self.tool_mode = m
        if m == 7: self.build_material = 0; self.preview.hide(); self.deselect_trampolines(); self.update_hud()
        else:
            self.build_material = m; self.deselect_movers()
            if m == 5: self.update_hud()
            else: self.deselect_trampolines(); self.ui.tool_text.setText("")
        
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
            if m == 7: v_idx = 0
        
        self.ui.update_selection(v_idx)

    def adj_dist(self, d): 
        if self.menu_open:
            self.ui.scroll_menu(d)
        else:
            self.build_dist = max(1, min(20, self.build_dist + d))
    
    def adj_val(self, d):
        if self.tool_mode == 7 and self.selected_movers:
            for m in self.selected_movers: m['speed'] = max(0.5, round(m['speed'] + d*0.5, 1))
            self.update_hud(); self.world.map_is_dirty = True; self.world.save_map()
        elif self.tool_mode == 5:
            if self.selected_trampolines:
                self.cur_bounce = max(0.1, round(self.cur_bounce + d*0.1, 1))
                for t in self.selected_trampolines: t.setTag("bounciness", str(self.cur_bounce))
                self.world.map_is_dirty = True; self.world.save_map()
                self.update_hud()

    def adj_h(self, d):
        if self.tool_mode == 5:
            if self.selected_trampolines:
                self.cur_h = max(0.0, round(self.cur_h + d*0.5, 1))
                for t in self.selected_trampolines: t.setTag("max_height", str(self.cur_h))
                self.world.map_is_dirty = True; self.world.save_map()
                self.update_hud()

    def adj_fly(self, d):
        self.physics.fly_speed = max(1.0, round(self.physics.fly_speed + d, 1))
        if not self.ui.gui_hidden and self.fly_text_enabled:
            self.ui.fly_text.setText(f"Fly Speed: {self.ui.format_number(self.physics.fly_speed)}"); self.ui.fly_text.show(); self.ui.fly_text.setAlphaScale(1.0); self.fly_text_timer = 3.0

    def handle_sel(self, mode):
        self.cTrav.traverse(self.render)
        if self.cHandler.getNumEntries() > 0:
            self.cHandler.sortEntries(); np = self.cHandler.getEntry(0).getIntoNodePath(); p = np.getParent()
            if mode == 7:
                for mc in self.world.moving_cubes:
                    if mc['np'] == p: return self.toggle_mov(mc)
                if p in self.world.cubes and p != self.world.god_collision_floor:
                    spd = self.selected_movers[0]['speed'] if self.selected_movers else 3.0
                    wps = []
                    if self.selected_movers:
                        ref = self.selected_movers[0]
                        for w in ref['waypoints']: wps.append(p.getPos() + (w - ref['origin']))
                    mc = self.world.convert_to_mover(p, {'waypoints': wps, 'speed': spd, 'current_idx': 0, 'wait_timer': 0, 'origin': p.getPos(), 'direction': 1})
                    self.toggle_mov(mc); self.world.map_is_dirty = True; self.world.save_map()
            elif mode == 5 and p in self.world.cubes and p.getTag("material") == "5":
                if p in self.selected_trampolines: 
                    p.clearColorScale(); p.setColor(0,0,1,1)
                    self.selected_trampolines.remove(p)
                    self.world.request_chunk_update(p.getPos())
                else: 
                    p.clearColorScale(); p.setColor(0,1,0,1)
                    self.selected_trampolines.append(p)
                    self.world.request_chunk_update(p.getPos())
                    self.cur_bounce = float(p.getTag("bounciness") or 1.3)
                    self.cur_h = float(p.getTag("max_height") or 0.0)
                self.update_hud()

    def handle_place_wp(self):
        if self.preview.getZ() < -19.5: return # Same world-height rule as block placement; visibility is only a display setting
        pos = self.preview.getPos(); c = len(self.selected_movers)
        if c > 0:
            avg = VBase3(sum(m['origin'].x for m in self.selected_movers), sum(m['origin'].y for m in self.selected_movers), sum(m['origin'].z for m in self.selected_movers)) / c
            
            # Use last selected block as origin if centroid is off-grid (e.g. 2 blocks) OR if setting is enabled
            use_last = self.saved_settings.get("Relative Waypoints", False)
            is_off_grid = (abs(avg.x - round(avg.x)) > 0.01 or abs(avg.y - round(avg.y)) > 0.01)

            ref = avg
            if use_last or is_off_grid:
                ref = self.selected_movers[-1]['origin']

            off = pos - ref
            for m in self.selected_movers: m['waypoints'].append(m['origin'] + off)
            self.draw_wp(); self.world.map_is_dirty = True; self.world.save_map()

    def toggle_mov(self, mc):
        if mc in self.selected_movers: mc['np'].clearColorScale(); self.selected_movers.remove(mc)
        else: mc['np'].setColorScale(0.5,0.5,1.5,1); self.selected_movers.append(mc)
        self.draw_wp(); self.update_hud()

    def deselect_movers(self):
        for m in self.selected_movers: m['np'].clearColorScale()
        self.selected_movers = []; self.draw_wp()

    def deselect_trampolines(self):
        for t in self.selected_trampolines: 
            t.clearColorScale(); t.setColor(0,0,1,1)
            self.world.request_chunk_update(t.getPos())
        self.selected_trampolines = []

    def undo_wp(self):
        if self.input_blocked(): return
        if self.tool_mode == 7 and self.selected_movers:
            for m in self.selected_movers:
                if m['waypoints']: 
                    m['waypoints'].pop()
            self.draw_wp(); self.world.map_is_dirty = True; self.world.save_map()

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
        fmt = self.ui.format_number
        if self.tool_mode == 7:
            self.ui.tool_text.setText(f"WAYPOINT TOOL\nSelected: {len(self.selected_movers)}\nSpeed: {fmt(self.selected_movers[-1]['speed'] if self.selected_movers else 3.0)} [-/+]\n[R] Undo | [L-Click] Select | [R-Click] Add" if self.selected_movers else "WAYPOINT TOOL\nSelect blocks (L-Click)")
        elif self.tool_mode == 5:
            if self.selected_trampolines:
                b, h = self.cur_bounce, self.cur_h
                self.ui.tool_text.setText(f"TRAMPOLINE TOOL\nSelected: {len(self.selected_trampolines)}\nBounce: {fmt(b)} [-/+]\nMax H: {fmt(h)} [Z/X]\n[L-Click] Select")
            else:
                self.ui.tool_text.setText("TRAMPOLINE TOOL\nSelect blocks (L-Click)")
        else: self.ui.tool_text.setText("")

    def repeat(self, k, t, f):
        if self.keyMap[k]:
            if self.timers[k] == 0: f(1 if k in ["plus","br_r","x"] else -1); self.timers[k] = t; self.repeats[k] = t + 0.5
            elif t >= self.repeats[k]: f(1 if k in ["plus","br_r","x"] else -1); self.repeats[k] = t + 0.1
        else: self.timers[k] = 0

    def update(self, task):
        foc = (self.win.getWindowHandle().getIntHandle() == user32.GetForegroundWindow()) if user32 else self.win.getProperties().getForeground()
        if foc != self.is_focused:
            self.is_focused = foc; wp = WindowProperties()
            wp.setCursorHidden(False if self.menu_open or not foc else True); wp.setZOrder(WindowProperties.Z_top if foc else WindowProperties.Z_normal); self.win.requestProperties(wp)
            if self.is_focused and not self.menu_open:
                self.center_mouse()
                self.ignore_mouse_input = True
        
        if not foc: return task.cont
        dt = globalClock.getDt(); t = globalClock.getFrameTime()
        self.ui.fps_text.setText(f"FPS: {round(globalClock.getAverageFrameRate())}")
        
        if self.fly_text_timer > 0 and not self.paused:
            self.fly_text_timer -= dt
            if not self.ui.gui_hidden and self.fly_text_enabled: self.ui.fly_text.show(); self.ui.fly_text.setAlphaScale(min(1.0, self.fly_text_timer))
            else: self.ui.fly_text.hide()
        elif self.fly_text_timer <= 0: self.ui.fly_text.hide()

        if self.paused: return task.cont

        if self.keyMap["mouse3"]:
            if self.timers["mouse3"] == 0: self.place(); self.timers["mouse3"] = t; self.repeats["mouse3"] = t + 0.5
            elif t >= self.repeats["mouse3"]: self.place(); self.repeats["mouse3"] = t + 0.1
        else: self.timers["mouse3"] = 0
        
        if self.keyMap["mouse1"]:
            if self.timers["mouse1"] == 0: self.delete(); self.timers["mouse1"] = t; self.repeats["mouse1"] = t + 0.5
            elif t >= self.repeats["mouse1"]: self.delete(); self.repeats["mouse1"] = t + 0.1
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

        if (self.tool_mode == 7 or self.build_material != 0):
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

        self.update_bounce_ghosts()
        self.world.update_chunks()
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
        return task.cont

    def place(self):
        if self.input_blocked(): return
        if self.tool_mode == 7: return self.handle_place_wp() if self.selected_movers else None
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
        self.world.map_is_dirty = True; self.world.save_map()
        self.play_sfx("place", random.uniform(0.95, 1.05))

        pos = c.getPos(); pp = self.physics.player.getPos()
        if abs(pp.x - pos.x) < 0.9 and abs(pp.y - pos.y) < 0.9 and pp.z < pos.z + 0.5 and pp.z + self.physics.player_height > pos.z - 0.5:
            self.physics.player.setZ(pos.z + 0.5); self.physics.vz = 0; self.physics.ground = True

    def delete(self):
        if self.input_blocked(): return
        if self.tool_mode == 7: return self.handle_sel(7)
        elif self.tool_mode == 5: return self.handle_sel(5)
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

            mc = self.world.find_mover(target)
            if mc and mc in self.selected_movers: self.selected_movers.remove(mc); self.draw_wp(); self.update_hud()
            if target in self.selected_trampolines: self.selected_trampolines.remove(target)
            was_cp = target == self.world.active_checkpoint_cube
            if self.world.remove_block(target):
                # Checkpoint block gone: fall back to the default spawn
                if was_cp: self.physics.checkpoint = VBase3(0, 0, 1)
                self.world.map_is_dirty = True; self.world.save_map()
                self.play_sfx("break", random.uniform(0.95, 1.05))

try:
    app = Disepshun()
    app.run()
except Exception: traceback.print_exc()