/* 8x8 pixel glyphs used when no real item icon is bundled. '#' = main colour, '+' = highlight. */
(function () {
  const G = {
    book:   ['.######.', '#++++++#', '#+####+#', '#++++++#', '#+###++#', '#++++++#', '#++++++#', '.######.'],
    mag:    ['########', '#++++++#', '#+##+++#', '#+##+#+#', '#++++++#', '#+####+#', '#++++++#', '########'],
    vhs:    ['########', '#++++++#', '#.#++#.#', '#++++++#', '########', '#.####.#', '#.####.#', '########'],
    cd:     ['..####..', '.#++++#.', '#++##++#', '#+#..#+#', '#+#..#+#', '#++##++#', '.#++++#.', '..####..'],
    map:    ['#.##.##.', '##+##+##', '#++#++##', '##+##+.#', '#+##+###', '##+##+##', '#++#++.#', '##.##.##'],
    seed:   ['.######.', '#++++++#', '#+#++#+#', '#++##++#', '#+####+#', '#++##++#', '#++++++#', '.######.'],
    gun:    ['........', '########', '#++++++#', '#####++#', '...##+##', '...#++#.', '...###..', '........'],
    blade:  ['......##', '.....#+#', '....#+#.', '...#+#..', '#.#+#...', '.##+....', '.###....', '#..#....'],
    tool:   ['.####...', '##++#...', '.#####..', '...#+#..', '...#+#..', '...#+#..', '...#+#..', '...###..'],
    food:   ['...##...', '..#..#..', '.######.', '#++++++#', '#+####+#', '#++++++#', '#++++++#', '.######.'],
    drink:  ['..###...', '..#+#...', '.#+++#..', '#+++++#.', '#++#++#.', '#++#++#.', '#+++++#.', '.#####..'],
    shirt:  ['.##..##.', '#+####+#', '##++++##', '.#++++#.', '.#++++#.', '.#++++#.', '.#++++#.', '.######.'],
    bag:    ['..####..', '.#....#.', '########', '#++++++#', '#+####+#', '#++++++#', '#++++++#', '########'],
    med:    ['.######.', '#++++++#', '#++##++#', '#+####+#', '#+####+#', '#++##++#', '#++++++#', '.######.'],
    part:   ['..#..#..', '.######.', '##++++##', '.#+##+#.', '.#+##+#.', '##++++##', '.######.', '..#..#..'],
    ammo:   ['.#..#..#', '#+##+##+', '#+##+##+', '#+##+##+', '#+##+##+', '####.###', '#+##+##+', '########'],
    photo:  ['########', '#++++++#', '#+##+++#', '#++++#+#', '#+#++###', '###+####', '#++++++#', '########'],
    box:    ['########', '#++++++#', '#+####+#', '#++++++#', '########', '#++++++#', '#++++++#', '########'],
    plant:  ['...#....', '..#+#.#.', '...#.#+#', '.#.##.#.', '#+#.#...', '.#..#...', '..####..', '..####..'],
  };
  const COL = {
    book: ['#ffe14d', '#7a5a00'], mag: ['#ff2fd0', '#3a0b33'], vhs: ['#29e6ff', '#083845'], cd: ['#c8d6ff', '#304070'],
    map: ['#ffb066', '#4a2a00'], seed: ['#39ff14', '#0b3d05'], gun: ['#b0b8c8', '#2a2f3a'], blade: ['#d0e0ff', '#3a4660'],
    tool: ['#ff9a1f', '#4a2a00'], food: ['#ff6a4d', '#4a1408'], drink: ['#29e6ff', '#083845'], shirt: ['#a68cff', '#2a1e55'],
    bag: ['#c8a060', '#3a2a10'], med: ['#ff4040', '#ffffff'], part: ['#9aa4b8', '#2a2f3a'], ammo: ['#ffd700', '#5a4300'],
    photo: ['#ffe9c4', '#5a4a30'], box: ['#8a9ab8', '#262a3a'], plant: ['#39ff14', '#0b3d05'],
  };
  const cache = {};
  function svg(kind) {
    if (cache[kind]) return cache[kind];
    const g = G[kind] || G.box; const [main, hi] = COL[kind] || COL.box;
    let rects = '';
    g.forEach((row, y) => { for (let x = 0; x < 8; x++) {
      const c = row[x]; if (c === '#') rects += `<rect x="${x}" y="${y}" width="1" height="1" fill="${main}"/>`;
      else if (c === '+') rects += `<rect x="${x}" y="${y}" width="1" height="1" fill="${hi}"/>`; } });
    const s = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8" width="32" height="32" shape-rendering="crispEdges" class="glyph" aria-hidden="true">${rects}</svg>`;
    cache[kind] = s; return s;
  }
  function kindFor(it) {
    const c = (it.c || '').toLowerCase(), t = it.t || '', col = it.col || '';
    if (col.startsWith('vhs')) return 'vhs';
    if (col === 'cds') return 'cd';
    if (col === 'skillbooks') return 'book';
    if (col === 'magazines') return 'mag';
    if (col === 'seeds') return 'seed';
    if (t === 'map' || c === 'cartography') return 'map';
    if (c === 'memento') return 'photo';
    if (t === 'literature' || c === 'literature') return 'book';
    if (c === 'ammo') return 'ammo';
    if (it.st && it.st.AmmoType && t === 'weapon') return 'gun';
    if (t === 'weapon') return /blade|knife|sword|machete/i.test(it.n) ? 'blade' : 'tool';
    if (c.includes('food') || t === 'food') return /water|juice|soda|pop|milk|beer|wine|whiskey|coffee/i.test(it.n) ? 'drink' : 'food';
    if (c.includes('watercontainer')) return 'drink';
    if (t === 'clothing' || c.includes('clothing') || c.includes('accessory') || c.includes('protective') || c === 'appearance') return 'shirt';
    if (t === 'container' || c === 'bag' || c === 'container') return 'bag';
    if (c.includes('firstaid') || c.includes('bandage') || c === 'wound') return 'med';
    if (c.includes('vehiclemaintenance') || t === 'weaponpart' || c === 'weaponpart') return 'part';
    if (c.includes('gardening') || c.includes('animalpart')) return 'plant';
    if (c.includes('tool') || c.includes('material') || c.includes('electronics')) return 'tool';
    return 'box';
  }
  window.PZGlyph = { svg, kindFor };
})();
