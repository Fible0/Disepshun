from disepshun.config import *
from panda3d.core import NodePath, CardMaker, TransparencyAttrib, ColorBlendAttrib, Vec3, Vec4
import random
import math

class Particle:
    __slots__ = ['node', 'cx', 'cy', 'cz', 'radius', 'angle', 'angular_vel', 'height', 'vz', 'start_time', 'decay', 'p_type']
    def __init__(self, node, cx, cy, cz, radius, angle, angular_vel, height, vz, start_time, decay, p_type):
        self.node = node
        self.cx = cx; self.cy = cy; self.cz = cz
        self.radius = radius
        self.angle = angle
        self.angular_vel = angular_vel
        self.height = height
        self.vz = vz
        self.start_time = start_time
        self.decay = decay
        self.p_type = p_type

class ParticleSystem:
    def __init__(self, parent, pool_size=300):
        self.active_parts = []
        self.pool_size = pool_size
        self.parent = parent
        
        cm = CardMaker("part_template")
        cm.setFrame(-0.4, 0.4, -0.4, 0.4) 
        self.template = NodePath(cm.generate())
        self.template.setBillboardPointEye()
        self.template.setTransparency(TransparencyAttrib.MAlpha)
        self.template.setColor(1, 1, 1, 1) # White base
        self.template.setLightOff(1)
        self.template.setShaderOff(1)
        self.template.setBin("fixed", 10)
        self.template.setDepthWrite(False)
        self.template.setDepthTest(True) 
        
    def explode(self, pos):
        # Respawn effect (Type 0)
        for p in self.active_parts:
            if p.p_type == 0 and not p.node.isEmpty():
                p.node.removeNode()
        
        self.active_parts = [p for p in self.active_parts if p.p_type != 0]
        
        rnd = random.uniform
        px, py, pz = pos.x, pos.y, pos.z
        curr_t = ClockObject.getGlobalClock().getFrameTime()
        
        for _ in range(60):
            angle = rnd(0, 6.28)
            radius = rnd(0.5, 6.0) 
            height = rnd(-3.0, 3.0) 
            
            angular_vel = rnd(3.0, 6.0)
            if rnd(0, 1) > 0.5: angular_vel *= -1 
            
            vz = rnd(-0.5, 0.5) 
            decay = rnd(1.0, 2.0) 
            
            np = self.template.copyTo(self.parent)
            np.setPos(px + math.cos(angle)*radius, py + math.sin(angle)*radius, pz + height)
            
            self.active_parts.append(Particle(np, px, py, pz, radius, angle, angular_vel, height, vz, curr_t, decay, 0))

    def activate_checkpoint(self, pos):
        # Checkpoint activation effect (Type 1)
        rnd = random.uniform
        px, py, pz = pos.x, pos.y, pos.z + 0.6
        curr_t = ClockObject.getGlobalClock().getFrameTime()
        
        # Increase size and count slightly to ensure visibility
        for _ in range(30):
            sx = px + rnd(-0.4, 0.4)
            sy = py + rnd(-0.4, 0.4)
            sz = pz
            
            vz = rnd(2.0, 5.0)
            decay = 0.8
            
            np = self.template.copyTo(self.parent)
            np.setPos(sx, sy, sz)
            np.setScale(0.6) # Slightly larger particles
            
            self.active_parts.append(Particle(np, sx, sy, sz, 0, 0, 0, 0, vz, curr_t, decay, 1))

    def update(self, dt):
        if not self.active_parts: return

        curr_t = ClockObject.getGlobalClock().getFrameTime()
        alive = []
        
        for p in self.active_parts:
            age = curr_t - p.start_time
            alpha = 1.0 - (age * p.decay)
            
            if alpha <= 0:
                if not p.node.isEmpty():
                    p.node.removeNode()
                continue
            
            if p.p_type == 0:
                # Respawn Swirl: Pure Cyan
                curr_angle = p.angle + p.angular_vel * age
                nx = p.cx + math.cos(curr_angle) * p.radius
                ny = p.cy + math.sin(curr_angle) * p.radius
                nz = p.cz + p.height + p.vz * age
                
                if not p.node.isEmpty():
                    p.node.setPos(nx, ny, nz)
                    p.node.setColorScale(0, 1, 1, alpha)

            elif p.p_type == 1:
                # Checkpoint Lift: Pure Lime -> Dark Cyan
                nx = p.cx
                ny = p.cy
                nz = p.cz + (p.vz * age)
                
                if not p.node.isEmpty():
                    p.node.setPos(nx, ny, nz)
                    
                    t = min(1.0, age * p.decay)
                    r = 0.0 * (1.0 - t) + 0.0 * t
                    g = 1.0 * (1.0 - t) + 0.6 * t
                    b = 0.0 * (1.0 - t) + 0.8 * t
                    
                    p.node.setColorScale(r, g, b, alpha)
                
            alive.append(p)
            
        self.active_parts = alive