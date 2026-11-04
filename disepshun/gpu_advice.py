"""Compare the active renderer with Windows' power/performance adapter ordering."""
import ctypes
import os
import re
import sys
import uuid


def _normalized(name):
    name = re.sub(r'\((?:r|tm)\)', '', name.casefold())
    return re.sub(r'[^a-z0-9]', '', name)


def gpu_recommendation(renderer, power_order, performance_order):
    """Only advise when the renderer matches a known lower-priority adapter."""
    if not renderer or not power_order or not performance_order:
        return None
    current = _normalized(renderer)
    def matches(name):
        other = _normalized(name)
        return len(other) >= 8 and (other in current or current in other)
    best = performance_order[0]
    if matches(best['name']):
        return None
    for adapter in power_order:
        if matches(adapter['name']) and adapter['id'] != best['id']:
            return dict(current=renderer, recommended=best['name'])
    return None


def windows_adapter_orders():
    """DXGI 1.6 orders real adapters by minimum power and high performance."""
    if os.name != 'nt':
        return [], []
    from ctypes import wintypes as w
    class GUID(ctypes.Structure):
        _fields_ = [('bytes',ctypes.c_ubyte*16)]
    class LUID(ctypes.Structure):
        _fields_ = [('low',w.DWORD),('high',w.LONG)]
    class Description(ctypes.Structure):
        _fields_ = [('name',w.WCHAR*128),('vendor',w.UINT),('device',w.UINT),
                    ('subsystem',w.UINT),('revision',w.UINT),
                    ('video_memory',ctypes.c_size_t),('system_memory',ctypes.c_size_t),
                    ('shared_memory',ctypes.c_size_t),('luid',LUID),('flags',w.UINT)]
    def guid(value):
        return GUID((ctypes.c_ubyte*16).from_buffer_copy(uuid.UUID(value).bytes_le))
    def method(pointer, index, result, *args):
        table = ctypes.cast(pointer,ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        return ctypes.WINFUNCTYPE(result,ctypes.c_void_p,*args)(table[index])
    def release(pointer):
        if pointer: method(pointer,2,w.ULONG)(pointer)
    factory = ctypes.c_void_p()
    factory_id = guid('c1b6694f-ff09-44a9-b03c-77900a0a1d17')
    adapter_id = guid('29038f61-3839-4626-91fd-086879011a05')
    try:
        create = ctypes.WinDLL('dxgi').CreateDXGIFactory1
        create.argtypes = [ctypes.POINTER(GUID),ctypes.POINTER(ctypes.c_void_p)]
        create.restype = w.LONG
        if create(ctypes.byref(factory_id),ctypes.byref(factory)) < 0:
            return [], []
        enum = method(factory,29,w.LONG,w.UINT,w.UINT,ctypes.POINTER(GUID),ctypes.POINTER(ctypes.c_void_p))
        orders = []
        for preference in (1,2):
            adapters = []
            for index in range(32):
                adapter = ctypes.c_void_p()
                if enum(factory,index,preference,ctypes.byref(adapter_id),ctypes.byref(adapter)) < 0:
                    break
                try:
                    description = Description()
                    get_description = method(adapter,10,w.LONG,ctypes.POINTER(Description))
                    if get_description(adapter,ctypes.byref(description)) >= 0 and not description.flags & 3:
                        adapters.append(dict(name=description.name,
                            id=(description.luid.high,description.luid.low)))
                finally:
                    release(adapter)
            orders.append(adapters)
        return tuple(orders)
    except (OSError,AttributeError):
        return [], []
    finally:
        release(factory)


def check_renderer(renderer):
    return gpu_recommendation(renderer,*windows_adapter_orders())


def executable_path():
    # For this source build, Windows' per-app preference applies to Python itself.
    return os.path.abspath(sys.executable)


def open_graphics_settings():
    if os.name != 'nt':
        return False
    try:
        os.startfile('ms-settings:display-advancedgraphics')
        return True
    except OSError:
        return False


def renderer_info(renderer):
    power, performance = windows_adapter_orders()
    names = list(dict.fromkeys(a['name'] for a in performance + power))
    current = _normalized(renderer)
    others = [name for name in names if not (_normalized(name) in current or current in _normalized(name))] if current else names
    return dict(current=renderer or 'Unknown renderer', others=others,
                enumerated=bool(names))
