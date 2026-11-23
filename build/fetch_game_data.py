#!/usr/bin/env python3
"""Copy the game files LOOTLOG needs into build/raw, from your own PC or your own server.

Sources (set in lootlog.toml, see lootlog.example.toml, or with PZ_* environment variables):
  local  - a Project Zomboid install on this computer (the game client or a dedicated server)
  ssh    - a dedicated server you can reach with `ssh` (read-only: it only runs `tar` to stdout)

Only reads from the game install / server. Never writes there.
Usage:  python3 build/fetch_game_data.py [--config lootlog.toml]
Then:   python3 build/build_data.py   (see README)
"""
import argparse, io, json, os, platform, re, shlex, shutil, subprocess, sys, tarfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW = os.path.join(HERE, 'raw')
WORKSHOP_APP = '108600'  # Project Zomboid's Steam Workshop app id

# vanilla folders (relative to the game's media folder)
VANILLA = ['scripts', 'lua/shared/Translate/EN', 'lua/server/Items', 'lua/server/Vehicles', 'lua/shared/RecordedMedia', 'radio']


def wanted_mod_file(rel):
    r = rel.replace('\\', '/')
    low = r.lower(); base = low.rsplit('/', 1)[-1]
    return (base == 'mod.info' or ('/media/scripts/' in low and low.endswith('.txt')) or '/translate/en/' in low
            or ('/media/lua/server/' in low and low.endswith('.lua')) or (base.startswith('item_') and base.endswith('.png')))


# ---------------------------------------------------------------- config
DEFAULTS = {'source': 'local', 'game_version': '42.22',
            'local': {'game_dir': '', 'workshop_dir': '', 'mods_ini': ''},
            'ssh': {'host': '', 'game_dir': '', 'workshop_dir': '', 'mods_ini': '', 'sudo': False, 'port': 0, 'identity_file': ''}}
ENV = {  # env var -> (section, key)
    'PZ_SOURCE': (None, 'source'), 'PZ_GAME_VERSION': (None, 'game_version'),
    'PZ_GAME_DIR': ('*', 'game_dir'), 'PZ_WORKSHOP_DIR': ('*', 'workshop_dir'), 'PZ_MODS_INI': ('*', 'mods_ini'),
    'PZ_SSH_HOST': ('ssh', 'host'), 'PZ_SSH_SUDO': ('ssh', 'sudo'), 'PZ_SSH_PORT': ('ssh', 'port'), 'PZ_SSH_IDENTITY': ('ssh', 'identity_file'),
}


def load_config(path):
    cfg = json.loads(json.dumps(DEFAULTS))
    if path and os.path.isfile(path):
        try:
            import tomllib
        except ImportError:
            sys.exit('Reading lootlog.toml needs Python 3.11+. Use PZ_* environment variables instead, or upgrade Python.')
        with open(path, 'rb') as f:
            user = tomllib.load(f)
        for k, v in user.items():
            if isinstance(v, dict): cfg.setdefault(k, {}).update(v)
            else: cfg[k] = v
        print(f'config: {path}')
    for var, (sec, key) in ENV.items():
        if var not in os.environ: continue
        val = os.environ[var]
        if key == 'sudo': val = val.lower() in ('1', 'true', 'yes')
        if sec is None: cfg[key] = val
        elif sec == '*': cfg[cfg['source']][key] = val
        else: cfg[sec][key] = val
    return cfg


# ---------------------------------------------------------------- local
def steam_roots():
    home = os.path.expanduser('~'); s = platform.system()
    if s == 'Darwin':
        return [os.path.join(home, 'Library/Application Support/Steam')]
    if s == 'Windows':
        return [os.path.join(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'), 'Steam'),
                os.path.join(os.environ.get('ProgramFiles', r'C:\Program Files'), 'Steam')]
    return [os.path.expanduser(p) for p in ('~/.steam/steam', '~/.local/share/Steam', '~/.var/app/com.valvesoftware.Steam/.local/share/Steam')]


def find_media(game_dir):
    for sub in ('media', 'Project Zomboid.app/Contents/Java/media', 'Contents/Java/media', ''):
        m = os.path.join(game_dir, sub)
        if os.path.isdir(os.path.join(m, 'scripts')) and os.path.isdir(os.path.join(m, 'lua')):
            return m
    return None


def fetch_local(c):
    game = os.path.expanduser(c['game_dir']) if c.get('game_dir') else ''
    if not game:
        for root in steam_roots():
            for name in ('ProjectZomboid', 'Project Zomboid Dedicated Server'):
                p = os.path.join(root, 'steamapps', 'common', name)
                if find_media(p): game = p; break
            if game: break
    media = find_media(game) if game else None
    if not media:
        sys.exit('Could not find the game files. Set [local] game_dir in lootlog.toml (or PZ_GAME_DIR) to your Project Zomboid install folder.')
    print(f'[1/3] vanilla game files from {media}')
    for rel in VANILLA:
        src = os.path.join(media, rel)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(RAW, 'media', rel), dirs_exist_ok=True)
        else:
            print(f'   (missing {rel}, skipped)')

    print('[2/3] mod list')
    ini = os.path.expanduser(c.get('mods_ini') or '')
    if ini:
        if not os.path.isfile(ini): sys.exit(f'mods_ini not found: {ini}')
        lines = [l for l in open(ini, encoding='utf-8', errors='replace') if re.match(r'^(Mods|WorkshopItems)=', l)]
        open(os.path.join(RAW, 'server_mods.ini'), 'w').writelines(lines)
    else:
        print('   no mods_ini set: building vanilla items only')

    ws = os.path.expanduser(c.get('workshop_dir') or '')
    if not ws and ini:
        # client: <steam>/steamapps/workshop/content/108600 ; dedicated server: <install>/steamapps/workshop/content/108600
        cands = [os.path.normpath(os.path.join(game, '..', '..', 'workshop', 'content', WORKSHOP_APP)),
                 os.path.join(game, 'steamapps', 'workshop', 'content', WORKSHOP_APP)]
        cands += [os.path.join(r, 'steamapps', 'workshop', 'content', WORKSHOP_APP) for r in steam_roots()]
        ws = next((p for p in cands if os.path.isdir(p)), '')
    print('[3/3] workshop mod data' + (f' from {ws}' if ws else ' (none)'))
    if ws and ini:
        ids = workshop_ids()
        n = 0
        for wid in (ids or sorted(os.listdir(ws))):
            base = os.path.join(ws, wid)
            if not os.path.isdir(base): continue
            for dp, _, files in os.walk(base):
                for fn in files:
                    full = os.path.join(dp, fn); rel = os.path.relpath(full, ws)
                    if wanted_mod_file('/' + rel):
                        dst = os.path.join(RAW, 'workshop', rel); os.makedirs(os.path.dirname(dst), exist_ok=True)
                        shutil.copyfile(full, dst); n += 1
        print(f'   {n} mod files copied')

    build_id = None
    for p in [os.path.normpath(os.path.join(game, '..', '..', f'appmanifest_{a}.acf')) for a in ('108600', '380870')] + \
             [os.path.join(game, 'steamapps', 'appmanifest_380870.acf')]:
        if os.path.isfile(p):
            m = re.search(r'"buildid"\s+"(\d+)"', open(p, errors='replace').read())
            if m: build_id = m.group(1); break
    return {'label': 'local game install', 'steamBuild': build_id}


def workshop_ids():
    p = os.path.join(RAW, 'server_mods.ini')
    if not os.path.isfile(p): return []
    m = re.search(r'^WorkshopItems=(.*)$', open(p).read(), re.M)
    return [w.strip() for w in (m.group(1) if m else '').split(';') if w.strip()]


# ---------------------------------------------------------------- ssh
def fetch_ssh(c):
    host, game = c.get('host'), (c.get('game_dir') or '').rstrip('/')
    if not host or not game:
        sys.exit('ssh source needs [ssh] host and game_dir in lootlog.toml (or PZ_SSH_HOST / PZ_GAME_DIR).')
    ssh = ['ssh']
    if c.get('port'): ssh += ['-p', str(c['port'])]
    if c.get('identity_file'): ssh += ['-i', os.path.expanduser(c['identity_file'])]
    ssh += [host]
    sudo = 'sudo -n ' if c.get('sudo') else ''
    q = shlex.quote

    def run_tar(remote_cmd, dest):
        print(f'   ssh {host}: {remote_cmd[:110]}{"..." if len(remote_cmd) > 110 else ""}')
        proc = subprocess.Popen(ssh + [remote_cmd], stdout=subprocess.PIPE)
        with tarfile.open(fileobj=proc.stdout, mode='r|gz') as tf:
            try: tf.extractall(dest, filter='data')
            except TypeError: tf.extractall(dest)  # Python < 3.12
        if proc.wait() != 0: sys.exit(f'ssh command failed (exit {proc.returncode})')
        for dp, _, files in os.walk(dest):  # drop macOS AppleDouble "._*" files if the server is a Mac
            for fn in files:
                if fn.startswith('._'): os.remove(os.path.join(dp, fn))

    def run(remote_cmd):
        r = subprocess.run(ssh + [remote_cmd], capture_output=True, text=True)
        return r.stdout

    print('[1/3] vanilla game files')
    paths = ' '.join(q('media/' + p) for p in VANILLA)
    run_tar(f'{sudo}tar -C {q(game)} -czf - {paths}', RAW)

    print('[2/3] mod list')
    ini = c.get('mods_ini')
    if ini:
        open(os.path.join(RAW, 'server_mods.ini'), 'w').write(run(f'{sudo}grep -E "^(Mods|WorkshopItems)=" {q(ini)}'))
        ws = (c.get('workshop_dir') or f'{game}/steamapps/workshop/content/{WORKSHOP_APP}').rstrip('/')
        ids = workshop_ids()
        print('[3/3] workshop mod data')
        sel = ' '.join(q(i) for i in ids) if ids else '.'
        find = (f'cd {q(ws)} && find {sel} \\( -name mod.info -o -path "*/media/scripts/*.txt" -o -path "*/Translate/EN/*" '
                f'-o -path "*/media/lua/server/*.lua" -o -iname "Item_*.png" \\) -type f -print0 2>/dev/null | tar --null -T - -czf -')
        os.makedirs(os.path.join(RAW, 'workshop'), exist_ok=True)
        run_tar(f'{sudo}sh -c {q(find)}', os.path.join(RAW, 'workshop'))
    else:
        print('   no mods_ini set: building vanilla items only\n[3/3] workshop mod data (skipped)')
    acf = run(f'{sudo}cat {q(game)}/steamapps/appmanifest_380870.acf 2>/dev/null || true')
    m = re.search(r'"buildid"\s+"(\d+)"', acf)
    return {'label': 'dedicated server (ssh)', 'steamBuild': m.group(1) if m else None}


def main():
    ap = argparse.ArgumentParser(description='Copy Project Zomboid game data into build/raw')
    ap.add_argument('--config', default=os.path.join(ROOT, 'lootlog.toml'), help='config file (default: lootlog.toml)')
    a = ap.parse_args()
    cfg = load_config(a.config)
    src = cfg['source']
    if src not in ('local', 'ssh'): sys.exit(f'source must be "local" or "ssh", not {src!r}')
    shutil.rmtree(RAW, ignore_errors=True); os.makedirs(RAW)
    info = fetch_local(cfg['local']) if src == 'local' else fetch_ssh(cfg['ssh'])
    info['gameVersion'] = str(cfg.get('game_version') or '42')
    json.dump(info, open(os.path.join(RAW, 'source.json'), 'w'), indent=2)
    print(f'done -> {RAW}')


if __name__ == '__main__':
    main()
