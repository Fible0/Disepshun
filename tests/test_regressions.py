"""Headless acceptance checks for BUG_REPORT.md B01-B24: execute source class definitions, never game startup/Config.
All scene/collision/math operations use real Panda3D; IO uses temporary directories.
The original defect proofs asserted the broken behavior; these now assert the fixed behavior.
"""
import ast
import builtins
from collections import defaultdict
import json
import shutil
import time
import math
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace as NS
from unittest.mock import patch
import panda3d.core as core

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'disepshun'
class ForbiddenShowBase:
    def __init__(self, *a, **kw):
        raise AssertionError('ShowBase/game construction is forbidden')
G = dict(vars(core), math=math, os=os, threading=threading, builtins=builtins,
         defaultdict=defaultdict, json=json, shutil=shutil, time=time, ShowBase=ForbiddenShowBase,
         COLLIDABLE_MASK=core.BitMask32(1), ROOT_DIR='/nonexistent/disepshun', DATA_DIR='/nonexistent/disepshun/data', SOUND_DIR=str(ROOT / 'assets' / 'sounds')) # Proofs set their own folders; never the real data/
for path in [SRC / 'particle_system.py', SRC / 'world_manager.py', SRC / 'player_physics.py', SRC / 'game_ui.py', ROOT / 'Main.py']:
    tree = ast.parse(path.read_text(), filename=path.name)
    tree.body = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    exec(compile(tree, path.name, 'exec'), G)
World, Physics, App = (G[n] for n in ['WorldManager', 'PlayerPhysics', 'Disepshun'])
V, NP = core.VBase3, core.NodePath
G['random'] = __import__('random')
builtins.base = NS(camera=NP("base-camera"), particles_enabled=False, sound_enabled=False, play_sfx=lambda *a: None,
                   win=NS(getXSize=lambda: 100, getYSize=lambda: 100, movePointer=lambda *a: None))
G['globalClock'] = NS(getDt=lambda: 0.1)
KEYS = dict.fromkeys(['w','s','a','d','space','lcontrol'], False)
TASK = NS(cont='cont')

class ImmediateThread:
    def __init__(self, target, args=(), **kw): self.target, self.args = target, args
    def start(self): self.target(*self.args)
    def is_alive(self): return False
    def join(self, timeout=None): pass

def world(tmp):
    w = World(NP('render'), NS(loadModel=lambda name: NP(name)))
    w.save_file = str(Path(tmp) / 'map.txt')
    return w

def cube(w, pos=(0,0,0.5), material='1'):
    c = w.get_cube('cube'); c.setPos(*pos); c.setTag('material', material); c.setColor(1,1,1,1)
    c.reparentTo(w.platform_holder); w.cubes.append(c); w.cube_map[w.get_grid_key(c.getPos())] = c
    w.register_cube(c); w.request_chunk_update(c.getPos())
    return c

def mover(w, pos=(0,0,0.5), material='1', wp=(5,0,0.5)):
    c = cube(w, pos, material); w.cubes.remove(c); del w.cube_map[w.get_grid_key(c.getPos())]; w.unregister_cube(c)
    m = dict(np=c, origin=c.getPos(), waypoints=[V(*wp)], speed=3., current_idx=1, direction=1, wait_timer=0)
    w.moving_cubes.append(m); w.update_cube_faces(c)
    return m

def physics(w): return Physics(w.render, NP('camera'), w)

def app(w):
    a = App.__new__(App); a.sfx={}; a.sound_enabled=False; a.world=w; a.render=w.render; a.physics=physics(w)
    a.preview=NP('preview'); a.preview.setZ(.5); a.tool_mode=1; a.build_material=1; a.spawned_cube_count=0
    a.cur_bounce=1.3; a.cur_h=0.; a.selected_movers=[]; a.selected_trampolines=[]
    a.paused=False; a.menu_open=False; a.is_focused=True; a.saved_settings={}; a.update_hud=lambda: None; a.draw_wp=lambda: None
    a.cTrav=NS(traverse=lambda render: None)
    a.cHandler=NS(getNumEntries=lambda: 0)
    return a

def hit(a,c):
    a.cHandler=NS(getNumEntries=lambda:1, sortEntries=lambda:None,
                 getEntry=lambda i: NS(getIntoNodePath=lambda:c.find('coll')))

def save(w):
    w.map_is_dirty=True
    with patch.object(threading,'Thread',ImmediateThread): w.save_map()

PROOFS=[]
def proof(name):
    def wrap(fn): PROOFS.append((name,fn)); return fn
    return wrap

def immediate(): return patch.object(threading,'Thread',ImmediateThread)

def live(w):
    return [c for c in w.cubes if c!=w.god_collision_floor]+[m['np'] for m in w.moving_cubes]

@proof('B01 attached moving block stays visible, owned and out of the reuse pool')
def attached(tmp):
    w=world(tmp); m=mover(w); a=app(w)
    with immediate():
        for x in (1,2):
            a.preview.setPos(x,0,.5); hit(a,m['np']); a.place(); m=w.moving_cubes[-1]
    for mc in w.moving_cubes:
        c=mc['np']
        assert c.getParent()==w.platform_holder and len(c.find('face_geom').getChildren())==6 and not c.find('coll').isEmpty()
        assert c not in w.cube_pool
    a.cHandler=NS(getNumEntries=lambda:0); a.preview.setPos(0,5,.5)
    with immediate(): a.place()
    nodes=live(w); assert len(set(nodes))==len(nodes)==4
    print('  2 attached blocks: parented, 6 faces, collider, not pooled; next placement is a distinct node')

@proof('B02 every material round-trips static and moving forms')
def trampoline_save(tmp):
    w=world(tmp)
    for i,mat in enumerate('12345'):
        c=cube(w,(i*3,0,.5),mat); m=mover(w,(i*3,5,.5),mat,wp=(i*3,9,.5))
        m['speed']=2.5
        for n in (c,m['np']):
            if mat=='5': n.setTag('bounciness','1.7'); n.setTag('max_height','8.0')
    save(w); w.load_map()
    assert len(w.cubes)==5 and len(w.moving_cubes)==5 and not w.load_errors
    for c in w.cubes: assert c.getY()==0
    for m in w.moving_cubes:
        assert m['origin'].y==5 and m['speed']==2.5 and [tuple(p) for p in m['waypoints']]==[(m['origin'].x,9,.5)]
    for n in live(w):
        if n.getTag('material')=='5': assert (n.getTag('bounciness'),n.getTag('max_height'))==('1.7','8.0')
    print('  materials 1-5 static and moving: origin, speed, waypoints, bounce, max height intact')

@proof('B03 property edits and conversion are saved without another action')
def unsaved(tmp):
    w=world(tmp); m=mover(w); save(w); a=app(w)
    with immediate():
        a.tool_mode=7; a.selected_movers=[m]; a.adj_val(1)
    w2=world(tmp); w2.load_map(); assert w2.moving_cubes[0]['speed']==3.5
    c=cube(w,(10,0,.5),'5'); save(w)
    with immediate():
        a.tool_mode=5; a.selected_trampolines=[c]; a.adj_val(1); a.adj_h(1)
    w2=world(tmp); w2.load_map(); t=w2.cube_map[(10,0,1)]
    assert t.getTag('bounciness')=='1.4' and t.getTag('max_height')=='0.5'
    s=cube(w,(20,0,.5),'1'); save(w)
    with immediate():
        a.tool_mode=7; a.selected_movers=[]; hit(a,s); a.handle_sel(7)
    w2=world(tmp); w2.load_map(); assert any(x['origin'].x==20 and x['waypoints']==[] for x in w2.moving_cubes)
    print('  speed, bounce, height and waypointless conversion each survive reopen')

@proof('B04 a delayed older writer cannot replace a newer snapshot')
def stale_save(tmp):
    w=world(tmp); c=cube(w); jobs=[]
    class QueuedThread:
        def __init__(self,target,args,**kw): self.target,self.args=target,args
        def start(self): jobs.append((self.target,self.args))
        def is_alive(self): return False
    with patch.object(threading,'Thread',QueuedThread):
        w.map_is_dirty=True; w.save_map(); c.setX(8); w.map_is_dirty=True; w.save_map()
    for fn,args in reversed(jobs): fn(*args)
    assert '\nB,8.0,' in Path(w.save_file).read_text()
    print('  newer x=8 committed first; older x=0 writer skipped')

@proof('B05 failed save keeps old file and dirty state, later retry succeeds')
def failed_save(tmp):
    w=world(tmp); c=cube(w); save(w); good=Path(w.save_file).read_text()
    c.setX(4); real_open=open
    def failing_open(f,*a,**k):
        if str(f).endswith('.tmp'): raise OSError('disk full')
        return real_open(f,*a,**k)
    with patch.object(builtins,'open',failing_open): save(w)
    assert w.map_is_dirty and w.save_error and Path(w.save_file).read_text()==good
    with immediate(): w.retry_save(1e9)
    assert not w.map_is_dirty and w.save_error is None and '\nB,4.0,' in Path(w.save_file).read_text()
    print('  failure: previous file intact, dirty kept, error recorded; retry saved x=4')

@proof('B06 god floor supports landing across its bounds only')
def floor(tmp):
    w=world(tmp); w.visual_floor.show(); w.update_god_collision(True)
    for x,y in [(10,0),(-500,30),(0,-999),(700,700)]:
        p=physics(w); p.god_mode=True; p.player.setPos(x,y,-19.99); p.vz=-2; p.update(.1,KEYS)
        assert abs(p.player.getZ()+20)<1e-4 and p.ground, (x,y,p.player.getZ())
    p=physics(w); p.god_mode=True; p.player.setPos(1001,0,-19.99); p.vz=-2; p.update(.1,KEYS)
    assert p.player.getZ()< -20 and not p.ground
    print('  lands at z=-20 at 4 positions; falls past the edge at x=1001')

@proof('B07 fast falls and rises stop at blocks instead of tunneling')
def tunnel(tmp):
    for dt in (.016,.05,.1):
        for mat in '1345':
            w=world(tmp); c=cube(w,material=mat); p=physics(w); p.player.setPos(0,0,2); p.vz=-40
            if mat=='4': builtins.base.particles_enabled=False
            with immediate():
                for _ in range(int(.3/dt)+1):
                    p.update(dt,KEYS)
                    if p.ground or p.just_respawned: break
            if mat=='3': assert p.just_respawned or p.player.getPos()==p.checkpoint, (dt,mat)
            else: assert p.ground and abs(p.player.getZ()-1)<1e-4, (dt,mat,p.player.getZ())
            if mat=='4': assert w.active_checkpoint_cube==c
        w=world(tmp); cube(w,(0,0,4.5)); p=physics(w); p.player.setPos(0,0,1); p.vz=60; peak=0
        for _ in range(int(.3/dt)+1):
            p.update(dt,KEYS); peak=max(peak,p.player.getZ()+p.player_height)
        assert 3.7<peak<=4.0+1e-4, (dt,peak)
    print('  vz=-40 at dt .016/.05/.1: lands on white/green/blue, dies on red; vz=+60 stops under ceiling')

@proof('B08 riders track vertical and horizontal platforms')
def upward(tmp):
    for wp,dt,spd in [((0,0,5.5),.1,3),((0,0,-4.5),.1,3),((0,0,5.5),.05,8),((5,0,.5),.1,6)]:
        w=world(tmp); m=mover(w,wp=wp); m['speed']=spd; a=app(w); a.physics.player.setPos(0,0,1)
        G['globalClock']=NS(getDt=lambda: dt)
        for _ in range(3):
            a.update_world(TASK); top=m['np'].getPos()+V(0,0,.5); pp=a.physics.player.getPos()
            assert abs(pp.z-top.z)<1e-4 and abs(pp.x-top.x)<1e-4, (wp,pp,top)
    G['globalClock']=NS(getDt=lambda: .1)
    print('  rider feet stay on platform top for up/down/horizontal at several speeds and frame times')

@proof('B09 arrival frames carry the rider by the exact displacement')
def arrival(tmp):
    w=world(tmp); m=mover(w,wp=(1,0,.5)); m['np'].setX(.8); a=app(w); a.physics.player.setPos(.8,0,1)
    a.update_world(TASK); assert m['np'].getX()==1 and abs(a.physics.player.getX()-1)<1e-6
    a.update_world(TASK); assert abs(a.physics.player.getX()-m['np'].getX())<1e-6  # reversal frame
    w=world(tmp); m=mover(w,wp=(5,0,.5)); m['current_idx']=0; a=app(w); a.physics.player.setPos(0,0,1)
    a.update_world(TASK); assert m['np'].getX()==0 and a.physics.player.getX()==0  # zero-distance frame
    print('  arrival, reversal and zero-distance frames move rider with platform')

@proof('B10 platforms cannot push the player through walls or ceilings')
def carry_wall(tmp):
    w=world(tmp); m=mover(w,pos=(.2,0,.5)); cube(w,(1,0,1.5)); a=app(w); p=a.physics
    p.player.setPos(.2,0,1)
    for _ in range(3): a.update_world(TASK)
    assert not p.check_collision(p.player.getPos(),p.player_height,False) and abs(p.player.getX()-.2)<1e-6
    w=world(tmp); m=mover(w,pos=(.2,0,.5)); cube(w,(1,0,1.5),'3'); a=app(w); a.physics.player.setPos(.2,0,1)
    a.update_world(TASK); assert a.physics.just_respawned
    w=world(tmp); m=mover(w,wp=(0,0,5.5)); cube(w,(0,0,3.5)); a=app(w); p=a.physics; p.player.setPos(0,0,1)
    for _ in range(10):
        a.update_world(TASK)
        if p.just_respawned: break
        assert p.player.getZ()+p.player_height<=3.0+1e-4
    assert p.just_respawned
    print('  wall blocks carry (no overlap); lethal wall kills; ceiling crush respawns')

@proof('B11 moving checkpoint away from origin is restored as active')
def moving_cp(tmp):
    w=world(tmp); m=mover(w,material='4'); w.active_checkpoint_cube=m['np']; m['np'].setX(2); save(w)
    w.load_map()
    assert w.active_checkpoint_cube==w.moving_cubes[0]['np'] and w.saved_checkpoint_pos==V(0,0,.5)
    print('  active mover checkpoint restored; spawn above its restored position x=0')

@proof('B12 moving checkpoints refresh their activation color')
def cp_color(tmp):
    w=world(tmp); m=mover(w,material='4'); m2=mover(w,(3,0,.5),material='4'); p=physics(w)
    coll=m['np'].find('coll').node()
    faces=lambda mc:[tuple(round(v,3) for v in n.getColor()) for n in mc['np'].findAllMatches('face_geom/*')]
    with immediate(): p.activate_checkpoint(m['np'])
    assert all(c==(0,.6,.8,1) for c in faces(m)) and len(faces(m))==6
    with immediate(): p.activate_checkpoint(m2['np'])
    assert all(c==(0,1,0,1) for c in faces(m)) and all(c==(0,.6,.8,1) for c in faces(m2))
    assert m['np'].find('coll').node()==coll
    print('  activation turns mover faces cyan, deactivation back to green; collider unchanged')

@proof('B13 deleting a moving checkpoint clears its identity before reuse')
def stale_cp(tmp):
    w=world(tmp); m=mover(w,material='4'); w.active_checkpoint_cube=m['np']; a=app(w); hit(a,m['np'])
    with immediate(): a.delete()
    assert w.active_checkpoint_cube is None and a.physics.checkpoint==V(0,0,1)
    c=cube(w,(9,0,.5),'1'); assert w.active_checkpoint_cube is None; save(w)
    assert 'CP' not in Path(w.save_file).read_text()
    print('  checkpoint cleared on delete; reused node is ordinary; no CP saved')

@proof('B14 lethal overlap triggers regardless of other contacts')
def masked_hazard(tmp):
    for order in ((('1',0),('3',1)),(('3',0),('1',1))):
        w=world(tmp)
        for mat,x in order: cube(w,(x,0,.5),mat)
        p=physics(w); pos=V(.5,0,.99)
        assert p.check_collision(pos,p.player_height,False) and not p.just_respawned
        assert p.check_collision(pos,p.player_height) and p.just_respawned
    w=world(tmp); cube(w,(0,0,.5)); m=mover(w,(1,0,.5),'3'); p=physics(w)
    assert p.check_collision(V(.5,0,.99),p.player_height) and p.just_respawned
    print('  red+white seam kills in either order and with a moving hazard; probes stay side-effect free')

@proof('B15 waypoints can be added with preview hidden or shown')
def preview_wp(tmp):
    w=world(tmp); m=mover(w); a=app(w); a.tool_mode=7; a.selected_movers=[m]; a.preview.setPos(2,0,.5)
    with immediate():
        a.set_preview_enabled(False); a.handle_place_wp(); assert len(m['waypoints'])==2
        a.preview.show(); a.handle_place_wp(); assert len(m['waypoints'])==3
        a.preview.setZ(-20.5); a.handle_place_wp(); assert len(m['waypoints'])==3
    print('  hidden preview adds 1, visible adds 1, below-floor rejected')

@proof('B16 malformed checkpoint line does not discard following blocks')
def malformed_cp(tmp):
    w=world(tmp); Path(w.save_file).write_text('CP,bad,0,0.5\n0,0,0.5,4\n1,0,0.5,1\n'); w.load_map()
    assert len(w.cubes)==2 and len(w.load_errors)==1 and list(Path(tmp).glob('map.txt.*.bak'))
    w2=world(tmp); Path(w2.save_file).unlink(); Path(w2.save_file).mkdir(); w2.load_map()
    assert w2.save_blocked; w2.map_is_dirty=True; save(w2); assert Path(w2.save_file).is_dir()
    print('  2 valid blocks loaded, 1 error reported, original backed up; unreadable map never overwritten')

@proof('B17 wrong settings types fall back to defaults')
def settings(tmp):
    a=App.__new__(App); a.settings_file=str(Path(tmp)/'settings.json')
    for data in ['[]','null','1','{"Sound": "no", "Shaders": false}']:
        Path(a.settings_file).write_text(data); a.load_settings()
        assert isinstance(a.saved_settings,dict) and a.saved_settings.get('Sound',True) is True
    assert a.saved_settings['Shaders'] is False
    print('  [], null, 1 and a non-bool option load as defaults; valid options kept')

@proof('B18 invalid trampoline numbers are rejected at load')
def bad_bounce(tmp):
    for rec in ['bad,0','nan,0','inf,0','1.3,-5','0,0','1.3,inf']:
        w=world(tmp); Path(w.save_file).write_text(f'0,0,0.5,5,{rec}\n2,0,0.5,5,1.5,2\n'); w.load_map()
        assert len(w.cubes)==1 and w.cubes[0].getX()==2 and w.load_errors, rec
    p=physics(w); p.player.setPos(2,0,1.2); p.vz=-6; p.update(.05,dict(KEYS,space=True)); assert p.vz>0
    print('  non-numeric/NaN/inf/out-of-range records rejected; valid trampoline still bounces')

@proof('B19 attaching a block leaves unrelated movers untouched')
def unrelated_reset(tmp):
    w=world(tmp); m=mover(w); other=mover(w,(30,0,.5),wp=(40,0,.5)); other['np'].setX(35); other['direction']=-1
    m['np'].setX(2)
    a=app(w); a.preview.setPos(3,0,.5); hit(a,m['np'])
    with immediate(): a.place()
    assert other['np'].getX()==35 and other['current_idx']==1 and other['direction']==-1
    new=w.moving_cubes[-1]; assert new['np'].getX()==3 and new['origin'].x==1 and m['np'].getX()==2
    print('  unrelated mover stays at x=35; new block joins in lockstep (origin x=1, now x=3)')

@proof('B20 R does not edit the map while paused, works after closing menu')
def paused_undo(tmp):
    w=world(tmp); m=mover(w); a=app(w); a.tool_mode=7; a.selected_movers=[m]; a.paused=True; a.menu_open=True
    with immediate(): a.undo_wp()
    assert len(m['waypoints'])==1 and not Path(w.save_file).exists()
    a.paused=False; a.menu_open=False
    with immediate(): a.undo_wp()
    assert m['waypoints']==[] and Path(w.save_file).exists()
    print('  paused: no change, no save; unpaused: waypoint removed and saved')

@proof('B21 crouching under a lethal ceiling does not kill; real contact does')
def ceiling(tmp):
    w=world(tmp); cube(w,(0,0,.5)); cube(w,(0,0,2.5),'3'); p=physics(w)
    p.player.setPos(0,0,1); p.curr_h=.9; p.player_height=.9; p.ground=True
    for _ in range(5): p.update(.01,KEYS)
    assert not p.just_respawned and p.player_height<1.0
    assert p.check_collision(p.player.getPos(),1.67) and p.just_respawned
    print('  stays crouched under red ceiling; actual standing contact still kills')

@proof('B22 duplicate coordinates are rejected consistently')
def duplicate(tmp):
    w=world(tmp); Path(w.save_file).write_text('0,0,0.5,1\n0,0,0.5,2\n'); w.load_map()
    assert len(w.cubes)==1 and len(w.cube_map)==1 and w.cubes[0].getTag('material')=='1' and w.load_errors
    a=app(w); hit(a,w.cubes[0])
    with immediate(): a.delete()
    w.update_chunks()
    assert not w.cubes and not w.cube_map and not w.chunks_visual
    print('  duplicate rejected (first kept); after deletion no geometry remains')

@proof('B23 rejected mover record leaves no scene nodes')
def orphan(tmp):
    w=world(tmp); Path(w.save_file).write_text('0,0,0.5,1,bad\n5,0,0.5,1\n'); w.load_map()
    assert len(w.cubes)==1 and len(w.moving_cubes)==0
    assert len(w.platform_holder.findAllMatches('**/+CollisionNode'))==1 and not w.cube_pool
    print('  one block, one collider, nothing pooled')

@proof('B24 pending save completes before process exit')
def exit_save(tmp):
    import subprocess
    code = """
import runpy, sys, threading
x=runpy.run_path(sys.argv[1])
w=x['world'](sys.argv[2]); x['cube'](w)
original=w._threaded_save
release=threading.Event()
def held(data, gen):
    release.wait(2)
    original(data, gen)
w._threaded_save=held
w.map_is_dirty=True
w.save_map()
"""
    result=subprocess.run([sys.executable,'-c',code,str(Path(__file__).resolve()),tmp],capture_output=True,text=True,timeout=10)
    assert result.returncode==0, result.stderr
    assert (Path(tmp)/'map.txt').read_text().startswith('#DISEPSHUN_MAP')
    w=world(tmp); cube(w); save(w); good=Path(w.save_file).read_text()
    # Forced interruption mid-write: temp file half written, never swapped in
    w.cubes[0].setX(3); w.map_is_dirty=True
    with patch.object(os,'replace',side_effect=KeyboardInterrupt):
        try: save(w)
        except KeyboardInterrupt: pass
    assert Path(w.save_file).read_text()==good
    w2=world(tmp); w2.cubes=[]; assert w2.flush_saves(5) is True
    print('  delayed writer finished before exit; interrupted write left previous save intact')


@proof('B26 coyote time: a jump just after walking off a ledge still works, but only once and only briefly')
def coyote(tmp):
    dt=.016; space=dict(KEYS, space=True)
    def off_ledge():
        w=world(tmp); cube(w); p=physics(w); p.player.setPos(0,0,1); p.update(dt,KEYS); assert p.ground
        p.player.setX(.8); p.update(dt,KEYS); assert not p.ground  # stepped off the edge
        return p
    p=off_ledge(); p.update(dt,space); assert p.vz>7, p.vz
    p.update(dt,space); p.update(dt,space); assert p.vz<p.jump-2*abs(p.g)*dt+1e-6, p.vz  # no second jump
    p=off_ledge()
    for _ in range(int(p.coyote_time/dt)+1): p.update(dt,KEYS)
    p.update(dt,space); assert p.vz<0, p.vz
    print('  jump 1 frame after leaving the ledge works; no double jump; jump after the window fails')

@proof('B27 trampoline ghost heights match the first and highest bounces of a real jump held on it')
def bounce_ghost(tmp):
    dt=1/60; space=dict(KEYS, space=True)
    for b,mh in [(1.3,4.),(1.5,2.),(.8,0.),(1.,0.),(2.,0.)]:
        w=world(tmp); t=cube(w,material='5'); t.setTag('bounciness',str(b)); t.setTag('max_height',str(mh))
        p=physics(w); p.player.setPos(0,0,1); p.update(dt,KEYS); assert p.ground
        first,top=p.bounce_heights(t,dt); apexes=[]; peak=0.; prev=0.
        for _ in range(int(40/dt)):
            p.update(dt,space); z=p.player.getZ()-1
            if p.vz<=0<prev: apexes.append(peak); peak=0.
            if p.vz>0: peak=max(peak,z)  # highest point of each rise
            prev=p.vz
            if len(apexes)>=12: break
        sim_first=apexes[1]; sim_top=max(apexes)  # apexes[0] is the standing jump
        if b>1 and mh==0: assert top>990 and sim_top>apexes[1]*1.5, (top,apexes)
        else: assert abs(sim_top-top)<.02, (b,mh,top,apexes)
        assert abs(sim_first-first)<.02, (b,mh,first,apexes)
        print(f'  bounce {b}, max {mh}: first {first:.2f} (sim {sim_first:.2f}), highest {top:.2f} (sim {sim_top:.2f})')

if __name__=='__main__':
    failures=[]
    print('Source classes only; no Config execution, ShowBase, graphics pipe, window, or game loop.')
    print('Panda3D:',core.PandaSystem.get_version_string())
    for name,fn in PROOFS:
        try:
            with tempfile.TemporaryDirectory(prefix='disepshun-proof-') as tmp: fn(tmp)
            print('PASSED',name)
        except Exception as e:
            failures.append(name); print('FAILED',name,repr(e)); __import__('traceback').print_exc()
    print(f'{len(PROOFS)-len(failures)}/{len(PROOFS)} checks passed')
    sys.exit(bool(failures))
