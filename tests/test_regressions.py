"""Headless acceptance checks for BUG_REPORT.md B01-B24: execute source class definitions, never game startup/Config.
All scene/collision/math operations use real Panda3D; IO uses temporary directories.
The original defect proofs asserted the broken behavior; these now assert the fixed behavior.
"""
import ast
import gzip
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
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from disepshun.editor_tools import EditorTools
import panda3d.core as core

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'disepshun'
class ForbiddenShowBase:
    def __init__(self, *a, **kw):
        raise AssertionError('ShowBase/game construction is forbidden')
G = dict(vars(core), EditorTools=EditorTools, math=math, os=os, threading=threading, builtins=builtins,
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
KEYS = dict.fromkeys(['w','s','a','d','space','lshift','rshift'], False)
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
    c = cube(w, pos, material); w.cubes.remove(c); del w.cube_map[w.get_grid_key(c.getPos())]; w.unregister_cube(c); c.reparentTo(w.platform_holder)
    m = dict(np=c, origin=c.getPos(), waypoints=[V(*wp)], speed=3., current_idx=1, direction=1, wait_timer=0)
    w.moving_cubes.append(m); w.update_cube_faces(c)
    return m

def physics(w): return Physics(w.render, NP('camera'), w)

def app(w):
    a = App.__new__(App); a.sfx={}; a.sound_enabled=False; a.world=w; a.render=w.render; a.physics=physics(w)
    a.preview=NP('preview'); a.preview.setZ(.5); a.tool_mode=1; a.build_material=1; a.build_dist=5; a.spawned_cube_count=0
    a.selected_objects=[]; a.clipboard=[]; a.selection_node=None
    a.tool_phases={tool:'tinker' for tool in a.TOOL_SLOTS}; a.tool_phases[10]='select'
    a.keyMap=dict.fromkeys(('mouse1','mouse3','minus','plus','z','x'),False); a.timers=dict.fromkeys(a.keyMap,0)
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

def map_text(path):
    data = Path(path).read_bytes()
    return json.loads(gzip.decompress(data[6:]))['records'] if data.startswith(b'DMAP3\n') else data.decode()

PROOFS=[]
def proof(name):
    def wrap(fn): PROOFS.append((name,fn)); return fn
    return wrap

def immediate(): return patch.object(threading,'Thread',ImmediateThread)

def settle(w):
    """Write the debounced save now, as the frame after the debounce window would."""
    with immediate(): w.flush_saves()

def mover_faces(node):
    """A mover's single styled cube geom."""
    geom=node.find('face_geom'); assert not geom.isEmpty() and geom.node().getNumGeoms()==1
    return [geom]

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
        assert c.getParent()==w.platform_holder and len(mover_faces(c))==1 and not c.find('coll').isEmpty()
        assert c not in w.cube_pool
    a.cHandler=NS(getNumEntries=lambda:0); a.preview.setPos(0,5,.5)
    with immediate(): a.place()
    nodes=live(w); assert len(set(nodes))==len(nodes)==4
    print('  2 attached blocks: parented, one cube geom, collider, not pooled; next placement is a distinct node')

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
    settle(w); w2=world(tmp); w2.load_map(); assert w2.moving_cubes[0]['speed']==3.5
    c=cube(w,(10,0,.5),'5'); save(w)
    with immediate():
        a.tool_mode=8; a.selected_trampolines=[c]; a.adj_val(1); a.adj_h(1)
    settle(w); w2=world(tmp); w2.load_map(); t=w2.cube_map[(10,0,1)]
    assert t.getTag('bounciness')=='1.4' and t.getTag('max_height')=='0.5'
    s=cube(w,(20,0,.5),'1'); save(w)
    with immediate():
        a.tool_mode=7; a.selected_movers=[]; a.tool_phases[7]='select'; hit(a,s); a.select_object()
        assert s in w.cubes, 'selection must not convert a static block'
        a.tool_phases[7]='tinker'; a.adj_val(1)
    settle(w); w2=world(tmp); w2.load_map(); assert any(x['origin'].x==20 and x['waypoints']==[] for x in w2.moving_cubes)
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
    assert '\nB,8.0,' in map_text(w.save_file)
    print('  newer x=8 committed first; older x=0 writer skipped')

@proof('B05 failed save keeps old file and dirty state, later retry succeeds')
def failed_save(tmp):
    w=world(tmp); c=cube(w); save(w); good=map_text(w.save_file)
    c.setX(4); real_open=open
    def failing_open(f,*a,**k):
        if str(f).endswith('.tmp'): raise OSError('disk full')
        return real_open(f,*a,**k)
    with patch.object(builtins,'open',failing_open): save(w)
    assert w.map_is_dirty and w.save_error and map_text(w.save_file)==good
    with immediate(): w.retry_save(1e9)
    assert not w.map_is_dirty and w.save_error is None and '\nB,4.0,' in map_text(w.save_file)
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
    a.update_world(TASK); assert abs(m['np'].getX()-.9)<1e-6 and abs(a.physics.player.getX()-.9)<1e-6
    a.update_world(TASK); assert abs(a.physics.player.getX()-m['np'].getX())<1e-6  # reversal frame
    w=world(tmp); m=mover(w,wp=(5,0,.5)); m['current_idx']=0; a=app(w); a.physics.player.setPos(0,0,1)
    a.update_world(TASK); assert abs(m['np'].getX()-.3)<1e-6 and abs(a.physics.player.getX()-.3)<1e-6  # no zero-distance pause
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
    faces=lambda mc:[tuple(round(v,3) for v in n.getColor()) for n in mover_faces(mc['np'])]
    with immediate(): p.activate_checkpoint(m['np'])
    assert all(c==(0,.6,.8,1) for c in faces(m)) and len(faces(m))==1
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
    assert 'CP' not in map_text(w.save_file)
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

@proof('B20 waypoint deletion does not edit the map while paused, works after closing menu')
def paused_undo(tmp):
    w=world(tmp); m=mover(w); a=app(w); a.tool_mode=7; a.selected_movers=[m]; a.paused=True; a.menu_open=True
    with immediate(): a.undo_wp()
    assert len(m['waypoints'])==1 and not Path(w.save_file).exists()
    a.paused=False; a.menu_open=False
    with immediate(): a.undo_wp()
    settle(w); assert m['waypoints']==[] and Path(w.save_file).exists()
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
    assert map_text(Path(tmp)/'map.txt').startswith('#DISEPSHUN_MAP')
    w=world(tmp); cube(w); save(w); good=map_text(w.save_file)
    # Forced interruption mid-write: temp file half written, never swapped in
    w.cubes[0].setX(3); w.map_is_dirty=True
    with patch.object(os,'replace',side_effect=KeyboardInterrupt):
        try: save(w)
        except KeyboardInterrupt: pass
    assert map_text(w.save_file)==good
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

@proof('E01 trampoline block places/deletes normally; tool selects static and moving trampolines')
def separate_trampoline(tmp):
    w=world(tmp); a=app(w); a.tool_mode=5; a.build_material=5
    with immediate(): a.place()
    c=w.cubes[0]; hit(a,c)
    with immediate(): a.delete()
    assert not w.cubes
    c=cube(w,material='5'); m=mover(w,(4,0,.5),'5')
    a.tool_mode=8; a.tool_phases[8]='select'; a.pick_object=lambda: c; a.select_object()
    a.pick_object=lambda: m['np']; a.select_object()
    a.tool_phases[8]='tinker'
    with immediate(): a.adj_val(1); a.adj_h(1)
    assert len(a.selected_objects)==2
    for n in (c,m['np']): assert n.getTag('bounciness')=='1.4' and n.getTag('max_height')=='0.5'

@proof('E02 grouping selects the whole group and persists across reopen')
def groups(tmp):
    w=world(tmp); a=app(w); a.tool_mode=10
    c=cube(w); d=cube(w,(1,0,.5)); a.selected_objects=[c,d]
    with immediate(): a.group_selection()
    group=c.getTag('group'); assert group and d.getTag('group')==group
    a.tool_phases[10]='select'
    a.selected_objects=[]; a.pick_object=lambda:c; a.select_object(); assert a.selected_objects==[c,d]
    a.select_object(); assert not a.selected_objects
    settle(w); w.load_map(); assert len(w.cubes)==2 and all(n.getTag('group')==group for n in w.cubes)
    a.selected_objects=list(w.cubes); a.tool_phases[10]='tinker'
    with immediate(): a.group_selection(True)
    assert all(not n.getTag('group') for n in w.cubes)

@proof('E03 batch move and rotate preserve collider ownership, grid indexes and mover paths')
def batch_transform(tmp):
    w=world(tmp); a=app(w); a.tool_mode=11
    c=cube(w,(1,0,.5)); m=mover(w,(0,0,.5),wp=(0,4,.5)); a.selected_objects=[c,m['np']]
    with immediate(): a.transform_selection(rotate=True); a.transform_selection(2,3,1)
    assert c.getPos()==V(2,4,1.5) and w.cube_map[w.get_grid_key(c.getPos())]==c
    assert m['origin']==V(2,3,1.5) and m['waypoints']==[V(-2,3,1.5)]
    assert c in w.chunk_contents[w.get_chunk_key(c.getPos())] and c not in w.cube_pool
    assert len(mover_faces(m['np']))==1
    settle(w); w.load_map(); assert w.moving_cubes[0]['waypoints']==[V(-2,3,1.5)]

@proof('E04 blocked batch transform makes no partial changes')
def batch_overlap(tmp):
    w=world(tmp); a=app(w); a.tool_mode=11; a.editor_notice=lambda text: None
    c=cube(w); d=cube(w,(1,0,.5)); cube(w,(2,0,.5)); a.selected_objects=[c,d]
    with immediate(): a.transform_selection(1,0,0)
    assert c.getPos()==V(0,0,.5) and d.getPos()==V(1,0,.5) and len(w.cube_map)==3
    assert not Path(w.save_file).exists()

@proof('E05 clipboard preserves paths/properties and gives copied groups new identities')
def clipboard(tmp):
    w=world(tmp); a=app(w); a.tool_mode=11
    c=cube(w,material='5'); c.setTag('bounciness','1.8'); c.setTag('max_height','8')
    m=mover(w,(1,0,.5),'4'); m['np'].setTag('heading','225')
    a.selected_objects=[c,m['np']]
    with immediate():
        a.tool_mode=10; a.group_selection(); group=c.getTag('group'); a.tool_mode=11; a.selection_command('copy')
        a.preview.setPos(11,0,.5); a.selection_command('paste')
    copied=a.selected_objects
    assert len(copied)==2 and copied[0].getPos()==V(10,0,.5)
    assert copied[0].getTag('bounciness')=='1.8' and copied[0].getTag('max_height')=='8.0'
    assert copied[0].getTag('group')==copied[1].getTag('group')!=group
    assert copied[1].getTag('heading')=='225'
    mm=w.find_mover(copied[1]); assert mm['origin']==V(11,0,.5) and mm['waypoints']==[V(15,0,.5)]
    with immediate(): a.selection_command('delete')
    assert len(w.all_blocks())==2 and not a.selected_objects
    settle(w); w.load_map(); assert len(w.all_blocks())==2

@proof('E06 checkpoint direction survives save/reopen and controls respawn; pooling clears it')
def facing(tmp):
    w=world(tmp); c=cube(w,material='4'); a=app(w); a.tool_mode=9; a.selected_objects=[c]
    with immediate(): a.adjust_checkpoint(-1); a.physics.activate_checkpoint(c)
    a.physics.respawn(); assert abs(a.physics.player.getH()-345)<.001
    with immediate(): assert w.flush_saves()
    w.load_map(); assert w.active_checkpoint_cube.getTag('heading')=='345.0'
    p=physics(w); p.respawn(); assert abs(p.player.getH()-345)<.001
    w.remove_block(w.active_checkpoint_cube); c=cube(w,(3,0,.5)); assert not c.getTag('heading') and not c.getTag('group')

@proof('E07 legacy maps migrate with backups and converter preserves originals')
def migration(tmp):
    source=Path(tmp)/'map.txt'; original='CP,0,0,0.5\n0,0,0.5,4\n1,0,0.5,5,1.7,4\n'
    source.write_text(original); w=world(tmp); w.save_file=str(Path(tmp)/'map.dmf')
    with immediate(): w.load_map()
    assert source.read_text()==original and list(Path(tmp).glob('map.txt.*.bak'))
    assert Path(w.save_file).read_bytes().startswith(b'DMAP3\n')
    source2=Path(tmp)/'other.txt'; source2.write_text(original)
    assert w.convert_maps(tmp)==1 and source2.read_text()==original
    assert w.convert_maps(tmp)==0
    w.save_file=str(Path(tmp)/'other.dmf'); w.load_map()
    assert len(w.cubes)==2 and w.active_checkpoint_cube.getTag('material')=='4'

@proof('E08 corrupt compressed maps leave the scene and source intact')
def corrupt_compressed(tmp):
    w=world(tmp); c=cube(w)
    for data in (b'DMAP3\nnot gzip', b'DMAP3\n'+gzip.compress(b'[]'), b'DMAP3\n'+gzip.compress(b'{"version":99}')):
        Path(w.save_file).write_bytes(data); w.load_map()
        assert w.save_blocked and w.cubes==[c] and Path(w.save_file).read_bytes()==data

@proof('E09 compressed format substantially reduces a representative map')
def compression(tmp):
    w=world(tmp)
    for x in range(30):
        for y in range(30): cube(w,(x,y,.5),str(1+(x+y)%5))
    compressed=w.serialize_map(); text=w.serialize_records().encode()
    assert len(compressed)<len(text)*.4, (len(compressed),len(text))
    save(w); w.load_map(); assert len(w.cubes)==900 and not w.load_errors
    print(f'  900 blocks: {len(text)} text bytes -> {len(compressed)} compressed bytes')

@proof('E10 edits reject paths outside format bounds and off-grid clipboard pastes')
def transform_limits(tmp):
    w=world(tmp); a=app(w); a.tool_mode=11; a.editor_notice=lambda text:None
    m=mover(w,wp=(10000,0,.5)); a.selected_objects=[m['np']]
    with immediate(): a.transform_selection(1,0,0)
    assert m['origin']==V(0,0,.5) and not Path(w.save_file).exists()
    c=cube(w,(2,0,.5)); m['np'].setX(.2); a.selected_objects=[c,m['np']]
    a.selection_command('copy'); a.preview.setPos(10,0,.5)
    with immediate(): a.selection_command('paste')
    assert len(w.all_blocks())==2

@proof('E11 Select/Tinker isolate selection changes from edits in dual-mode tools')
def two_modes(tmp):
    for tool in (7,11):
        w=world(tmp); c=cube(w,material='5' if tool==8 else '4' if tool==9 else '1')
        d=cube(w,(3,0,.5),material=c.getTag('material')); a=app(w); a.tool_mode=tool
        a.tool_phases[tool]='select'; a.pick_object=lambda:c
        before=w.serialize_records(); a.select_object(); assert a.selected_objects==[c]
        with immediate():
            a.adj_val(1); a.adj_h(1); a.handle_place_wp(); a.undo_wp()
            a.transform_selection(2,0,0); a.group_selection(); a.selection_command('delete')
            a.checkpoint_face_camera(); a.adjust_checkpoint(1)
        assert w.serialize_records()==before and not Path(w.save_file).exists()
        a.toggle_tool_phase(); assert a.tool_phases[tool]=='tinker' and a.selected_objects==[c]
        a.pick_object=lambda:d; a.select_object(); assert a.selected_objects==[c]
        with immediate():
            if tool==7: a.preview.setPos(0,5,.5); a.handle_place_wp(); assert len(w.moving_cubes)==1
            elif tool==8: a.adj_val(1); assert c.getTag('bounciness')=='1.4'
            elif tool==9: a.adjust_checkpoint(1); assert c.getTag('heading')=='15.0'
            elif tool==10: a.group_selection(); assert c.getTag('group')
            else: a.transform_selection(1,0,0); assert c.getX()==1
        settle(w); assert Path(w.save_file).exists(); Path(w.save_file).unlink()
        a.toggle_tool_phase(); assert a.tool_phases[tool]=='select' and a.selected_objects==[c]
        a.pick_object=lambda:c; a.select_object(); assert not a.selected_objects

@proof('E12 restored tool selection colors apply to ordinary and glowing static/moving blocks')
def tool_colors(tmp):
    colors=App.SELECTION_COLORS; assert len(set(colors.values()))==6
    for tool,color in colors.items():
        w=world(tmp); c=cube(w); m=mover(w,(3,0,.5),'3'); a=app(w); a.tool_mode=tool
        a.selected_objects=[c,m['np']]; a.refresh_object_selection(); w.update_chunks()
        assert c.getPythonTag('selection_color')==color
        assert all(tuple(round(v,2) for v in f.getColor())==color for f in mover_faces(m['np']))
        assert all(f.getMaterial().getEmission().lengthSquared()>0 and f.hasTexture(w.glow_stage) for f in mover_faces(m['np']))
        face=NP('selected_static'); w.style_face(face,c)
        assert tuple(round(v,2) for v in face.getColor())==color and tuple(face.getColorScale())==(1,1,1,1)
        a.selected_objects=[]; a.refresh_object_selection()
        assert not c.hasPythonTag('selection_color') and not m['np'].hasPythonTag('selection_color')
        assert all(tuple(f.getColor())==(1,0,0,1) for f in mover_faces(m['np']))
        w.style_face(face,c); assert tuple(face.getColor())==(1,1,1,1)

@proof('E13 glowing blocks retain emission and a diffuse lighting response')
def lit_glow(tmp):
    w=world(tmp)
    for material in (w.red_glow_mat,w.lime_glow_mat,w.cyan_glow_mat):
        emission=tuple(material.getEmission()); diffuse=tuple(material.getDiffuse())
        assert max(emission[:3])>0 and max(emission[:3])<.65
        assert max(diffuse[:3])>.3 and material.hasAmbient()
    c=cube(w,material='4'); m=mover(w,(3,0,.5),'3'); w.update_chunks()
    for node in w.chunks_visual.values():
        for geom in node.findAllMatches('**/+GeomNode'):
            for i in range(geom.node().getNumGeoms()):
                state=geom.node().getGeomState(i); attr=state.getAttrib(core.MaterialAttrib)
                assert attr is not None and max(tuple(attr.getMaterial().getEmission())[:3])>0
    assert all(f.hasMaterial() for f in mover_faces(m['np']))

@proof('E14 either Shift crouches and descends in flight; Ctrl does neither')
def shift_crouch(tmp):
    w=world(tmp); cube(w)
    for key in ('lshift','rshift'):
        p=physics(w); p.player.setPos(0,0,1)
        for _ in range(10): p.update(.016,dict(KEYS,**{key:True}))
        assert p.player_height<1.2
        p.flying=True; z=p.player.getZ(); p.update(.1,dict(KEYS,**{key:True})); assert p.player.getZ()<z
    p=physics(w); p.player.setPos(0,0,1)
    for _ in range(10): p.update(.016,dict(KEYS,lcontrol=True))
    assert p.player_height>1.6
    p.flying=True; z=p.player.getZ(); p.update(.1,dict(KEYS,lcontrol=True)); assert p.player.getZ()==z

@proof('E15 every selected checkpoint has a visible facing arrow in both tool modes')
def checkpoint_arrows(tmp):
    w=world(tmp); c=cube(w,material='4'); m=mover(w,(3,0,.5),'4')
    c.setTag('heading','90'); m['np'].setTag('heading','225')
    a=app(w); a.tool_mode=9; a.selected_objects=[c,m['np']]
    for phase in ('select','tinker'):
        a.tool_phases[9]=phase; a.draw_checkpoint_direction()
        markers=list(a.selection_node.getChildren()); assert len(markers)==2
        assert not a.selection_node.getDepthTest() and not a.selection_node.getDepthWrite()
        for marker,checkpoint in zip(markers,a.selected_objects):
            assert (marker.getPos()-checkpoint.getPos()-V(0,0,.95)).length()<1e-5
            h=math.radians(float(checkpoint.getTag('heading')))
            forward=marker.getQuat().getForward()
            assert (forward-V(-math.sin(h),math.cos(h),0)).length()<1e-5
            assert not marker.find('**/checkpoint_arrow_mesh').isEmpty()
    m['np'].setPos(5,2,3); a.draw_checkpoint_direction()
    assert (a.selection_node.getChild(1).getPos()-V(5,2,3.95)).length()<1e-5
    a.tool_mode=8; a.draw_checkpoint_direction(); assert a.selection_node is None

@proof('E16 bloom masks belong to glowing faces and survive selection/restyling')
def glow_masks(tmp):
    w=world(tmp)
    for mat in ('1','3','4'):
        c=cube(w,(int(mat)*2,0,.5),mat)
        face=NP('face'); w.style_face(face,c)
        assert face.hasTexture(w.glow_stage)==(mat in ('3','4'))
        if mat in ('3','4'):
            c.setPythonTag('selection_color',App.SELECTION_COLORS[9]); w.style_face(face,c)
            assert face.hasTexture(w.glow_stage)
            c.clearPythonTag('selection_color'); w.style_face(face,c)
            assert face.hasTexture(w.glow_stage)
    m=mover(w,(12,0,.5),'4')
    assert all(f.hasTexture(w.glow_stage) for f in mover_faces(m['np']))

@proof('E17 a checkpoint seam retains one activation across frames and partial collision probes')
def stable_checkpoint_seam(tmp):
    w=world(tmp); a=cube(w,(0,0,.5),'4'); b=cube(w,(1,0,.5),'4'); p=physics(w)
    p.player.setPos(.5,0,1)
    with patch.object(p,'activate_checkpoint',wraps=p.activate_checkpoint) as activate:
        for _ in range(300): p.update(1/120,KEYS)
        active=w.active_checkpoint_cube; assert active in (a,b) and activate.call_count==1
        other=b if active==a else a
        for _ in range(20):
            p.checkpoint_activated_this_update=False
            p.handle_contacts([other])
            assert w.active_checkpoint_cube==active
        assert activate.call_count==1
        p.player.setX(other.getX())
        p.update(1/120,KEYS)
        assert w.active_checkpoint_cube==other and activate.call_count==2
        assert p.activate_checkpoint(other) is False

@proof('E18 checkpoint placements batch snapshots and still save the latest checkpoint at exit')
def checkpoint_save_burst(tmp):
    w=world(tmp); a=app(w); a.tool_mode=4; a.build_material=4
    for i in range(500): cube(w,(i%50,i//50, -2.5))
    with patch.object(time,'monotonic',return_value=10), patch.object(w,'serialize_map',wraps=w.serialize_map) as snapshots:
        for z in range(40):
            a.preview.setPos(0,0,z+.5); a.place(); a.physics.activate_checkpoint(w.cubes[-1])
        assert snapshots.call_count==0 and not Path(w.save_file).exists()
        with immediate(): w.retry_save(999)
        assert snapshots.call_count==0
        with patch.object(time,'monotonic',return_value=10.36), immediate(): w.retry_save(999)
        assert snapshots.call_count==1
        last=w.active_checkpoint_cube.getPos()
        w2=world(tmp); w2.load_map(); assert w2.saved_checkpoint_pos==last
        a.preview.setPos(0,0,40.5); a.place(); a.physics.activate_checkpoint(w.cubes[-1])
        with immediate(): assert w.flush_saves()
        assert snapshots.call_count==2
        w2.load_map(); assert w2.saved_checkpoint_pos==V(0,0,40.5)

@proof('E19 checkpoint particle bursts respect the configured node budget')
def checkpoint_particle_budget(tmp):
    particles=G['ParticleSystem'](NP('particles'),pool_size=45)
    for _ in range(100): particles.activate_checkpoint(V(0,0,0))
    assert len(particles.active_parts)==45 and particles.parent.getNumChildren()==45

@proof('E20 nearby glow lights have a fixed budget and update checkpoint color/position')
def glow_light_budget(tmp):
    w=world(tmp)
    for x in range(20): cube(w,(x,0,.5),'4')
    m=mover(w,(0,1,.5),'3')
    w.update_glow_lights(V(0,0,2),now=0)
    assert len(w.glow_lights)==4 and len(w.glow_sources)==4
    assert m['np'] in w.glow_sources
    i=w.glow_sources.index(m['np']); m['np'].setZ(2)
    w.update_glow_lights(V(0,0,2),now=.1)
    assert w.glow_lights[i][1].getPos()==m['np'].getPos()
    cp=next(c for c in w.glow_sources if c.getTag('material')=='4')
    w.active_checkpoint_cube=cp; w.update_glow_lights(V(0,0,2),now=.11)
    light=w.glow_lights[w.glow_sources.index(cp)][0]
    assert light.getColor().z>1 and light.getColor().x==0

@proof('E21 Grouping and Selection expose only their own editing actions')
def separate_tools(tmp):
    w=world(tmp); c=cube(w); d=cube(w,(2,0,.5)); a=app(w); a.selected_objects=[c,d]; a.tool_mode=10
    before=w.serialize_records()
    with immediate():
        for command in ('copy','cut','paste','delete','all','clear'): a.selection_command(command)
        a.transform_selection(1,0,0); a.place()
    assert w.serialize_records()==before and not a.clipboard and a.selected_objects==[c,d]
    with immediate(): a.group_selection()
    group=c.getTag('group'); assert group and d.getTag('group')==group
    a.tool_mode=11
    with immediate(): a.group_selection(True)
    assert c.getTag('group')==group
    a.selection_command('copy'); assert len(a.clipboard)==2
    with immediate(): a.transform_selection(1,0,0)
    assert c.getX()==1 and d.getX()==3

@proof('E22 shared pivot setting controls Selection rotation, movement and paste')
def selection_pivots(tmp):
    for use_last in (False,True):
        sub=Path(tmp)/str(use_last); sub.mkdir(); w=world(sub); a=app(w); a.tool_mode=11
        nodes=[cube(w,(x,0,.5)) for x in (0,2,4)]; a.selected_objects=nodes
        a.saved_settings['Use Last Selected as Pivot']=use_last
        with immediate(): a.transform_selection(rotate=True)
        pivot=4 if use_last else 2
        assert [tuple(c.getPos()) for c in nodes]==[(pivot,x-pivot,.5) for x in (0,2,4)]
        a.draw_selection_center(); marker=a.selection_center_node
        center=a.reference_point([c.getPos() for c in nodes],grid_z=True)
        assert (marker.getPos()-center).length()<1e-5
        assert a.selection_pivot_node==marker and not marker.isHidden()
        for _ in range(5): a.draw_selection_center()
        assert a.selection_center_node==marker
        with immediate(): a.transform_selection(1,1,0)
        a.draw_selection_center(); assert (marker.getPos()-center-V(1,1,0)).length()<1e-5
        a.selected_objects=[]; a.draw_selection_center(); assert marker.isHidden()
    w=world(tmp); a=app(w); a.tool_mode=11; a.selected_objects=[cube(w,(x,0,.5)) for x in (0,2,4)]
    a.saved_settings['Use Last Selected as Pivot']=True; a.selection_command('copy')
    a.saved_settings['Use Last Selected as Pivot']=False; a.preview.setPos(10,0,.5)
    with immediate(): a.selection_command('paste')
    assert [c.getX() for c in a.selected_objects]==[8,10,12]

@proof('E23 pivot preference migrates and also controls Waypoint reference')
def shared_pivot_setting(tmp):
    a=App.__new__(App); a.settings_file=str(Path(tmp)/'settings.json')
    Path(a.settings_file).write_text('{"Relative Waypoints":true,"Sound":false}')
    a.load_settings(); assert a.saved_settings=={'Use Last Selected as Pivot':True,'Sound':False}
    for use_last in (False,True):
        sub=Path(tmp)/str(use_last); sub.mkdir(); w=world(sub); a=app(w); a.tool_mode=7
        a.selected_movers=[mover(w,(x,0,.5)) for x in (0,2,4)]
        for m in a.selected_movers: m['waypoints']=[]
        a.saved_settings['Use Last Selected as Pivot']=use_last; a.preview.setPos(10,5,.5)
        with immediate(): a.handle_place_wp()
        pivot=4 if use_last else 2
        assert all(m['waypoints']==[m['origin']+V(10-pivot,5,0)] for m in a.selected_movers)

@proof('E24 batched meshes cull shared faces, retain normals, and pick logical colliders')
def batched_mesh(tmp):
    w=world(tmp); a=cube(w); b=cube(w,(1,0,.5)); w.update_chunks()
    chunk=next(iter(w.chunks_visual.values())).node(); assert chunk.getNumGeoms()==1
    geom=chunk.getGeom(0); assert geom.getVertexData().getNumRows()==40 and geom.getPrimitive(0).getNumPrimitives()==20
    positions=core.GeomVertexReader(geom.getVertexData(),'vertex'); normals=core.GeomVertexReader(geom.getVertexData(),'normal')
    for _ in range(10):
        points=[positions.getData3() for _ in range(4)]; ns=[normals.getData3() for _ in range(4)]
        assert (points[1]-points[0]).cross(points[2]-points[0]).dot(ns[0])>.9
    assert a.getParent()==w.collision_chunks[w.get_chunk_key(a.getPos())]
    ray=core.CollisionRay(-3,0,.5,1,0,0); node=core.CollisionNode('probe'); node.addSolid(ray)
    node.setFromCollideMask(core.BitMask32(1)); node.setIntoCollideMask(core.BitMask32.allOff())
    probe=w.render.attachNewNode(node); traverser=core.CollisionTraverser(); queue=core.CollisionHandlerQueue(); traverser.addCollider(probe,queue)
    traverser.traverse(w.render); queue.sortEntries(); assert queue.getEntry(0).getIntoNodePath().getParent()==a
    w.remove_block(b); w.update_chunks(); assert next(iter(w.chunks_visual.values())).node().getGeom(0).getVertexData().getNumRows()==24

@proof('E25 save compression runs on its writer thread and preserves the captured snapshot')
def background_compression(tmp):
    w=world(tmp); c=cube(w); main=threading.get_ident(); threads=[]; original=gzip.compress
    def tracked(*args,**kwargs): threads.append(threading.get_ident()); return original(*args,**kwargs)
    with patch.object(gzip,'compress',side_effect=tracked):
        w.map_is_dirty=True; w.save_map(); c.setX(7); assert w.flush_saves()
    assert threads and all(t!=main for t in threads)
    w.load_map(); assert len(w.cubes)==1 and w.cubes[0].getX()==0

@proof('E26 checkpoint arrows reuse nodes and checkpoint glow parameters remain unchanged')
def persistent_overlays_and_glow(tmp):
    w=world(tmp); c=cube(w,material='4'); a=app(w); a.tool_mode=9; a.selected_objects=[c]
    a.draw_checkpoint_direction(); root=a.selection_node; marker=root.getChild(0)
    for _ in range(20): a.draw_checkpoint_direction()
    assert a.selection_node==root and root.getChild(0)==marker
    assert abs(w.red_glow_mat.getEmission().x-.45)<1e-5
    assert abs(w.lime_glow_mat.getEmission().y-.45)<1e-5
    assert abs(w.cyan_glow_mat.getEmission().z-.36)<1e-5

@proof('E27 Selection center follows a moving object in the same world update')
def moving_selection_center(tmp):
    w=world(tmp); m=mover(w); a=app(w); a.tool_mode=11; a.selected_objects=[m['np']]
    a.physics.flying=True; G['globalClock']=NS(getDt=lambda:.1)
    a.update_world(TASK)
    assert m['np'].getX()>0 and a.selection_center_node.getPos()==m['np'].getPos()

@proof('E28 deleting or cutting one grouped member affects the entire group, with checkpoint-safe undo/redo')
def group_deletion_history(tmp):
    w=world(tmp); c=cube(w); t=cube(w,(2,0,.5),'5'); t.setTag('bounciness','1.8')
    m=mover(w,(4,0,.5),'4'); m['np'].setTag('heading','135'); m['np'].setX(4.25)
    for n in (c,t,m['np']): n.setTag('group','three')
    outside=cube(w,(20,0,.5)); a=app(w); a.physics.activate_checkpoint(m['np']); hit(a,c)
    with immediate(): a.delete()
    assert w.all_blocks()==[outside] and w.active_checkpoint_cube is None
    assert a.physics.checkpoint==V(0,0,1) and len(a.edit_history.undo_stack)==1
    assert a.history_step(); assert len(w.all_blocks())==4 and w.active_checkpoint_cube is not None
    assert w.active_checkpoint_cube.getTag('heading')=='135' and w.moving_cubes[0]['np'].getX()==4.25
    assert a.history_step(True); assert w.all_blocks()==[outside] and w.active_checkpoint_cube is None
    assert a.history_step(); a.tool_mode=11
    a.selected_objects=[next(n for n in w.cubes if n.getTag('group')=='three')]
    with immediate(): a.selection_command('cut')
    assert len(a.clipboard)==3 and w.all_blocks()==[outside]
    assert a.history_step(); assert len(w.all_blocks())==4
    with immediate(): assert w.flush_saves()
    w2=world(tmp); w2.load_map(); assert len(w2.all_blocks())==4 and float(w2.active_checkpoint_cube.getTag('heading'))==135

@proof('E29 undo/redo covers placement, movement, properties and checkpoint facing')
def editor_history_roundtrip(tmp):
    w=world(tmp); a=app(w); a.preview.setPos(0,0,.5)
    with immediate(): a.place()
    assert len(w.cubes)==1 and a.history_step() and not w.cubes
    assert a.history_step(True) and len(w.cubes)==1
    a.tool_mode=11; a.selected_objects=list(w.cubes)
    with immediate(): a.transform_selection(2,0,0)
    assert w.cubes[0].getX()==2
    assert a.history_step(); assert w.cubes[0].getX()==0
    assert a.history_step(True); assert w.cubes[0].getX()==2
    t=cube(w,(5,0,.5),'5'); a.tool_mode=8; a.selected_trampolines=[t]; a.selected_objects=[t]
    with immediate(): a.adj_val(1); a.adj_h(1)
    assert a.history_step(); t=w.cube_map[(5,0,1)]; assert not t.getTag('max_height')
    assert a.history_step(); t=w.cube_map[(5,0,1)]; assert not t.getTag('bounciness')
    assert a.history_step(True); assert w.cube_map[(5,0,1)].getTag('bounciness')=='1.4'
    cp=cube(w,(8,0,.5),'4'); a.tool_mode=9; a.selected_objects=[cp]
    with immediate(): a.adjust_checkpoint(1)
    assert a.history_step(); assert not w.cube_map[(8,0,1)].getTag('heading')
    assert a.history_step(True); assert w.cube_map[(8,0,1)].getTag('heading')=='15.0'

@proof('E30 undoing Waypoint conversion restores a static block; redo restores path and speed')
def waypoint_history(tmp):
    w=world(tmp); c=cube(w); a=app(w); a.tool_mode=7; a.selected_objects=[c]; a.preview.setPos(4,0,.5)
    with immediate(): a.handle_place_wp()
    assert not w.cubes and len(w.moving_cubes)==1
    assert a.history_step(); assert len(w.cubes)==1 and not w.moving_cubes
    assert a.history_step(True); assert w.moving_cubes[0]['waypoints']==[V(4,0,.5)]
    a.selected_objects=[w.moving_cubes[0]['np']]; a.selected_movers=list(w.moving_cubes)
    with immediate(): a.adj_val(1)
    assert a.history_step(); assert w.moving_cubes[0]['speed']==3
    assert a.history_step(True); assert w.moving_cubes[0]['speed']==3.5

@proof('E31 a new edit clears redo; history stores only changed objects and survives node reuse')
def history_branches(tmp):
    w=world(tmp); a=app(w)
    for i in range(300): cube(w,(i,10,.5))
    with immediate(): a.place()
    entry=a.edit_history.undo_stack[-1]; assert not entry[0] and len(entry[1])==1
    assert a.history_step(); a.preview.setPos(5,0,.5)
    with immediate(): a.place()
    assert not a.history_step(True) and (5,0,1) in w.cube_map and (0,0,1) not in w.cube_map
    assert a.history_step(); assert len(w.cubes)==300
    assert a.history_step(True); assert len(w.cubes)==301 and (5,0,1) in w.cube_map
    assert len({a.edit_history.identity(c) for c in w.all_blocks()})==len(w.all_blocks())

@proof('E32 Left Ctrl shortcuts work; Right Ctrl and chord releases never group accidentally')
def handed_shortcuts(tmp):
    from direct.showbase.DirectObject import DirectObject
    from direct.showbase.MessengerGlobal import messenger
    w=world(tmp); cube(w); cube(w,(2,0,.5)); a=app(w); owner=DirectObject()
    a.accept=owner.accept; a.disableMouse=lambda:None; a.setup_input()
    def send(*names):
        for name in names: messenger.send(name)
    try:
        a.tool_mode=10; a.selected_objects=list(w.cubes)
        send('raw-rcontrol','raw-rcontrol-up'); assert all(not c.getTag('group') for c in w.cubes)
        with immediate(): send('raw-lcontrol','raw-lcontrol-up')
        assert all(c.getTag('group') for c in w.cubes) and a.selecting() and a.tinkering()
        a.toggle_tool_phase(); assert a.selecting() and a.tool_phases[10]=='select'
        send('raw-rcontrol','control-z','raw-rcontrol-up'); assert all(c.getTag('group') for c in w.cubes)
        send('raw-lcontrol','raw-z','control-z','raw-z-up','raw-lcontrol-up')
        assert all(not c.getTag('group') for c in w.cubes) and not a.keyMap['z']
        send('raw-lcontrol','control-y','raw-lcontrol-up'); assert all(c.getTag('group') for c in w.cubes)
        a.selected_objects=list(w.cubes)
        send('raw-lcontrol'); messenger.send('editor-button-down',['control-f']); send('raw-lcontrol-up')
        assert all(c.getTag('group') for c in w.cubes)
        with immediate(): send('raw-lcontrol','raw-lcontrol-up')
        assert all(not c.getTag('group') for c in w.cubes)
        a.tool_mode=11; a.tool_phases[11]='select'; a.selected_objects=[]
        send('raw-rcontrol','control-a','raw-rcontrol-up'); assert not a.selected_objects
        send('raw-lcontrol','raw-a','control-a','raw-a-up','raw-lcontrol-up'); assert len(a.selected_objects)==2
        send('raw-rcontrol','control-d','raw-rcontrol-up'); assert len(a.selected_objects)==2
        send('raw-lcontrol','control-d','raw-lcontrol-up'); assert not a.selected_objects
        a.tool_phases[11]='tinker'; a.selected_objects=list(w.cubes)
        send('raw-rcontrol','control-c','raw-rcontrol-up'); assert not a.clipboard
        send('raw-lcontrol','control-c','raw-lcontrol-up'); assert len(a.clipboard)==2
        send('raw-rcontrol','control-x','raw-rcontrol-up'); assert len(w.cubes)==2
        with immediate(): send('raw-lcontrol','raw-x','control-x','raw-x-up','raw-lcontrol-up')
        assert not w.cubes and not a.keyMap['x']
        a.preview.setPos(10,0,.5)
        send('raw-rcontrol','control-v','raw-rcontrol-up'); assert not w.cubes
        with immediate(): send('raw-lcontrol','control-v','raw-lcontrol-up')
        assert len(w.cubes)==2
    finally: owner.ignoreAll()

@proof('E33 landing plays once and varies in pitch/volume with actual fall height')
def landing_audio(tmp):
    w=world(tmp); cube(w); recordings=[]
    with patch.object(builtins.base,'play_sfx',side_effect=lambda *args:recordings.append(args)):
        for height in (2.1,35):
            p=physics(w); p.player.setPos(0,0,height)
            for _ in range(900):
                p.update(1/120,KEYS)
                if p.ground: break
            assert p.ground
            for _ in range(10): p.update(1/120,KEYS)
    landings=[s for s in recordings if s[0]=='land']; assert len(landings)==2
    assert landings[1][1]<landings[0][1] and landings[1][2]>landings[0][2]

@proof('E34 Flight and Invincibility share exactly one enable and one disable cue')
def universal_power_audio(tmp):
    a=app(world(tmp)); sounds=[]; a.play_sfx=lambda *args:sounds.append(args)
    a.toggle_fly(); a.toggle_fly(); a.toggle_god(); a.toggle_god()
    assert sounds==[('power_on',),('power_off',),('power_on',),('power_off',)]

@proof('E35 Selection center and pivot use one cyan waypoint-style point')
def unified_selection_point(tmp):
    w=world(tmp); a=app(w); a.tool_mode=11; a.selected_objects=[cube(w,(x,0,.5)) for x in (0,2,4)]
    for use_last,expected in ((False,2),(True,4)):
        a.saved_settings['Use Last Selected as Pivot']=use_last; a.draw_selection_center()
        assert a.selection_center_node==a.selection_pivot_node
        assert a.selection_center_node.getPos()==V(expected,0,.5)
        assert a.selection_center_node.node().getGeom(0).getVertexData().getNumRows()==4
        assert tuple(a.selection_center_node.getColor())==(0,1,1,.5)

@proof('E36 paste, rotate and ungroup redo preserve group identities and complete deltas')
def group_transform_history(tmp):
    w=world(tmp); a=app(w); a.tool_mode=10; a.selected_objects=[cube(w),cube(w,(2,0,.5),'5')]
    with immediate(): a.group_selection()
    original_group=w.cubes[0].getTag('group')
    a.tool_mode=11; a.selection_command('copy'); a.preview.setPos(10,0,.5)
    with immediate(): a.selection_command('paste')
    copied_group=a.selected_objects[0].getTag('group'); assert copied_group!=original_group
    assert a.history_step() and len(w.cubes)==2
    assert a.history_step(True) and len(w.cubes)==4
    a.selected_objects=[c for c in w.cubes if c.getTag('group')==copied_group]
    assert sorted(c.getX() for c in a.selected_objects)==[9,11]
    with immediate(): a.transform_selection(rotate=True)
    assert a.history_step(); assert sorted(c.getX() for c in w.cubes if c.getTag('group')==copied_group)==[9,11]
    assert a.history_step(True)
    assert sorted((c.getX(),c.getY()) for c in w.cubes if c.getTag('group')==copied_group)==[(10,-1),(10,1)]
    a.tool_mode=10; a.selected_objects=[c for c in w.cubes if c.getTag('group')==original_group]
    with immediate(): a.group_selection()
    assert len([c for c in w.cubes if c.getTag('group')==original_group])==0
    assert a.history_step(); assert len([c for c in w.cubes if c.getTag('group')==original_group])==2
    assert a.history_step(True); assert len([c for c in w.cubes if c.getTag('group')==original_group])==0

@proof('E37 undoing an unrelated edit preserves later checkpoint progress')
def history_checkpoint_progress(tmp):
    w=world(tmp); first=cube(w,material='4'); second=cube(w,(4,0,.5),'4'); a=app(w)
    a.physics.activate_checkpoint(first); a.preview.setPos(8,0,.5)
    with immediate(): a.place()
    a.physics.activate_checkpoint(second)
    assert a.history_step() and w.active_checkpoint_cube==second
    assert a.history_step(True) and w.active_checkpoint_cube==second
    assert a.physics.checkpoint==second.getPos()+V(0,0,1)

@proof('E38 Checkpoint, Trampoline and Grouping select and edit together, without mode or global shortcut hints')
def combined_tools(tmp):
    class Text:
        def setText(self,text): self.text=text
        def setFg(self,color): pass
    for tool in (8,9,10):
        w=world(tmp); a=app(w); a.tool_mode=tool
        mat='5' if tool==8 else '4' if tool==9 else '1'
        c=cube(w,material=mat); d=cube(w,(3,0,.5),mat)
        a.pick_object=lambda:c; a.select_object()
        assert a.selecting() and a.tinkering() and a.selected_objects==[c]
        phase=a.tool_phases[tool]; a.toggle_tool_phase(); assert a.tool_phases[tool]==phase
        with immediate():
            if tool==8: a.adj_val(1); a.adj_h(1); assert c.getTag('bounciness')=='1.4' and float(c.getTag('max_height'))>0
            elif tool==9: a.adjust_checkpoint(1); assert float(c.getTag('heading'))==15
            else: a.group_selection(); assert not c.getTag('group')
        a.pick_object=lambda:d; a.select_object(); assert d in a.selected_objects
        if tool==10:
            with immediate(): a.group_selection()
            assert c.getTag('group') and c.getTag('group')==d.getTag('group')
        a.ui=NS(tool_text=Text(),format_number=str)
        App.update_hud(a); text=a.ui.tool_text.text
        assert 'Tab' not in text and 'SELECT' not in text and 'TINKER' not in text
        assert 'Undo / Redo' not in text and 'LCtrl+Z' not in text
    for tool in (7,11):
        a.tool_mode=tool; App.update_hud(a)
        assert 'LCtrl+Z' not in a.ui.tool_text.text and 'Undo / Redo' not in a.ui.tool_text.text

@proof('E39 all tools select grouped members, with material filtering for specialized tools')
def specialized_groups(tmp):
    for tool in App.TOOL_SLOTS:
        w=world(tmp); a=app(w); a.tool_mode=tool; a.tool_phases[tool]='select'
        mat='5' if tool==8 else '4' if tool==9 else '1'
        c=cube(w,material=mat); d=mover(w,(3,0,.5),mat)['np']; other=cube(w,(6,0,.5),'2')
        outsider=cube(w,(9,0,.5),mat)
        for node in (c,d,other): node.setTag('group','shared')
        a.pick_object=lambda:c; a.select_object()
        assert set(a.selected_objects)==({c,d} if tool in (8,9) else {c,d,other})
        if tool==8:
            assert set(a.selected_trampolines)=={c,d}
            with immediate(): a.adj_val(1)
            assert c.getTag('bounciness')==d.getTag('bounciness')=='1.4'
        if tool==9:
            with immediate(): a.adjust_checkpoint(1)
            assert float(c.getTag('heading'))==float(d.getTag('heading'))==15
        assert not other.hasTag('bounciness') and not other.hasTag('heading') and outsider not in a.selected_objects
        a.pick_object=lambda:d; a.select_object(); assert not a.selected_objects

@proof('E40 flight speed uses one cue pitched by direction, only when speed changes')
def flight_speed_audio(tmp):
    a=app(world(tmp)); a.ui=NS(gui_hidden=True); sounds=[]; a.play_sfx=lambda *args:sounds.append(args)
    a.adj_fly(1); assert a.physics.fly_speed==11 and sounds==[('checkpoint_turn',1.12)]
    a.adj_fly(-1); assert a.physics.fly_speed==10 and sounds[-1]==('checkpoint_turn',.88)
    a.physics.fly_speed=1; a.adj_fly(-1); assert len(sounds)==2
    a.adj_fly(1); assert sounds[-1]==('checkpoint_turn',1.12) and len(sounds)==3
    assert all((ROOT/'assets'/'sounds'/(name[0]+'.mp3')).is_file() for name in sounds)

@proof('E41 jumping on landing or immediately afterward suppresses the landing cue')
def jump_landing_audio(tmp):
    w=world(tmp); cube(w); recordings=[]
    with patch.object(builtins.base,'play_sfx',side_effect=lambda *args:recordings.append(args)):
        for held in (False,True):
            p=physics(w); p.player.setPos(0,0,1.1); p.fall_peak_z=4; p.vz=-5
            keys=dict(KEYS,space=held)
            p.vertical_step(-.2,keys)
            assert p.ground
            if not held:
                assert p.pending_land is not None
                p.update(1/120,dict(KEYS,space=True))
                assert p.vz>0 and not p.ground
            for _ in range(12):p.update_landing_sound(1/120,keys)
            assert p.pending_land is None
        assert not [s for s in recordings if s[0]=='land']
        p=physics(w); p.player.setPos(0,0,1.1); p.fall_peak_z=4; p.vz=-5
        p.vertical_step(-.2,KEYS); assert p.pending_land is not None
        p.respawn(); assert p.pending_land is None

class RecordedSound:
    def __init__(self): self.rates=[]; self.volumes=[]; self.times=[]; self.plays=0; self.stops=0
    def stop(self): self.stops+=1
    def setPlayRate(self,v): self.rates.append(v)
    def setVolume(self,v): self.volumes.append(v)
    def setTime(self,v): self.times.append(v)
    def play(self): self.plays+=1

@proof('E42 every shared sound varies rate and volume while preserving caller parameters and checkpoint playback')
def all_sound_variation(tmp):
    a=app(world(tmp)); a.sound_enabled=True
    a.sfx={p.stem:RecordedSound() for p in (ROOT/'assets'/'sounds').glob('*.mp3')}
    for name,sound in a.sfx.items():
        if name=='checkpoint': continue
        with patch.object(G['random'],'uniform',side_effect=[.95,.94,1.05,1.0]):
            a.play_sfx(name,.8,.5); a.play_sfx(name,.8,.5)
        assert all(abs(v-e)<1e-8 for v,e in zip(sound.rates,(.76,.84))),name
        assert sound.volumes==[.47,.5] and sound.plays==2 and sound.stops==2,name
    with patch.object(G['random'],'uniform',side_effect=AssertionError('Checkpoint must not be randomized')):
        a.play_sfx('checkpoint',1.3,.7)
    assert a.sfx['checkpoint'].rates==[1.3] and a.sfx['checkpoint'].volumes==[.7]
    a.sound_enabled=False
    with patch.object(G['random'],'uniform',side_effect=AssertionError('Muted sounds must not play')):
        a.play_sfx('ungroup')
    assert a.sfx['ungroup'].plays==2

@proof('E43 respawn varies without changing its seek time; checkpoint keeps its existing pitch progression')
def direct_sound_variation(tmp):
    w=world(tmp); p=physics(w); a=app(w); a.sound_enabled=True
    a.sfx={'respawn':RecordedSound(),'checkpoint':RecordedSound()}
    with patch.object(builtins.base,'play_sfx',a.play_sfx):
        with patch.object(G['random'],'uniform',side_effect=[.95,.94,1.05,1.0]):
            p.respawn(); p.just_respawned=False; p.respawn()
        respawn=a.sfx['respawn']
        assert respawn.rates==[.95,1.05] and respawn.volumes==[.94,1.0]
        assert respawn.times==[.5,.5] and respawn.plays==2
        c=cube(w,material='4'); d=cube(w,(2,0,.5),'4')
        with patch.object(G['random'],'uniform',side_effect=AssertionError('Checkpoint must not be randomized')):
            p.activate_checkpoint(c); p.activate_checkpoint(d)
        checkpoint=a.sfx['checkpoint']
        assert checkpoint.rates==[1.0,1.1] and checkpoint.times==[.3,.3]
        assert checkpoint.volumes==[1.0,1.0] and checkpoint.plays==2

@proof('E44 trampoline height uses the Checkpoint numeric cue in both directions')
def height_sound_directions(tmp):
    w=world(tmp); c=cube(w,material='5'); a=app(w); a.tool_mode=8
    a.selected_objects=[c]; a.selected_trampolines=[c]; sounds=[]; a.play_sfx=lambda *args:sounds.append(args)
    with immediate(): a.adj_h(1); a.adj_h(-1)
    assert sounds==[('checkpoint_turn',1.12),('checkpoint_turn',.88)]
    assert all((ROOT/'assets'/'sounds'/(sound[0]+'.mp3')).is_file() for sound in sounds)

@proof('E45 presence uses the fixed public ID and saved visibility preferences, ignoring legacy ID settings')
def presence_preferences(tmp):
    from disepshun.presence import DiscordPresence
    a=App.__new__(App); a.settings_file=str(Path(tmp)/'settings.json')
    initial={'Discord Application ID':'123','Discord Show Activity':False,'Discord Show Block Count':False,
             'Discord Show Time':False,'Discord Show Icon':False,'Sound':True}
    Path(a.settings_file).write_text(json.dumps(initial)); a.load_settings()
    assert 'Discord Application ID' not in a.saved_settings
    a.save_setting('Discord Show Activity',True); a.load_settings()
    assert 'Discord Show Activity' not in a.saved_settings and 'Sound' not in a.saved_settings
    with patch.dict(os.environ,{'DISEPSHUN_DISCORD_APP_ID':'123'}):
        p=DiscordPresence(a.saved_settings)
    assert p.client_id=='1566233876823678996'
    assert p.activity_payload()=={'details':'Exploring'}
    for setting in DiscordPresence.DISPLAY_SETTINGS: assert setting in App.BOOL_SETTINGS
    initial.update({name:'bad' for name in DiscordPresence.DISPLAY_SETTINGS})
    Path(a.settings_file).write_text(json.dumps(initial)); a.load_settings()
    assert all(name not in a.saved_settings for name in DiscordPresence.DISPLAY_SETTINGS)

@proof('E46 presence visibility switches remove fields from real PyPresence payloads and wake the worker')
def presence_field_privacy(tmp):
    from disepshun.presence import DiscordPresence
    from pypresence.payloads import Payload
    from itertools import product
    p=DiscordPresence();p.status=('Trampoline',123)
    with patch.object(DiscordPresence,'IMAGE_KEY','test_logo'):
        for activity,count,clock,icon in product((False,True),repeat=4):
            p.configure(show_activity=activity,show_block_count=count,show_time=clock,show_icon=icon)
            payload=p.activity_payload()
            assert ('details' in payload)==activity and ('state' in payload)==count
            assert ('start' in payload)==clock and ('large_image' in payload)==icon
            wire=Payload.set_activity(**payload).data['args']['activity']
            assert ('details' in wire)==activity and ('state' in wire)==count
            assert ('timestamps' in wire)==clock and ('assets' in wire)==icon
        p.wake.clear();p.configure(show_activity=False);assert p.wake.is_set()
    p.enabled=False;assert p.connection_status=='Discord presence is off.'
    with patch('disepshun.presence.threading.Thread',side_effect=AssertionError('Disabled presence started a worker')):
        p.tick('Building',1)
    p.close()

@proof('E47 presence applies live visibility changes, clears on disable/exit, and reconnects using the fixed ID')
def presence_worker_lifecycle(tmp):
    from disepshun.presence import DiscordPresence
    p=DiscordPresence();p.status=('Selection',99);instances=[];payloads=[]
    class RPC:
        def __init__(self,client_id,**kwargs):
            assert client_id==DiscordPresence.APP_ID
            self.clears=0;self.closed=False;instances.append(self)
        def connect(self): pass
        def update(self,**data):payloads.append(data)
        def clear(self):self.clears+=1
        def close(self):self.closed=True
    class Wake:
        def __init__(self):self.stage=0
        def clear(self):pass
        def set(self):pass
        def wait(self,delay):
            assert delay==15
            if self.stage==0:p.configure(show_activity=False,show_block_count=False,show_time=False,show_icon=False)
            elif self.stage==1:p.enabled=False
            elif self.stage==2:
                assert instances[0].clears==1 and instances[0].closed
                p.configure(enabled=True,show_activity=True)
            else:p.stop.set()
            self.stage+=1
    p.wake=Wake()
    with patch('pypresence.Presence',RPC):p._run()
    assert len(instances)==2 and len(payloads)==3
    assert payloads[0]['details']=='Selection' and payloads[0]['state']=='99 blocks in the map'
    assert payloads[1]=={} and payloads[2]=={'details':'Selection'}
    assert all(rpc.closed and rpc.clears==1 for rpc in instances) and not p.connected

@proof('E48 every numerical editor adjustment uses its shared cue with directional pitch and variation')
def shared_direction_audio(tmp):
    w=world(tmp); a=app(w); a.sound_enabled=True; a.ui=NS(gui_hidden=True)
    names=('trampoline_height','trampoline_bounce','mover_speed','checkpoint_turn','flight_speed')
    a.sfx={name:RecordedSound() for name in names}
    t=cube(w,material='5'); a.tool_mode=8; a.selected_objects=[t]; a.selected_trampolines=[t]
    with immediate(),patch.object(G['random'],'uniform',side_effect=lambda lo,hi:(lo+hi)/2):
        a.adj_h(1); a.adj_h(-1); a.adj_val(1); a.adj_val(-1)
        a.tool_mode=7;a.tool_phases[7]='tinker';a.selected_trampolines=[]
        a.adj_val(1);a.adj_val(-1)
        c=cube(w,(4,0,.5),'4');a.tool_mode=9;a.selected_objects=[c]
        a.adjust_checkpoint(1);a.adjust_checkpoint(-1)
        a.adj_fly(1);a.adj_fly(-1)
    assert a.sfx['checkpoint_turn'].rates==[1.12,.88]*5
    assert a.sfx['checkpoint_turn'].volumes==[.97]*10
    assert all(sound.plays==0 for name,sound in a.sfx.items() if name!='checkpoint_turn')

@proof('E49 the GPU overview lists the renderer and other adapters, and is Windows-only')
def gpu_detection(tmp):
    from disepshun.gpu_advice import renderer_info
    low={'name':'Intel(R) UHD Graphics 770','id':(0,1)}
    high={'name':'NVIDIA GeForce RTX 3050','id':(0,2)}
    with patch('disepshun.gpu_advice.windows_adapter_orders',return_value=([low,high],[high,low])):
        info=renderer_info('Intel UHD Graphics 770')
    assert info=={'current':'Intel UHD Graphics 770','others':[high['name']],'enumerated':True}
    with patch('disepshun.gpu_advice.windows_adapter_orders',return_value=([],[])):
        assert renderer_info('')=={'current':'Unknown renderer','others':[],'enumerated':False}
    a=app(world(tmp)); notices=[]; a.saved_settings={}
    a.ui=NS(show_gpu_notice=notices.append)
    a.win=NS(getGsg=lambda:NS(getDriverRenderer=lambda:'llvmpipe'))
    with patch.object(os,'name','posix'): a.check_startup_gpu()
    assert not notices and 'GPU Notice Shown' not in a.saved_settings

@proof('E50 GPU overview appears once, persists across launches, and Escape closes it')
def gpu_startup_and_escape(tmp):
    a=app(world(tmp)); notices=[]; a.saved_settings={}
    a.ui=NS(show_gpu_notice=lambda info:notices.append(info))
    a.win=NS(getGsg=lambda:NS(getDriverRenderer=lambda:'Intel UHD Graphics 770'))
    info={'current':'Intel UHD Graphics 770','recommended':'NVIDIA GeForce RTX 3050'}
    a.settings_file=str(Path(tmp)/'settings.json')
    with patch('disepshun.gpu_advice.renderer_info',return_value=info) as check:
        with patch.object(os,'name','nt'): a.check_startup_gpu();a.check_startup_gpu()
        assert notices==[info] and check.call_count==1
        a.load_settings();assert a.saved_settings['GPU Notice Shown'] is True
        with patch.object(os,'name','nt'): a.check_startup_gpu()
        assert check.call_count==1
    a.gpu_notice_open=True;a.paused=True
    a.ui.close_gpu_notice=lambda:setattr(a,'gpu_notice_open',False)
    a.toggle_menu();assert not a.gpu_notice_open and not a.menu_open
    a.gpu_notice_open=True;a.paused=False;assert a.input_blocked()

@proof('E51 a missing save starts from the bundled DMF default map, unchanged and without a backup')
def default_map(tmp):
    w=world(tmp); w.save_file=str(Path(tmp)/'data'/'map_save.dmf'); w.default_map_file=str(ROOT/'assets'/'default_map.dmf')
    with immediate(): w.load_map()
    assert Path(w.save_file).read_bytes()==Path(w.default_map_file).read_bytes()
    assert len(live(w))==9 and not w.load_errors and not w.save_blocked and not w.map_is_dirty
    assert w.cube_map[w.get_grid_key(V(0,0,0.5))].getTag('material')=='4'
    assert not list(Path(tmp).rglob('*.bak'))
    w2=world(tmp); w2.save_file=str(Path(tmp)/'empty'/'map_save.dmf'); w2.default_map_file=str(Path(tmp)/'missing.dmf')
    w2.load_map(); assert not live(w2) and not w2.save_blocked

@proof('E52 closing Settings discards the stale menu cursor position instead of turning the camera with it')
def menu_close_mouse(tmp):
    a=app(world(tmp)); warps=[]; a.ignore_mouse_input=False; a.play_sfx=lambda *x:None
    a.ui=NS(set_menu_visible=lambda v:None)
    a.win=NS(getXSize=lambda:100,getYSize=lambda:100,movePointer=lambda *p:warps.append(p),requestProperties=lambda wp:None)
    a.toggle_menu(); assert a.menu_open
    a.ignore_mouse_input=False
    a.toggle_menu(); assert not a.menu_open and warps[-1]==(0,50,50) and a.ignore_mouse_input

@proof('E53 crouch plays once per transition and increases gravity during ascent and descent')
def crouch_fall(tmp):
    sounds=[]
    with patch.object(builtins.base, 'play_sfx', side_effect=lambda *args:sounds.append(args)):
        p=physics(world(tmp)); p.player.setZ(20); p.vz=-2; p.ground=False
        keys=dict(KEYS,lshift=True)
        p.update(.02,keys); fast=p.vz
        p.update(.02,keys)
        assert [x[0] for x in sounds].count('crouch')==1
        p.update(.02,KEYS); p.update(.02,keys)
        assert [x[0] for x in sounds].count('crouch')==2
        q=physics(world(tmp)); q.player.setZ(20); q.vz=-2; q.ground=False; q.update(.02,KEYS)
        assert fast < q.vz
        p.vz=q.vz=5; p.ground=q.ground=False
        p.update(.02,keys); q.update(.02,KEYS)
        assert 0 < p.vz < q.vz
        assert abs((5-p.vz)-2.5*(5-q.vz))<1e-6
    assert (ROOT/'assets'/'sounds'/'crouch.mp3').stat().st_size>0

@proof('E54 fill handles reversed corners, materials, checkers, obstacles, and undo/redo')
def fill_boxes(tmp):
    for mode in range(1,7):
        w=world(tmp); a=app(w); a.tool_mode=12; a.fill_material=mode
        a.physics.player.setPos(30,30,30)
        existing=cube(w,(0,0,.5),'3')
        a.preview.setPos(1,1,1.5); a.fill_corner(); assert len(w.cubes)==1
        a.preview.setPos(0,0,.5); a.fill_corner()
        assert len(w.cubes)==8 and existing in w.cubes and a.fill_start is None
        for c in w.cubes:
            if c==existing: continue
            x,y,z=c.getPos(); expected=1+(int(x+y+z-.5)%2) if mode==6 else mode
            assert int(c.getTag('material'))==expected
        assert a.history_step() and w.cubes==[existing]
        assert a.history_step(True) and len(w.cubes)==8
    a.fill_start=V(0,0,.5); a.delete(); assert a.fill_start is None
    a.fill_start=V(0,0,.5); a.preview.setPos(100,100,100.5)
    a.editor_notice=lambda text:None; a.fill_corner(); assert len(w.cubes)==8

@proof('E55 hollow fill omits interior cells; mode and cancellation have distinct cues')
def hollow_fill(tmp):
    w=world(tmp); a=app(w); a.tool_mode=12; a.physics.player.setPos(30,30,30)
    sounds=[]; a.play_sfx=lambda *args:sounds.append(args[0])
    a.toggle_fill_solid(); assert a.fill_solid is False
    a.preview.setPos(0,0,.5); a.fill_corner()
    a.preview.setPos(2,2,2.5); a.fill_corner()
    assert len(w.cubes)==26 and w.get_grid_key(V(1,1,1.5)) not in w.cube_map
    assert sounds==['toggle','place','place']
    a.fill_corner(); a.cancel_fill(); assert sounds[-1]=='break' and a.fill_start is None
    a.toggle_fill_solid(); assert a.fill_solid and sounds[-1]=='toggle'
    assert a.history_step() and not w.cubes
    assert a.history_step(True) and len(w.cubes)==26
    for name in ('fill_material','fill_point','fill_cancel','fill_solid','fill_hollow','fill_complete','fill_error','uncrouch'):
        assert (ROOT/'assets'/'sounds'/(name+'.mp3')).stat().st_size>0

@proof('E56 uncrouch cue waits for clearance and uses shared sound variation')
def uncrouch_clearance(tmp):
    w=world(tmp); p=physics(w); p.player.setZ(20); p.was_crouching=True
    sounds=[]
    with patch.object(builtins.base,'play_sfx',side_effect=lambda *args:sounds.append(args[0])):
        with patch.object(p,'check_collision',return_value=True): p.update(.01,KEYS)
        assert 'uncrouch' not in sounds
        with patch.object(p,'check_collision',return_value=False):
            p.update(.01,KEYS); p.update(.01,KEYS)
        assert sounds.count('uncrouch')==1

@proof('E57 GPU overview lists all other hardware and handles enumeration failure')
def gpu_overview(tmp):
    from disepshun.gpu_advice import renderer_info
    adapters=[dict(name='Intel UHD Graphics 770',id=1),dict(name='NVIDIA RTX 3050',id=2),dict(name='AMD Radeon RX 6600',id=3)]
    with patch('disepshun.gpu_advice.windows_adapter_orders',return_value=(adapters,adapters[::-1])):
        info=renderer_info('Intel(R) UHD Graphics 770')
        assert info['current']=='Intel(R) UHD Graphics 770'
        assert info['others']==['AMD Radeon RX 6600','NVIDIA RTX 3050'] and info['enumerated']
    with patch('disepshun.gpu_advice.windows_adapter_orders',return_value=([],[])):
        assert not renderer_info('Unknown')['enumerated']

@proof('E58 compressed settings migrate legacy preferences and save only nondefaults')
def compact_settings(tmp):
    a=App.__new__(App); a.settings_file=str(Path(tmp)/'settings.json.gz')
    legacy=Path(tmp)/'settings.json'
    legacy.write_text(json.dumps(dict(App.DEFAULT_SETTINGS, Sound=False, **{'Relative Waypoints':True})))
    a.load_settings()
    assert a.saved_settings=={'Sound':False} and not legacy.exists()
    assert json.loads(gzip.decompress(Path(a.settings_file).read_bytes()))=={'Sound':False}
    a.save_setting('Sound',True); a.load_settings(); assert a.saved_settings=={}
    assert gzip.decompress(Path(a.settings_file).read_bytes())==b'{}'
    for key,default in App.DEFAULT_SETTINGS.items():
        a.save_setting(key,not default); a.load_settings(); assert a.saved_settings[key] is not default
        a.save_setting(key,default); a.load_settings(); assert key not in a.saved_settings

@proof('E59 mover steps consume remaining distance through corners and close loop paths')
def smooth_loop_motion(tmp):
    G['globalClock']=NS(getDt=lambda: .1)
    w=world(tmp); a=app(w); m=mover(w,wp=(1,0,.5))
    m['waypoints'].append(V(1,1,.5)); m['speed']=3
    m['np'].setX(.9); m['loop']=True
    a.update_world(TASK); assert (m['np'].getPos()-V(1,.2,.5)).length()<1e-6
    m['np'].setPos(1,.9,.5); m['current_idx']=2
    a.update_world(TASK)
    expected=V(1,1,.5)-V(1,1,0).normalized()*.2
    assert (m['np'].getPos()-expected).length()<1e-6 and m['current_idx']==0
    m['loop']=False; m['np'].setPos(1,.9,.5); m['current_idx']=2; m['direction']=1
    a.update_world(TASK); assert (m['np'].getPos()-V(1,.8,.5)).length()<1e-6
    # Duplicate points and speeds crossing many tiny segments must terminate.
    m['origin']=V(0,0,.5); m['waypoints']=[V(0,0,.5),V(.01,0,.5)]
    m['np'].setPos(m['origin']); m['current_idx']=0; m['speed']=100; m['loop']=True
    a.update_world(TASK); assert math.isfinite(m['np'].getX())

@proof('E60 loop mode survives toggles, undo/redo, save/reload, copying and attached blocks')
def loop_persistence(tmp):
    w=world(tmp); a=app(w); m=mover(w); a.tool_mode=7
    a.selected_objects=[m['np']]; a.selected_movers=[m]
    with immediate(): a.toggle_mover_loop()
    assert m['loop']; a.history_step(); assert not w.moving_cubes[0]['loop']
    a.history_step(True); assert w.moving_cubes[0]['loop']
    save(w); w.load_map(); assert not w.load_errors and w.moving_cubes[0]['loop']
    a.selected_objects=[w.moving_cubes[0]['np']]; a.selection_command('copy'); a.preview.setPos(10,0,.5)
    with immediate(): a.selection_command('paste')
    assert w.moving_cubes[-1]['loop']
    a.tool_mode=1; a.preview.setPos(11,0,.5); hit(a,w.moving_cubes[-1]['np'])
    with immediate(): a.place()
    assert w.moving_cubes[-1]['loop']
    a.paused=True
    a.toggle_mover_loop(); assert w.moving_cubes[-1]['loop']

@proof('E61 loading below the initial spawn resets fall height; actual falls still sound once')
def spawn_landing_audio(tmp):
    recordings=[]
    with patch.object(builtins.base,'play_sfx',lambda *args:recordings.append(args)):
        w=world(tmp); cube(w,(0,0,-9.5)); p=physics(w)
        p.set_spawn_position(V(0,0,-9)); p.pending_land=None
        for _ in range(50): p.update(.01,KEYS)
        assert p.ground and not [s for s in recordings if s[0]=='land']
        p.set_spawn_position(V(0,0,-6))
        for _ in range(200): p.update(.01,KEYS)
        assert p.ground and len([s for s in recordings if s[0]=='land'])==1

@proof('E62 GPU window explains Python GPU selection and plays menu cues once per open/close')
def gpu_window_audio(tmp):
    widgets=[]; sounds=[]
    class Widget:
        def __init__(self,**kw): self.options=kw; self.destroyed=False; widgets.append(self)
        def setScale(self,*args): pass
        def getCanvas(self): return self
        def destroy(self): self.destroyed=True
    a=app(world(tmp)); a.play_sfx=lambda *args:sounds.append(args)
    a.aspect2d=NP('aspect2d'); a.getAspectRatio=lambda:16/9
    a.win=NS(requestProperties=lambda *args:None); a.center_mouse=lambda:None
    ui=G['GameUI'].__new__(G['GameUI']); ui.base=a
    gui=dict(DirectFrame=Widget,DirectLabel=Widget,DirectButton=Widget,
             DGG=NS(NORMAL=0,DISABLED=1))
    with patch.dict(G,gui), patch.dict(sys.modules,{'direct.gui.DirectGui':NS(DirectScrolledFrame=Widget)}):
        ui.show_gpu_notice(dict(current='Intel',others=['NVIDIA'],enumerated=True))
        ui.show_gpu_notice({})
        assert any('Python can sometimes be set to use the less powerful GPU.' in w.options.get('text','') for w in widgets)
        ui.close_gpu_notice(); ui.close_gpu_notice()
    assert sounds==[('menu_open',),('menu_close',)] and not a.gpu_notice_open and not a.paused

@proof('E63 moving riders stay on the platform across repeated world and physics updates')
def synchronized_platform_updates(tmp):
    dt=1/120
    G['globalClock']=NS(getDt=lambda: dt)
    try:
        for target in ((4,0,.5),(0,0,4.5),(0,0,-3.5)):
            w=world(tmp); a=app(w); m=mover(w,wp=target)
            a.physics.player.setPos(0,0,1); a.physics.ground=True
            for _ in range(400):
                a.update_world(TASK); a.physics.update(dt,KEYS)
                expected=m['np'].getPos()+V(0,0,.5)
                assert (a.physics.player.getPos()-expected).length()<1e-4
                assert a.physics.ground
    finally: G['globalClock']=NS(getDt=lambda: .1)

@proof('E64 Selection, Grouping and object selection retain their original cues')
def restored_selection_audio(tmp):
    w=world(tmp); a=app(w); sounds=[]; a.play_sfx=lambda *args:sounds.append(args)
    c=cube(w); d=cube(w,(3,0,.5)); a.pick_object=lambda:c
    for tool in (10,11):
        a.tool_mode=tool; a.tool_phases[tool]='select'; a.selected_objects=[]
        a.select_object(); a.select_object()
        assert sounds[-2:]==[('object_select',),('object_deselect',)]
    a.selected_objects=[c,d]; a.tool_mode=10
    with immediate(): a.group_selection(); a.group_selection()
    assert sounds[-2:]==[('group',),('ungroup',)]
    a.tool_mode=11; a.tool_phases[11]='select'
    a.selection_command('all'); a.selection_command('clear')
    assert sounds[-2:]==[('selection_all',),('selection_clear',)]
    a.tool_phases[11]='tinker'; a.selected_objects=[c]
    a.selection_command('copy'); a.preview.setPos(8,0,.5)
    with immediate():
        a.selection_command('paste'); a.transform_selection(1,0,0)
        a.transform_selection(rotate=True); a.selection_command('cut')
    assert sounds[-5:]==[('copy',),('paste',),('move',),('rotate',),('cut',)]
    a.selected_objects=[d]
    with immediate(): a.selection_command('delete')
    assert sounds[-1]==('delete',)
    a.toggle_tool_phase(); a.toggle_tool_phase()
    assert sounds[-2:]==[('mode_select',),('mode_tinker',)]

@proof('E65 every tool has the Waypoint translucent magenta unshaded cursor preview')
def unified_tool_previews(tmp):
    a=app(world(tmp)); a.preview_shading=True; a.hotbar_page=1
    a.ui=NS(update_selection=lambda *args:None,show_item_name=lambda *args:None)
    a.world.dlnp=NP(core.DirectionalLight('sun')); a.world.alnp=NP(core.AmbientLight('ambient'))
    for tool in a.TOOL_SLOTS:
        a.set_tool(tool)
        assert tuple(a.preview.getColorScale())==(1,0,1,.5)
        assert a.preview.getAttrib(core.LightAttrib).hasAllOff()
        assert a.preview.getShader() is None
        # Changing the shading preference while a tool is active keeps this style.
        a.toggle_preview_shading(False); a.toggle_preview_shading(True)
        assert a.preview.getAttrib(core.LightAttrib).hasAllOff()
        assert a.preview.getShader() is None
    a.set_tool(2)
    assert tuple(round(v,2) for v in a.preview.getColorScale())==(.4,.4,.4,.5)
    assert a.preview.getAttrib(core.LightAttrib).getNumOnLights()==2
    a.toggle_preview_shading(False)
    assert a.preview.getAttrib(core.LightAttrib).hasAllOff()

@proof('E66 block actions share left/right click cues without duplicate Fill success sounds')
def shared_block_action_audio(tmp):
    w=world(tmp); a=app(w); sounds=[]; a.play_sfx=lambda *args:sounds.append(args)
    with patch.object(G['random'],'uniform',return_value=1):
        a.play_block_action(False); a.play_block_action(True)
        assert sounds==[('break',1),('place',1)]
        sounds.clear(); a.tool_mode=7; a.selected_objects=[cube(w)]; a.preview.setPos(4,0,.5)
        with immediate(): a.handle_place_wp()
        assert sounds==[('place',1)]
        sounds.clear(); a.tool_mode=12; a.preview.setPos(8,0,.5)
        a.fill_corner(); a.cancel_fill()
        assert sounds==[('place',1),('break',1)]
        sounds.clear(); a.fill_corner(); a.preview.setPos(9,0,.5); a.fill_corner()
        assert sounds==[('place',1),('place',1)]

@proof('E67 vertical rotation updates blocks, mover paths, indexes and history')
def vertical_rotation(tmp):
    w=world(tmp); a=app(w); a.tool_mode=11
    c=cube(w); m=mover(w,(0,2,.5),wp=(0,4,.5))
    a.selected_objects=[c,m['np']]
    with immediate(): a.transform_selection(rotate=True,rotate_axis='x')
    assert c.getPos()==V(0,1,-.5) and m['np'].getPos()==V(0,1,1.5)
    assert m['origin']==V(0,1,1.5) and m['waypoints']==[V(0,1,3.5)]
    assert w.cube_map[w.get_grid_key(c.getPos())]==c
    assert a.history_step(); assert w.moving_cubes[0]['waypoints']==[V(0,4,.5)]
    assert a.history_step(True); assert w.moving_cubes[0]['waypoints']==[V(0,1,3.5)]
    save(w); w.load_map(); assert w.moving_cubes[0]['waypoints']==[V(0,1,3.5)]

@proof('E68 grouping requires two distinct blocks, leaves singleton edits and saves untouched')
def reject_single_groups(tmp):
    w=world(tmp); a=app(w); a.tool_mode=10; c=cube(w)
    sounds=[]; a.play_sfx=lambda *args:sounds.append(args)
    for selected in ([],[c],[c,c]):
        a.selected_objects=selected
        with immediate(): a.group_selection(False)
        assert not c.getTag('group') and not hasattr(a,'edit_history')
        assert not Path(w.save_file).exists() and not sounds
    d=cube(w,(3,0,.5)); a.selected_objects=[c,d]
    with immediate(): a.group_selection()
    assert c.getTag('group')==d.getTag('group') and c.getTag('group')

@proof('E69 Waypoint left click removes only the last waypoint in Tinker and selects in Select')
def left_click_waypoints(tmp):
    w=world(tmp); a=app(w); m=mover(w); m['waypoints'].append(V(8,0,.5))
    a.tool_mode=7; a.selected_objects=[m['np']]; a.selected_movers=[m]
    sounds=[]; a.play_sfx=lambda *args:sounds.append(args)
    with immediate(): a.delete()
    assert m['waypoints']==[V(5,0,.5)] and sounds[-1][0]=='break'
    assert a.history_step(); assert len(w.moving_cubes[0]['waypoints'])==2
    m=w.moving_cubes[0]; a.tool_phases[7]='select'; a.pick_object=lambda:m['np']
    a.delete(); assert a.selected_objects==[m['np']] and len(m['waypoints'])==2
    assert sounds[-1][0]=='object_select'

@proof('E70 Shift-modified mouse clicks, tool keys and releases reach existing actions')
def shift_actions(tmp):
    from direct.showbase.DirectObject import DirectObject
    from direct.showbase.MessengerGlobal import messenger
    a=app(world(tmp)); owner=DirectObject(); a.accept=owner.accept; a.disableMouse=lambda:None
    actions=[]; a.toggle_hotbar=lambda:actions.append('hotbar')
    a.handle_slot=lambda slot:actions.append(('slot',slot))
    a.transform_selection=lambda *args:actions.append(('transform',args))
    history=[]; a.history_step=lambda *args:history.append(args)
    a.setup_input()
    try:
        for shift in ('lshift','rshift'):
            messenger.send('raw-'+shift)
            for button in ('mouse1','mouse3'):
                messenger.send('shift-'+button); assert a.keyMap[button]
                messenger.send('shift-'+button+'-up'); assert not a.keyMap[button]
                messenger.send('shift-'+button); messenger.send('raw-'+shift+'-up')
                messenger.send(button+'-up'); assert not a.keyMap[button]
            messenger.send('shift-q'); messenger.send('shift-1'); messenger.send('shift-t')
        assert actions==['hotbar',('slot',1),('transform',(0,0,0,True,False,'x'))]*2
        messenger.send('raw-lcontrol')
        messenger.send('control-shift-z'); messenger.send('shift-control-y')
        messenger.send('raw-lcontrol-up')
        assert history==[(),(True,)]
    finally: owner.ignoreAll()

@proof('E71 undo/redo and hotbar switches play distinct cues only on successful actions')
def history_hotbar_sounds(tmp):
    w=world(tmp); a=app(w); sounds=[]; a.play_sfx=lambda *args:sounds.append(args)
    assert not a.history_step() and not a.history_step(True) and not sounds
    a.preview.setPos(4,0,.5)
    with immediate(): a.place()
    sounds.clear(); assert a.history_step(); assert a.history_step(True)
    assert sounds==[('undo',),('redo',)]
    assert not a.history_step(True); assert len(sounds)==2
    a.hotbar_page=0; a.preview_shading=False
    a.ui=NS(update_hotbar_layout=lambda *args:None,update_selection=lambda *args:None,show_item_name=lambda *args:None)
    sounds.clear(); a.toggle_hotbar(); a.toggle_hotbar()
    assert sounds==[('hotbar_tools',),('hotbar_blocks',)]
    a.paused=True; a.toggle_hotbar(); assert len(sounds)==2
    for name in ('undo','redo','hotbar_tools','hotbar_blocks'):
        assert (ROOT/'assets'/'sounds'/(name+'.mp3')).stat().st_size>0

@proof('P01 collision queries match brute force for off-grid blocks, boundaries, movers and ignored contacts')
def optimized_contacts(tmp):
    import random
    rng=random.Random(7401); w=world(tmp); p=physics(w)
    for _ in range(180):
        pos=V(*(rng.uniform(-5,5) for _ in range(3)))
        if w.get_grid_key(pos) not in w.cube_map: cube(w,pos)
    for _ in range(15): mover(w,tuple(rng.uniform(-6,6) for _ in range(3)))
    positions=[V(*(rng.uniform(-7,7) for _ in range(3))) for _ in range(750)]
    for c in w.cubes[:20]:
        cp=c.getPos()
        positions.extend((cp+V(.7,0,0),cp-V(.7,0,0),cp+V(0,0,.5),cp-V(0,0,2.17)))
    positions.extend((V(-10000,0,0),V(10000,0,0),V(0,0,1000),V(999,0,-20.1)))
    for enabled in (False,True):
        w.visual_floor.show(); w.update_god_collision(enabled)
        for i,pos in enumerate(positions):
            h=(.9,1.23,1.67)[i%3]
            ignore=tuple(w.cubes[:4]) if i%4==0 else ()
            floor,hits=p.get_contacts(pos,h,ignore)
            if not (-10000<pos.x<10000 and -10000<pos.y<10000 and -1000<pos.z<1000):
                assert floor and not hits; continue
            def overlap(c,half=.5):
                cp=c.getPos(w.render)
                return (pos.x-p.w/2<cp.x+half and pos.x+p.w/2>cp.x-half and
                        pos.y-p.w/2<cp.y+half and pos.y+p.w/2>cp.y-half and
                        pos.z<cp.z+.5 and pos.z+h>cp.z-.5)
            expected=[m['np'] for m in w.moving_cubes if m['np'] not in ignore and overlap(m['np'])]
            expected.extend(c for _,c in sorted(w.cube_map.items()) if c not in ignore and overlap(c))
            assert hits==expected, (pos,h,hits,expected)
            assert floor==bool(enabled and overlap(w.god_collision_floor,w.FLOOR_HALF))
    w.visual_floor.hide(); w.update_god_collision(True)
    assert not w.god_floor_enabled and w.god_collision_floor not in w.cubes
    save(w); w.load_map(); assert not w.god_floor_enabled
    w.visual_floor.show(); w.update_god_collision(True)
    save(w); w.load_map()
    assert w.god_floor_enabled and w.god_collision_floor in w.cubes
    assert p.get_contacts(V(999,0,-20.1),p.h_stand)[0]


@proof('P02 nearby glow search retains nearest-light ordering through ties, moves, conversion, deletion and reload')
def optimized_glow_search(tmp):
    import random
    rng=random.Random(401); w=world(tmp)
    for i in range(160):
        pos=V(rng.uniform(-45,45),rng.uniform(-45,45),rng.uniform(-3,3))
        if w.get_grid_key(pos) not in w.cube_map: cube(w,pos,'134'[i%3])
    tied=[cube(w,(-1,0,.5),'3'),cube(w,(1,0,.5),'4')]
    for i in range(12): mover(w,(0,i-6,.5),'3' if i%2 else '4')
    cameras=[V(0,0,.5),V(-16,16,0),V(-.001,-.001,2),V(32,-32,5),V(1000,1000,0)]
    def check():
        for pos in cameras:
            expected=[c for c in w.all_blocks() if c.getTag('material') in ('3','4') and
                      (c.getPos(w.render)-pos).lengthSquared()<225]
            expected.sort(key=lambda c:(c.getPos(w.render)-pos).lengthSquared())
            w.next_glow_scan=0; w.update_glow_lights(pos,now=0)
            assert w.glow_sources==expected[:4]
    check()
    c=tied[0]; w.unregister_cube(c); w.cube_map.pop(w.get_grid_key(c.getPos()))
    c.setPos(-17,16,.5); w.cube_map[w.get_grid_key(c.getPos())]=c; w.register_cube(c)
    check()
    w.convert_to_mover(c,dict(origin=c.getPos(),waypoints=[],speed=3.,current_idx=0,direction=1))
    check(); w.remove_block(tied[1]); cube(w,(0,0,.5),'4'); check()
    save(w); w.load_map(); check()


@proof('P03 cached mover paths refresh after live waypoint, loop, transform, history and reload edits')
def optimized_path_cache(tmp):
    w=world(tmp); a=app(w); m=mover(w); a.tool_mode=7
    a.selected_objects=[m['np']]; a.selected_movers=[m]
    def check():
        for m in w.moving_cubes:
            points,circuit=w.mover_path(m)
            expected=[m['origin']]+m['waypoints']
            length=sum((b-a).length() for a,b in zip(expected,expected[1:]))
            expected_length=length+(expected[-1]-expected[0]).length() if m.get('loop',False) else 2*length
            assert points==expected and circuit==expected_length
            assert w.mover_path(m)[0] is points
    check()
    a.preview.setPos(5,5,.5)
    with immediate():
        a.handle_place_wp(); check()
        a.toggle_mover_loop(); check()
        a.undo_wp(); check()
        a.tool_mode=11; a.tool_phases[11]='tinker'
        a.transform_selection(rotate=True,rotate_axis='x'); check()
        assert a.history_step(); check()
        assert a.history_step(True); check()
    save(w); w.load_map(); check()


@proof('P04 bloom retains shader inputs until buffer dimensions or padding change')
def optimized_bloom_inputs(tmp):
    import runpy
    bloom=runpy.run_path(str(SRC/'bloom.py'))['NeonBloom']
    effect=bloom.__new__(bloom); effect.input_sizes={}
    inputs={}
    # Shader quads are hashable NodePaths; wrap a real one to count writes.
    class Quad:
        def __init__(self): self.node=NP('quad'); self.calls=0
        def setShaderInput(self,name,value):
            self.calls+=1; self.node.setShaderInput(name,value); inputs[name]=value
    quad=Quad(); tex=core.Texture('buffer'); tex.setup2dTexture(64,32,core.Texture.TUnsignedByte,core.Texture.FRgba)
    effect.passes=[(quad,{'src':tex})]
    effect.update(); assert quad.calls==2
    scale=tex.getTexScale()
    assert inputs['src_scale']==core.Vec2(scale.x,scale.y)
    assert inputs['src_texel']==core.Vec2(1/(64*scale.x),1/(32*scale.y))
    effect.update(); assert quad.calls==2
    tex.setup2dTexture(128,64,core.Texture.TUnsignedByte,core.Texture.FRgba)
    effect.update(); assert quad.calls==4
    assert inputs['src_texel']==core.Vec2(1/128,1/64)
    tex.setPadSize(16,8,0); effect.update(); assert quad.calls==6
    scale=tex.getTexScale()
    assert inputs['src_scale']==core.Vec2(scale.x,scale.y)
    assert inputs['src_texel']==core.Vec2(1/(128*scale.x),1/(64*scale.y))
    effect.manager=NS(cleanup=lambda:None); effect.cleanup()
    assert not effect.passes and not effect.input_sizes


@proof('P05 editor spatial validation matches exhaustive overlap checks, including thresholds and multi-block edits')
def optimized_editor_overlap(tmp):
    import random
    rng=random.Random(9005); w=world(tmp); a=app(w); notices=[]
    a.editor_notice=notices.append
    for i in range(80):
        pos=V(rng.uniform(-6,6),rng.uniform(-6,6),rng.uniform(-3,3))
        if w.get_grid_key(pos) not in w.cube_map: cube(w,pos)
    for i in range(8): mover(w,(rng.uniform(-6,6),rng.uniform(-6,6),rng.uniform(-3,3)))
    cases=[[V(*(rng.uniform(-8,8) for _ in range(3))) for _ in range(i%12+1)] for i in range(150)]
    cases.extend(([V(30,0,.5),V(30+d,0,.5)] for d in (.9989,.999,.9991,1.0)))
    cases.extend(([V(0,0,-20)], [V(float('nan'),0,0)], [V(float('inf'),0,0)], [V(10001,0,0)]))
    for i,positions in enumerate(cases):
        ignored=w.all_blocks()[:10] if i%2 else []
        others=[c.getPos() for c in w.all_blocks() if c not in ignored]
        expected=True; reason=None
        for j,p in enumerate(positions):
            if any(not math.isfinite(v) or abs(v)>w.COORD_LIMIT for v in p) or p.z < -19.5:
                expected=False; reason='Objects must stay inside the map bounds'; break
            if any(all(abs(p[k]-q[k])<.999 for k in range(3)) for q in others+positions[:j]):
                expected=False; reason='Edit blocked: objects would overlap'; break
        notices.clear()
        assert a.valid_positions(positions,ignored)==expected
        assert notices==([reason] if reason else [])


@proof('R01 block containers keep list behaviour with O(1) lookups; empty chunk bookkeeping is dropped')
def block_containers(tmp):
    w=world(tmp); a=cube(w); b=cube(w,(40,40,.5)); m=mover(w,(3,0,.5))
    assert w.cubes==[a,b] and w.cubes[-1]==b and w.cubes[:1]==[a] and b in w.cubes and len(w.cubes)==2
    assert w.find_mover(m['np']) is m and w.find_mover(a) is None and m in w.moving_cubes
    assert w.find_mover(m['np'].find('coll').getParent()) is m  # another handle to the same node
    for c in w.cubes: w.cubes.remove(c)  # removal while iterating is safe
    assert not w.cubes and w.cubes==[]
    w.cubes.extend([a,b]); key=w.get_chunk_key(b.getPos())
    assert key in w.chunk_contents and key in w.collision_chunks
    w.remove_block(b); assert key not in w.chunk_contents and b not in w.cubes
    w.update_chunks(); assert key not in w.collision_chunks
    before=dict(w.chunk_contents); w.remove_block(m['np'])
    assert w.chunk_contents==before and not w.moving_cubes and w.find_mover(m['np']) is None
    print('  list operations intact; mover lookup by node; empty chunk entries and collider holders removed')

@proof('R02 mover cell index gives the same contacts and landings as scanning every mover')
def mover_index(tmp):
    import random
    rng=random.Random(2024); w=world(tmp); a=app(w); p=a.physics; p.flying=True
    for _ in range(60):
        pos=V(*(rng.uniform(-6,6) for _ in range(3)))
        if w.get_grid_key(pos) not in w.cube_map: cube(w,pos)
    for _ in range(80): mover(w,tuple(rng.uniform(-6,6) for _ in range(3)),wp=tuple(rng.uniform(-6,6) for _ in range(3)))
    for frame in range(3):
        a.update_world(TASK); assert w.mover_index is not None
        for i in range(400):
            pos=V(*(rng.uniform(-7,7) for _ in range(3))); h=(.9,1.67)[i%2]
            ignore=tuple(m['np'] for m in w.moving_cubes[:3]) if i%3==0 else ()
            indexed=p.get_contacts(pos,h,ignore)
            saved=w.mover_index; w.mover_index=None
            assert p.get_contacts(pos,h,ignore)==indexed, pos
            w.mover_index=saved
    a.update_world(TASK); w.remove_block(w.moving_cubes[0]['np'])
    assert w.movers_near(0,0,0,0,0,0)==[(m['np'],m['np'].getPos(w.render)) for m in w.moving_cubes]  # stale index unused
    w=world(tmp); m=mover(w,(0,0,.5),wp=(0,0,.5)); a=app(w); a.physics.player.setPos(0,0,1.3); a.physics.vz=-3
    a.update_world(TASK); assert w.mover_index is not None
    for _ in range(20): a.physics.update(1/120,KEYS)
    assert a.physics.ground and abs(a.physics.player.getZ()-1)<1e-4
    print('  1,200 indexed queries over 80 moving blocks match the full scan; landing on an indexed mover works')

@proof('R03 jump height is independent of frame rate with fixed physics steps')
def fixed_step(tmp):
    peaks=[]
    for fps in (30,60,144,240,300):
        w=world(tmp); cube(w); a=app(w); p=a.physics; p.player.setPos(0,0,1); a.keyMap=dict(KEYS,space=True)
        top=[0.]; real=p.update
        def update(dt,keys): real(dt,keys); top[0]=max(top[0],p.player.getZ())
        p.update=update
        for _ in range(int(fps*.9)): a.step_physics(1/fps)
        peaks.append(top[0])
    assert max(peaks)-min(peaks)<1e-6, peaks
    a.physics_time=0; a.step_physics(5.0); assert a.physics_time<a.PHYSICS_STEP  # a long hitch runs at most 0.1 s
    w=world(tmp); t=cube(w,material='5'); a=app(w)
    a.tool_mode=8; a.selected_trampolines=[t]; a.bounce_ghosts=[]; a.make_ghost=lambda color: NP('ghost')
    a.update_bounce_ghosts(); assert any(k[2]==round(a.PHYSICS_STEP,4) for k in a.physics.bounce_cache)
    print(f'  standing jump peaks {min(peaks)-1:.4f} at 30, 60, 144, 240 and 300 FPS; ghosts use the physics step')

@proof('R04 falls have a terminal speed and invincible falls below the map return to the checkpoint')
def terminal_fall(tmp):
    w=world(tmp); p=physics(w); p.player.setPos(0,0,500); p.vz=-1e6; p.update(1/240,KEYS)
    assert p.vz>=-p.max_fall_speed and p.player.getZ()>500-2
    w=world(tmp); p=physics(w); p.god_mode=True; p.checkpoint=V(0,0,1); p.player.setPos(0,0,-999.9); p.vz=-50
    p.update(1/240,KEYS); assert p.just_respawned and p.player.getPos()==V(0,0,1)
    steps=max(1,math.ceil(p.max_fall_speed/240/p.max_step)); assert steps==5
    print('  speed capped at 300 (at most 5 sub-steps per 1/240 s step); z<-1000 respawns at the checkpoint')

@proof('R05 a v3 map with one rejected record loads the rest with their own groups and headings')
def partial_v3(tmp):
    w=world(tmp)
    for x,g,h in ((0,'one',15),(2,'two',30),(4,'three',45)):
        c=cube(w,(x,0,.5)); c.setTag('group',g); c.setTag('heading',str(h))
    m=mover(w,(6,0,.5)); m['np'].setTag('group','four'); m['np'].setTag('heading','60')
    save(w); data=json.loads(gzip.decompress(Path(w.save_file).read_bytes()[6:]))
    data['records']=data['records'].replace('B,2.0,0.0,0.5,1','B,2.0,0.0,0.5,9')
    Path(w.save_file).write_bytes(b'DMAP3\n'+gzip.compress(json.dumps(data).encode()))
    w.load_map()
    assert not w.save_blocked and len(w.load_errors)==1 and list(Path(tmp).glob('map.txt.*.bak'))
    got={(c.getX(),c.getTag('group'),c.getTag('heading')) for c in w.all_blocks()}
    assert got=={(0,'one','15.0'),(4,'three','45.0'),(6,'four','60.0')}, got
    data['properties']=data['properties'][:-1]
    Path(w.save_file).write_bytes(b'DMAP3\n'+gzip.compress(json.dumps(data).encode()))
    w.load_map(); assert not w.save_blocked and len(w.all_blocks())==3 and len(w.load_errors)==2
    print('  bad middle record dropped; remaining blocks and mover keep their own properties; mismatched list still loads blocks')

@proof('R06 undo and redo patch surviving blocks in place, and history is capped by captured blocks')
def history_in_place(tmp):
    w=world(tmp); a=app(w); a.tool_mode=11
    nodes=[cube(w,(x,0,.5)) for x in range(5)]; m=mover(w,(0,3,.5),wp=(0,6,.5)); a.selected_objects=nodes+[m['np']]
    with immediate(): a.transform_selection(0,0,2)
    assert a.history_step()
    assert all(c in w.cubes and c.getZ()==.5 and w.cube_map[w.get_grid_key(c.getPos())]==c for c in nodes)
    assert w.find_mover(m['np']) is m and m['origin']==V(0,3,.5) and m['waypoints']==[V(0,6,.5)]
    assert list(w.cubes)==nodes and not w.cube_pool
    assert a.history_step(True) and all(c.getZ()==2.5 for c in nodes) and m['origin']==V(0,3,2.5)
    from disepshun.edit_history import EditHistory
    h=EditHistory(w,limit=100,max_states=12)
    for i in range(6):
        token=h.begin(nodes[:3]); nodes[0].setTag('heading',str(i+1)); h.finish(token,nodes[:3],'turn')
    assert len(h.undo_stack)==2 and sum(h.entry_size(e) for e in h.undo_stack)<=12
    big=EditHistory(w,limit=100,max_states=1)
    token=big.begin(nodes); nodes[0].setTag('heading','99'); big.finish(token,nodes,'turn')
    assert len(big.undo_stack)==1  # the newest entry is always kept
    print('  move undo/redo keeps the same nodes and save order; 12-state cap keeps the 2 newest 6-state entries')

@proof('R07 deletes and editor commits are debounced; superseded snapshots are not written')
def debounced_edits(tmp):
    w=world(tmp); c=cube(w); d=cube(w,(2,0,.5)); a=app(w)
    hit(a,c)
    with immediate(): a.delete()
    assert c not in w.cubes and not Path(w.save_file).exists() and w.pending_save_at is not None
    with patch.object(time,'monotonic',return_value=w.pending_save_at+1), immediate(): w.retry_save(0)
    assert '\nB,2.0,' in map_text(w.save_file) and '\nB,0.0,' not in map_text(w.save_file)
    jobs=[]; writes=[]
    class QueuedThread:
        def __init__(self,target,args,**kw): self.target,self.args=target,args
        def start(self): jobs.append((self.target,self.args))
        def is_alive(self): return False
    with patch.object(threading,'Thread',QueuedThread):
        w.map_is_dirty=True; w.save_map(); d.setX(8); w.map_is_dirty=True; w.save_map()
    real_open=open
    def counting_open(f,*args,**kw):
        if str(f).endswith('.tmp'): writes.append(f)
        return real_open(f,*args,**kw)
    with patch.object(builtins,'open',counting_open):
        for fn,args in jobs: fn(*args)
    assert len(writes)==1 and '\nB,8.0,' in map_text(w.save_file)
    print('  delete waits for the debounce; of two queued snapshots only the newest is written')

@proof('R08 per-frame selection work runs only after the selection, tool or blocks change')
def selection_dirty(tmp):
    w=world(tmp); a=app(w); a.tool_mode=11
    nodes=[cube(w,(x,0,.5)) for x in range(4)]; m=mover(w,(4,0,.5),wp=(9,0,.5))
    calls=[]; real=a.refresh_object_selection
    a.refresh_object_selection=lambda: (calls.append(1), real())
    a.selected_objects=nodes[:2]
    for _ in range(5): a.refresh_selection_if_changed()
    assert len(calls)==1 and nodes[0].hasPythonTag('selection_color')
    a.selected_objects.append(nodes[2]); a.refresh_selection_if_changed(); assert len(calls)==2
    w.touch(); a.refresh_selection_if_changed(); assert len(calls)==3
    a.tool_mode=10; a.refresh_selection_if_changed(); assert len(calls)==4
    a.tool_mode=11; a.refresh_selection_if_changed(); a.refresh_selection_if_changed(); assert len(calls)==5
    a.draw_selection_center(); cache=a.selection_pivot_cache
    a.draw_selection_center(); assert a.selection_pivot_cache is cache
    a.selected_objects=nodes+[m['np']]; a.draw_selection_center(); first=V(a.selection_center_node.getPos())
    m['np'].setX(9); a.draw_selection_center()
    assert first==V(2,0,.5) and abs(a.selection_center_node.getX()-3)<1e-5  # the moving block is re-read every frame
    expected=a.reference_point([c.getPos(w.render) for c in a.selected_objects],grid_z=True)
    assert (a.selection_center_node.getPos()-expected).length()<1e-5
    print('  5 idle frames: 1 rescan; append, block edit and tool change each rescan once; pivot follows movers')


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
