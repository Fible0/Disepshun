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
        for i in range(5):
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
        # Page 0: Building Blocks (Materials 1-5)
        # Page 1: Tools (Only slot 1 visible, centered)
        
        if page == 0:
            # Show all 5 slots and reset positions
            for i, slot in enumerate(self.inv_slots):
                slot.show()
                slot.setX(self.slot_orig_x[i])
                
            # Colors for blocks 1-5: White, Gray, Red, Green, Blue
            colors = [(1,1,1,1), (0.4,0.4,0.4,1), (1,0,0,1), (0,1,0,1), (0,0,1,1)]
            for i, col in enumerate(colors):
                self.inv_cards[i].setColor(col)
        else:
            # Show only the first slot, center it, hide the rest
            self.inv_slots[0].show()
            self.inv_slots[0].setX(0.0) # Center the single tool slot
            self.inv_cards[0].setColor((1,0,1,1)) # Magenta for Movement Tool
            
            for i in range(1, 5):
                self.inv_slots[i].hide()

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
        widget.bind('wheel_up', lambda e: self.scroll_menu(1))
        widget.bind('wheel_down', lambda e: self.scroll_menu(-1))

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
            ("Relative Waypoints", lambda v: None, False), # Handled in Main via saved_settings
            ("Shaders", lambda v: self.base.toggle_shaders(v), True)
        ]

        has_old_save = bool(self.base.old_save_files())

        # Calculate exact canvas height based on items to prevent scrolling past content
        start_y = -0.05
        step = 0.11
        rows = len(opts) + (2 if has_old_save else 0) # Import button and its status line
        last_item_y = start_y - ((rows - 1) * step)
        canvas_bottom = last_item_y - 0.06

        self.scroll_frame = DirectScrolledFrame(
            parent=self.menu_frame,
            pos=(-0.075, 0, 0.05),
            frameSize=(-0.4, 0.4, -0.5, 0.5), 
            canvasSize=(-0.4, 0.4, canvas_bottom, 0),     
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

        if has_old_save:
            y = start_y - (len(opts) * step)
            self.import_btn = DirectButton(parent=self.scroll_frame.getCanvas(), pos=(0, 0, y), text="Import old save", text_scale=0.05, text_pos=(0, -0.015),
                                           text_fg=(1, 1, 1, 1), frameSize=(-0.3, 0.3, -0.04, 0.04), frameColor=(0.25, 0.25, 0.25, 1), relief=DGG.FLAT, command=self.import_old_save)
            self.import_status = DirectLabel(parent=self.scroll_frame.getCanvas(), pos=(0, 0, y - step), text="", text_scale=0.04, text_fg=(1, 1, 1, 1),
                                             text_wordwrap=18, frameColor=(0, 0, 0, 0), state=DGG.DISABLED)
            self.bind_scroll_events(self.import_btn)

    def import_old_save(self):
        self.import_status['text'] = self.base.import_old_save()
        if not self.base.old_save_files(): self.import_btn.hide()

    def apply_settings(self):
        """Shows and applies saved_settings after they were replaced, without saving them again."""
        for n, (btn, cb, def_val) in self.switches.items():
            v = self.base.saved_settings.get(n, def_val)
            btn.set_value(v); cb(v)

    def create_switch(self, parent, label_text, x, y, initial_value, callback):
        btn = DirectButton(parent=parent, pos=(0, 0, y), frameSize=(-0.38, 0.38, -0.04, 0.04), frameColor=(0, 0, 0, 0), relief=DGG.FLAT)
        DirectLabel(parent=btn, text=label_text, scale=0.05, pos=(-0.35, 0, -0.015), text_align=TextNode.ALeft, text_fg=(1, 1, 1, 1), frameColor=(0, 0, 0, 0), state=DGG.DISABLED)
        
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
            callback(btn.is_on)
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

    def set_menu_visible(self, v): self.menu_frame.show() if v else self.menu_frame.hide()
    
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