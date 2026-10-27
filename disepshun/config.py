import sys,os,ctypes,math,threading,random;from direct.showbase.ShowBase import ShowBase;from direct.gui.OnscreenText import OnscreenText;from direct.gui.DirectGui import*;from direct.gui import DirectGuiGlobals as DGG;from panda3d.core import*
if os.name=='nt':user32=ctypes.windll.user32;user32.SetProcessDPIAware();w,h=user32.GetSystemMetrics(0),user32.GetSystemMetrics(1)
else:user32=None;_pipe=GraphicsPipeSelection.getGlobalPtr().makeDefaultPipe();w,h=_pipe.getDisplayWidth(),_pipe.getDisplayHeight()
COLLIDABLE_MASK=BitMask32(1)
for c in[f'win-size {w} {h-1}'if user32 else f'win-size {w} {h}','fullscreen 0'if user32 else'fullscreen 1','undecorated 1','window-title Disepshun','sync-video 1','show-frame-rate-meter 0','prefer-discrete-gpu 1','depth-bits 24','audio-buffering-seconds 0.02']:loadPrcFileData('',c)
ROOT_DIR=os.path.dirname(os.path.dirname(os.path.abspath(__file__)));DATA_DIR=os.path.join(ROOT_DIR,'data');SOUND_DIR=os.path.join(ROOT_DIR,'assets','sounds')
