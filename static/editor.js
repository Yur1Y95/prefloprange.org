// ── LOCAL HELPERS (self-contained, no dependency on visualizer.js) ───────────
const _RANKS_ED  = ['A','K','Q','J','T','9','8','7','6','5','4','3','2'];

function handName(r, c) {
  if (r === c) return _RANKS_ED[r] + _RANKS_ED[c];
  if (r < c)   return _RANKS_ED[r] + _RANKS_ED[c] + 's';
  return _RANKS_ED[c] + _RANKS_ED[r] + 'o';
}

function comboCnt(hand) {
  if (hand.length === 2)      return 6;
  if (hand.endsWith('s'))     return 4;
  return 12;
}

function rfiColor(freq) {
  if (freq >= 1.0)  return ['#2E7D32', '#fff'];
  if (freq >= 0.75) return ['#66BB6A', '#000'];
  if (freq >= 0.5)  return ['#D4E157', '#000'];
  if (freq > 0)     return ['#FFA726', '#000'];
  return ['#1e2a22', '#3a5a44'];
}

// ── EDITOR STATE ─────────────────────────────────────
const ed = {
  // File config
  gameType:  'MTT',
  tableSize: '8max',
  depth:     '100',

  // Spot config
  spot:       'RFI',
  heroPos:    'UTG',
  villainPos: null,

  // Paint tools
  action:    'open',
  freq:      100,
  isDragging: false,

  // Full range being built:
  // ranges.RFI[heroPos][hand]                        = frequency (0..1)
  // ranges.vs_RFI[heroPos][`vs_${vPos}`][hand]       = {action: freq, ...}
  // ranges.vs_3bet[heroPos][`vs_${vPos}`][hand]      = {action: freq, ...}
  ranges: { RFI: {}, vs_RFI: {}, vs_3bet: {} },
};

// ── POSITION CONFIGS ──────────────────────────────────
const POS_CONFIGS = {
  'mtt_8max': {
    positions: ['UTG','UTG+1','MP','HJ','CO','BTN','SB','BB'],
    rfi:       ['UTG','UTG+1','MP','HJ','CO','BTN','SB'],
    vs_rfi: {
      'UTG+1': ['UTG'],
      'MP':    ['UTG','UTG+1'],
      'HJ':    ['UTG','UTG+1','MP'],
      'CO':    ['UTG','UTG+1','MP','HJ'],
      'BTN':   ['UTG','UTG+1','MP','HJ','CO'],
      'SB':    ['UTG','UTG+1','MP','HJ','CO','BTN'],
      'BB':    ['UTG','UTG+1','MP','HJ','CO','BTN','SB'],
    },
    vs_3bet: {
      'UTG':   ['UTG+1','MP','HJ','CO','BTN','SB','BB'],
      'UTG+1': ['MP','HJ','CO','BTN','SB','BB'],
      'MP':    ['HJ','CO','BTN','SB','BB'],
      'HJ':    ['CO','BTN','SB','BB'],
      'CO':    ['BTN','SB','BB'],
      'BTN':   ['SB','BB'],
      'SB':    ['BB'],
    },
  },
  'mtt_9max': {
    positions: ['UTG','UTG+1','UTG+2','MP','HJ','CO','BTN','SB','BB'],
    rfi:       ['UTG','UTG+1','UTG+2','MP','HJ','CO','BTN','SB'],
    vs_rfi: {
      'UTG+1': ['UTG'],
      'UTG+2': ['UTG','UTG+1'],
      'MP':    ['UTG','UTG+1','UTG+2'],
      'HJ':    ['UTG','UTG+1','UTG+2','MP'],
      'CO':    ['UTG','UTG+1','UTG+2','MP','HJ'],
      'BTN':   ['UTG','UTG+1','UTG+2','MP','HJ','CO'],
      'SB':    ['UTG','UTG+1','UTG+2','MP','HJ','CO','BTN'],
      'BB':    ['UTG','UTG+1','UTG+2','MP','HJ','CO','BTN','SB'],
    },
    vs_3bet: {
      'UTG':   ['UTG+1','UTG+2','MP','HJ','CO','BTN','SB','BB'],
      'UTG+1': ['UTG+2','MP','HJ','CO','BTN','SB','BB'],
      'UTG+2': ['MP','HJ','CO','BTN','SB','BB'],
      'MP':    ['HJ','CO','BTN','SB','BB'],
      'HJ':    ['CO','BTN','SB','BB'],
      'CO':    ['BTN','SB','BB'],
      'BTN':   ['SB','BB'],
      'SB':    ['BB'],
    },
  },
  'cash_6max': {
    positions: ['UTG','MP','CO','BTN','SB','BB'],
    rfi:       ['UTG','MP','CO','BTN','SB'],
    vs_rfi: {
      'MP':  ['UTG'],
      'CO':  ['UTG','MP'],
      'BTN': ['UTG','MP','CO'],
      'SB':  ['UTG','MP','CO','BTN'],
      'BB':  ['UTG','MP','CO','BTN','SB'],
    },
    vs_3bet: {
      'UTG': ['MP','CO','BTN','SB','BB'],
      'MP':  ['CO','BTN','SB','BB'],
      'CO':  ['BTN','SB','BB'],
      'BTN': ['SB','BB'],
      'SB':  ['BB'],
    },
  },
};

// Action colours matching the main palette
const ACTION_COLORS = {
  open:  '#0c3a1a',
  '3bet':'#7a1a2e',
  call:  '#0b2d52',
  '4bet':'#2a0c3a',
  fold:  '#1a1a1a',
};
const ACTION_TEXT_COLORS = {
  open:  '#7effa8',
  '3bet':'#ffb3c0',
  call:  '#7ec8ff',
  '4bet':'#e0b3ff',
  fold:  '#aaa',
};

// ── HELPERS ───────────────────────────────────────────
function edPosConfig() {
  const key = `${ed.gameType.toLowerCase()}_${ed.tableSize}`;
  return POS_CONFIGS[key] || POS_CONFIGS['mtt_8max'];
}

function edRangeKey() {
  // Returns the current sub-range object being edited
  const cfg = ed.ranges;
  if (ed.spot === 'RFI') {
    if (!cfg.RFI[ed.heroPos]) cfg.RFI[ed.heroPos] = {};
    return cfg.RFI[ed.heroPos];
  }
  const spotObj = cfg[ed.spot];
  if (!spotObj[ed.heroPos]) spotObj[ed.heroPos] = {};
  const villainKey = `vs_${ed.villainPos}`;
  if (!spotObj[ed.heroPos][villainKey]) spotObj[ed.heroPos][villainKey] = {};
  return spotObj[ed.heroPos][villainKey];
}

// ── QUICK SELECT GROUPS ───────────────────────────────
const QS_GROUPS = {
  'pairs-all':   () => allPairs(),
  'pairs-prem':  () => pairsRange('A','J'),
  'pairs-med':   () => pairsRange('T','7'),
  'pairs-small': () => pairsRange('6','2'),
  's-bw':  () => suitedRange([['A','K'],['A','Q'],['A','J'],['A','T'],['K','Q'],['K','J'],['K','T'],['Q','J'],['Q','T'],['J','T']]),
  's-ax':  () => suitedRange([['A','K'],['A','Q'],['A','J'],['A','T'],['A','9'],['A','8'],['A','7'],['A','6'],['A','5'],['A','4'],['A','3'],['A','2']]),
  's-kx':  () => suitedRange([['K','Q'],['K','J'],['K','T'],['K','9'],['K','8'],['K','7'],['K','6'],['K','5'],['K','4'],['K','3'],['K','2']]),
  's-sc':  () => suitedRange([['J','T'],['T','9'],['9','8'],['8','7'],['7','6'],['6','5'],['5','4']]),
  's-og':  () => suitedRange([['J','9'],['T','8'],['9','7'],['8','6'],['7','5'],['6','4'],['5','3']]),
  'o-bw':  () => offsuitRange([['A','K'],['A','Q'],['A','J'],['A','T'],['K','Q'],['K','J'],['K','T'],['Q','J'],['Q','T'],['J','T']]),
  'o-ax':  () => offsuitRange([['A','K'],['A','Q'],['A','J'],['A','T'],['A','9'],['A','8'],['A','7'],['A','6'],['A','5'],['A','4'],['A','3'],['A','2']]),
  'all-ax': () => [...suitedRange([['A','K'],['A','Q'],['A','J'],['A','T'],['A','9'],['A','8'],['A','7'],['A','6'],['A','5'],['A','4'],['A','3'],['A','2']]),
                   ...offsuitRange([['A','K'],['A','Q'],['A','J'],['A','T'],['A','9'],['A','8'],['A','7'],['A','6'],['A','5'],['A','4'],['A','3'],['A','2']])],
  'all-bw': () => {
    const bw = ['A','K','Q','J','T'];
    const hands = [];
    for (let i = 0; i < bw.length; i++)
      for (let j = i+1; j < bw.length; j++) {
        hands.push(bw[i]+bw[j]+'s');
        hands.push(bw[i]+bw[j]+'o');
      }
    return [...allPairs().filter(h => ['AA','KK','QQ','JJ','TT'].includes(h)), ...hands];
  },
};

const _RANKS_ORDER = ['A','K','Q','J','T','9','8','7','6','5','4','3','2'];

function allPairs() {
  return _RANKS_ORDER.map(r => r + r);
}

function pairsRange(hi, lo) {
  const hiIdx = _RANKS_ORDER.indexOf(hi);
  const loIdx = _RANKS_ORDER.indexOf(lo);
  return _RANKS_ORDER.slice(hiIdx, loIdx + 1).map(r => r + r);
}

function suitedRange(pairs) {
  return pairs.map(([a, b]) => a + b + 's');
}

function offsuitRange(pairs) {
  return pairs.map(([a, b]) => a + b + 'o');
}

function edApplyQuickSelect(groupKey) {
  const hands = QS_GROUPS[groupKey]?.();
  if (!hands) return;
  hands.forEach(hand => {
    // Only paint hands that exist in the 13x13 matrix
    if (document.querySelector(`#editorMatrix [data-hand="${hand}"]`))
      edPaintHand(hand);
  });
}

// ── QUICK SELECT POPUP BINDING ────────────────────────
function bindQsPopup() {
  const trigger = document.getElementById('qsTrigger');
  const popup   = document.getElementById('qsPopup');
  if (!trigger || !popup) return;

  trigger.addEventListener('click', e => {
    e.stopPropagation();
    const isOpen = popup.style.display !== 'none';
    if (isOpen) {
      popup.style.display = 'none';
      trigger.classList.remove('open');
      return;
    }

    // Position popup: open to the left of the trigger, aligned to its top
    const rect   = trigger.getBoundingClientRect();
    const popupW = 430;
    const left   = Math.max(8, rect.left - popupW - 8);
    popup.style.top    = rect.bottom + 6 + 'px';
    popup.style.left   = left + 'px';
    popup.style.display = 'flex';
    trigger.classList.add('open');
  });

  popup.querySelectorAll('.qs-btn').forEach(btn => {
    btn.addEventListener('click', e => {
      e.stopPropagation();
      edApplyQuickSelect(btn.dataset.qs);
      popup.style.display = 'none';
      trigger.classList.remove('open');
    });
  });

  document.addEventListener('click', () => {
    popup.style.display = 'none';
    trigger.classList.remove('open');
  });
}

// ── BOOT ─────────────────────────────────────────────
function editorBoot() {
  edBindEvents();
  bindQsPopup();
  edRenderControls();
  edBuildMatrix();
  edUpdateMatrix();
  edUpdateFilename();
}

// ── EVENTS ────────────────────────────────────────────
function edBindEvents() {
  // Format selects
  ['eGameType','eTableSize','eDepth'].forEach(id => {
    document.getElementById(id).addEventListener('change', () => {
      ed.gameType  = document.getElementById('eGameType').value;
      ed.tableSize = document.getElementById('eTableSize').value;
      ed.depth     = document.getElementById('eDepth').value;
      ed.heroPos   = edPosConfig().rfi[0];
      ed.villainPos = null;
      edRenderControls();
      edUpdateMatrix();
      edUpdateFilename();
    });
  });

  // Spot buttons
  document.querySelectorAll('[data-espot]').forEach(btn => {
    btn.addEventListener('click', () => {
      ed.spot = btn.dataset.espot;
      document.querySelectorAll('[data-espot]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      edRenderControls();
      edUpdateMatrix();
    });
  });

  // Paint action buttons
  document.querySelectorAll('[data-action]').forEach(btn => {
    btn.addEventListener('click', () => {
      ed.action = btn.dataset.action;
      document.querySelectorAll('[data-action]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
    });
  });

  // Frequency slider
  const slider = document.getElementById('freqSlider');
  slider.addEventListener('input', () => {
    ed.freq = parseInt(slider.value);
    document.getElementById('freqVal').textContent = ed.freq + '%';
    document.querySelectorAll('.qf-btn').forEach(b => b.classList.remove('active'));
  });

  // Quick freq buttons
  document.querySelectorAll('.qf-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      ed.freq = parseInt(btn.dataset.freq);
      slider.value = ed.freq;
      document.getElementById('freqVal').textContent = ed.freq + '%';
      document.querySelectorAll('.qf-btn').forEach(b =>
        b.classList.toggle('active', parseInt(b.dataset.freq) === ed.freq)
      );
    });
  });

  // Save
  document.getElementById('eSaveBtn').addEventListener('click', edSave);

  // Clear all
  document.getElementById('eClearAllBtn').addEventListener('click', () => {
    const range = edRangeKey();
    Object.keys(range).forEach(k => delete range[k]);
    edUpdateMatrix();
  });

  // Matrix drag
  const matrix = document.getElementById('editorMatrix');
  matrix.addEventListener('mousedown', e => {
    ed.isDragging = true;
    edPaintFromEvent(e);
  });
  matrix.addEventListener('mouseover', e => {
    if (ed.isDragging) edPaintFromEvent(e);
  });
  document.addEventListener('mouseup', () => { ed.isDragging = false; });
}

function edPaintFromEvent(e) {
  const cell = e.target.closest('.matrix-cell');
  if (!cell) return;
  edPaintHand(cell.dataset.hand);
}

// ── POSITION CONTROLS ─────────────────────────────────
function edRenderControls() {
  const cfg = edPosConfig();

  // Hero buttons
  const heroWrap = document.getElementById('eHeroBtns');
  heroWrap.innerHTML = '';
  const heroPositions = ed.spot === 'RFI' ? cfg.rfi : cfg.positions;

  if (!heroPositions.includes(ed.heroPos)) ed.heroPos = heroPositions[0];

  heroPositions.forEach(pos => {
    const btn = document.createElement('button');
    btn.className = 'pos-btn' + (pos === ed.heroPos ? ' active' : '');
    btn.textContent = pos;
    btn.addEventListener('click', () => {
      ed.heroPos = pos;
      edRenderControls();
      edUpdateMatrix();
    });
    heroWrap.appendChild(btn);
  });

  // Villain
  const vGroup = document.getElementById('eVillainGroup');
  if (ed.spot === 'RFI') {
    vGroup.style.display = 'none';
    ed.villainPos = null;
    return;
  }

  vGroup.style.display = 'flex';
  const available = (ed.spot === 'vs_RFI' ? cfg.vs_rfi : cfg.vs_3bet)[ed.heroPos] || [];
  if (!available.includes(ed.villainPos)) ed.villainPos = available[0] || null;

  const vWrap = document.getElementById('eVillainBtns');
  vWrap.innerHTML = '';
  available.forEach(pos => {
    const btn = document.createElement('button');
    btn.className = 'pos-btn' + (pos === ed.villainPos ? ' active' : '');
    btn.textContent = pos;
    btn.addEventListener('click', () => {
      ed.villainPos = pos;
      edRenderControls();
      edUpdateMatrix();
    });
    vWrap.appendChild(btn);
  });
}

// ── BUILD MATRIX ──────────────────────────────────────
function edBuildMatrix() {
  const grid = document.getElementById('editorMatrix');
  grid.innerHTML = '';

  for (let r = 0; r < 13; r++) {
    for (let c = 0; c < 13; c++) {
      const h    = handName(r, c);   // from visualizer.js
      const cell = document.createElement('div');
      cell.className    = 'matrix-cell';
      cell.dataset.hand = h;

      const label = document.createElement('span');
      label.className   = 'cell-label';
      label.textContent = h;
      cell.appendChild(label);

      cell.addEventListener('mouseenter', () => edShowHover(h));
      grid.appendChild(cell);
    }
  }
}

// ── PAINT A HAND ─────────────────────────────────────
function edPaintHand(hand) {
  const range = edRangeKey();
  const freq  = ed.freq / 100;

  if (ed.action === 'clear') {
    delete range[hand];
    edRenderCell(hand);
    edUpdateStats();
    return;
  }

  // RFI and vs spots both use {action: freq} map
  if (!range[hand]) range[hand] = {};

  if (freq === 0) {
    delete range[hand][ed.action];
    if (Object.keys(range[hand]).length === 0) delete range[hand];
  } else {
    range[hand][ed.action] = freq;

    // Cap total to 1.0
    const total = Object.values(range[hand]).reduce((s, v) => s + v, 0);
    if (total > 1.0) {
      const excess = total - 1.0;
      const others = Object.keys(range[hand]).filter(a => a !== ed.action);
      const otherTotal = others.reduce((s, a) => s + range[hand][a], 0);
      if (otherTotal > 0) {
        others.forEach(a => {
          range[hand][a] = Math.max(0, range[hand][a] - excess * (range[hand][a] / otherTotal));
          if (range[hand][a] < 0.01) delete range[hand][a];
        });
      }
    }
  }

  edRenderCell(hand);
  edUpdateStats();
}

// ── RENDER SINGLE CELL ────────────────────────────────
function edRenderCell(hand) {
  const cell  = document.querySelector(`#editorMatrix [data-hand="${hand}"]`);
  if (!cell) return;
  const range = edRangeKey();
  const value = range[hand];

  if (!value || Object.keys(value).length === 0) {
    cell.style.background = '#1e2a22';
    cell.style.color      = '#3a5a44';
    return;
  }

  // Action colour map — open uses RFI green, call uses blue, fold dark
  const COLOR = {
    open:  '#2E7D32',
    call:  '#3F7FB5',
    '3bet':'#F44336',
    '4bet':'#c0392b',
    fold:  '#232b26',
  };

  const actionOrder = ed.spot === 'vs_3bet'
    ? ['4bet', 'call', 'fold']
    : ed.spot === 'vs_RFI'
    ? ['3bet', 'call', 'fold']
    : ['open', 'call', 'fold'];  // RFI

  let cum = 0;
  const stops = [];

  for (const a of actionOrder) {
    const f = value[a] || (a === 'fold'
      ? Math.max(0, 1 - Object.values(value).reduce((s,v)=>s+v,0))
      : 0);
    if (f <= 0) continue;
    stops.push(`${COLOR[a] || '#333'} ${Math.round(cum*100)}% ${Math.round((cum+f)*100)}%`);
    cum += f;
  }

  cell.style.background = stops.length
    ? `linear-gradient(to right, ${stops.join(', ')})`
    : '#1e2a22';
  cell.style.color = '#fff';
}

// ── UPDATE ALL CELLS ──────────────────────────────────
function edUpdateMatrix() {
  for (let r = 0; r < 13; r++)
    for (let c = 0; c < 13; c++)
      edRenderCell(handName(r, c));
  edUpdateStats();
}

// ── HOVER INFO ────────────────────────────────────────
function edShowHover(hand) {
  const el    = document.getElementById('editorHover');
  const range = edRangeKey();
  const value = range[hand];

  if (!value) { el.textContent = `${hand}: empty — click to paint`; return; }

  if (ed.spot === 'RFI') {
    el.textContent = `${hand}: open ${Math.round(value * 100)}%`;
  } else {
    const parts = Object.entries(value)
      .filter(([,f]) => f > 0)
      .map(([a,f]) => `${a} ${Math.round(f*100)}%`);
    el.textContent = `${hand}: ${parts.join(' / ')}`;
  }
}

// ── STATS ─────────────────────────────────────────────
const TOTAL_COMBOS = 1326;

function edUpdateStats() {
  const range = edRangeKey();
  let combos  = 0;

  for (const [hand, value] of Object.entries(range)) {
    const cnt = comboCnt(hand);
    if (!value || typeof value !== 'object') continue;
    const total = Object.values(value).reduce((s,v) => s+v, 0);
    combos += cnt * Math.min(1, total);
  }

  document.getElementById('eCombos').textContent = combos.toFixed(0);
  document.getElementById('ePct').textContent    = (combos / TOTAL_COMBOS * 100).toFixed(1) + '%';
  document.getElementById('editorStatus').textContent =
    `${ed.spot} · ${ed.heroPos}${ed.villainPos ? ' vs ' + ed.villainPos : ''} · ${combos.toFixed(0)} combos`;
}

// ── AUTO FILENAME ─────────────────────────────────────
function edUpdateFilename() {
  const fn = `${ed.gameType.toLowerCase()}_${ed.tableSize}_${ed.depth}bb`;
  document.getElementById('eSaveFilename').placeholder = fn;
}

// ── SAVE ──────────────────────────────────────────────
async function edSave() {
  const inputEl = document.getElementById('eSaveFilename');
  const cfg     = edPosConfig();

  const rawName  = inputEl.value.trim() || inputEl.placeholder;
  const filename = rawName.endsWith('.json') ? rawName : rawName + '.json';

  const rangeData = {
    meta: {
      game_type:   ed.gameType,
      table_size:  ed.tableSize,
      stack_depth: ed.depth + 'bb',
      label:       `${ed.gameType} ${ed.tableSize} ${ed.depth}bb`,
    },
    config: {
      positions:       cfg.positions,
      rfi_positions:   cfg.rfi,
      vs_rfi_options:  cfg.vs_rfi,
      vs_3bet_options: cfg.vs_3bet,
    },
    spots: ed.ranges,
  };

  const saveBtn = document.getElementById('eSaveBtn');
  saveBtn.textContent = 'Saving…';
  saveBtn.disabled    = true;

  try {
    const res    = await fetch('/api/ranges/save', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ filename: rawName, range_data: rangeData }),
    });
    const result = await res.json();

    if (result.status === 'saved') {
      saveBtn.textContent = '✓ Saved!';
      saveBtn.style.background    = 'rgba(39,174,96,.25)';
      saveBtn.style.borderColor   = '#27ae60';
      saveBtn.style.color         = '#2ecc71';
      inputEl.value = '';

      // Refresh drill file list so new range appears immediately
      if (typeof drillRefreshFileList === 'function') drillRefreshFileList();

      setTimeout(() => {
        saveBtn.textContent          = 'Save Range';
        saveBtn.style.background     = '';
        saveBtn.style.borderColor    = '';
        saveBtn.style.color          = '';
        saveBtn.disabled             = false;
      }, 2000);
    } else {
      throw new Error('Server returned non-saved status');
    }
  } catch (e) {
    saveBtn.textContent = '✗ Error';
    saveBtn.style.borderColor = '#e74c3c';
    saveBtn.style.color       = '#e74c3c';
    setTimeout(() => {
      saveBtn.textContent       = 'Save Range';
      saveBtn.style.borderColor = '';
      saveBtn.style.color       = '';
      saveBtn.disabled          = false;
    }, 2000);
  }
}

function edShowSaveToast(msg) {
  const t = document.getElementById('toast');
  if (t) {
    t.textContent = msg;
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 2500);
  }
}

// ── SHOW EDITOR (called from drill.js mode switcher) ──
function showEditor() {
  document.getElementById('drillMode').style.display     = 'none';
  document.getElementById('vizMode').style.display       = 'none';
  document.getElementById('analyzerMode').style.display  = 'none';
  document.getElementById('editorMode').style.display    = 'grid';
}

// ── BOOT ─────────────────────────────────────────────
editorBoot();