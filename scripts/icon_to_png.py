"""Render assets/icon.svg to assets/icon.png and assets/icon.ico (needs rsvg-convert)."""
import os, struct, subprocess

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SVG = os.path.join(ROOT_DIR, 'assets', 'icon.svg')
PNG = os.path.join(ROOT_DIR, 'assets', 'icon.png')
ICO = os.path.join(ROOT_DIR, 'assets', 'icon.ico')
SIZE = 256
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]  # Windows picks the closest size for the taskbar, title bar and Alt-Tab

def render(size):
    return subprocess.run(['rsvg-convert', '-w', str(size), '-h', str(size), SVG], check=True, capture_output=True).stdout

def main():
    with open(PNG, 'wb') as f: f.write(render(SIZE))
    pngs = [render(s) for s in ICO_SIZES]
    # ICO with one embedded PNG image per size (0 in the size fields means 256)
    header = struct.pack('<HHH', 0, 1, len(pngs))
    entries, offset = b'', 6 + 16 * len(pngs)
    for s, png in zip(ICO_SIZES, pngs):
        entries += struct.pack('<BBBBHHII', s % 256, s % 256, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
    with open(ICO, 'wb') as f: f.write(header + entries + b''.join(pngs))
    print(f'Wrote {PNG}\nWrote {ICO}')

if __name__ == '__main__':
    main()
