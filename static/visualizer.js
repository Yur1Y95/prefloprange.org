// ── VISUALIZER STATE ─────────────────────────────────
const viz = {
  config:      null,
  rangeData:   null,
  gameType:    'Cash',
  currentFile: '',
  spot:        'RFI',
  heroPos:     'UTG',
  villainPos:  null,
  action:      'all',
  rngEnabled:  false,
  rngValues:   {},
  cachedRange: {},
  cachedType:  'RFI',
  _allFiles:   [],
};

const RANKS = ['A','K','Q','J','T','9','8','7','6','5','4','3','2'];

function rfiColor(freq) {
  if (freq >= 1.0) return ['#2E7D32', '#fff'];
  if (freq >= 0.75) return ['#66BB6A', '#000'];
  if (freq >= 0.5)  return ['#D4E157', '#000'];
  if (freq > 0)     return ['#FFA726', '#000'];
  return ['#1e2a22', '#3a5a44'];
}

// ── BOOT ─────────────────────────────────────────────
async function vizBoot() {
  try {
    try {
      const listRes = await fetchWithTimeout('/api/ranges/list');
      viz._allFiles = await listRes.json();
    } catch (e) {
      console.warn('Visualizer: could not load file list:', e);
      viz._allFiles = [];
    }

    buildMatrix();
    vizBindEvents();
    vizRefreshDepthOptions();

    if (viz.currentFile !== undefined) {
      try {
        await vizLoadFile(viz.currentFile);
      } catch (e) {
        console.warn('Visualizer: could not load range file:', e);
      }
    }

    vizRenderControls();
    vizUpdate();
  } catch (e) {
    console.error('Visualizer boot failed:', e);
  }
}

// Called from editor after save — just re-fetch the server list. Used to
// also re-merge UserStorage entries; that path is gone (see P-001).
async function vizRefreshAfterSave() {
  try {
    const res = await fetch('/api/ranges/list');
    if (res.ok) viz._allFiles = await res.json();
  } catch (_) { /* ignore */ }
  vizRefreshDepthOptions();
}

function vizRefreshDepthOptions() {
  const select    = document.getElementById('vDepthSelect');
  const tableSize = (document.getElementById('vTableSelect')?.value || '').toLowerCase().replace('-','');
  if (!select) return;

  const filtered = viz._allFiles.filter(f => {
    const gameMatch  = f.game_type === viz.gameType;
    const tableMatch = !tableSize || (f.table_size || '').toLowerCase().replace('-','') === tableSize;
    return gameMatch && tableMatch;
  });

  select.innerHTML = filtered.length
    ? filtered.map(f => {
        // Filename is the user's chosen identity — show it as the primary
        // name. The auto-generated label (game/table/depth) is secondary
        // context. Skip the suffix when it would just duplicate the name.
        const name = f.filename.replace(/\.json$/, '');
        const meta = (f.label && f.label !== name) ? f.label : (f.stack_depth || '');
        const text = (meta && meta !== name) ? `${name} · ${meta}` : name;
        return `<option value="${f.filename}">${text}</option>`;
      }).join('')
    : '<option value="">No ranges</option>';
  viz.currentFile = filtered.length ? filtered[0].filename : '';
}

async function vizLoadFile(filename) {
  if (!filename) {
    const res = await fetch('/api/ranges');
    if (!res.ok) return;
    viz.rangeData = await res.json();
  } else {
    // All ranges live on the server now; user:-prefixed localStorage path
    // is gone (see P-001).
    const res = await fetch(`/api/ranges?file=${encodeURIComponent(filename)}`);
    if (!res.ok) return;
    viz.rangeData = await res.json();
  }
  viz.config     = viz.rangeData.config;
  viz.heroPos    = viz.config.rfi_positions[0];
  viz.villainPos = null;
}

// ── BUILD 13×13 MATRIX ───────────────────────────────
function buildMatrix() {
  const grid = document.getElementById('matrix');
  grid.innerHTML = '';

  for (let r = 0; r < 13; r++) {
    for (let c = 0; c < 13; c++) {
      const hand = handName(r, c);
      const cell = document.createElement('div');
      cell.className   = 'matrix-cell';
      cell.dataset.hand = hand;

      const label = document.createElement('span');
      label.className = 'cell-label';
      label.textContent = hand;
      cell.appendChild(label);

      cell.addEventListener('mouseenter', () => vizShowHover(hand));
      grid.appendChild(cell);
    }
  }
}

function handName(r, c) {
  if (r === c) return RANKS[r] + RANKS[c];
  if (r < c)   return RANKS[r] + RANKS[c] + 's';
  return RANKS[c] + RANKS[r] + 'o';
}

// ── BIND EVENTS ──────────────────────────────────────
function vizBindEvents() {
  // Refresh button
  const refreshBtn = document.getElementById('vRefreshBtn');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', async () => {
      refreshBtn.textContent = '↻ Refreshing…';
      refreshBtn.disabled = true;
      try {
        const listRes = await fetch('/api/ranges/list');
        viz._allFiles = await listRes.json();
        vizRefreshDepthOptions();
        await vizLoadFile(viz.currentFile);
        vizRenderControls();
        vizUpdate();
        refreshBtn.textContent = '✓ Updated';
        setTimeout(() => {
          refreshBtn.textContent = '↻ Refresh Ranges';
          refreshBtn.disabled = false;
        }, 1500);
      } catch (e) {
        refreshBtn.textContent = '✗ Error';
        setTimeout(() => {
          refreshBtn.textContent = '↻ Refresh Ranges';
          refreshBtn.disabled = false;
        }, 1500);
      }
    });
  }

  // Game type buttons
  document.querySelectorAll('[data-vgame]').forEach(btn => {
    btn.addEventListener('click', async () => {
      viz.gameType = btn.dataset.vgame;
      document.querySelectorAll('[data-vgame]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      vizRefreshDepthOptions();
      await vizLoadFile(viz.currentFile);
      vizRenderControls();
      vizUpdate();
    });
  });

  // Table size dropdown
  const tableSelect = document.getElementById('vTableSelect');
  if (tableSelect) {
    tableSelect.addEventListener('change', async () => {
      vizRefreshDepthOptions();
      await vizLoadFile(viz.currentFile);
      vizRenderControls();
      vizUpdate();
    });
  }

  // Depth dropdown
  const depthSel = document.getElementById('vDepthSelect');
  if (depthSel) {
    depthSel.addEventListener('change', async () => {
      viz.currentFile = depthSel.value;
      await vizLoadFile(viz.currentFile);
      vizRenderControls();
      vizUpdate();
    });
  }

  // Spot buttons
  document.querySelectorAll('[data-vspot]').forEach(btn => {
    btn.addEventListener('click', () => {
      viz.spot = btn.dataset.vspot;
      document.querySelectorAll('[data-vspot]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      vizRenderControls();
      vizUpdate();
    });
  });

  // Action filter buttons
  document.querySelectorAll('[data-vaction]').forEach(btn => {
    btn.addEventListener('click', () => {
      viz.action = btn.dataset.vaction;
      document.querySelectorAll('[data-vaction]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      vizUpdate();
    });
  });

  // RNG toggle
  document.getElementById('vRngToggle').addEventListener('change', e => {
    viz.rngEnabled = e.target.checked;
    if (!viz.rngEnabled) viz.rngValues = {};
    vizUpdate();
  });

  // RNG generate
  document.getElementById('vRngGenBtn').addEventListener('click', () => {
    if (!viz.rngEnabled) {
      document.getElementById('vRngToggle').checked = true;
      viz.rngEnabled = true;
    }
    viz.rngValues = {};
    for (let r = 0; r < 13; r++)
      for (let c = 0; c < 13; c++)
        viz.rngValues[handName(r, c)] = Math.floor(Math.random() * 100);
    vizUpdate();
  });
}

// ── RENDER POSITION CONTROLS ─────────────────────────
function vizRenderControls() {
  // Hero buttons
  const heroWrap = document.getElementById('vHeroBtns');
  heroWrap.innerHTML = '';
  const positions = viz.spot === 'RFI'
    ? viz.config.rfi_positions
    : viz.config.positions;

  positions.forEach(pos => {
    const btn = document.createElement('button');
    btn.className = 'pos-btn' + (pos === viz.heroPos ? ' active' : '');
    btn.textContent = pos;
    btn.addEventListener('click', () => {
      viz.heroPos = pos;
      vizRenderControls();
      vizUpdate();
    });
    heroWrap.appendChild(btn);
  });

  // Villain section
  const villainGroup  = document.getElementById('vVillainGroup');
  const actionGroup   = document.getElementById('vActionGroup');
  const vsLegend      = document.getElementById('vsLegend');
  const vsLegendLabel = document.getElementById('vsLegendLabel');
  const rfiLegend     = document.getElementById('rfiLegend');

  if (viz.spot === 'RFI') {
    villainGroup.style.display  = 'none';
    actionGroup.style.display   = 'none';
    vsLegend.style.display      = 'none';
    if (vsLegendLabel) vsLegendLabel.style.display = 'none';
    rfiLegend.style.display     = 'flex';
    viz.villainPos = null;
  } else {
    villainGroup.style.display  = 'flex';
    actionGroup.style.display   = 'flex';
    vsLegend.style.display      = 'flex';
    if (vsLegendLabel) vsLegendLabel.style.display = 'block';
    rfiLegend.style.display     = 'none';

    const optMap = viz.spot === 'vs_RFI'
      ? viz.config.vs_rfi_options
      : (viz.config.vs_3bet_options || {});
    const available = optMap[viz.heroPos] || [];

    if (!available.includes(viz.villainPos)) viz.villainPos = available[0] || null;

    const villainWrap = document.getElementById('vVillainBtns');
    villainWrap.innerHTML = '';
    available.forEach(pos => {
      const btn = document.createElement('button');
      btn.className = 'pos-btn' + (pos === viz.villainPos ? ' active' : '');
      btn.textContent = pos;
      btn.addEventListener('click', () => {
        viz.villainPos = pos;
        vizRenderControls();
        vizUpdate();
      });
      villainWrap.appendChild(btn);
    });
  }
}

// ── FETCH RANGE AND UPDATE MATRIX ────────────────────
async function vizUpdate() {
  const rangeData = viz.rangeData;
  if (!rangeData) return;

  let range = {};
  let type  = viz.spot;

  if (viz.spot === 'RFI') {
    const pos = viz.config.rfi_positions.includes(viz.heroPos)
      ? viz.heroPos : viz.config.rfi_positions[0];
    const raw = rangeData.spots?.RFI?.[pos] || {};
    range = expandRFI(raw);

  } else if (viz.spot === 'vs_RFI' && viz.villainPos) {
    const key = `vs_${viz.villainPos}`;
    const raw = rangeData.spots?.vs_RFI?.[viz.heroPos]?.[key] || {};
    range = expandActions(raw);

  } else if (viz.spot === 'vs_3bet' && viz.villainPos) {
    const key = `vs_${viz.villainPos}`;
    const raw = rangeData.spots?.vs_3bet?.[viz.heroPos]?.[key] || {};
    range = expandActions(raw);
  }

  viz.cachedRange = range;
  viz.cachedType  = type;

  renderMatrix(range, type);
  renderStatus(range, type);
}

// ── RANGE EXPANSION (mirrors range_engine.py in JS) ──

const RANKS_ASC = ['2','3','4','5','6','7','8','9','T','J','Q','K','A'];

function rankVal(r) { return RANKS_ASC.indexOf(r); }

function normalizeHand(a, b, suffix) {
  if (a === b) return a + b;
  return rankVal(a) > rankVal(b) ? a + b + suffix : b + a + suffix;
}

function expandNotation(notation) {
  notation = notation.trim();

  // AA
  if (notation.length === 2 && notation[0] === notation[1]) return [notation];
  // AKs / AKo
  if (notation.length === 3 && 'so'.includes(notation[2])) return [notation];

  // 55+
  if (notation.length === 3 && notation[0] === notation[1] && notation[2] === '+') {
    const start = rankVal(notation[0]);
    return RANKS_ASC.filter(r => rankVal(r) >= start).map(r => r + r);
  }

  // A2s+
  if (notation.length === 4 && notation[3] === '+') {
    const hi = notation[0], lo = notation[1], sfx = notation[2];
    const loVal = rankVal(lo), hiVal = rankVal(hi);
    return RANKS_ASC
      .filter(r => rankVal(r) >= loVal && rankVal(r) < hiVal)
      .map(r => normalizeHand(hi, r, sfx));
  }

  // 99-22 or A5s-A2s
  if (notation.includes('-')) {
    const [start, end] = notation.split('-');
    if (start.length === 2 && end.length === 2) {
      // pair range
      const lo = Math.min(rankVal(start[0]), rankVal(end[0]));
      const hi = Math.max(rankVal(start[0]), rankVal(end[0]));
      return RANKS_ASC.filter(r => rankVal(r) >= lo && rankVal(r) <= hi).map(r => r + r);
    }
    if (start.length === 3 && end.length === 3) {
      // suited/offsuit range
      const hiCard = start[0], sfx = start[2];
      const lo = Math.min(rankVal(start[1]), rankVal(end[1]));
      const hi = Math.max(rankVal(start[1]), rankVal(end[1]));
      return RANKS_ASC
        .filter(r => rankVal(r) >= lo && rankVal(r) <= hi)
        .map(r => normalizeHand(hiCard, r, sfx));
    }
  }

  console.warn('Unrecognised notation:', notation);
  return [];
}

function expandRFI(raw) {
  const out = {};
  for (const [notation, value] of Object.entries(raw)) {
    for (const hand of expandNotation(notation)) {
      if (typeof value === 'object') {
        // Multi-action format
        if (!out[hand]) out[hand] = {};
        for (const [action, freq] of Object.entries(value)) {
          out[hand][action] = Math.max(out[hand][action] || 0, freq);
        }
      } else {
        // Legacy single-frequency
        out[hand] = Math.max(out[hand] || 0, value);
      }
    }
  }
  return out;
}

function expandActions(raw) {
  const out = {};
  for (const [notation, actions] of Object.entries(raw)) {
    for (const hand of expandNotation(notation)) {
      if (!out[hand]) out[hand] = {};
      for (const [action, freq] of Object.entries(actions)) {
        out[hand][action] = Math.max(out[hand][action] || 0, freq);
      }
    }
  }
  return out;
}

// ── RENDER MATRIX CELLS ───────────────────────────────
function renderMatrix(range, type) {
  document.querySelectorAll('.matrix-cell').forEach(cell => {
    const hand  = cell.dataset.hand;
    const value = range[hand];
    if (type === 'RFI') {
      paintRFI(cell, hand, value ?? 0);
    } else {
      paintActions(cell, hand, value || {});
    }
  });
}

function paintRFI(cell, hand, value) {
  // value is either a number (old format) or {action: freq} (new format)
  const isMulti = typeof value === 'object' && value !== null;

  if (!isMulti) {
    // Legacy single-frequency
    const freq = value || 0;
    let displayFreq = freq;
    if (viz.rngEnabled && freq > 0 && freq < 1) {
      const rng = viz.rngValues[hand] ?? 0;
      if (rng >= freq * 100) displayFreq = 0;
    }
    const [bg, fg] = rfiColor(displayFreq);
    cell.style.background = displayFreq === 0 && freq > 0
      ? `repeating-linear-gradient(45deg,${rfiColor(freq)[0]}55 0px,${rfiColor(freq)[0]}55 4px,${rfiColor(freq)[0]}22 4px,${rfiColor(freq)[0]}22 8px)`
      : bg;
    cell.style.color   = fg;
    cell.style.opacity = displayFreq === 0 && freq > 0 ? '0.55' : '1';
    return;
  }

  // Multi-action: open=green, call=blue, fold=empty-cell base (no distinct stripe)
  const COLOR = { open: '#2E7D32', call: '#3F7FB5', fold: '#1e2a22' };
  const ORDER = ['open', 'call', 'fold'];
  let cum = 0;
  const stops = [];

  for (const a of ORDER) {
    const f = value[a] || (a === 'fold'
      ? Math.max(0, 1 - Object.values(value).reduce((s,v)=>s+v,0))
      : 0);
    if (f <= 0) continue;
    stops.push(`${COLOR[a]} ${Math.round(cum*100)}% ${Math.round((cum+f)*100)}%`);
    cum += f;
  }

  cell.style.background = stops.length
    ? `linear-gradient(to right, ${stops.join(', ')})`
    : '#1e2a22';
  cell.style.color   = '#fff';
  cell.style.opacity = '1';
}

function paintActions(cell, hand, actions) {
  const actionKeys = viz.spot === 'vs_3bet'
    ? ['4bet', 'call']
    : ['3bet', 'call'];

  // Filter by selected action tab
  let filteredActions = { ...actions };
  if (viz.action !== 'all') {
    filteredActions = {};
    if (actions[viz.action]) filteredActions[viz.action] = actions[viz.action];
  }

  // Apply RNG per hand
  let rngChosen = null;
  if (viz.rngEnabled && Object.keys(actions).length > 0) {
    const rng = (viz.rngValues[hand] ?? 0) / 100;
    let cum = 0;
    for (const a of [...actionKeys, 'fold']) {
      cum += (actions[a] || 0);
      if (rng < cum) { rngChosen = a; break; }
    }
    if (!rngChosen) rngChosen = 'fold';
  }

  // Build CSS gradient segments
  const COLOR = { '3bet': '#F44336', '4bet': '#c0392b', call: '#3F7FB5', fold: '#1e2a22' };
  let cum = 0;
  const stops = [];

  for (const a of [...actionKeys, 'fold']) {
    const f = filteredActions[a] !== undefined
      ? filteredActions[a]
      : (a === 'fold' ? Math.max(0, 1 - Object.values(filteredActions).reduce((s,v)=>s+v,0)) : 0);
    if (f <= 0) continue;
    const pct1 = Math.round(cum * 100);
    const pct2 = Math.round((cum + f) * 100);
    stops.push(`${COLOR[a]} ${pct1}% ${pct2}%`);
    cum += f;
  }
  // Fill remainder as fold
  if (cum < 1) {
    stops.push(`${COLOR.fold} ${Math.round(cum*100)}% 100%`);
  }

  cell.style.background = stops.length > 0
    ? `linear-gradient(to right, ${stops.join(', ')})`
    : COLOR.fold;

  // RNG highlight: dim non-chosen
  if (viz.rngEnabled && rngChosen) {
    cell.style.opacity = '0.4';
    const chosenColor  = COLOR[rngChosen] || COLOR.fold;
    cell.style.background = chosenColor;
    cell.style.opacity    = '1';
    if (rngChosen === 'fold') cell.style.background = COLOR.fold;
  }

  cell.style.color = '#fff';
}

// ── HOVER INFO ────────────────────────────────────────
function vizShowHover(hand) {
  const el    = document.getElementById('vizHover');
  const type  = viz.cachedType;
  const range = viz.cachedRange;

  if (type === 'RFI') {
    const value = range[hand];
    if (!value) { el.textContent = `${hand}: fold`; return; }

    // Multi-action format (MTT with limp)
    if (typeof value === 'object') {
      const parts = Object.entries(value)
        .filter(([,f]) => f > 0)
        .map(([a,f]) => `${a} ${Math.round(f*100)}%`);
      el.textContent = `${hand}: ${parts.join(' / ')}`;
      return;
    }

    // Legacy single-frequency
    const pct = Math.round(value * 100);
    let rngInfo = '';
    if (viz.rngEnabled) {
      const rng  = viz.rngValues[hand] ?? 0;
      const play = rng < pct;
      rngInfo = ` · RNG ${rng} ${play ? '<' : '≥'} ${pct} → ${play ? 'open' : 'fold'}`;
    }
    el.textContent = `${hand}: open ${pct}%${rngInfo}`;

  } else {
    const actions = range[hand] || {};
    if (!Object.keys(actions).length) {
      el.textContent = `${hand}: fold 100%`;
      return;
    }
    const parts = Object.entries(actions)
      .filter(([,f]) => f > 0)
      .map(([a,f]) => `${a} ${Math.round(f*100)}%`);

    let rngInfo = '';
    if (viz.rngEnabled) {
      const rng = (viz.rngValues[hand] ?? 0) / 100;
      const actionOrder = viz.spot === 'vs_3bet' ? ['4bet','call'] : ['3bet','call'];
      let cum = 0, chosen = 'fold';
      for (const a of actionOrder) {
        cum += actions[a] || 0;
        if (rng < cum) { chosen = a; break; }
      }
      rngInfo = ` · RNG → ${chosen}`;
    }
    el.textContent = `${hand}: ${parts.join(' / ')}${rngInfo}`;
  }
}

// ── STATUS BAR ────────────────────────────────────────
function renderStatus(range, type) {
  const TOTAL = 1326;
  let combos = 0;

  try {
    if (type === 'RFI') {
      for (const [hand, value] of Object.entries(range)) {
        if (!value) continue;
        const freq = typeof value === 'object'
          ? Math.min(1, Object.values(value).reduce((s,v) => s+v, 0))
          : value;
        combos += comboCnt(hand) * freq;
      }
    } else {
      const filterAction = viz.action === 'all' ? null : viz.action;
      for (const [hand, actions] of Object.entries(range)) {
        if (!actions || typeof actions !== 'object') continue;
        const freq = filterAction
          ? (actions[filterAction] || 0)
          : Object.values(actions).reduce((s,v) => s+v, 0);
        combos += comboCnt(hand) * Math.min(freq, 1);
      }
    }
  } catch(e) {
    console.warn('renderStatus error:', e);
  }

  const pct = (combos / TOTAL * 100).toFixed(1);
  const pos = viz.villainPos ? `${viz.heroPos} vs ${viz.villainPos}` : viz.heroPos;
  document.getElementById('vizStatus').textContent =
    `${viz.spot} · ${pos} · ${Math.round(combos)} combos · ${pct}%`;
}

function comboCnt(hand) {
  if (hand.length === 2) return 6;
  if (hand.endsWith('s')) return 4;
  return 12;
}

// ── MODE SWITCHING (called from drill.js) ────────────
function showVisualizer() {
  document.getElementById('drillMode').style.display    = 'none';
  document.getElementById('analyzerMode').style.display = 'none';
  document.getElementById('editorMode').style.display   = 'none';
  document.getElementById('vizMode').style.display      = 'grid';

  if (!viz.rangeData) {
    vizBoot();
  } else {
    // Refresh file list in case new ranges were saved in editor
    fetch('/api/ranges/list')
      .then(r => r.json())
      .then(files => {
        viz._allFiles = files;
        vizRefreshDepthOptions();
      });
  }
}

function hideVisualizer() {
  document.getElementById('vizMode').style.display = 'none';
}

// Boot happens on demand (when tab is clicked)
