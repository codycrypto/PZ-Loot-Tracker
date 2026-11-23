#!/usr/bin/env python3
"""Build data/items.js for the PZ item tracker from raw game files.

Inputs (from fetch_game_data.py): build/raw/media/..., build/raw/workshop/..., build/raw/server_mods.ini (optional),
build/raw/source.json; plus assets/icons/vanilla/ (from extract_icons.py, optional).
Outputs: data/items.js (window.PZDATA = {...}) and assets/icons/mod/*.png for modded item icons.
Needs: python3 + lupa (pip install lupa) to evaluate the Lua loot / recorded media tables.
"""
import json, os, re, sys, shutil, collections, datetime
import lupa
from lupa import lua54 as lupa_rt  # closest to Kahlua semantics (no Lua 5.5 const loop vars)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW = os.path.join(HERE, 'raw')
MEDIA = os.path.join(RAW, 'media')
_SRC_PATH = os.path.join(RAW, 'source.json')
SOURCE = json.load(open(_SRC_PATH)) if os.path.exists(_SRC_PATH) else {}
GAME_VERSION_STR = str(SOURCE.get('gameVersion') or '42.22')
GAME_VERSION = tuple(int(x) for x in (GAME_VERSION_STR.split('.') + ['0'])[:2])
TOP_N = 12

# ---------------------------------------------------------------- script parsing
def strip_comments(t):
    t = re.sub(r'/\*.*?\*/', ' ', t, flags=re.S)
    # line comments: only when // starts the line or follows whitespace/comma (avoid URLs)
    t = re.sub(r'(^|[\s,])//[^\n]*', r'\1', t)
    return t

BLOCK_RE = re.compile(r'([A-Za-z_][\w]*)(?:[ \t]+([^\n{}=]*?))?\s*\{')

def parse_blocks(text):
    """Return list of (kind, name, body, children) for a text fragment (one level)."""
    out = []; i = 0; n = len(text)
    while i < n:
        m = BLOCK_RE.search(text, i)
        if not m: break
        start = m.end(); depth = 1; j = start
        while j < n and depth:
            c = text[j]
            if c == '{': depth += 1
            elif c == '}': depth -= 1
            j += 1
        out.append((m.group(1), (m.group(2) or '').strip(), text[start:j-1], text[i:m.start()]))
        i = j
    return out

def top_level_text(body):
    """body text with nested {...} blocks removed."""
    res = []; depth = 0
    for c in body:
        if c == '{': depth += 1; continue
        if c == '}': depth -= 1; continue
        if depth == 0: res.append(c)
    return ''.join(res)

def parse_props(body):
    props = {}
    flat = top_level_text(body)
    for line in flat.split('\n'):
        parts = [line]
        if line.count('=') > 1: parts = line.split(',')
        for p in parts:
            p = p.strip().rstrip(',').strip()
            if '=' not in p: continue
            k, v = p.split('=', 1)
            k = k.strip(); v = v.strip().rstrip(',').strip()
            if not k or ' ' in k: continue
            props[k] = v
    return props

def parse_recipe_io(body):
    """craftRecipe inputs/outputs -> (inputs:[{items:[], tags:[]}], outputs:[ids])"""
    ins, outs = [], []
    for kind, name, sub, _ in parse_blocks(body):
        k = kind.lower()
        if k not in ('inputs', 'outputs'): continue
        for line in top_level_text(sub).split('\n'):
            line = line.strip().rstrip(',')
            if not line.startswith('item'): continue
            items = []
            for grp in re.findall(r'\[([^\]]*)\]', re.sub(r'(tags|flags|mappers?)\[[^\]]*\]', '', line)):
                items += [x.strip() for x in grp.split(';') if x.strip() and x.strip() != '*']
            tags = []
            for grp in re.findall(r'tags\[([^\]]*)\]', line):
                tags += [x.strip().lower() for x in grp.split(';') if x.strip()]
            if k == 'outputs':
                m = re.match(r'item\s+\d+\s+([\w.]+)', line)
                if m and not items: items = [m.group(1)]
                outs += items
            else:
                ins.append({'items': items, 'tags': tags, 'keep': 'mode:keep' in line})
    return ins, outs

def parse_old_recipe(body):
    ins = []; outs = []
    for part in re.split(r',\s*\n|\n', body):
        part = part.strip().rstrip(',')
        if not part: continue
        if part.lower().startswith('result:'):
            outs.append(part.split(':', 1)[1].split('=')[0].strip()); continue
        if ':' in part: continue
        part = re.sub(r'^(keep|destroy)\s+', '', part)
        names = [x.split('=')[0].strip() for x in part.split('/')]
        names = [x for x in names if re.match(r'^[\w.]+$', x)]
        if names: ins.append({'items': names, 'tags': [], 'keep': False})
    return ins, outs

def parse_script_file(path, src, items, recipes):
    try:
        text = open(path, encoding='utf-8', errors='replace').read()
    except OSError:
        return
    text = strip_comments(text)
    for kind, mname, body, _ in parse_blocks(text):
        if kind != 'module': continue
        module = mname.split()[0] if mname else 'Base'
        for k2, name, b2, _ in parse_blocks(body):
            if not name: continue
            name = name.split()[0] if k2 == 'item' else name
            if k2 == 'item':
                props = parse_props(b2)
                iid = f'{module}.{name}'
                prev = items.get(iid)
                if prev is not None and prev['src'] == 'vanilla' and src != 'vanilla':
                    merged = dict(prev['props']); merged.update(props)
                    prev['props'] = merged; prev.setdefault('ov', []).append(src)
                    continue
                items[iid] = {'id': iid, 'module': module, 'name': name, 'props': props, 'src': src, 'file': os.path.relpath(path, RAW)}
            elif k2 == 'craftRecipe':
                ins, outs = parse_recipe_io(b2)
                props = parse_props(b2)
                recipes[f'{module}.{name}'] = {'id': name, 'module': module, 'inputs': ins, 'outputs': outs, 'props': props, 'src': src}
            elif k2 == 'recipe':
                ins, outs = parse_old_recipe(b2)
                recipes[f'{module}.{name}'] = {'id': name, 'module': module, 'inputs': ins, 'outputs': outs, 'props': {}, 'src': src}

# ---------------------------------------------------------------- translations
def load_translations(dirs):
    names, recipes_tr, ig = {}, {}, {}
    def put(dic, k, v):
        if k not in dic or dic[k] == '': dic[k] = v
    for d in dirs:
        if not os.path.isdir(d): continue
        for fn in sorted(os.listdir(d)):
            p = os.path.join(d, fn)
            low = fn.lower()
            target = names if low.startswith('itemname') else recipes_tr if low.startswith('recipes') else ig if low.startswith(('ig_ui', 'recorded_media', 'tooltip')) else None
            if target is None: continue
            raw = open(p, encoding='utf-8', errors='replace').read()
            if low.endswith('.json'):
                try:
                    data = json.loads(raw)
                except Exception:
                    try: data = json.loads(re.sub(r',\s*}', '}', raw))
                    except Exception: continue
                for k, v in data.items():
                    if isinstance(v, str): target[k] = v
            else:  # legacy txt: KEY = "value",
                for k, v in re.findall(r'^\s*([\w.\-]+)\s*=\s*"((?:[^"\\]|\\.)*)"', raw, flags=re.M):
                    if low.startswith('itemname') and k.startswith('ItemName_'): k = k[len('ItemName_'):]
                    if low.startswith('recipes') and k.startswith('Recipe_'): k = k[len('Recipe_'):]
                    target[k] = v.replace('\\"', '"')
    return names, recipes_tr, ig

# ---------------------------------------------------------------- lua env
LUA_PRELUDE = r'''
__load = load
local stubmt = {}
local function mkstub() return setmetatable({}, stubmt) end
stubmt.__index = function(t,k) return mkstub() end
stubmt.__call = function(...) return mkstub() end
stubmt.__add = function() return 0 end stubmt.__sub = stubmt.__add stubmt.__mul = stubmt.__add
stubmt.__div = stubmt.__add stubmt.__unm = stubmt.__add stubmt.__concat = function() return "" end
stubmt.__lt = function() return false end stubmt.__le = stubmt.__lt
STUB = mkstub
__deferred = {}
Events = setmetatable({}, {__index = function(t,k)
    local ev = {Add = function(fn) table.insert(__deferred, {k, fn}) end, Remove = function() end}
    rawset(t, k, ev); return ev end})
function getActivatedMods() return setmetatable({}, {__index=function(t,k) if k=="contains" then return function() return true end end; return function() return 0 end end}) end
function isServer() return true end
function isClient() return false end
function getDebug() return false end
function require() return mkstub() end
function getTexture() return nil end
function getText(s) return s end
function getTextOrNull(s) return s end
function instanceof() return false end
function print() end
SandboxVars = setmetatable({}, {__index = function() return setmetatable({}, {__index=function() return 1 end}) end})
setmetatable(_G, {__index = function(t,k) return mkstub() end})
'''

def new_lua():
    L = lupa_rt.LuaRuntime(unpack_returned_tuples=True)
    L.execute(LUA_PRELUDE)
    return L

def run_lua_file(L, path):
    code = open(path, encoding='utf-8', errors='replace').read()
    f = L.eval('function(code, name) local fn, err = __load(code, "@" .. name) if not fn then return false, err end '
               'debug.sethook(function() error("instruction budget exceeded") end, "", 50000000) '
               'local r = table.pack(pcall(fn)) debug.sethook() return table.unpack(r, 1, r.n) end')
    r = f(code, os.path.basename(path))
    if isinstance(r, tuple): ok, err = r[0], (r[1] if len(r) > 1 else None)
    else: ok, err = r, None
    run_lua_file.last_return = err if ok else None
    return bool(ok), (None if ok else str(err))

def lua_list_pairs(tbl):
    """Lua array {'a', 1, 'b', 2} -> [(a,1),(b,2)]"""
    out = []
    if tbl is None or lupa_rt.lua_type(tbl) != 'table': return out
    arr = [tbl[i] for i in range(1, len(tbl) + 1)]
    for i in range(0, len(arr) - 1, 2):
        name, w = arr[i], arr[i + 1]
        if isinstance(name, str) and isinstance(w, (int, float)): out.append((name, float(w)))
    return out

# ---------------------------------------------------------------- location grouping
# keyword -> group; matched against CamelCase-split words of the list name (word prefix match)
GROUP_RULES = [
    ('Vehicles', ['vehicle', 'trunk', 'glovebox', 'seat', 'truckbed']),
    ('Bookstore / Library', ['book', 'books', 'bookstore', 'library', 'literature', 'comic', 'magazine', 'magazines', 'newspaper', 'reading', 'novel']),
    ('Gun Store / Ammo', ['gun', 'guns', 'gunstore', 'ammo', 'ammunition', 'firearm', 'firearms', 'rifle', 'rifles', 'pistol', 'pistols', 'shotgun', 'shotguns', 'gunrack']),
    ('Police / Security', ['police', 'jail', 'prison', 'sheriff', 'evidence', 'security', 'swat', 'cell', 'precinct']),
    ('Military', ['army', 'military', 'armysurplus', 'bunker', 'soldier', 'hecu', 'barracks']),
    ('Hospital / Medical', ['hospital', 'medical', 'morgue', 'doctor', 'surgery', 'clinic', 'ambulance', 'paramedic', 'dentist', 'nurse', 'optometrist', 'vet', 'medicine', 'first', 'laboratory', 'lab']),
    ('Pharmacy', ['pharmacy', 'pharmacist', 'drugstore', 'chemist', 'pills']),
    ('Kitchen / Restaurant', ['kitchen', 'fridge', 'freezer', 'restaurant', 'bakery', 'diner', 'pizza', 'burger', 'spiffo', 'spiffos', 'chicken', 'cafe', 'coffee', 'deli', 'grill', 'cook', 'chef', 'sushi', 'icecream', 'donut', 'bar', 'pub', 'brewery', 'butcher', 'jays', 'food', 'counter', 'dining', 'oven', 'microwave', 'bbq', 'cafeteria']),
    ('Grocery / Store', ['grocery', 'grocer', 'gigamart', 'store', 'shop', 'mall', 'retail', 'liquor', 'convenience', 'cornerstore', 'gas', 'fossoil', 'zippee', 'pawn', 'pawnshop', 'shelves', 'display', 'crate', 'warehouse']),
    ('Garage / Mechanic', ['mechanic', 'mechanics', 'garage', 'auto', 'motor', 'tire', 'carsupply', 'carparts', 'engine', 'carpart']),
    ('Tools / Hardware', ['tool', 'tools', 'toolstore', 'hardware', 'carpentry', 'carpenter', 'construction', 'lumber', 'metalwork', 'welding', 'plumbing', 'electrician', 'electrical', 'forge', 'blacksmith', 'factory', 'workshop', 'industrial', 'masonry', 'mine', 'mining', 'janitor']),
    ('Farm / Garden', ['farm', 'farming', 'farmer', 'garden', 'gardening', 'seed', 'seeds', 'barn', 'agri', 'nursery', 'greenhouse', 'ranch', 'stable', 'animal', 'feed', 'orchard', 'seasonal']),
    ('Hunting / Camping', ['hunting', 'hunter', 'camp', 'camping', 'fishing', 'fish', 'fisherman', 'outdoors', 'trapper', 'trapping', 'survival', 'survivalist', 'cabin', 'ranger', 'bait', 'lodge']),
    ('Electronics / Media', ['electronic', 'electronics', 'electronicstore', 'radio', 'tv', 'computer', 'vhs', 'video', 'music', 'record', 'tech', 'arcade', 'movie', 'cinema', 'generator']),
    ('Clothing', ['clothing', 'clothes', 'clothingstore', 'wardrobe', 'dresser', 'laundry', 'uniform', 'tailor', 'fashion', 'shoe', 'shoes', 'boutique', 'sewing', 'salon']),
    ('Office / School', ['office', 'desk', 'school', 'classroom', 'bank', 'post', 'admin', 'court', 'lecture', 'daycare', 'university', 'teacher', 'filing', 'stationery']),
    ('Home', ['bedroom', 'livingroom', 'living', 'bathroom', 'house', 'home', 'closet', 'sidetable', 'kids', 'nightstand', 'attic', 'basement', 'bed', 'safehouse', 'medicine cabinet', 'hall', 'shelf', 'dresser', 'motel', 'hotel']),
    ('Bags / Bodies', ['inventory', 'outfit', 'bag', 'duffel', 'backpack', 'purse', 'body', 'briefcase', 'suitcase', 'lunchbox', 'cache', 'gunbox', 'stash', 'plankstash']),
    ('Trash', ['bin', 'bins', 'trash', 'garbage', 'dumpster', 'junk', 'clutter', 'recycling']),
]

def _words(s):
    s = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', s)
    return [w for w in re.split(r'[^A-Za-z]+', s.lower()) if w]

def groups_for(name, rooms=()):
    words = _words(name)
    gs = []
    for g, keys in GROUP_RULES:
        if any(w == k or (len(k) >= 4 and w.startswith(k)) for w in words for k in keys):
            gs.append(g)
    if not gs and rooms:
        hay = ' '.join(rooms)
        for g, keys in GROUP_RULES:
            if any(len(k) >= 4 and k in hay for k in keys):
                gs.append(g)
    return gs[:2] or ['Other']

# ---------------------------------------------------------------- mods
def pick_mod_media_dirs(moddir):
    """B42 layout: common/ + highest 42.x folder <= game version; legacy: root media."""
    subs = [d for d in os.listdir(moddir) if os.path.isdir(os.path.join(moddir, d))]
    vers = []
    for d in subs:
        m = re.fullmatch(r'(\d+)(?:\.(\d+))?(?:\.\d+)?', d)
        if m and int(m.group(1)) == 42:
            v = (42, int(m.group(2) or 0))
            if v <= GAME_VERSION: vers.append((v, d))
    dirs = []
    if vers or 'common' in subs:
        if 'common' in subs: dirs.append(os.path.join(moddir, 'common'))
        if vers: dirs.append(os.path.join(moddir, max(vers)[1]))
    else:
        dirs.append(moddir)
    return dirs

def read_modinfo(p):
    info = {}
    for line in open(p, encoding='utf-8', errors='replace'):
        if '=' in line:
            k, v = line.split('=', 1); info.setdefault(k.strip().lower(), v.strip())
    return info

def discover_mods():
    ini_path = os.path.join(RAW, 'server_mods.ini')
    if not os.path.exists(ini_path): return [], []  # vanilla-only build
    ini = open(ini_path).read()
    mods_m = re.search(r'^Mods=(.*)$', ini, re.M); ws_m = re.search(r'^WorkshopItems=(.*)$', ini, re.M)
    enabled = [m.strip().lstrip('\\') for m in (mods_m.group(1) if mods_m else '').split(';') if m.strip()]
    ws_ids = [w.strip() for w in (ws_m.group(1) if ws_m else '').split(';') if w.strip()]
    if not ws_ids and os.path.isdir(os.path.join(RAW, 'workshop')):
        ws_ids = sorted(os.listdir(os.path.join(RAW, 'workshop')))  # no WorkshopItems= line: look through everything copied
    found = {}
    for wid in ws_ids:
        base = os.path.join(RAW, 'workshop', wid, 'mods')
        if not os.path.isdir(base): continue
        for md in os.listdir(base):
            mdir = os.path.join(base, md)
            cands = [os.path.join(mdir, 'mod.info')] + [os.path.join(d, 'mod.info') for d in pick_mod_media_dirs(mdir)]
            info = None
            for c in cands:
                if os.path.isfile(c): info = read_modinfo(c); break
            if not info or 'id' not in info: continue
            mid = info['id'].lstrip('\\')
            if mid in found: continue
            found[mid] = {'id': mid, 'name': info.get('name', mid), 'workshop': wid, 'dirs': pick_mod_media_dirs(mdir)}
    mods = [found[m] for m in enabled if m in found]
    missing = [m for m in enabled if m not in found]
    return mods, missing

def friendly_mod_group(mod):
    n = (mod['name'] + ' ' + mod['id']).lower()
    if re.search(r'ki5|damnlib|^\d\d|trailer|camper|vehicle', mod['id'].lower()) or 'ki5' in n: return 'KI5 Vehicles'
    return mod['name']

# ---------------------------------------------------------------- skills / media codes
SKILL_NAMES = {
    'Carpentry': 'Carpentry', 'Woodwork': 'Carpentry', 'Cooking': 'Cooking', 'Farming': 'Agriculture', 'Doctor': 'First Aid',
    'Electricity': 'Electrical', 'Electrical': 'Electrical', 'MetalWelding': 'Welding', 'Mechanics': 'Mechanics', 'Tailoring': 'Tailoring',
    'Fishing': 'Fishing', 'Trapping': 'Trapping', 'PlantScavenging': 'Foraging', 'Foraging': 'Foraging', 'Husbandry': 'Animal Care',
    'Pottery': 'Pottery', 'Blacksmith': 'Blacksmithing', 'FlintKnapping': 'Knapping', 'Masonry': 'Masonry', 'Carving': 'Carving',
    'Butchering': 'Butchering', 'Glassmaking': 'Glassmaking', 'Tracking': 'Tracking', 'Maintenance': 'Maintenance', 'Aiming': 'Aiming', 'Reloading': 'Reloading', 'FirstAid': 'First Aid', 'LongBlade': 'Long Blade',
    'ShortBlade': 'Short Blade', 'SmallBlade': 'Short Blade', 'Blunt': 'Long Blunt', 'SmallBlunt': 'Short Blunt', 'Spear': 'Spear', 'Axe': 'Axe',
}
MEDIA_CODES = {
    'CRP': 'Carpentry', 'COO': 'Cooking', 'FRM': 'Agriculture', 'DOC': 'First Aid', 'ELC': 'Electrical', 'MTL': 'Welding',
    'MEC': 'Mechanics', 'TAI': 'Tailoring', 'FIS': 'Fishing', 'TRA': 'Trapping', 'FOR': 'Foraging', 'AIM': 'Aiming',
    'REL': 'Reloading', 'HUS': 'Animal Care', 'POT': 'Pottery', 'BLA': 'Blacksmithing', 'FKN': 'Knapping', 'SBA': 'Short Blunt',
    'LBA': 'Long Blade', 'SBL': 'Short Blade', 'BUA': 'Long Blunt', 'SPE': 'Spear', 'AXE': 'Axe', 'MAI': 'Maintenance',
    'SNE': 'Sneaking', 'NIM': 'Nimble', 'LFT': 'Lightfooted', 'SPR': 'Sprinting', 'MAS': 'Masonry', 'CAR': 'Carving', 'BUT': 'Butchering',
}
MOOD_CODES = {'BOR': 'Boredom', 'STS': 'Stress', 'FAT': 'Fatigue', 'PAN': 'Panic', 'UHP': 'Unhappiness', 'HUN': 'Hunger', 'THI': 'Thirst'}

# ---------------------------------------------------------------- main
def main():
    log = []
    items, recipes = {}, {}
    # vanilla scripts
    nfiles = 0
    for dp, _, fns in os.walk(os.path.join(MEDIA, 'scripts')):
        for fn in sorted(fns):
            if fn.endswith('.txt'):
                parse_script_file(os.path.join(dp, fn), 'vanilla', items, recipes); nfiles += 1
    log.append(f'vanilla script files parsed: {nfiles}')
    vanilla_ids = set(items)
    tr_dirs = [os.path.join(MEDIA, 'lua/shared/Translate/EN')]

    # mods
    mods, missing = discover_mods()
    log.append(f'enabled mods resolved: {len(mods)}; not found in workshop copy: {missing}')
    mod_meta = {}
    for mod in mods:
        mod_meta[mod['id']] = {'id': mod['id'], 'name': mod['name'], 'workshop': mod['workshop'], 'group': friendly_mod_group(mod), 'items': 0}
        for d in mod['dirs']:
            sdir = os.path.join(d, 'media', 'scripts')
            for dp, _, fns in os.walk(sdir):
                for fn in sorted(fns):
                    if fn.endswith('.txt'): parse_script_file(os.path.join(dp, fn), mod['id'], items, recipes)
            tr_dirs.append(os.path.join(d, 'media/lua/shared/Translate/EN'))

    names_tr, recipe_tr, ig_tr = load_translations(tr_dirs)

    # drop obsolete / hidden helper items
    for iid in list(items):
        p = items[iid]['props']
        if p.get('OBSOLETE', '').lower() == 'true' or p.get('Obsolete', '').lower() == 'true':
            del items[iid]

    # ------------- loot distributions (vanilla first, then mod lua on top)
    L = new_lua()
    itemdir = os.path.join(MEDIA, 'lua/server/Items')
    vdir = os.path.join(MEDIA, 'lua/server/Vehicles')
    order = sorted(f for f in os.listdir(itemdir) if f.startswith('Distribution_')) + ['ProceduralDistributions.lua', 'Distributions.lua']
    for f in order:
        ok, err = run_lua_file(L, os.path.join(itemdir, f))
        if not ok: log.append(f'lua error {f}: {err[:200]}')
    for f in sorted(os.listdir(vdir)):
        if 'Distribution' in f:
            ok, err = run_lua_file(L, os.path.join(vdir, f))
            if not ok: log.append(f'lua error {f}: {err[:200]}')
    mod_lua_ok = mod_lua_fail = 0
    mod_data_loot = []
    for mod in mods:
        for d in mod['dirs']:
            sdir = os.path.join(d, 'media/lua/server')
            for dp, _, fns in os.walk(sdir):
                for fn in sorted(fns):
                    if not fn.endswith('.lua'): continue
                    p = os.path.join(dp, fn)
                    try:
                        txt = open(p, encoding='utf-8', errors='replace').read()
                    except OSError: continue
                    if not (re.search(r'Distributions|ProceduralDistributions|VehicleDistributions', txt) or (re.match(r'\s*return\s*\{', txt) and re.search(r'list\s*=', txt))): continue
                    ok, err = run_lua_file(L, p)
                    ret = run_lua_file.last_return
                    if ok and lupa_rt.lua_type(ret) == 'table':
                        # data-style loot files, e.g. Gael's: return { {list=, item=, weight=}, ... }
                        for k in range(1, len(ret) + 1):
                            e = ret[k]
                            if lupa_rt.lua_type(e) == 'table' and e['list'] and e['item'] and isinstance(e['weight'], (int, float)):
                                mod_data_loot.append((str(e['list']), str(e['item']), float(e['weight'])))
                    if ok: mod_lua_ok += 1
                    else: mod_lua_fail += 1
    # run deferred distribution-merge hooks
    L.execute('''
    debug.sethook(function() error("budget") end, "", 50000000)
    for _, ev in ipairs(__deferred) do
      local n = ev[1]
      if n == "OnPreDistributionMerge" or n == "OnDistributionMerge" or n == "OnPostDistributionMerge" or n == "OnInitGlobalModData" or n == "OnGameBoot" or n == "OnLoadedTileDefinitions" then
        pcall(ev[2])
      end
    end
    debug.sethook()''')
    log.append(f'mod distribution lua files run ok={mod_lua_ok} failed={mod_lua_fail}')
    G = L.globals()

    def norm(n):
        return n if '.' in n else 'Base.' + n

    lists = {}  # list name -> {'rooms': set, 'items': {id: weight}}
    def add_list(name, entries, rooms=None, kind='proc'):
        rec = lists.setdefault(name, {'rooms': set(), 'items': {}, 'kind': kind})
        if rooms: rec['rooms'].update(rooms)
        for n, w in entries:
            iid = norm(n)
            rec['items'][iid] = max(rec['items'].get(iid, 0), w)

    PD = G.ProceduralDistributions
    if PD and lupa_rt.lua_type(PD.list) == 'table':
        for name, t in PD.list.items():
            if lupa_rt.lua_type(t) != 'table': continue
            entries = lua_list_pairs(t['items'])
            j = t['junk']
            if lupa_rt.lua_type(j) == 'table': entries += lua_list_pairs(j['items'])
            add_list(str(name), entries)
    for lname, iid, w in mod_data_loot:
        add_list(lname, [(iid, w)])
    log.append(f'mod data-table loot entries: {len(mod_data_loot)}')
    # rooms -> containers -> procList / direct items
    D = G.Distributions
    dist_tables = []
    if lupa_rt.lua_type(D) == 'table':
        for i in range(1, len(D) + 1):
            if lupa_rt.lua_type(D[i]) == 'table': dist_tables.append(D[i])
    for dt in dist_tables:
        for room, rt in dt.items():
            if lupa_rt.lua_type(rt) != 'table': continue
            room = str(room)
            for cont, ct in rt.items():
                if lupa_rt.lua_type(ct) != 'table': continue
                pl = ct['procList']
                if lupa_rt.lua_type(pl) == 'table':
                    for k in range(1, len(pl) + 1):
                        e = pl[k]
                        if lupa_rt.lua_type(e) == 'table' and e['name']:
                            lists.setdefault(str(e['name']), {'rooms': set(), 'items': {}, 'kind': 'proc'})['rooms'].add(room)
                entries = lua_list_pairs(ct['items'])
                if lupa_rt.lua_type(ct['junk']) == 'table': entries += lua_list_pairs(ct['junk']['items'])
                if entries:
                    add_list(f'{room}/{cont}', entries, {room}, 'room')
    VD = G.VehicleDistributions
    if lupa_rt.lua_type(VD) == 'table':
        for name, t in VD.items():
            if lupa_rt.lua_type(t) != 'table': continue
            entries = lua_list_pairs(t['items'])
            if lupa_rt.lua_type(t['junk']) == 'table': entries += lua_list_pairs(t['junk']['items'])
            if entries: add_list('Vehicle:' + str(name), entries, kind='vehicle')
    CT = G.ClutterTables
    if lupa_rt.lua_type(CT) == 'table':
        for name, t in CT.items():
            entries = lua_list_pairs(t)
            if entries: add_list('Clutter:' + str(name), entries, kind='clutter')
    log.append(f'loot lists: {len(lists)} (with items: {sum(1 for v in lists.values() if v["items"])})')

    # list index for output
    list_names = sorted(k for k, v in lists.items() if v['items'])
    list_idx = {n: i for i, n in enumerate(list_names)}
    list_out = []
    for n in list_names:
        rec = lists[n]
        rooms = sorted(rec['rooms'])
        list_out.append({'n': n, 'g': groups_for(n, rooms), 'r': rooms[:12], 'k': rec['kind'], 'c': len(rec['items'])})
    spawns = collections.defaultdict(list)
    for n in list_names:
        for iid, w in lists[n]['items'].items():
            spawns[iid].append((list_idx[n], w))

    # ------------- recorded media
    Lm = new_lua()
    ok, err = run_lua_file(Lm, os.path.join(MEDIA, 'lua/shared/RecordedMedia/recorded_media.lua'))
    media_out = []
    if ok:
        RM = Lm.globals().RecMedia
        for uuid, v in RM.items():
            gains = collections.Counter(); moods = collections.Counter(); recipes_taught = []
            lines = v['lines']
            n_lines = 0
            if lupa_rt.lua_type(lines) == 'table':
                for i in range(1, len(lines) + 1):
                    l = lines[i]; n_lines += 1
                    codes = l['codes'] if lupa_rt.lua_type(l) == 'table' else None
                    if not codes: continue
                    for c in str(codes).split(','):
                        c = c.strip()
                        m = re.match(r'([A-Z]{3})([+-=])(.*)', c)
                        if not m: continue
                        code, op, val = m.groups()
                        if code == 'RCP': recipes_taught.append(val); continue
                        try: num = float(val)
                        except ValueError: continue
                        if op == '-': num = -num
                        if code in MEDIA_CODES: gains[MEDIA_CODES[code]] += num
                        else: moods[MOOD_CODES.get(code, code)] += num
            cat = str(v['category'])
            title = ig_tr.get(str(v['itemDisplayName']), '') or ig_tr.get(str(v['title']), '') or str(uuid)
            media_out.append({
                'id': 'Media.' + str(uuid), 'uuid': str(uuid), 'cat': cat, 'name': title,
                'title': ig_tr.get(str(v['title'] or ''), ''), 'author': ig_tr.get(str(v['author'] or ''), ''),
                'extra': ig_tr.get(str(v['extra'] or ''), ''), 'spawning': v['spawning'],
                'skills': {k: round(x, 2) for k, x in gains.items()}, 'moods': {k: round(x, 2) for k, x in moods.items()},
                'recipes': [recipe_tr.get(r, r) for r in recipes_taught], 'lines': n_lines,
            })
        log.append(f'recorded media entries: {len(media_out)}')
    else:
        log.append(f'recorded media failed: {err}')

    # ------------- tags index, recipe usage
    tag_items = collections.defaultdict(set)
    for iid, it in items.items():
        for t in it['props'].get('Tags', '').split(';'):
            t = t.strip().lower()
            if t:
                tag_items[t].add(iid)
                if ':' not in t: tag_items['base:' + t].add(iid)
                else: tag_items[t.split(':', 1)[1]].add(iid)

    def resolve(n, module):
        if '.' in n: return n
        for cand in (f'{module}.{n}', f'Base.{n}'):
            if cand in items: return cand
        return f'Base.{n}'

    used_in = collections.defaultdict(set); made_by = collections.defaultdict(set)
    recipe_out = {}
    for rid, r in recipes.items():
        rname = recipe_tr.get(r['id'], '') or re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', r['id'])
        recipe_out[rid] = rname
        for inp in r['inputs']:
            for n in inp['items']:
                used_in[resolve(n, r['module'])].add(rid)
            for t in inp['tags']:
                for iid in tag_items.get(t, ()):
                    used_in[iid].add(rid)
        for n in r['outputs']:
            made_by[resolve(n, r['module'])].add(rid)

    # learned-recipe display names
    def recipe_label(x):
        x = x.strip()
        return recipe_tr.get(x, '') or recipe_tr.get(x.split(':', 1)[-1], '') or x.split(':', 1)[-1]

    # ------------- icons for modded items
    icon_dir = os.path.join(ROOT, 'assets', 'icons', 'mod')
    shutil.rmtree(icon_dir, ignore_errors=True); os.makedirs(icon_dir)
    mod_icon_files = {}
    for mod in mods:
        for d in mod['dirs']:
            tdir = os.path.join(d, 'media', 'textures')
            for dp, _, fns in os.walk(tdir):
                for fn in fns:
                    if fn.lower().startswith('item_') and fn.lower().endswith('.png'):
                        mod_icon_files.setdefault(fn[5:-4].lower(), os.path.join(dp, fn))
    vanilla_icon_dir = os.path.join(ROOT, 'assets', 'icons', 'vanilla')
    vanilla_icons = {}  # lowercase icon name -> real filename (filesystems differ in case sensitivity)
    if os.path.isdir(vanilla_icon_dir):  # filled by build/extract_icons.py
        vanilla_icons = {f[5:-4].lower(): f for f in os.listdir(vanilla_icon_dir) if f.lower().startswith('item_') and f.lower().endswith('.png')}

    # ------------- assemble items
    out_items = []
    skip_cats = {'Hidden', 'Corpse', 'MaleBody', 'ZedDmg', 'Wound'}
    used_lists = set()
    copied_icons = 0
    for iid in sorted(items):
        it = items[iid]; p = it['props']
        cat = p.get('DisplayCategory', '') or 'Uncategorized'
        if cat in skip_cats: continue
        itype = (p.get('ItemType', '') or p.get('Type', '')).replace('base:', '').lower() or 'normal'
        name = names_tr.get(iid) or names_tr.get(it['name']) or p.get('DisplayName', '') or re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', it['name'])
        tags = [t.strip() for t in p.get('Tags', '').split(';') if t.strip()]
        try: weight = float(p.get('Weight', '1'))
        except ValueError: weight = None
        rec = {'id': iid, 'n': name, 'c': cat, 't': itype, 'w': weight}
        if tags: rec['tg'] = tags
        if it['src'] != 'vanilla': rec['m'] = it['src']; mod_meta[it['src']]['items'] += 1
        if it.get('ov'): rec['ov'] = sorted(set(it['ov']))
        sk = p.get('SkillTrained')
        if sk:
            rec['sk'] = SKILL_NAMES.get(sk, sk)
            try:
                lvl = int(p.get('LvlSkillTrained', '1')); nl = int(p.get('NumLevelsTrained', '2'))
                rec['lv'] = [lvl, lvl + nl - 1]; rec['vol'] = (lvl + 1) // 2 if nl == 2 else None
            except ValueError: pass
            if p.get('NumberOfPages'): rec['pg'] = p.get('NumberOfPages')
        lr = p.get('LearnedRecipes') or p.get('TeachedRecipes')
        if lr: rec['rc'] = [recipe_label(x) for x in lr.split(';') if x.strip()]
        # B42 clothing/bags often have no Icon, only IconsForTexture = A;B;C (one per texture variant)
        icon = p.get('Icon', '') or p.get('IconsForTexture', '').split(';')[0].strip()
        if icon:
            rec['ic'] = icon
            ikey = icon.lower()
            # mod items, and vanilla items a mod re-skins (it['ov']), prefer the mod's icon
            if (it['src'] != 'vanilla' or it.get('ov')) and ikey in mod_icon_files:
                dst = os.path.join(icon_dir, 'Item_' + icon + '.png')
                if not os.path.exists(dst): shutil.copyfile(mod_icon_files[ikey], dst); copied_icons += 1
                rec['img'] = 'mod/Item_' + icon + '.png'
            # vanilla icons are resolved in the browser from assets/icons/vanilla/icons.js (see extract_icons.py),
            # so data/items.js is the same whether or not you have extracted them
        stats = {}
        for k in ('MaxDamage', 'MinDamage', 'MaxRange', 'MaxAmmo', 'AmmoType', 'ConditionMax', 'Capacity', 'WeightReduction',
                  'HungerChange', 'Calories', 'DaysFresh', 'DaysTotallyRotten', 'UseDelta', 'FireMode', 'BulletDefense', 'BiteDefense',
                  'ScratchDefense', 'Insulation', 'WindResistance', 'RunSpeedModifier', 'BodyLocation', 'CanBeEquipped', 'MetalValue',
                  'BoredomChange', 'StressChange', 'UnhappyChange', 'NumberOfPages', 'MediaCategory', 'Map', 'BloodLocation'):
            if k in p and p[k] != '': stats[k] = p[k]
        if stats: rec['st'] = stats
        sp = sorted(spawns.get(iid, []), key=lambda x: -x[1])
        if sp:
            rec['sp'] = [[i, round(w, 3)] for i, w in sp[:TOP_N]]
            gscore = collections.Counter()
            for i, w in sp:
                for g in list_out[i]['g']: gscore[g] += w
            tot = sum(gscore.values()) or 1
            rec['lg'] = [g for g, v in gscore.most_common(4) if v / tot >= 0.08 and g not in ('Other',)] or [gscore.most_common(1)[0][0]]
            rec['spn'] = len(sp)
            for i, _ in sp[:TOP_N]: used_lists.add(i)
        ui = sorted(used_in.get(iid, ()), key=lambda r: (recipes[r]['src'] != 'vanilla', recipe_out[r]))
        if ui: rec['ui'] = [recipe_out[r] for r in ui[:40]]; rec['uin'] = len(ui)
        mb = sorted(made_by.get(iid, ()), key=lambda r: (recipes[r]['src'] != 'vanilla', recipe_out[r]))
        if mb: rec['mb'] = [recipe_out[r] for r in mb[:15]]
        out_items.append(rec)

    # ------------- collections
    def is_seed_packet(r): return 'BagSeed' in r['id'] and not r['id'].endswith('_Empty') and r.get('rc')
    for r in out_items:
        col = None
        if r.get('sk') and r['c'] == 'SkillBook': col = 'skillbooks'
        elif is_seed_packet(r): col = 'seeds'
        elif r['c'] == 'RecipeResource' and r.get('rc') and not r['id'].endswith('_Empty'): col = 'magazines'
        elif r['t'] == 'map': col = 'maps'
        elif r['c'] == 'Literature': col = 'literature'
        elif r['c'] == 'Memento': col = 'mementos'
        elif r['t'] == 'weapon' and r.get('st', {}).get('AmmoType'): col = 'firearms'
        if col: r['col'] = col
    for mo in media_out:
        if mo['cat'] == 'Retail-VHS': mo['col'] = 'vhs_skill' if mo['skills'] else 'vhs_retail'
        elif mo['cat'] == 'Home-VHS': mo['col'] = 'vhs_home'
        elif mo['cat'] == 'CDs': mo['col'] = 'cds'
    # spawn info for media carriers
    carriers = {'Retail-VHS': 'Base.VHS_Retail', 'Home-VHS': 'Base.VHS_Home', 'CDs': 'Base.Disc_Retail'}
    carrier_spawns = {}
    for cat, cid in carriers.items():
        sp = sorted(spawns.get(cid, []), key=lambda x: -x[1])
        carrier_spawns[cat] = [[i, round(w, 3)] for i, w in sp[:TOP_N]]
        for i, _ in sp[:TOP_N]: used_lists.add(i)

    data = {
        'meta': {'game': 'Project Zomboid', 'version': GAME_VERSION_STR, 'steamBuild': SOURCE.get('steamBuild'),
                 'generated': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'), 'source': SOURCE.get('label', 'game files'),
                 'topN': TOP_N, 'log': log},
        'mods': sorted(mod_meta.values(), key=lambda m: -m['items']),
        'lists': list_out,
        'items': out_items,
        'media': media_out,
        'carrierSpawns': carrier_spawns,
    }
    os.makedirs(os.path.join(ROOT, 'data'), exist_ok=True)
    js = 'window.PZDATA = ' + json.dumps(data, separators=(',', ':'), ensure_ascii=False) + ';\n'
    open(os.path.join(ROOT, 'data', 'items.js'), 'w', encoding='utf-8').write(js)
    # summary
    van = [r for r in out_items if 'm' not in r]; mod = [r for r in out_items if 'm' in r]
    cc = collections.Counter(r.get('col') for r in van if r.get('col'))
    mc = collections.Counter(m['col'] for m in media_out)
    summary = {'vanilla_items': len(van), 'modded_items': len(mod), 'collections_vanilla': dict(cc), 'media': dict(mc),
               'vanilla_with_spawns': sum(1 for r in van if r.get('sp')), 'mod_with_spawns': sum(1 for r in mod if r.get('sp')),
               'items_with_icon': sum(1 for r in out_items if r.get('img') or (r.get('ic') or '').lower() in vanilla_icons), 'mod_icons_copied': copied_icons,
               'recipes': len(recipes), 'size_kb': len(js) // 1024}
    log.append('summary: ' + json.dumps(summary))
    print('\n'.join(log))
    json.dump(summary, open(os.path.join(HERE, 'last_build_summary.json'), 'w'), indent=2)

if __name__ == '__main__':
    main()
