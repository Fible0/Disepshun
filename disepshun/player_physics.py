from disepshun.config import *
from disepshun.particle_system import ParticleSystem
import builtins

class PlayerPhysics:
    def __init__(self, render, camera, world_manager):
        self.render = render
        self.camera = camera
        self.world_manager = world_manager
        self.player = NodePath("Player"); self.player.reparentTo(self.render); self.player.setPos(0, 0, 1)
        self.head = self.player.attachNewNode("Head"); self.camera.reparentTo(self.head)
        self.w = 0.4; self.h_stand = 1.67; self.h_crouch = 0.9
        self.player_height = self.h_stand
        self.curr_h = self.h_stand
        self.head_stand = 1.5; self.head_crouch = 0.8; self.head.setZ(self.head_stand)
        self.vz = 0; self.g = -19.6; self.jump = 8.0; self.ground = False
        # Faster than any fall inside the map's height at normal gravity, so it only bounds runaway falls.
        self.max_fall_speed = 300.0; self.lower_bound = -1000.0
        self.bounce_cache = {} # (bounciness, max height, frame time) -> (first, highest) bounce heights
        self.coyote_time = 0.1; self.coyote = 0.0 # Seconds after leaving a ledge that a jump still works
        self.max_step = 0.25 # Largest movement per collision test, well under a block or the player's width
        self.flying = False; self.fly_speed = 10.0; self.god_mode = False
        self.checkpoint = VBase3(0, 0, 1); self.just_respawned = False
        self.checkpoint_pitch = 1.0
        self.checkpoint_activated_this_update = False
        self.fall_peak_z = self.player.getZ()
        self.pending_land = None
        self.step_dist = 0.0; self.step_len = 1.6 # Ground distance between footstep sounds
        self.particles = ParticleSystem(self.render)

    def set_spawn_position(self, position):
        self.player.setPos(position)
        self.fall_peak_z = self.player.getZ()
        self.pending_land = None

    def start_cyan_effect(self):
        if hasattr(builtins.base, 'particles_enabled') and not builtins.base.particles_enabled: return
        q = self.camera.getQuat(self.render)
        spawn_pos = self.camera.getPos(self.render) + q.getForward() * 2.0
        self.particles.explode(spawn_pos)

    def respawn(self):
        if self.just_respawned: return
        print(f"Respawning at {self.checkpoint}...")
        self.checkpoint_pitch = 1.0
        builtins.base.play_sfx("respawn", 1.0, 1.0, .5)
        ac = self.world_manager.active_checkpoint_cube
        if ac is not None and not ac.isEmpty() and not ac.getParent().isEmpty():
            self.checkpoint = ac.getPos(self.render) + VBase3(0, 0, 1)
        self.set_spawn_position(self.checkpoint)
        self.player.setHpr(float(ac.getTag("heading") or 0) if ac is not None and not ac.isEmpty() else 0, 0, 0)
        self.camera.setP(0)
        self.vz = 0; self.ground = False; self.coyote = 0.0; self.just_respawned = True; self.start_cyan_effect()
        
        if hasattr(builtins, 'base'):
            win = builtins.base.win
            cx, cy = win.getXSize() // 2, win.getYSize() // 2
            win.movePointer(0, cx, cy)

    def activate_checkpoint(self, cube):
        if cube == self.world_manager.active_checkpoint_cube: return False
        if cube is None or cube.isEmpty() or cube.getTag('material') != '4': return False
        builtins.base.play_sfx("checkpoint", self.checkpoint_pitch, 1.0, .3)
        self.checkpoint_pitch += 0.1

        old_active = self.world_manager.active_checkpoint_cube
        self.world_manager.active_checkpoint_cube = cube
        self.checkpoint = cube.getPos() + VBase3(0, 0, 1)
        
        if hasattr(builtins.base, 'particles_enabled') and builtins.base.particles_enabled:
            self.particles.activate_checkpoint(cube.getPos())
        
        # Refresh materials of both old and new (chunk rebuild for static blocks, face restyle for movers)
        if old_active and not old_active.isEmpty():
            self.world_manager.update_cube_faces(old_active)
        self.world_manager.update_cube_faces(cube)
        
        self.world_manager.queue_save()
        return True

    def get_contacts(self, p_pos, h, ignore=()):
        """Side-effect-free overlap query. Returns (out_of_bounds_or_floor, [overlapping cubes])."""
        if not (-10000 < p_pos.x < 10000) or not (-10000 < p_pos.y < 10000) or not (-1000 < p_pos.z < 1000): return True, []
        min_x = p_pos.x - self.w/2; max_x = p_pos.x + self.w/2
        min_y = p_pos.y - self.w/2; max_y = p_pos.y + self.w/2
        min_z = p_pos.z; max_z = p_pos.z + h
        overlaps = lambda cp: (min_x < cp.x+0.5 and max_x > cp.x-0.5 and min_y < cp.y+0.5 and max_y > cp.y-0.5 and min_z < cp.z+0.5 and max_z > cp.z-0.5)
        hits = []
        wm = self.world_manager

        for c, cp in wm.movers_near(min_x, max_x, min_y, max_y, min_z, max_z):
            if c not in ignore and overlaps(cp): hits.append(c)

        floor = False
        if wm.god_floor_enabled:
             gp = wm.god_collision_floor.getPos(self.render); fh = wm.FLOOR_HALF
             if (min_x < gp.x+fh and max_x > gp.x-fh and min_y < gp.y+fh and max_y > gp.y-fh and min_z < gp.z+0.5 and max_z > gp.z-0.5): floor = True

        try:
            # A unit cube's rounded center key can overlap only these cells.
            # The extra half-cell covers legacy blocks with off-grid centers too.
            sx, ex = math.floor(min_x), math.ceil(max_x+1)
            sy, ey = math.floor(min_y), math.ceil(max_y+1)
            sz, ez = math.floor(min_z), math.ceil(max_z+1)
        except: return True, hits

        for x in range(sx, ex):
            for y in range(sy, ey):
                for z in range(sz, ez):
                    if (c := wm.cube_map.get((x, y, z))) and c not in ignore and overlaps(c.getPos(self.render)): hits.append(c)
        return floor, hits

    def handle_contacts(self, hits):
        """Lethal contacts take precedence; touching the active checkpoint retains it."""
        if self.god_mode or not hits: return
        if any(c.getTag('material') == '3' for c in hits): self.respawn(); return
        cps = [c for c in hits if c.getTag('material') == '4']
        if not cps or self.checkpoint_activated_this_update: return
        active = self.world_manager.active_checkpoint_cube
        if active in cps: return
        pp = self.player.getPos(self.render)
        # Collision probes can see only one side of a seam. Include the player's
        # actual body/support contacts before deciding it has left its checkpoint.
        if active is not None:
            _, actual = self.get_contacts(pp-VBase3(0,0,.02), self.player_height+.02)
            if active in actual: return
        target = min(cps, key=lambda c: ((c.getPos(self.render)-pp).lengthSquared(), tuple(c.getPos(self.render))))
        if self.activate_checkpoint(target): self.checkpoint_activated_this_update = True

    def check_collision(self, p_pos, h, trigger_events=True, ignore=()):
        floor, hits = self.get_contacts(p_pos, h, ignore)
        if trigger_events: self.handle_contacts(hits)
        return floor or bool(hits)

    def carry(self, move, ignore=()):
        """Move the player with a platform, using the same collision and contact rules as voluntary movement."""
        steps = max(1, math.ceil(move.length() / self.max_step))
        step = move / steps
        for _ in range(steps):
            for axis in (2, 0, 1):
                d = VBase3(0, 0, 0); d[axis] = step[axis]
                if d[axis] == 0: continue
                np_ = self.player.getPos() + d
                if self.check_collision(np_, self.player_height, ignore=ignore):
                    if self.just_respawned: return
                    # Pushed up into a ceiling: crushed. Blocked sideways or downward: the platform slides on without the player.
                    if axis == 2 and d.z > 0 and not self.god_mode: self.respawn(); return
                    continue
                self.player.setPos(np_)
                if self.just_respawned: return

    def vertical_step(self, dz, keys):
        """Move by one vertical sub-step. Returns True when the fall/rise was stopped."""
        pp = self.player.getPos() + VBase3(0, 0, dz)
        if not self.check_collision(pp, self.player_height):
            self.player.setPos(pp); self.ground = False
            self.fall_peak_z=max(self.fall_peak_z,self.player.getZ())
            return False
        if self.just_respawned: return True
        if self.vz > 0: self.vz = 0; return True

        hgz = -float('inf'); g_cube = None
        check_area = lambda cx, cy, cz, mx, my, mz, hw=0.5: (mx - self.w/2 < cx+hw and mx + self.w/2 > cx-hw and my - self.w/2 < cy+hw and my + self.w/2 > cy-hw and mz < cz+0.5 and mz + self.player_height > cz-0.5)

        def check_obj(c, cp=None):
            nonlocal hgz, g_cube
            if cp is None: cp = c.getPos(self.render)
            if (cp.x - pp.x)**2 + (cp.y - pp.y)**2 + (cp.z - pp.z)**2 > 9.0: return
            if check_area(cp.x, cp.y, cp.z, pp.x, pp.y, pp.z) and cp.z+0.5 > hgz: hgz = cp.z+0.5; g_cube = c

        hw = self.w/2
        for c, cp in self.world_manager.movers_near(pp.x-hw, pp.x+hw, pp.y-hw, pp.y+hw, pp.z, pp.z+self.player_height): check_obj(c, cp)
        gf = self.world_manager.god_collision_floor
        if self.world_manager.god_floor_enabled:
            cp = gf.getPos(self.render)
            if check_area(cp.x, cp.y, cp.z, pp.x, pp.y, pp.z, self.world_manager.FLOOR_HALF) and cp.z+0.5 > hgz: hgz = cp.z+0.5; g_cube = None

        try:
            sx, ex = int(round(pp.x - self.w/2)), int(round(pp.x + self.w/2))
            sy, ey = int(round(pp.y - self.w/2)), int(round(pp.y + self.w/2))
            sz = int(round(pp.z + 0.5))
            for x in range(sx-1, ex+2):
                for y in range(sy-1, ey+2):
                    for z_chk in range(sz-2, sz+2):
                        if c := self.world_manager.cube_map.get((x, y, z_chk)): check_obj(c)
        except: pass

        if g_cube is not None and g_cube.getTag("material") == "5" and self.vz < -4.0 and keys["space"]:
            b = self.tag_num(g_cube, "bounciness", 1.3, 0.1); mh = self.tag_num(g_cube, "max_height", 0.0, 0.0)
            nv = abs(self.vz) * b; cap = math.sqrt(2 * abs(self.g) * mh) if mh > 0 else 11.0
            self.vz = min(nv, cap) if mh > 0 else nv
            self.player.setZ(hgz + 0.01); self.ground = False
            builtins.base.play_sfx("bounce", random.uniform(0.95, 1.05))
            return True
        if hgz > -10000:
            drop=max(0,self.fall_peak_z-hgz)
            if not self.ground and abs(self.vz)>1.5 and drop>.06 and not keys['space']:
                severity=min(1,math.sqrt(drop/30))
                self.pending_land = (.08,1.25-.65*severity,.2+.8*severity)
            self.fall_peak_z=hgz
            self.player.setZ(hgz); self.vz = 0; self.ground = True
            return True
        self.player.setPos(pp); self.ground = False
        return False

    def bounce_heights(self, c, dt):
        """Feet heights above trampoline c's top, holding space at frame time dt: the first bounce after a standing jump, and the highest bounce reachable."""
        b = self.tag_num(c, "bounciness", 1.3, 0.1); mh = self.tag_num(c, "max_height", 0.0, 0.0)
        key = (b, mh, round(dt, 4))
        if (r := self.bounce_cache.get(key)) is None:
            r = self.bounce_cache[key] = self.sim_bounces(b, mh, min(dt, 0.1))
        ceiling = 1000 - (c.getZ(self.render) + 0.5) # Out of bounds above z 1000 stops the player like a ceiling
        return min(r[0], ceiling), min(r[1], ceiling)

    def sim_bounces(self, b, mh, dt):
        """Bounce apexes with update()'s stepping (gravity applied before each frame's move), solved per flight instead of per frame."""
        gdt = abs(self.g) * dt
        cap = math.sqrt(2 * abs(self.g) * mh) if mh > 0 else float('inf')
        def apex(v, z0):
            k = math.floor(v / gdt)
            return z0 + dt * (k * v - gdt * k * (k + 1) / 2)
        def impact(v, z0):
            # First frame k whose end height is below the top: z0 + dt*(k*v - gdt*k*(k+1)/2) < 0
            a = gdt / 2; bq = gdt / 2 - v
            k = max(1, math.floor((-bq + math.sqrt(bq * bq + 4 * a * z0 / dt)) / (2 * a)) - 1)
            while z0 + dt * (k * v - gdt * k * (k + 1) / 2) >= 0: k += 1
            return k * gdt - v
        # The standing jump counts toward the highest point: weak trampolines bounce lower than it
        v = impact(self.jump, 0.0); first = None; last = top = apex(self.jump, 0.0)
        for _ in range(2000):
            if v <= 4.0: break # Too slow to bounce: the player lands and jumps again, repeating the same bounces
            launch = min(v * b, cap); h = apex(launch, 0.01)
            if first is None: first = h
            elif h <= last + 1e-6: break # No longer climbing
            last = h; top = max(top, h)
            if top > 2000: return first, float('inf')
            v = impact(launch, 0.01)
        return (first if first is not None else 0.0), top

    @staticmethod
    def tag_num(c, tag, default, lo):
        try: v = float(c.getTag(tag) or default)
        except ValueError: return default
        return v if math.isfinite(v) and v >= lo else default

    def update_landing_sound(self, dt, keys):
        if self.pending_land is None: return
        # Allow a jump immediately after contact to cancel the landing cue.
        if keys['space'] or self.flying or self.just_respawned:
            self.pending_land = None
            return
        delay,pitch,volume = self.pending_land
        delay -= dt
        if delay <= 0:
            self.pending_land = None
            builtins.base.play_sfx('land',pitch,volume)
        else:
            self.pending_land = (delay,pitch,volume)

    def update(self, dt, keys):
        self.checkpoint_activated_this_update = False
        self.particles.update(dt)
        if self.just_respawned: self.just_respawned = False; return
        dt = min(dt, 0.1)
        self.update_landing_sound(dt, keys)
        self.fall_peak_z=self.player.getZ() if self.ground or self.flying else max(self.fall_peak_z,self.player.getZ())
        crouching = keys.get("lshift", False) or keys.get("rshift", False)

        if self.flying:
            v = VBase3(0,0,0); q = self.camera.getQuat(self.render); f = q.getForward(); f.setZ(0); f.normalize(); r = q.getRight(); r.setZ(0); r.normalize()
            if keys["w"]: v += f
            if keys["s"]: v -= f
            if keys["a"]: v -= r
            if keys["d"]: v += r
            if keys["space"]: v.z += 1
            if crouching: v.z -= 1
            if v.lengthSquared() > 0: self.player.setPos(self.player.getPos() + v.normalized() * self.fly_speed * dt)
        else:
            wants_crouch = crouching
            if not wants_crouch:
                if self.check_collision(self.player.getPos(), self.h_stand, trigger_events=False):
                    wants_crouch = True

            if wants_crouch and not getattr(self, "was_crouching", False):
                builtins.base.play_sfx("crouch", 1.0, 0.9)
            if not wants_crouch and getattr(self, "was_crouching", False):
                builtins.base.play_sfx("uncrouch", 1.0, 0.85)
            self.was_crouching = wants_crouch
            th = self.h_crouch if wants_crouch else self.h_stand
            t_head = self.head_crouch if wants_crouch else self.head_stand
            
            self.curr_h += (th - self.curr_h) * dt * 7.0
            self.head.setZ(self.head.getZ() + (t_head - self.head.getZ()) * dt * 7.0)
            self.player_height = self.curr_h

            if keys["space"] and (self.ground or self.coyote > 0):
                self.vz = self.jump; self.ground = False; self.coyote = 0.0
                builtins.base.play_sfx("jump", random.uniform(0.95, 1.05))
            self.vz += self.g * dt * (2.5 if crouching and not self.ground else 1.0)
            self.vz = max(self.vz, -self.max_fall_speed)
            dz = self.vz * dt; steps = max(1, math.ceil(abs(dz) / self.max_step))
            for _ in range(steps):
                if self.vertical_step(dz / steps, keys): break
            if self.just_respawned: return
            # Below the map nothing can stop a fall (invincibility skips the -20 respawn), so return to the checkpoint.
            if self.player.getZ() < self.lower_bound: self.respawn(); return
            self.coyote = self.coyote_time if self.ground else max(0.0, self.coyote - dt)

            sp = 2.0 if crouching else 5.0
            mv = VBase3(0,0,0)
            if keys["w"]: mv.y += 1
            if keys["s"]: mv.y -= 1
            if keys["a"]: mv.x -= 1
            if keys["d"]: mv.x += 1
            if mv.lengthSquared() > 0:
                ov = self.player.getQuat().xform(mv.normalized()) * sp * dt
                start = self.player.getPos()
                
                next_x = self.player.getPos() + VBase3(ov.x, 0, 0)
                if not self.check_collision(next_x, self.player_height): 
                    can_move = True
                    if crouching and self.ground:
                        if not self.check_collision(next_x - VBase3(0, 0, 0.1), self.player_height, trigger_events=False):
                            can_move = False
                    if can_move:
                        if not self.just_respawned: self.player.setX(self.player.getX() + ov.x)

                next_y = self.player.getPos() + VBase3(0, ov.y, 0)
                if not self.check_collision(next_y, self.player_height): 
                    can_move = True
                    if crouching and self.ground:
                        if not self.check_collision(next_y - VBase3(0, 0, 0.1), self.player_height, trigger_events=False):
                            can_move = False
                    if can_move:
                        if not self.just_respawned: self.player.setY(self.player.getY() + ov.y)

                if self.ground and not self.just_respawned:
                    d = self.player.getPos() - start; self.step_dist += math.hypot(d.x, d.y)
                    if self.step_dist >= self.step_len * (0.5 if crouching else 1.0):
                        self.step_dist = 0.0
                        builtins.base.play_sfx("walk", random.uniform(0.85, 1.15), 0.15 if crouching else 0.3)
            else: self.step_dist = self.step_len * 0.7 # First step sounds soon after starting to walk
