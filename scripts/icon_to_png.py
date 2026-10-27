"""Render assets/icon.svg to assets/icon.png and assets/icon.ico (needs rsvg-convert)."""
import os, struct, subprocess

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SVG = os.path.join(ROOT_DIR, 'assets', 'icon.svg')
PNG = os.path.join(ROOT_DIR, 'assets', 'icon.png')
ICO = os.path.join(ROOT_DIR, 'assets', 'icon.ico')
SIZE = 256

def main():
    subprocess.run(['rsvg-convert', '-w', str(SIZE), '-h', str(SIZE), SVG, '-o', PNG], check=True)
    with open(PNG, 'rb') as f: png = f.read()
    # ICO with one embedded PNG image (0 in the size fields means 256)
    header = struct.pack('<HHH', 0, 1, 1)
    entry = struct.pack('<BBBBHHII', 0, 0, 0, 0, 1, 32, len(png), 6 + 16)
    with open(ICO, 'wb') as f: f.write(header + entry + png)
    print(f'Wrote {PNG}\nWrote {ICO}')

if __name__ == '__main__':
    main()
