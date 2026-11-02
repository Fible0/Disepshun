"""Discord IPC runs outside the render thread; settings changes wake it immediately."""
import threading
import time


class DiscordPresence:
    APP_ID = '1566233876823678996'
    # Reuse the application's existing public icon as Rich Presence artwork.
    IMAGE_KEY = f'https://cdn.discordapp.com/app-icons/{APP_ID}/f08d14484ba90f335150be5dd29c8a80.png?size=512'
    DISPLAY_SETTINGS = {
        'Discord Show Activity': 'show_activity',
        'Discord Show Block Count': 'show_block_count',
        'Discord Show Time': 'show_time',
        'Discord Show Icon': 'show_icon',
    }

    def __init__(self, settings=None):
        settings = settings or {}
        self._enabled = settings.get('Discord Rich Presence', True) is not False
        self._options = {option: settings.get(label, True) is not False
                         for label,option in self.DISPLAY_SETTINGS.items()}
        self.status = ('Exploring', 0)
        self.started = int(time.time())
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.worker = None
        self.connected = False
        self.error = None

    @property
    def client_id(self): return self.APP_ID

    @property
    def enabled(self): return self._enabled

    @enabled.setter
    def enabled(self, value): self.configure(enabled=value)

    @property
    def connection_status(self):
        if not self.enabled: return 'Discord presence is off.'
        if self.connected: return 'Connected to Discord.'
        return self.error or 'Connecting to Discord...'

    def configure(self, *, enabled=None, show_activity=None, show_block_count=None,
                  show_time=None, show_icon=None):
        changed = False
        if enabled is not None and bool(enabled) != self._enabled:
            self._enabled = bool(enabled)
            self.connected = False
            changed = True
        options = dict(self._options)
        for key,value in (('show_activity',show_activity),('show_block_count',show_block_count),
                          ('show_time',show_time),('show_icon',show_icon)):
            if value is not None and bool(value) != options[key]:
                options[key] = bool(value)
                changed = True
        self._options = options
        if changed:
            self.error = None
            self.wake.set()

    def activity_payload(self):
        activity,count = self.status
        options = self._options
        payload = {}
        if options['show_activity']: payload['details'] = activity
        if options['show_block_count']: payload['state'] = f'{count} blocks in the map'
        if options['show_time']: payload['start'] = self.started
        if options['show_icon'] and self.IMAGE_KEY:
            payload.update(large_image=self.IMAGE_KEY,large_text='Disepshun')
        return payload

    def tick(self, activity, count):
        self.status = (activity, count)
        if (self.worker is None or not self.worker.is_alive()) and not self.stop.is_set() and self.enabled:
            self.worker = threading.Thread(target=self._run, daemon=True, name='DiscordPresence')
            self.worker.start()

    @staticmethod
    def _disconnect(rpc, clear=False):
        if rpc is None: return
        if clear:
            try: rpc.clear()
            except Exception: pass
        try: rpc.close()
        except Exception: pass
        # Failed handshakes can leave a loop behind even when close() raises.
        loop = getattr(rpc, 'loop', None)
        if loop is not None and not loop.is_closed(): loop.close()

    def _run(self):
        rpc = None
        try:
            while not self.stop.is_set():
                self.wake.clear()
                try:
                    if rpc and not self.enabled:
                        self._disconnect(rpc, clear=True); rpc = None
                        self.connected = False
                    if self.enabled:
                        if rpc is None:
                            from pypresence import Presence
                            rpc = Presence(self.client_id, connection_timeout=5, response_timeout=5)
                            rpc.connect()
                        if self.enabled:
                            rpc.update(**self.activity_payload())
                            self.connected = True
                            self.error = None
                except Exception as e:
                    self.connected = False
                    kind = type(e).__name__
                    if kind in ('DiscordNotFound', 'InvalidPipe', 'PipeClosed', 'ConnectionRefusedError', 'FileNotFoundError'):
                        self.error = 'Open Discord desktop; retrying connection.'
                    elif kind == 'InvalidID': self.error = 'Discord rejected this Application ID.'
                    elif kind == 'ModuleNotFoundError': self.error = 'Install requirements.txt to enable Discord.'
                    else: self.error = f'Discord connection failed ({kind}); retrying.'
                    print(f'Discord Rich Presence: {kind}: {e}')
                    self._disconnect(rpc); rpc = None
                if self.stop.is_set(): break
                self.wake.wait(15)
        finally:
            self.connected = False
            self._disconnect(rpc, clear=True)

    def close(self):
        self.stop.set(); self.wake.set()
        if self.worker: self.worker.join(timeout=.5)
