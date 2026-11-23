/* PZ Item Tracker - vanilla JS, no build step. Data: window.PZDATA from data/items.js */
(function () {
  'use strict';
  const D = window.PZDATA;
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const STORE_KEY = 'pzItemTracker.v1';
  const PAGE = 60;

  // ------------------------------------------------------------------ storage (localStorage with safe fallback)
  let storageOK = true;
  function loadState() {
    try {
      const raw = window.localStorage.getItem(STORE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (e) { storageOK = false; return null; }
  }
  const blank = () => ({ v: 1, items: {}, skills: {}, day: 1, runName: '', notes: '', ui: {} });
  let S = Object.assign(blank(), loadState() || {});
  let saveTimer = null;
  function save() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      try { window.localStorage.setItem(STORE_KEY, JSON.stringify(S)); }
      catch (e) { storageOK = false; $('#storage-warning').classList.remove('hidden'); }
    }, 150);
  }
  const st = (id) => S.items[id] || {};
  function setFlag(id, flag, val) {
    const cur = Object.assign({}, S.items[id] || {});
    if (val) cur[flag] = typeof val === 'string' ? val : 1; else delete cur[flag];
    if (Object.keys(cur).length) S.items[id] = cur; else delete S.items[id];
    save();
  }

  // ------------------------------------------------------------------ data prep
  const lists = D.lists;
  const modsById = Object.fromEntries(D.mods.map((m) => [m.id, m]));
  const MEDIA_CAT = { 'Retail-VHS': 'Retail VHS', 'Home-VHS': 'Home VHS', 'CDs': 'Music CD' };
  const RARITY = ['Common', 'Uncommon', 'Rare'];
  function groupsFromSpawns(sp) {
    const score = {}; let tot = 0;
    (sp || []).forEach(([i, w]) => lists[i].g.forEach((g) => { score[g] = (score[g] || 0) + w; tot += w; }));
    return Object.entries(score).sort((a, b) => b[1] - a[1]).filter(([g, v]) => v / (tot || 1) >= 0.08 && g !== 'Other').slice(0, 4).map(([g]) => g);
  }
  const mediaItems = D.media.map((m) => {
    const sp = D.carrierSpawns[m.cat] || [];
    return { id: m.id, n: m.name, c: MEDIA_CAT[m.cat] || m.cat, t: 'media', w: m.cat === 'CDs' ? 0.3 : 0.5, col: m.col, media: m,
      sp, lg: groupsFromSpawns(sp), spn: sp.length, sk: Object.keys(m.skills)[0] };
  });
  const ALL = D.items.concat(mediaItems);
  const BYID = new Map(ALL.map((it) => [it.id, it]));
  ALL.forEach((it) => {
    it.hay = [it.n, it.id, it.c, (it.tg || []).join(' '), (it.rc || []).join(' '), it.sk || '', it.m ? (modsById[it.m] || {}).name : '',
      it.media ? [it.media.author, it.media.title, Object.keys(it.media.skills).join(' ')].join(' ') : ''].join(' ').toLowerCase();
    it.wsum = (it.sp || []).reduce((a, [, w]) => a + w, 0);
  });
  const isReadable = (it) => it.t === 'literature' || it.t === 'media' || it.col === 'skillbooks' || it.col === 'magazines';
  const pretty = (s) => String(s).replace(/^Vehicle:/, 'Vehicle: ').replace(/^Clutter:/, 'Clutter: ').replace(/_/g, ' ')
    .replace(/([a-z])([A-Z])/g, '$1 $2').replace(/\//g, ' / ');

  const COLLECTIONS = [
    { key: 'skillbooks', name: 'Skill Books', icon: 'book', matrix: true, read: 'READ' },
    { key: 'magazines', name: 'Recipe Magazines', icon: 'mag', read: 'READ' },
    { key: 'vhs_skill', name: 'Skill VHS Tapes', icon: 'vhs', read: 'WATCHED' },
    { key: 'vhs_retail', name: 'Movie & TV VHS', icon: 'vhs', read: 'WATCHED' },
    { key: 'vhs_home', name: 'Home VHS', icon: 'vhs', read: 'WATCHED' },
    { key: 'cds', name: 'Music CDs', icon: 'cd', read: 'PLAYED' },
    { key: 'seeds', name: 'Seed Packets', icon: 'seed', read: 'READ' },
    { key: 'maps', name: 'Maps', icon: 'map', read: 'READ' },
    { key: 'literature', name: 'Leisure Reading', icon: 'book', read: 'READ' },
    { key: 'mementos', name: 'Mementos', icon: 'photo' },
    { key: 'firearms', name: 'Firearms', icon: 'gun' },
  ];
  const COLBYKEY = Object.fromEntries(COLLECTIONS.map((c) => [c.key, c]));
  const readLabel = (it) => (COLBYKEY[it.col] && COLBYKEY[it.col].read) || (it.t === 'media' ? 'WATCHED' : 'READ');

  // ------------------------------------------------------------------ shared renderers
  // Vanilla icons are not shipped (game art). build/extract_icons.py writes assets/icons/vanilla/icons.js,
  // which defines window.PZ_VANILLA_ICONS = { lowercased Icon name: "Item_X.png" }. Without it: category glyphs.
  const VICONS = window.PZ_VANILLA_ICONS || {};
  function iconSrc(it) {
    if (it.img) return it.img;
    const f = it.ic && VICONS[it.ic.toLowerCase()];
    return f ? 'vanilla/' + f : '';
  }
  function iconHTML(it, big) {
    const src = iconSrc(it);
    const kind = window.PZGlyph.kindFor(it);
    // if an icon file is missing, swap in the category glyph instead of showing a broken image
    if (src) return `<img src="assets/icons/${esc(src)}" alt="" loading="lazy" width="${big ? 64 : 32}" height="${big ? 64 : 32}" onerror="this.outerHTML=window.PZGlyph.svg('${esc(kind)}')">`;
    return window.PZGlyph.svg(kind);
  }
  function actionButtons(it) {
    const s = st(it.id);
    let h = `<button class="px-btn tiny ${s.h ? 'on-have' : ''}" data-act="h" data-id="${esc(it.id)}" title="Have it">${s.h ? '&#10003; HAVE' : 'HAVE'}</button>`;
    if (isReadable(it)) h += `<button class="px-btn tiny ${s.r ? 'on-read' : ''}" data-act="r" data-id="${esc(it.id)}" title="${readLabel(it)}">${s.r ? '&#10003; ' : ''}${readLabel(it)}</button>`;
    h += `<button class="px-btn tiny ${s.w ? 'on-want' : ''}" data-act="w" data-id="${esc(it.id)}" title="Add to wishlist">${s.w ? '&#9733;' : '&#9734;'} WANT</button>`;
    return h;
  }
  function rowHTML(it) {
    const s = st(it.id);
    const sub = [];
    if (it.sk && it.lv) sub.push(`${it.sk} Lv ${it.lv[0]}-${it.lv[1]}`);
    else if (it.media && Object.keys(it.media.skills).length) sub.push(Object.entries(it.media.skills).map(([k, v]) => `${k} +${v}`).join(', '));
    if (it.rc && !it.sk) sub.push(`Teaches ${it.rc.length} recipe${it.rc.length > 1 ? 's' : ''}`);
    if (s.s) sub.push(`<span class="stashflag">&#9873; ${esc(s.s)}</span>`);
    const mod = it.m ? `<span class="modflag" title="${esc((modsById[it.m] || {}).name || it.m)}">MOD</span>` : '';
    return `<div class="row ${s.h ? 'is-have' : ''}" data-open="${esc(it.id)}">
      <div class="icon">${iconHTML(it)}</div>
      <div class="nm">${esc(it.n)}${mod}<small>${sub.join(' &middot; ') || esc(it.id)}</small></div>
      <div class="ct">${esc(pretty(it.c))}</div>
      <div class="wt">${it.w != null ? it.w : ''}</div>
      <div class="tagchips">${(it.lg || []).map((g) => `<span class="loc">${esc(g)}</span>`).join('')}</div>
      <div class="acts">${actionButtons(it)}</div></div>`;
  }
  function bar(pct, label, cls) {
    return `<div class="bar ${cls || ''}"><div class="bar-fill" style="width:${Math.round(pct * 100)}%"></div><span class="bar-label">${esc(label)}</span></div>`;
  }

  // delegated clicks for status buttons + opening details
  document.addEventListener('click', (e) => {
    const act = e.target.closest('[data-act]');
    if (act) {
      e.stopPropagation();
      const id = act.dataset.id, f = act.dataset.act;
      setFlag(id, f, !st(id)[f]);
      refreshAfterChange(id);
      return;
    }
    const op = e.target.closest('[data-open]');
    if (op) openDetail(op.dataset.open);
  });
  function refreshAfterChange(id) {
    renderHUD();
    $$(`[data-open="${CSS.escape(id)}"]`).forEach((row) => {
      const it = BYID.get(id);
      if (row.classList.contains('row')) row.outerHTML = rowHTML(it);
    });
    if (currentTab === 'collections') renderCollections(true);
    if (currentTab === 'loot') renderLoot();
    if (currentTab === 'skills') renderSkills();
    if (!$('#detail').classList.contains('hidden') && detailId === id) openDetail(id);
  }

  // ------------------------------------------------------------------ HUD
  function collectionItems(key, withMods) {
    return ALL.filter((it) => it.col === key && (withMods || !it.m));
  }
  function renderHUD() {
    $('#hud-build').textContent = `${D.meta.version}`;
    $('#hud-day').textContent = S.day || 1;
    const all = ALL.filter((it) => it.col && !it.m);
    const have = all.filter((it) => st(it.id).h).length;
    $('#hud-found').textContent = Object.values(S.items).filter((x) => x.h).length;
    $('#hud-want').textContent = Object.values(S.items).filter((x) => x.w).length;
    const pct = all.length ? have / all.length : 0;
    $('#overall-fill').style.width = (pct * 100).toFixed(1) + '%';
    $('#overall-text').textContent = `VANILLA COLLECTIONS ${have} / ${all.length}  (${(pct * 100).toFixed(1)}%)`;
  }
  $('#day-inc').onclick = () => { S.day = (S.day || 1) + 1; save(); renderHUD(); };
  $('#day-dec').onclick = () => { S.day = Math.max(1, (S.day || 1) - 1); save(); renderHUD(); };

  // ------------------------------------------------------------------ tabs
  let currentTab = 'collections';
  function showTab(name) {
    currentTab = name;
    $$('.tab').forEach((b) => b.classList.toggle('active', b.dataset.tab === name));
    $$('.tab-panel').forEach((p) => p.classList.toggle('active', p.id === 'tab-' + name));
    S.ui.tab = name; save();
    if (name === 'collections') renderCollections();
    if (name === 'items') renderItems();
    if (name === 'loot') renderLoot();
    if (name === 'skills') renderSkills();
    if (name === 'save') renderSave();
  }
  $$('.tab').forEach((b) => b.addEventListener('click', () => showTab(b.dataset.tab)));

  // ------------------------------------------------------------------ collections
  let activeCol = S.ui.col || 'skillbooks';
  $('#col-mods').checked = !!S.ui.colMods;
  $('#col-mods').addEventListener('change', (e) => { S.ui.colMods = e.target.checked; save(); renderCollections(); });
  function renderCollections(keepScroll) {
    const withMods = !!S.ui.colMods;
    $('#collection-cards').innerHTML = COLLECTIONS.map((c) => {
      const its = collectionItems(c.key, withMods);
      if (!its.length) return '';
      const have = its.filter((it) => st(it.id).h).length;
      const read = its.filter((it) => st(it.id).r).length;
      return `<div class="card ${activeCol === c.key ? 'active' : ''}" data-col="${c.key}" tabindex="0" role="button">
        <div class="card-title">${window.PZGlyph.svg(c.icon)} ${esc(c.name.toUpperCase())}</div>
        ${bar(its.length ? have / its.length : 0, `${have}/${its.length}`)}
        ${c.read ? bar(its.length ? read / its.length : 0, `${c.read} ${read}`, 'cyan') : ''}
      </div>`;
    }).join('');
    $$('#collection-cards .card').forEach((el) => {
      const go = () => { activeCol = el.dataset.col; S.ui.col = activeCol; save(); renderCollections(); };
      el.addEventListener('click', go);
      el.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } });
    });
    const c = COLBYKEY[activeCol];
    const its = collectionItems(activeCol, withMods);
    const y = window.scrollY;
    $('#collection-view').innerHTML = c.matrix ? matrixHTML(its) : listCollectionHTML(c, its);
    if (c.matrix) bindMatrix();
    if (keepScroll) window.scrollTo(0, y);
  }
  function matrixHTML(its) {
    const bySkill = {};
    its.forEach((it) => { (bySkill[it.sk] = bySkill[it.sk] || {})[it.vol || 0] = it; });
    const skills = Object.keys(bySkill).sort();
    let h = `<div class="panel"><h2>SKILL BOOKS &mdash; ${skills.length} SKILLS &times; 5 VOLUMES</h2>
      <p class="hint">Click a cell to cycle: empty &rarr; HAVE &rarr; HAVE + READ &rarr; READ only &rarr; empty. Right-click (or long-press) for details, spawn spots and wishlist.</p>
      <div class="legend"><span><i style="background:#0a0a14;box-shadow:0 0 0 2px #2f2f5c"></i>missing</span><span><i style="background:#0f5a12"></i>have</span><span><i style="background:#0e4560"></i>read</span><span style="color:#ff2fd0">&#9733; wishlist</span></div>
      <table class="matrix"><thead><tr><th>SKILL</th>${[1, 2, 3, 4, 5].map((v) => `<th>VOL ${v}</th>`).join('')}<th></th></tr></thead><tbody>`;
    skills.forEach((sk) => {
      const row = bySkill[sk]; let haveN = 0;
      h += `<tr><td class="skillname">${esc(sk)}</td>`;
      [1, 2, 3, 4, 5].forEach((v) => {
        const it = row[v];
        if (!it) { h += '<td></td>'; return; }
        const s = st(it.id); if (s.h) haveN++;
        const label = s.h && s.r ? 'HAVE+READ' : s.h ? 'HAVE' : s.r ? 'READ' : `LV${it.lv[0]}-${it.lv[1]}`;
        h += `<td><button class="cell ${s.h ? 'have' : ''} ${s.r && !s.h ? 'read' : ''} ${s.w ? 'want' : ''}" data-cell="${esc(it.id)}" title="${esc(it.n)}">${label}</button></td>`;
      });
      h += `<td style="width:120px">${bar(haveN / 5, haveN + '/5')}</td></tr>`;
    });
    return h + '</tbody></table></div>';
  }
  function bindMatrix() {
    $$('[data-cell]').forEach((b) => {
      b.addEventListener('click', () => {
        const id = b.dataset.cell, s = st(id);
        // cycle: none -> have -> have+read -> read -> none
        if (!s.h && !s.r) { setFlag(id, 'h', 1); }
        else if (s.h && !s.r) { setFlag(id, 'r', 1); }
        else if (s.h && s.r) { setFlag(id, 'h', 0); }
        else { setFlag(id, 'r', 0); }
        renderHUD(); renderCollections(true);
      });
      b.addEventListener('contextmenu', (e) => { e.preventDefault(); openDetail(b.dataset.cell); });
      let t; b.addEventListener('touchstart', () => { t = setTimeout(() => openDetail(b.dataset.cell), 600); }, { passive: true });
      b.addEventListener('touchend', () => clearTimeout(t));
    });
  }
  function listCollectionHTML(c, its) {
    const sorted = its.slice().sort((a, b) => a.n.localeCompare(b.n));
    const have = its.filter((it) => st(it.id).h).length;
    let extra = '';
    if (c.key.startsWith('vhs') || c.key === 'cds') extra = '<p class="hint">Tapes and CDs all spawn as the same carrier item (VHS / CD), so the spawn spots shown are for that carrier. Rarity tier comes from the game&#39;s recorded-media data.</p>';
    return `<div class="panel"><h2>${esc(c.name.toUpperCase())} &mdash; ${have} / ${its.length}</h2>${extra}
      <div class="toolbar"><button class="px-btn tiny" id="col-want-missing">&#9733; WISHLIST ALL MISSING</button></div>
      <div class="item-list">${sorted.map(rowHTML).join('')}</div></div>`;
  }
  document.addEventListener('click', (e) => {
    if (e.target.id === 'col-want-missing') {
      collectionItems(activeCol, !!S.ui.colMods).forEach((it) => { if (!st(it.id).h) setFlag(it.id, 'w', 1); });
      renderHUD(); renderCollections(true);
    }
  });

  // ------------------------------------------------------------------ all items
  const F = Object.assign({ q: '', cat: '', loc: '', skill: '', col: '', status: '', src: 'all', mod: '', wmax: '', sort: 'name', spawnonly: false, page: 0 }, S.ui.filters || {});
  function fillSelect(sel, values, fmt) {
    const el = $(sel);
    values.forEach((v) => { const o = document.createElement('option'); o.value = v; o.textContent = fmt ? fmt(v) : v; el.appendChild(o); });
  }
  fillSelect('#f-cat', [...new Set(ALL.map((it) => it.c))].sort(), (v) => pretty(v).toUpperCase());
  fillSelect('#f-loc', [...new Set(lists.flatMap((l) => l.g))].sort(), (v) => v.toUpperCase());
  fillSelect('#f-skill', [...new Set(ALL.map((it) => it.sk).filter(Boolean))].sort(), (v) => v.toUpperCase());
  fillSelect('#f-col', COLLECTIONS.map((c) => c.key), (v) => COLBYKEY[v].name.toUpperCase());
  fillSelect('#f-mod', D.mods.filter((m) => m.items > 0).map((m) => m.id), (v) => `${modsById[v].name} (${modsById[v].items})`.toUpperCase());
  const bindings = { q: '#f-search', cat: '#f-cat', loc: '#f-loc', skill: '#f-skill', col: '#f-col', status: '#f-status', src: '#f-src', mod: '#f-mod', wmax: '#f-wmax', sort: '#f-sort' };
  Object.entries(bindings).forEach(([k, sel]) => {
    const el = $(sel); el.value = F[k];
    el.addEventListener(sel === '#f-search' || sel === '#f-wmax' ? 'input' : 'change', () => { F[k] = el.value; F.page = 0; persistFilters(); renderItems(); });
  });
  $('#f-spawnonly').checked = F.spawnonly;
  $('#f-spawnonly').addEventListener('change', (e) => { F.spawnonly = e.target.checked; F.page = 0; persistFilters(); renderItems(); });
  $('#pg-prev').onclick = () => { F.page = Math.max(0, F.page - 1); renderItems(); window.scrollTo(0, $('#tab-items').offsetTop); };
  $('#pg-next').onclick = () => { F.page++; renderItems(); window.scrollTo(0, $('#tab-items').offsetTop); };
  function persistFilters() { S.ui.filters = Object.assign({}, F, { page: 0 }); save(); }
  function filtered() {
    const terms = F.q.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const wmax = F.wmax === '' ? null : parseFloat(F.wmax);
    let out = ALL.filter((it) => {
      if (F.src === 'vanilla' && it.m) return false;
      if (F.src === 'mod' && !it.m) return false;
      if (F.mod && it.m !== F.mod) return false;
      if (F.cat && it.c !== F.cat) return false;
      if (F.loc && !(it.lg || []).includes(F.loc)) return false;
      if (F.skill && it.sk !== F.skill && !(it.media && it.media.skills[F.skill])) return false;
      if (F.col && it.col !== F.col) return false;
      if (F.spawnonly && !it.sp) return false;
      if (wmax != null && !isNaN(wmax) && (it.w == null || it.w > wmax)) return false;
      const s = st(it.id);
      if (F.status === 'have' && !s.h) return false;
      if (F.status === 'missing' && s.h) return false;
      if (F.status === 'want' && !s.w) return false;
      if (F.status === 'read' && !s.r) return false;
      if (F.status === 'unread' && (s.r || !isReadable(it))) return false;
      if (F.status === 'stashed' && !s.s) return false;
      if (terms.length) {
        const hay = s.s ? it.hay + ' ' + s.s.toLowerCase() : it.hay;
        if (!terms.every((t) => hay.includes(t))) return false;
      }
      return true;
    });
    const by = {
      name: (a, b) => a.n.localeCompare(b.n),
      weight: (a, b) => (b.w || 0) - (a.w || 0) || a.n.localeCompare(b.n),
      cat: (a, b) => a.c.localeCompare(b.c) || a.n.localeCompare(b.n),
      spawn: (a, b) => (b.spn || 0) - (a.spn || 0) || a.n.localeCompare(b.n),
      rare: (a, b) => ((a.sp ? a.wsum : 1e9) - (b.sp ? b.wsum : 1e9)) || a.n.localeCompare(b.n),
      used: (a, b) => (b.uin || 0) - (a.uin || 0) || a.n.localeCompare(b.n),
    }[F.sort] || ((a, b) => a.n.localeCompare(b.n));
    return out.sort(by);
  }
  function renderItems() {
    const res = filtered();
    const pages = Math.max(1, Math.ceil(res.length / PAGE));
    F.page = Math.min(F.page, pages - 1);
    const slice = res.slice(F.page * PAGE, F.page * PAGE + PAGE);
    $('#result-count').textContent = `${res.length.toLocaleString()} ITEMS`;
    $('#pg-info').textContent = `PAGE ${F.page + 1} / ${pages}`;
    $('#item-list').innerHTML = slice.length ? slice.map(rowHTML).join('') : '<div class="empty">NO ITEMS FOUND. GAME OVER?</div>';
  }

  // ------------------------------------------------------------------ detail drawer
  let detailId = null;
  function openDetail(id) {
    const it = BYID.get(id); if (!it) return;
    detailId = id;
    const s = st(id);
    const kv = [['ID', it.id], ['Category', pretty(it.c)], ['Type', it.t], ['Weight', it.w]];
    if (it.m) kv.push(['Source', `MOD: ${(modsById[it.m] || {}).name || it.m} (workshop ${(modsById[it.m] || {}).workshop || '?'})`]);
    else kv.push(['Source', 'Vanilla' + (it.ov ? ` (changed by ${it.ov.map((m) => (modsById[m] || {}).name || m).join(', ')})` : '')]);
    if (it.sk && it.lv) kv.push(['Skill', `${it.sk}, levels ${it.lv[0]}-${it.lv[1]}${it.vol ? ` (Vol ${it.vol})` : ''}`]);
    if (it.pg) kv.push(['Pages', it.pg]);
    if (it.media) {
      const m = it.media;
      if (m.author) kv.push(['Author / Artist', m.author]);
      if (m.extra) kv.push(['Info', m.extra]);
      kv.push(['Rarity tier', `${RARITY[m.spawning] || m.spawning} (spawning=${m.spawning})`]);
      if (Object.keys(m.skills).length) kv.push(['Skill XP lines', Object.entries(m.skills).map(([k, v]) => `${k} +${v}`).join(', ')]);
      if (Object.keys(m.moods).length) kv.push(['Mood effect', Object.entries(m.moods).map(([k, v]) => `${k} ${v > 0 ? '+' : ''}${v}`).join(', ')]);
      kv.push(['Length', `${m.lines} lines`]);
    }
    Object.entries(it.st || {}).forEach(([k, v]) => kv.push([pretty(k), v]));
    const maxW = Math.max(1, ...(it.sp || []).map(([, w]) => w));
    const spawnHTML = (it.sp || []).map(([i, w]) => {
      const l = lists[i];
      const rooms = l.r && l.r.length ? `rooms: ${l.r.slice(0, 5).map(pretty).join(', ')}${l.r.length > 5 ? '...' : ''}` : '';
      return `<div class="spawnrow"><div>${esc(pretty(l.n))}<small>${esc(l.g.join(' / '))}${rooms ? ' &middot; ' + esc(rooms) : ''}</small></div>
        <div class="sb"><i style="width:${Math.max(4, (w / maxW) * 100)}%"></i></div><div class="sw">${w}</div></div>`;
    }).join('');
    const teaches = (it.rc || []).concat(it.media ? it.media.recipes : []);
    $('#detail-body').innerHTML = `
      <div class="bigicon">${iconHTML(it, true)}</div>
      <h2>${esc(it.n)}</h2>
      <div class="toolbar">${actionButtons(it)}</div>
      <label class="field">&#9873; STASHED AT <input type="text" id="d-stash" value="${esc(s.s || '')}" placeholder="e.g. Base - Rosewood fire station"></label>
      <label class="field">NOTE <input type="text" id="d-note" value="${esc(s.n || '')}" placeholder="anything..."></label>
      <dl class="kv">${kv.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl>
      ${it.tg ? `<div class="sec"><h3>TAGS</h3><div class="tagchips">${it.tg.map((t) => `<span class="loc">${esc(t)}</span>`).join('')}</div></div>` : ''}
      ${teaches.length ? `<div class="sec"><h3>TEACHES</h3><ul class="plain">${teaches.map((r) => `<li>${esc(r)}</li>`).join('')}</ul></div>` : ''}
      <div class="sec"><h3>BEST PLACES TO LOOK ${it.spn ? `(${it.spn} loot tables${it.spn > it.sp.length ? `, top ${it.sp.length}` : ''})` : ''}</h3>
        ${spawnHTML || '<p class="hint">No loot-table spawn found (crafted, foraged, or found another way).</p>'}
        ${it.media ? '<p class="hint">Spawn spots shown for the carrier item (' + esc(it.c) + ').</p>' : ''}
        ${spawnHTML ? '<p class="hint">Numbers are raw loot-table weights. Bigger means more likely within that container type; they are not exact percentages.</p>' : ''}</div>
      ${it.mb ? `<div class="sec"><h3>MADE BY</h3><ul class="plain">${it.mb.map((r) => `<li>${esc(r)}</li>`).join('')}</ul></div>` : ''}
      ${it.ui ? `<div class="sec"><h3>USED IN ${it.uin} RECIPE${it.uin > 1 ? 'S' : ''}${it.uin > it.ui.length ? ` (first ${it.ui.length})` : ''}</h3><ul class="plain">${it.ui.map((r) => `<li>${esc(r)}</li>`).join('')}</ul></div>` : ''}`;
    $('#detail').classList.remove('hidden');
    $('#d-stash').addEventListener('input', (e) => { setFlag(id, 's', e.target.value.trim()); });
    $('#d-stash').addEventListener('change', () => refreshAfterChange(id));
    $('#d-note').addEventListener('input', (e) => { setFlag(id, 'n', e.target.value.trim()); });
  }
  $('#detail-close').onclick = () => { $('#detail').classList.add('hidden'); detailId = null; };
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') $('#detail-close').click(); });

  // ------------------------------------------------------------------ loot planner
  fillSelect('#loot-source', COLLECTIONS.map((c) => 'missing:' + c.key), (v) => 'MISSING: ' + COLBYKEY[v.split(':')[1]].name.toUpperCase());
  $('#loot-source').value = S.ui.lootSrc || 'want';
  $('#loot-mods').checked = !!S.ui.lootMods;
  $('#loot-veh').checked = S.ui.lootVeh !== false;
  ['#loot-source', '#loot-mods', '#loot-veh'].forEach((sel) => $(sel).addEventListener('change', () => {
    S.ui.lootSrc = $('#loot-source').value; S.ui.lootMods = $('#loot-mods').checked; S.ui.lootVeh = $('#loot-veh').checked; save(); renderLoot();
  }));
  function lootTargets() {
    const src = $('#loot-source').value, withMods = $('#loot-mods').checked;
    if (src === 'want') return ALL.filter((it) => st(it.id).w && !st(it.id).h); // starred items always count, modded or not
    return collectionItems(src.split(':')[1], withMods).filter((it) => !st(it.id).h);
  }
  function renderLoot() {
    const targets = lootTargets(), veh = $('#loot-veh').checked;
    $('#loot-targets').innerHTML = targets.length
      ? `<span class="hint">${targets.length} target items:</span>` + targets.slice(0, 80).map((it) => `<span class="chip" data-open="${esc(it.id)}">${esc(it.n)}</span>`).join('') + (targets.length > 80 ? `<span class="hint">+${targets.length - 80} more</span>` : '')
      : '<span class="hint">Nothing to hunt. Star items with WANT (or pick a collection above) to plan a run.</span>';
    // A list's share of an item = weight / item's total weight across its listed loot tables
    const G = {}, Lr = {};
    targets.forEach((it) => {
      const sp = (it.sp || []).filter(([i]) => veh || lists[i].k !== 'vehicle');
      const tot = sp.reduce((a, [, w]) => a + w, 0) || 1;
      const seenG = {};
      sp.forEach(([i, w]) => {
        const share = w / tot;
        const l = (Lr[i] = Lr[i] || { i, n: 0, s: 0, items: [] }); l.n++; l.s += share; l.items.push(it.n);
        lists[i].g.forEach((g) => {
          const e = (G[g] = G[g] || { g, n: 0, s: 0, items: new Set() });
          e.s += share; if (!seenG[g]) { seenG[g] = 1; e.n++; e.items.add(it.n); }
        });
      });
    });
    const rank = (arr) => arr.sort((a, b) => b.n - a.n || b.s - a.s);
    const gs = rank(Object.values(G)).filter((g) => g.g !== 'Other' || Object.keys(G).length === 1).slice(0, 12);
    $('#loot-groups').innerHTML = gs.length ? gs.map((g, k) => `<div class="rank"><div class="pos">${k + 1}</div>
      <div><div class="rn">${esc(g.g)}</div><div class="ri">${esc([...g.items].slice(0, 8).join(', '))}${g.items.size > 8 ? ` +${g.items.size - 8}` : ''}</div></div>
      <div class="rs">${g.n} ITEM${g.n > 1 ? 'S' : ''}</div></div>`).join('') : '<div class="empty">-</div>';
    const ls = rank(Object.values(Lr)).slice(0, 15);
    $('#loot-lists').innerHTML = ls.length ? ls.map((l, k) => {
      const L = lists[l.i];
      return `<div class="rank"><div class="pos">${k + 1}</div>
      <div><div class="rn">${esc(pretty(L.n))}</div><div class="ri">${esc(L.g.join(' / '))}${L.r && L.r.length ? ' &middot; rooms: ' + esc(L.r.slice(0, 4).map(pretty).join(', ')) : ''}</div>
      <div class="ri">${esc(l.items.slice(0, 6).join(', '))}${l.items.length > 6 ? ` +${l.items.length - 6}` : ''}</div></div>
      <div class="rs">${l.n} ITEM${l.n > 1 ? 'S' : ''}</div></div>`;
    }).join('') : '<div class="empty">-</div>';
  }

  // ------------------------------------------------------------------ skills
  // Book XP multipliers per volume (classic PZ values; not stored in the item scripts)
  const BOOK_MULT = { 1: 3, 2: 5, 3: 8, 4: 12, 5: 16 };
  function renderSkills() {
    const books = ALL.filter((it) => it.col === 'skillbooks' && !it.m);
    const skills = [...new Set(books.map((b) => b.sk))].sort();
    const tapes = mediaItems.filter((m) => Object.keys(m.media.skills).length);
    $('#skill-table').innerHTML = skills.map((sk) => {
      const lvl = S.skills[sk] || 0;
      const next = lvl >= 10 ? null : books.find((b) => b.sk === sk && b.lv && b.lv[0] <= lvl + 1 && lvl + 1 <= b.lv[1]);
      let info;
      if (!next) info = lvl >= 10 ? '<b class="ok">MAXED OUT</b>' : 'No book for this level';
      else {
        const s = st(next.id);
        const status = s.r ? '<b class="ok">read</b>' : s.h ? '<b class="meh">have it, not read</b>' : '<b class="bad">missing</b>';
        info = `Next: <b data-open="${esc(next.id)}" style="cursor:pointer;text-decoration:underline">${esc(next.n)}</b> (Vol ${next.vol}, x${BOOK_MULT[next.vol] || '?'} XP) &mdash; ${status}`;
      }
      const tp = tapes.filter((m) => m.media.skills[sk]);
      const watched = tp.filter((m) => st(m.id).r).length;
      if (tp.length) info += `<br>VHS: ${watched}/${tp.length} watched (${tp.map((m) => `<span data-open="${esc(m.id)}" style="cursor:pointer" class="${st(m.id).r ? 'ok' : ''}">${esc(m.n.replace(/^VHS: /, ''))} +${m.media.skills[sk]}</span>`).join(', ')})`;
      const pips = Array.from({ length: 10 }, (_, i) => `<span class="pip ${i < lvl ? 'on' : ''}"></span>`).join('');
      return `<div class="skillrow"><div style="font-size:22px">${esc(sk)}</div>
        <div class="lvl"><button class="px-btn tiny" data-sk="${esc(sk)}" data-d="-1">-</button><span class="lvlnum">${lvl}</span><button class="px-btn tiny" data-sk="${esc(sk)}" data-d="1">+</button><span class="pips">${pips}</span></div>
        <div class="skillinfo">${info}</div></div>`;
    }).join('') + '<p class="hint">Book multipliers shown are the classic PZ values (x3 / x5 / x8 / x12 / x16). They live in the game&#39;s Java code, not the item scripts, so double-check them in game. VHS numbers count the XP-granting lines in each tape.</p>';
    $$('[data-sk]').forEach((b) => b.addEventListener('click', () => {
      const sk = b.dataset.sk; S.skills[sk] = Math.max(0, Math.min(10, (S.skills[sk] || 0) + parseInt(b.dataset.d, 10))); save(); renderSkills();
    }));
  }

  // ------------------------------------------------------------------ save / load
  function renderSave() {
    $('#run-name').value = S.runName || '';
    $('#run-notes').value = S.notes || '';
    const vc = ALL.filter((i) => !i.m).length, mc = ALL.filter((i) => i.m).length;
    $('#data-info').textContent = [
      `Game build: ${D.meta.version} (Steam build ${D.meta.steamBuild || '?'})`,
      `Data generated: ${D.meta.generated} from ${D.meta.source}`,
      `Items: ${vc} vanilla (incl. ${mediaItems.length} VHS/CD titles) + ${mc} modded from ${D.mods.filter((m) => m.items).length} mods`,
      `Loot tables: ${lists.length}`,
      `Tracked entries in your save: ${Object.keys(S.items).length}`,
      storageOK ? 'Storage: browser localStorage (OK)' : 'Storage: BLOCKED - export to keep progress',
    ].join('\n');
  }
  $('#run-name').addEventListener('input', (e) => { S.runName = e.target.value; save(); });
  $('#run-notes').addEventListener('input', (e) => { S.notes = e.target.value; save(); });
  $('#btn-export').addEventListener('click', () => {
    const payload = { app: 'pz-item-tracker', version: 1, exported: new Date().toISOString(), game: D.meta.version, state: S };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `pz-tracker-${(S.runName || 'save').replace(/[^\w-]+/g, '_')}-day${S.day || 1}.json`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    $('#save-msg').textContent = 'Exported. Keep that file somewhere safe.';
  });
  $('#btn-import').addEventListener('change', async (e) => {
    const [file] = e.target.files;
    if (!file) return;
    try {
      const data = JSON.parse(await file.text());
      const incoming = data && data.app === 'pz-item-tracker' ? data.state : data;
      if (!incoming || typeof incoming.items !== 'object') throw new Error('not a tracker save');
      S = Object.assign(blank(), incoming);
      save(); renderHUD(); renderSave();
      $('#save-msg').textContent = `Imported ${Object.keys(S.items).length} tracked items.`;
    } catch (err) {
      $('#save-msg').textContent = 'Import failed: ' + err.message;
    }
    e.target.value = '';
  });
  $('#btn-reset').addEventListener('click', () => {
    if (!confirm('Wipe all progress in this browser? Export first if you want a backup.')) return;
    S = blank(); save(); renderHUD(); renderSave();
    $('#save-msg').textContent = 'Progress reset.';
  });

  // ------------------------------------------------------------------ boot
  try { window.localStorage.setItem(STORE_KEY + '.probe', '1'); window.localStorage.removeItem(STORE_KEY + '.probe'); }
  catch (e) { storageOK = false; }
  if (!storageOK) $('#storage-warning').classList.remove('hidden');
  renderHUD();
  showTab(S.ui.tab || 'collections');
  window.PZTracker = { state: () => S, items: ALL };
})();
