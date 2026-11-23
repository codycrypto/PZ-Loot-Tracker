#!/usr/bin/env python3
"""Extract Project Zomboid's vanilla inventory icons (Item_*.png) from your own game install.

The game ships most item icons packed into texture atlases (media/texturepacks/*.pack),
plus a few loose files under media/textures. This script unpacks both into
assets/icons/vanilla/ so the tracker can show real icons instead of placeholder glyphs.

Usage:
  uv run --with pillow build/extract_icons.py                 # auto-detect the game install
  uv run --with pillow build/extract_icons.py --media "/path/to/media"
  (or: python3 -m pip install pillow && python3 build/extract_icons.py ...)

It also writes assets/icons/vanilla/icons.js (an index of the files). Reload the app and the icons show up.

.pack format (PZ B42, read by zombie.fileSystem.TexturePackDevice), all ints little-endian int32:
  ["PZPK" magic + int version(=1)]   (version 0 files have no magic)
  int pageCount
  per page:
    string pageName                   (int length + bytes)
    int entryCount, int hasAlpha
    per entry: string name, int x, y, w, h, offsetX, offsetY, fullW, fullH
    v1: int pngLength + PNG bytes     v0: PNG bytes terminated by 0xDEADBEEF
Each sprite is cropped from the page at (x, y, w, h) and placed at (offsetX, offsetY)
on a transparent fullW x fullH canvas (the packer trims transparent borders).
"""
import argparse, io, json, os, struct, sys, glob, platform

try:
    from PIL import Image
except ImportError:
    sys.exit('Pillow is required: uv run --with pillow build/extract_icons.py  (or pip install pillow)')

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_OUT = os.path.join(ROOT, 'assets', 'icons', 'vanilla')
# Packs that hold world tiles / trees / weather only. They never contain Item_ icons and are huge.
SKIP_PACKS = ('tiles2x', 'jumbotrees', 'b42chunkcaching', 'overlays2x', 'weatherfx')


def candidate_media_dirs():
    home = os.path.expanduser('~')
    sysname = platform.system()
    c = []
    if sysname == 'Darwin':
        c.append(os.path.join(home, 'Library/Application Support/Steam/steamapps/common/ProjectZomboid/Project Zomboid.app/Contents/Java/media'))
    elif sysname == 'Windows':
        for base in (os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'), os.environ.get('ProgramFiles', r'C:\Program Files')):
            c.append(os.path.join(base, 'Steam', 'steamapps', 'common', 'ProjectZomboid', 'media'))
    else:
        for base in ('~/.steam/steam', '~/.local/share/Steam', '~/.var/app/com.valvesoftware.Steam/.local/share/Steam'):
            c.append(os.path.join(os.path.expanduser(base), 'steamapps/common/ProjectZomboid/media'))
    return c


def find_media(arg):
    if arg:
        p = os.path.expanduser(arg)
        for sub in ('', 'media', 'Project Zomboid.app/Contents/Java/media', 'Contents/Java/media'):
            q = os.path.join(p, sub)
            if os.path.isdir(os.path.join(q, 'texturepacks')) or os.path.isdir(os.path.join(q, 'textures')):
                return q
        sys.exit(f'No media/texturepacks or media/textures found under {p}')
    for q in candidate_media_dirs():
        if os.path.isdir(q):
            return q
    sys.exit('Could not auto-detect the Project Zomboid install. Pass --media "<game install>/media".\nTried:\n  ' + '\n  '.join(candidate_media_dirs()))


class Reader:
    def __init__(self, f): self.f = f
    def int(self):
        b = self.f.read(4)
        if len(b) < 4: raise EOFError
        return struct.unpack('<i', b)[0]
    def str(self):
        n = self.int()
        return self.f.read(n).decode('latin-1')


def read_pack(path, want):
    """Yield (name, PIL.Image) for every entry whose name satisfies want(name)."""
    with open(path, 'rb') as f:
        r = Reader(f)
        magic = f.read(4)
        if magic == b'PZPK':
            version = r.int()
            if version != 1: raise ValueError(f'{path}: unsupported .pack version {version}')
        else:
            f.seek(0); version = 0
        pages = r.int()
        for _ in range(pages):
            r.str()  # page name
            n = r.int(); r.int()  # entries, hasAlpha
            entries = []
            for _ in range(n):
                name = r.str()
                x, y, w, h, ox, oy, fw, fh = struct.unpack('<8i', f.read(32))
                entries.append((name, x, y, w, h, ox, oy, fw, fh))
            if version >= 1:
                ln = r.int()
                hits = [e for e in entries if want(e[0])]
                if not hits:
                    f.seek(ln, 1); continue
                png = f.read(ln)
            else:
                buf = bytearray()
                while not buf.endswith(b'\xef\xbe\xad\xde'):
                    ch = f.read(1)
                    if not ch: raise EOFError
                    buf += ch
                png = bytes(buf[:-4])
                hits = [e for e in entries if want(e[0])]
                if not hits: continue
            page = Image.open(io.BytesIO(png)).convert('RGBA')
            for name, x, y, w, h, ox, oy, fw, fh in hits:
                sprite = page.crop((x, y, x + w, y + h))
                canvas = Image.new('RGBA', (max(fw, w + ox), max(fh, h + oy)), (0, 0, 0, 0))
                canvas.paste(sprite, (ox, oy))
                yield name, canvas


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--media', help='game media folder (or the game install folder); auto-detected if omitted')
    ap.add_argument('--out', default=DEFAULT_OUT, help='output folder (default: assets/icons/vanilla)')
    ap.add_argument('--all-packs', action='store_true', help='also scan the big tile/tree packs (slow, normally pointless)')
    a = ap.parse_args()
    media = find_media(a.media)
    os.makedirs(a.out, exist_ok=True)
    print(f'media: {media}\nout:   {a.out}')
    written = {}  # lowercase name -> filename (macOS/Windows filesystems are case-insensitive)
    want = lambda n: n.lower().startswith('item_')

    packs = sorted(glob.glob(os.path.join(media, 'texturepacks', '*.pack')))
    for p in packs:
        base = os.path.basename(p).lower()
        if not a.all_packs and base.startswith(SKIP_PACKS):
            continue
        cnt = 0
        for name, img in read_pack(p, want):
            key = name.lower()
            if key in written: continue
            fn = name + '.png'
            img.save(os.path.join(a.out, fn)); written[key] = fn; cnt += 1
        print(f'  {os.path.basename(p):28s} {cnt:5d} icons')

    loose = 0
    for dp, _, files in os.walk(os.path.join(media, 'textures')):
        for fn in files:
            if not (fn.lower().startswith('item_') and fn.lower().endswith('.png')): continue
            key = fn[:-4].lower()
            if key in written: continue
            Image.open(os.path.join(dp, fn)).save(os.path.join(a.out, fn)); written[key] = fn; loose += 1
    print(f'  {"media/textures (loose files)":28s} {loose:5d} icons')
    with open(os.path.join(a.out, 'icons.js'), 'w', encoding='utf-8') as f:
        f.write('// generated by build/extract_icons.py - not committed (game art)\nwindow.PZ_VANILLA_ICONS = '
                + json.dumps({k[5:]: v for k, v in sorted(written.items())}, separators=(',', ':')) + ';\n')
    print(f'total: {len(written)} icons in {a.out}  (+ icons.js index). Reload the tracker to see them.')


if __name__ == '__main__':
    main()
