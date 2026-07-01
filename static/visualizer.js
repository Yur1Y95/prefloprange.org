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

// Matrix palette + gradient builders now live in static/mtx_palette.js
// (window.MTX), shared with editor.js and drill.js. See design.md §9.1.
// RFI is no longer a solid colour bucket — it's a split-bar of the open
// colour with width = open frequency (MTX.rfiFill).

// Legend strip under the matrix (not a side panel) — built per spot from the
// shared MTX palette so swatches always match the cells.
function buildVizLegend(spot) {
  const el = document.getElementById('vizLegend');
  if (!el) return;
  const A = MTX.COLORS.act;
  const fold = `${MTX.COLORS.fold};border:1px solid var(--stroke)`;
  let rows;
  if (spot === 'vs_3bet')      rows = [[A['4bet'], '4-Bet'], [A.call, 'Call'], [fold, 'Fold']];
  else if (spot === 'vs_4bet') rows = [[A.allin, 'All-In'], [A.call, 'Call'], [fold, 'Fold']];
  else if (spot === 'iso')     rows = [[A.open, 'Raise'], [A.call, 'Call'], [fold, 'Fold']];
  else if (spot === 'RFI')     rows = [[A.open, 'Open'], [fold, 'Fold']];
  else                         rows = [[A['3bet'], '3-Bet'], [A.call, 'Call'], [fold, 'Fold']];  // vs_RFI
  el.innerHTML = rows.map(([bg, label]) =>
    `<div class="legend-row"><span class="legend-swatch" style="background:${bg}"></span>${label}</div>`
  ).join('');
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

      grid.appendChild(cell);
    }
  }

  // Action-frequency tooltip on hover (Track B.3) — replaces the old #vizHover
  // frequency line. The resolver reads the live cached range on every move, so
  // recolors/rebuilds need no extra wiring. Attaches once (guarded in MatrixTip).
  if (window.MatrixTip) {
    MatrixTip.attach(grid, cell => ({
      hand:  cell.dataset.hand,
      value: viz.cachedRange ? viz.cachedRange[cell.dataset.hand] : null,
    }));
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

  buildVizLegend(viz.spot);

  if (viz.spot === 'RFI') {
    villainGroup.style.display  = 'none';
    actionGroup.style.display   = 'none';
    viz.villainPos = null;
  } else {
    villainGroup.style.display  = 'flex';
    actionGroup.style.display   = 'flex';

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

// Split-bar gradient (1px divider between segments) lives in
// static/mtx_palette.js as MTX.splitGradient — shared by Visualizer, Editor
// and Drill (§9.1). Call it directly: MTX.splitGradient(segs, foldColor).

function paintRFI(cell, hand, value) {
  // value is either a number (old format) or {action: freq} (new format)
  const isMulti = typeof value === 'object' && value !== null;

  if (!isMulti) {
    // Legacy single-frequency → split-bar of the open colour (width = freq).
    const freq = value || 0;
    let displayFreq = freq;
    if (viz.rngEnabled && freq > 0 && freq < 1) {
      const rng = viz.rngValues[hand] ?? 0;
      if (rng >= freq * 100) displayFreq = 0;
    }
    const open = MTX.COLORS.act.open;
    cell.style.background = displayFreq === 0 && freq > 0
      ? `repeating-linear-gradient(45deg,${open}55 0px,${open}55 4px,${open}22 4px,${open}22 8px)`
      : MTX.rfiFill(displayFreq);
    cell.style.color   = '#eef0f3';
    cell.style.opacity = displayFreq === 0 && freq > 0 ? '0.55' : '1';
    return;
  }

  // Multi-action: open + call split-bar; fold remainder = matrix empty base.
  const segs = [[MTX.COLORS.act.open, value.open || 0], [MTX.COLORS.act.call, value.call || 0]];
  cell.style.background = MTX.splitGradient(segs, MTX.COLORS.fold);
  cell.style.color   = '#eef0f3';
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

  // Build CSS gradient segments (1px divider via MTX.splitGradient).
  const A = MTX.COLORS.act;
  const COLOR = { '3bet': A['3bet'], '4bet': A['4bet'], call: A.call, fold: MTX.COLORS.fold };
  const segs = actionKeys
    .map(a => [COLOR[a], filteredActions[a] || 0])
    .filter(([, f]) => f > 0);
  cell.style.background = MTX.splitGradient(segs, COLOR.fold);

  // RNG highlight: dim non-chosen
  if (viz.rngEnabled && rngChosen) {
    cell.style.opacity = '0.4';
    const chosenColor  = COLOR[rngChosen] || COLOR.fold;
    cell.style.background = chosenColor;
    cell.style.opacity    = '1';
    if (rngChosen === 'fold') cell.style.background = COLOR.fold;
  }

  cell.style.color = '#eef0f3';
}

// ── HOVER INFO ────────────────────────────────────────
// Per-hand action frequencies now appear in a floating tooltip next to the cursor
// (static/matrix_tip.js, wired in buildMatrix) instead of the cramped #vizHover
// line above the grid. The line stays as a static hint. (Track B.3, 2026-06-15)

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
