from disepshun.config import *

class GameUI:
    def __init__(self, base):
        self.base = base
        self.slot_orig_x = [] # Store original X positions
        self.create_hud()
        self.create_crosshair()
        self.create_fly_ui()
        self.gui_hidden = False
        self.dragging = False
        self.drag_offset = Point3(0, 0, 0)
        self.show_fps = True
        self.show_tool = True
        
        # Create menu last to ensure handlers are ready
        self.create_settings_menu()

    def create_crosshair(self):
        self.crosshair_node = self.base.aspect2d.attachNewNode("crosshair_root")
        cm = CardMaker("crosshair")
        cm.setFrame(-0.005, 0.005, -0.03, 0.03)
        v = self.crosshair_node.attachNewNode(cm.generate())
        cm.setFrame(-0.04, 0.04, -0.004, 0.004)
        h = self.crosshair_node.attachNewNode(cm.generate())
        v.setColor(1, 1, 1, 1); h.setColor(1, 1, 1, 1)

    def create_hud(self):
        self.fps_text = OnscreenText(text="FPS: 0", parent=self.base.a2dTopLeft, pos=(0.05, -0.12), scale=0.15, fg=(1, 1, 1, 1), align=TextNode.ALeft)
        self.tool_text = OnscreenText(text="", parent=self.base.a2dTopLeft, pos=(0.05, -0.2), scale=0.07, fg=(1, 1, 0, 1), align=TextNode.ALeft)
        self.create_inventory_ui()

    def create_fly_ui(self):
        self.fly_text = OnscreenText(text="", parent=self.base.a2dTopCenter, pos=(0, -0.15), scale=0.1, fg=(0, 1, 1, 1), align=TextNode.ACenter)
        self.fly_text.hide()

    def create_inventory_ui(self):
        self.inv_node = self.base.a2dBottomCenter.attachNewNode("Inventory")
        self.inv_node.setPos(0, 0, 0.1)
        self.inv_slots = []
        self.inv_cards = []
        self.slot_orig_x = []
        
        # Create 5 slots for the hotbar
        for i in range(6):
            x = -0.2 + i*0.1
            self.slot_orig_x.append(x)
            slot, card = self.create_inv_slot(i+1, (1,1,1,1), x)
            self.inv_slots.append(slot)
            self.inv_cards.append(card)
        
        ls = LineSegs()
        ls.setThickness(4.0)
        ls.setColor(0, 1, 1, 1)
        d = 0.06
        ls.moveTo(-d, 0, d); ls.drawTo(d, 0, d); ls.drawTo(d, 0, -d); ls.drawTo(-d, 0, -d); ls.drawTo(-d, 0, d)
        self.selection_indicator = self.inv_node.attachNewNode(ls.create())
        self.selection_indicator.setBin("fixed", 2)
        self.selection_indicator.hide()
        
        self.item_name = OnscreenText(text='', parent=self.inv_node, pos=(0,.12), scale=.05, fg=(1,1,1,1))
        self.item_name_time = 0.0
        self.item_name.hide()
        # Initialize default view (Page 0: Blocks)
        self.update_hotbar_layout(0)

    def create_inv_slot(self, idx, color, x_pos):
        slot = self.inv_node.attachNewNode(f"slot_{idx}")
        slot.setPos(x_pos, 0, 0)
        cm = CardMaker(f"slot_card_{idx}")
        cm.setFrame(-0.045, 0.045, -0.045, 0.045)
        card = slot.attachNewNode(cm.generate())
        card.setColor(color)
        card.setBin("fixed", 1)
        OnscreenText(text=str(idx), parent=slot, pos=(0, -0.085), scale=0.05, fg=(1, 1, 1, 1), align=TextNode.ACenter)
        return slot, card

    def update_hotbar_layout(self, page):
        colors = ([(1,1,1,1), (.4,.4,.4,1), (1,0,0,1), (0,1,0,1), (0,0,1,1)]
                  if page == 0 else [(1,0,1,1), (0,.3,1,1), (0,1,.4,1), (1,.65,0,1), (0,1,1,1), (1,.85,.35,1)])
        for i, slot in enumerate(self.inv_slots):
            if i >= len(colors):
                slot.hide(); continue
            slot.show(); slot.setX(self.slot_orig_x[i])
            self.inv_cards[i].setColor(colors[i])

    def show_item_name(self, name):
        self.item_name.setText(name)
        self.item_name_time = 2.0 if name else 0.0
        self.item_name.setAlphaScale(1)
        self.item_name.show() if name else self.item_name.hide()

    def update_item_name(self, dt):
        self.item_name_time = max(0.0, self.item_name_time-dt)
        if self.item_name_time <= 0: self.item_name.hide()
        else: self.item_name.setAlphaScale(min(1, self.item_name_time/.7))

    def update_presence_status(self):
        text = self.base.presence.connection_status
        if self.presence_status['text'] != text:
            self.presence_status['text'] = text
            self.layout_settings()

    def drag_start(self, event):
        if self.base.mouseWatcherNode.hasMouse():
            m = self.base.mouseWatcherNode.getMouse()
            self.drag_offset = self.menu_frame.getPos() - Point3(m.x * self.base.getAspectRatio(), 0, m.y)
            self.base.taskMgr.add(self.drag_task, "drag_menu_task")

    def drag_task(self, task):
        if self.base.mouseWatcherNode.hasMouse():
            m = self.base.mouseWatcherNode.getMouse()
            self.menu_frame.setPos(Point3(m.x * self.base.getAspectRatio(), 0, m.y) + self.drag_offset)
        return task.cont
        
    def drag_stop(self, event): 
        self.base.taskMgr.remove("drag_menu_task")

    def scroll_menu(self, direction):
        if not self.base.menu_open or not self.base.is_focused or not self.base.mouseWatcherNode.hasMouse(): return
        mouse = self.base.mouseWatcherNode.getMouse()
        point = self.menu_frame.getRelativePoint(self.base.aspect2d, Point3(mouse.x * self.base.getAspectRatio(), 0, mouse.y))
        left, right, bottom, top = self.menu_frame['frameSize']
        if not (left <= point.x <= right and bottom <= point.z <= top): return
        if not hasattr(self, 'scroll_frame') or not self.scroll_frame: return
        bar = self.scroll_frame.verticalScroll
        val = bar['value']
        step = 0.2
        new_val = max(0.0, min(1.0, val - (direction * step)))
        bar['value'] = new_val

    def toggle_fps(self, v): 
        self.show_fps = v
        if v: self.fps_text.show() 
        else: self.fps_text.hide()

    def toggle_tool(self, v): 
        self.show_tool = v
        if v: self.tool_text.show() 
        else: self.tool_text.hide()

    def bind_scroll_events(self, widget):
        """Recursively bind scroll events to a widget and its children if needed"""
        if not widget: return
        widget.bind('press-wheel_up-', lambda e: self.scroll_menu(1))
        widget.bind('press-wheel_down-', lambda e: self.scroll_menu(-1))

    def create_settings_menu(self):
        self.menu_frame = DirectFrame(frameColor=(0.1, 0.1, 0.1, 0.95), frameSize=(-0.5, 0.35, -0.5, 0.75), pos=(0, 0, 0), state=DGG.NORMAL)
        
        self.menu_frame.bind(DGG.B1PRESS, self.drag_start)
        self.menu_frame.bind(DGG.B1RELEASE, self.drag_stop)
        self.bind_scroll_events(self.menu_frame)
        
        self.menu_frame.hide()

        # Set label to DISABLED so it lets scroll events pass through to the frame
        DirectLabel(parent=self.menu_frame, text="SETTINGS", scale=0.08, pos=(-0.075, 0, 0.65), text_fg=(1, 1, 1, 1), frameColor=(0, 0, 0, 0), state=DGG.DISABLED)

        # Define options first to calculate size
        opts = [
            ("Crosshair", lambda v: self.crosshair_node.show() if v else self.crosshair_node.hide(), True),
            ("FPS Counter", lambda v: self.toggle_fps(v), True),
            ("Tool Info", lambda v: self.toggle_tool(v), True),
            ("Inventory", lambda v: self.inv_node.show() if v else self.inv_node.hide(), True),
            ("Sound", lambda v: self.base.toggle_sound(v), True),
            ("Particles", lambda v: self.base.toggle_particles(v), True),
            ("Fly Speed Text", lambda v: self.base.toggle_fly_text(v), True),
            ("Block Preview", lambda v: self.base.set_preview_enabled(v), True),
            ("Preview Shading", lambda v: self.base.toggle_preview_shading(v), True),
            ("Visual Floor", lambda v: self.base.set_visual_floor_visible(v), False),
            ("Use Last Selected as Pivot", lambda v: None, False), # Handled in Main via saved_settings
            ("Shaders", lambda v: self.base.toggle_shaders(v), True),
            ("Discord Rich Presence", lambda v: self.base.presence.configure(enabled=v), True),
            ("Discord Show Activity", lambda v: self.base.presence.configure(show_activity=v), True),
            ("Discord Show Block Count", lambda v: self.base.presence.configure(show_block_count=v), True),
            ("Discord Show Time", lambda v: self.base.presence.configure(show_time=v), True),
            ("Discord Show Icon", lambda v: self.base.presence.configure(show_icon=v), True)
        ]

        start_y = -0.05
        step = 0.11
        self.scroll_frame = DirectScrolledFrame(
            parent=self.menu_frame,
            state=DGG.NORMAL,
            pos=(-0.075, 0, 0.05),
            frameSize=(-0.4, 0.4, -0.5, 0.5), 
            canvasSize=(-0.4, 0.4, -1, 0),
            frameColor=(0, 0, 0, 0.01), # Almost invisible, but catches hits
            scrollBarWidth=0.04,
            verticalScroll_frameSize=(-0.02, 0.02, -0.5, 0.5),
            horizontalScroll_frameSize=(0,0,0,0)
        )
        
        if self.scroll_frame.horizontalScroll:
            self.scroll_frame.horizontalScroll.destroy()
            self.scroll_frame.horizontalScroll = None
            
        self.bind_scroll_events(self.scroll_frame)
        
        # Aggressively bind scrollbar parts to ensure no dead zones
        if self.scroll_frame.verticalScroll:
            self.bind_scroll_events(self.scroll_frame.verticalScroll)
            self.bind_scroll_events(self.scroll_frame.verticalScroll.thumb)
            self.bind_scroll_events(self.scroll_frame.verticalScroll.incButton)
            self.bind_scroll_events(self.scroll_frame.verticalScroll.decButton)

        self.switches = {}
        for i, (n, cb, def_val) in enumerate(opts):
            val = self.base.saved_settings.get(n, def_val)
            def wrapped(v, name=n, func=cb):
                func(v)
                self.base.save_setting(name, v)
                if name == "Discord Rich Presence": self.layout_settings()

            btn = self.create_switch(self.scroll_frame.getCanvas(), n, 0.2, start_y - (i * step), val, wrapped)
            self.bind_scroll_events(btn)
            self.switches[n] = (btn, cb, def_val)

            if n == "Crosshair": 
                if val: self.crosshair_node.show()
                else: self.crosshair_node.hide()
            elif n == "FPS Counter": self.toggle_fps(val)
            elif n == "Tool Info": self.toggle_tool(val)
            elif n == "Inventory": 
                if val: self.inv_node.show()
                else: self.inv_node.hide()

        y = start_y - len(opts) * step
        self.convert_button = DirectButton(parent=self.scroll_frame.getCanvas(), text='Convert legacy maps', scale=.045,
                               pos=(-.05,0,y), command=self.base.convert_legacy_maps)
        self.bind_scroll_events(self.convert_button)
        self.presence_status = DirectLabel(parent=self.scroll_frame.getCanvas(),
                    text=self.base.presence.connection_status, text_wordwrap=17,
                    text_align=TextNode.ALeft, scale=.037, pos=(-.35,0,y-step),
                    frameColor=(0,0,0,0), text_fg=(1,1,1,1), state=DGG.DISABLED)

        self.layout_settings()

    def layout_settings(self):
        y = -.05
        for name,(button,_,_) in self.switches.items():
            if name.startswith('Discord Show ') and not self.base.presence.enabled:
                button.hide()
            else:
                button.show(); button.setZ(y); y -= .11
        self.convert_button.setZ(y)
        bottom = y + self.convert_button.getBounds()[2]*self.convert_button.getSz()
        if self.base.presence.enabled:
            self.presence_status.show(); self.presence_status.setZ(y-.11)
            bottom = min(bottom,self.presence_status.getZ()+self.presence_status.getBounds()[2]*self.presence_status.getSz())
        else:
            self.presence_status.hide()
        # Use actual visible widget bounds instead of reserving empty text rows.
        self.scroll_frame['canvasSize'] = (-.4,.4,bottom-.025,0)

    def show_gpu_notice(self, recommendation):
        if getattr(self.base,'gpu_notice_open',False): return
        from disepshun.gpu_advice import executable_path
        self.base.play_sfx('menu_open')
        self.base.gpu_notice_open = True; self.base.paused = True
        for key in self.base.keyMap: self.base.keyMap[key] = False
        self.base.ctrl_group_tap_pending = False
        aspect = self.base.getAspectRatio()
        self.gpu_notice = DirectFrame(parent=self.base.aspect2d,
            frameSize=(-aspect,aspect,-1,1),frameColor=(0,0,0,.75),
            state=DGG.NORMAL,sortOrder=200)
        panel = DirectFrame(parent=self.gpu_notice,frameSize=(-.9,.9,-.78,.78),
            frameColor=(.1,.1,.1,1),state=DGG.NORMAL)
        panel.setScale(min(1,(aspect-.05)/.95))
        DirectLabel(parent=panel,text='Your graphics processors',scale=.07,pos=(0,0,.65),
            frameColor=(0,0,0,0),text_fg=(1,1,1,1),state=DGG.DISABLED)
        others = '\n'.join(recommendation['others']) or ('None detected' if recommendation['enumerated'] else 'Could not enumerate other GPUs')
        message = ("Python can sometimes be set to use the less powerful GPU.\n"
                   "Check the GPU below to make sure the game uses the one you want.\n\n"
                   f"Currently using: {recommendation['current']}\n"
                   f"Other GPUs:\n{others}\n\n"
                   "To change the GPU in Windows:\n"
                   "1. Settings > System > Display > Graphics.\n"
                   "2. Add a desktop app and browse to:\n"
                   f"{executable_path()}\n"
                   "3. Select the app > Options, choose a GPU\n"
                   "or High performance, then Save.\n"
                   "4. Restart the game to apply the change.\n\n"
                   "This notice is shown only once.")
        from direct.gui.DirectGui import DirectScrolledFrame
        import textwrap
        rows = sum(max(1,len(textwrap.wrap(line, 35))) for line in message.split('\n'))
        scroll = DirectScrolledFrame(parent=panel,frameSize=(-.81,.81,-.9,0),
            canvasSize=(-.76,.76,-max(.9,rows*.06+.12),0),
            pos=(0,0,.52),frameColor=(0,0,0,0),scrollBarWidth=.035)
        DirectLabel(parent=scroll.getCanvas(),text=message,text_wordwrap=35,text_align=TextNode.ALeft,
            scale=.043,pos=(-.75,0,-.05),frameColor=(0,0,0,0),text_fg=(1,1,1,1),state=DGG.DISABLED)
        self.gpu_action_status = DirectLabel(parent=panel,text='',text_wordwrap=38,
            text_align=TextNode.ALeft,scale=.037,pos=(-.78,0,-.4),
            frameColor=(0,0,0,0),text_fg=(.6,.9,1,1),state=DGG.DISABLED)
        self.gpu_switch_button = DirectButton(parent=panel,text='Graphics settings',scale=.055,
            pos=(-.36,0,-.68),command=self.open_gpu_settings)
        self.gpu_close_button = DirectButton(parent=panel,text='Close [Esc]',scale=.055,
            pos=(.42,0,-.68),command=self.close_gpu_notice)
        properties = WindowProperties(); properties.setCursorHidden(False)
        self.base.win.requestProperties(properties)

    def open_gpu_settings(self):
        from disepshun.gpu_advice import open_graphics_settings
        opened = open_graphics_settings()
        self.gpu_action_status['text'] = ('Graphics settings opened. Save your choice, then restart the game.'
            if opened else 'Open Settings > System > Display > Graphics manually, then follow the steps above.')

    def close_gpu_notice(self):
        if not getattr(self.base,'gpu_notice_open',False): return
        self.base.play_sfx('menu_close')
        self.gpu_notice.destroy()
        self.base.gpu_notice_open = False; self.base.paused = self.base.menu_open
        for key in self.base.keyMap: self.base.keyMap[key] = False
        self.base.ctrl_group_tap_pending = False
        properties = WindowProperties(); properties.setCursorHidden(not self.base.menu_open)
        self.base.win.requestProperties(properties)
        if not self.base.menu_open: self.base.center_mouse()

    def create_switch(self, parent, label_text, x, y, initial_value, callback):
        btn = DirectButton(parent=parent, pos=(0, 0, y), frameSize=(-0.38, 0.38, -0.04, 0.04), frameColor=(0, 0, 0, 0), relief=DGG.FLAT)
        label_scale=min(.05,.46/max(.01,TextNode('measure').calcWidth(label_text)))
        DirectLabel(parent=btn, text=label_text, scale=label_scale, pos=(-0.35, 0, -0.015), text_align=TextNode.ALeft, text_fg=(1, 1, 1, 1), frameColor=(0, 0, 0, 0), state=DGG.DISABLED)
        
        c_on = (0.2, 0.8, 0.2, 1)
        c_off = (0.2, 0.2, 0.2, 1)
        track = DirectFrame(parent=btn, pos=(x, 0, 0), frameSize=(-0.06, 0.06, -0.025, 0.025), 
                            frameColor=c_on if initial_value else c_off, relief=DGG.FLAT, state=DGG.DISABLED)
        thumb = DirectFrame(parent=track, pos=(0.035 if initial_value else -0.035, 0, 0), 
                            frameSize=(-0.02, 0.02, -0.02, 0.02), frameColor=(1, 1, 1, 1), relief=DGG.FLAT, state=DGG.DISABLED)
        
        btn.is_on = initial_value
        def set_value(v):
            btn.is_on = v
            thumb.posInterval(0.15, Point3(0.035 if btn.is_on else -0.035, 0, 0), blendType='easeInOut').start()
            track['frameColor'] = (0.2, 0.8, 0.2, 1) if btn.is_on else (0.2, 0.2, 0.2, 1)
        def toggle():
            set_value(not btn.is_on)
            if not btn.is_on: self.base.play_sfx("toggle", .85) # Before the callback, so switching Sound off still clicks
            callback(btn.is_on)
            if btn.is_on: self.base.play_sfx("toggle", 1.0)
        btn.set_value = set_value
        btn['command'] = toggle
        
        return btn
    
    def toggle_gui(self):
        self.gui_hidden = not self.gui_hidden
        nodes = [self.crosshair_node, self.inv_node, self.fps_text, self.tool_text, self.fly_text]
        for n in nodes: n.hide() if self.gui_hidden else n.show()
        if not self.gui_hidden:
            if not self.show_fps: self.fps_text.hide()
            if not self.show_tool: self.tool_text.hide()
            self.fly_text.hide()

    def set_menu_visible(self, v):
        self.menu_frame.show() if v else self.menu_frame.hide()
        if not v:
            self.drag_stop(None)
    
    def update_selection(self, idx):
        if idx is None or idx < 0 or idx >= len(self.inv_slots):
            self.selection_indicator.hide()
        else:
            if self.inv_slots[idx].isHidden():
                self.selection_indicator.hide()
            else:
                self.selection_indicator.show()
                self.selection_indicator.setPos(self.inv_slots[idx].getX(), 0, 0)
                self.selection_indicator.setColor(0, 1, 1, 1)
    
    @staticmethod
    def format_number(n): return str(int(n)) if round(float(n), 2).is_integer() else f"{round(float(n), 2):.1f}"