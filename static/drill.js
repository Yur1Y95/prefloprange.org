// ── STATE ────────────────────────────────────────────
const state = {
  config:       null,
  spot:         'RFI',
  heroPos:      'UTG',
  villainPos:   null,
  heroMode:     'fixed',
  villainMode:  'fixed',
  drillHand:    null,
  waiting:      false,
  timer:        { id: null, left: 8, total: 8 },
  autoNext:     { id: null },
  gameType:     'Cash',
  selectedFile: '',      // empty = default cash file
  _allFiles:    [],
};

// ── SLOT POSITIONS BY PLAYER COUNT ───────────────────
const SLOT_POS = {
  6: [
    { top: '88%', left: '50%' },
    { top: '78%', left: '80%' },
    { top: '14%', left: '80%' },
    { top: '6%',  left: '50%' },
    { top: '14%', left: '20%' },
    { top: '78%', left: '20%' },
  ],
  8: [
    { top: '90%', left: '50%' },
    { top: '80%', left: '78%' },
    { top: '50%', left: '95%' },
    { top: '14%', left: '78%' },
    { top: '6%',  left: '50%' },
    { top: '14%', left: '22%' },
    { top: '50%', left: '5%'  },
    { top: '80%', left: '22%' },
  ],
  9: [
    { top: '90%', left: '50%' },
    { top: '80%', left: '76%' },
    { top: '52%', left: '95%' },
    { top: '20%', left: '86%' },
    { top: '6%',  left: '62%' },
    { top: '6%',  left: '38%' },
    { top: '20%', left: '14%' },
    { top: '52%', left: '5%'  },
    { top: '80%', left: '24%' },
  ],
};

const SLOT_CHIP = {
  6: [
    [   0, -38], [ -28, -28], [ -28,  28],
    [   0,  32], [  28,  28], [  28, -28],
  ],
  8: [
    [   0, -35], [ -28, -28], [ -42,   0],
    [ -28,  25], [   0,  30], [  28,  25],
    [  42,   0], [  28, -28],
  ],
  9: [
    [   0, -35], [ -25, -25], [ -42,   0],
    [ -32,  22], [ -12,  30], [  12,  30],
    [  32,  22], [  42,   0], [  25, -25],
  ],
};

function getPositions() {
  return state.config?.positions || ['UTG', 'MP', 'CO', 'BTN', 'SB', 'BB'];
}

function slotForPos(pos) {
  const positions = getPositions();
  const n         = positions.length;
  const heroIdx   = positions.indexOf(state.heroPos);
  const posIdx    = positions.indexOf(pos);
  return (heroIdx - posIdx + n) % n;
}

function getSlotArrays() {
  const n = getPositions().length;
  return {
    pos:  SLOT_POS[n]  || SLOT_POS[6],
    chip: SLOT_CHIP[n] || SLOT_CHIP[6],
  };
}

// ── BOOT ─────────────────────────────────────────────
// ── FETCH WITH TIMEOUT ───────────────────────────────
async function fetchWithTimeout(url, options = {}, ms = 5000) {
  const controller = new AbortController();
  const timeout    = setTimeout(() => controller.abort(), ms);
  try {
    const res = await fetch(url, { ...options, signal: controller.signal });
    clearTimeout(timeout);
    return res;
  } catch (e) {
    clearTimeout(timeout);
    throw e;
  }
}
window._fetchWithTimeout = fetchWithTimeout;

// ── BOOT ─────────────────────────────────────────────
async function boot() {
  try {
    // Step 1: file list
    try {
      const listRes   = await fetchWithTimeout('/api/ranges/list');
      const server    = await listRes.json();
      state._allFiles = [...server, ...UserStorage.allFileEntries()];
    } catch (e) {
      console.warn('Could not load file list:', e);
      state._allFiles = UserStorage.allFileEntries();
    }

    // Step 2: config
    try {
      await drillLoadConfig('');
    } catch (e) {
      console.warn('Could not load config:', e);
    }

    if (!state.config) {
      console.error('Boot: no config loaded, aborting');
      return;
    }

    bindEvents();
    drillRenderFormatSelectors();
    renderHeroButtons();
    renderVillainSection();
    renderSeats();

    // Step 3: stats + history (non-blocking)
    loadStats().catch(() => {});
    loadHistory().catch(() => {});

    // Step 4: first hand
    await newHand();

  } catch (e) {
    console.error('Boot failed:', e);
  }
}

async function drillLoadConfig(filename) {
  let data;
  if (!filename) {
    const res = await fetchWithTimeout('/api/config');
    data = await res.json();
  } else if (filename.startsWith('user:')) {
    data = UserStorage.load(filename.slice(5));
    if (!data) throw new Error('User range not found: ' + filename);
  } else {
    const res = await fetchWithTimeout(`/api/config?file=${encodeURIComponent(filename)}`);
    data = await res.json();
  }
  state.config       = data.config || data;
  state.rangeData    = data;
  state.selectedFile = filename;
}

function drillRenderFormatSelectors() {
  const select    = document.getElementById('dDepthSelect');
  const tableSize = (document.getElementById('dTableSelect')?.value || '').toLowerCase().replace('-','');
  if (!select) return;

  const filtered = state._allFiles.filter(f => {
    const gameMatch  = f.game_type === state.gameType;
    const tableMatch = !tableSize || (f.table_size || '').toLowerCase().replace('-','') === tableSize;
    return gameMatch && tableMatch;
  });

  select.innerHTML = filtered.length
    ? filtered.map(f => `<option value="${f.filename}">${f.label || f.stack_depth}</option>`).join('')
    : '<option value="">No ranges</option>';
  state.selectedFile = filtered.length ? filtered[0].filename : '';
}

// ── EVENT BINDINGS ────────────────────────────────────
function bindEvents() {
  // Game type buttons
  document.querySelectorAll('[data-dgame]').forEach(btn => {
    btn.addEventListener('click', async () => {
      state.gameType = btn.dataset.dgame;
      document.querySelectorAll('[data-dgame]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      drillRenderFormatSelectors();
      await drillLoadConfig(state.selectedFile);
      renderHeroButtons();
      renderVillainSection();
      renderSeats();
      newHand();
    });
  });

  // Table size dropdown (drill)
  const dTable = document.getElementById('dTableSelect');
  if (dTable) {
    dTable.addEventListener('change', async () => {
      drillRenderFormatSelectors();
      await drillLoadConfig(state.selectedFile);
      renderHeroButtons();
      renderVillainSection();
      renderSeats();
      newHand();
    });
  }

  // Depth dropdown
  const dDepth = document.getElementById('dDepthSelect');
  if (dDepth) {
    dDepth.addEventListener('change', async () => {
      state.selectedFile = dDepth.value;
      await drillLoadConfig(state.selectedFile);
      renderHeroButtons();
      renderVillainSection();
      renderSeats();
      newHand();
    });
  }

  // Mode tabs (top nav)
  document.querySelectorAll('.mode-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.mode-tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const mode = btn.dataset.mode;
      document.getElementById('drillMode').style.display     = mode === 'drill'      ? 'grid' : 'none';
      document.getElementById('vizMode').style.display       = mode === 'visualizer' ? 'grid' : 'none';
      document.getElementById('analyzerMode').style.display  = mode === 'analyzer'   ? 'grid' : 'none';
      document.getElementById('editorMode').style.display    = mode === 'editor'     ? 'grid' : 'none';
      if (mode === 'visualizer') showVisualizer();
    });
  });

  // Right panel tabs (Stats / History)
  document.querySelectorAll('.right-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.right-tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const tab = btn.dataset.rtab;
      document.getElementById('statsView').style.display   = tab === 'stats'   ? 'contents' : 'none';
      document.getElementById('historyView').style.display = tab === 'history' ? 'flex'     : 'none';
      if (tab === 'history') loadHistory();
    });
  });

  // Spot buttons
  document.querySelectorAll('.seg[data-spot]').forEach(btn => {
    btn.addEventListener('click', () => {
      state.spot = btn.dataset.spot;
      document.querySelectorAll('.seg[data-spot]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      if (state.spot === 'RFI' && !state.config.rfi_positions.includes(state.heroPos)) {
        state.heroPos = state.config.rfi_positions[0];
      }
      renderHeroButtons();
      renderVillainSection();
      renderSeats();
      newHand();
    });
  });

  // Hero/villain mode selects
  document.getElementById('heroMode').addEventListener('change', e => {
    state.heroMode = e.target.value;
    const heroBtns = document.getElementById('heroBtns');
    heroBtns.style.opacity = state.heroMode === 'random' ? '.4' : '1';
    heroBtns.style.pointerEvents = state.heroMode === 'random' ? 'none' : 'auto';
    newHand();
  });
  document.getElementById('villainMode').addEventListener('change', e => {
    state.villainMode = e.target.value;
    const vBtns = document.getElementById('villainBtns');
    vBtns.style.opacity = state.villainMode === 'random' ? '.4' : '1';
    vBtns.style.pointerEvents = state.villainMode === 'random' ? 'none' : 'auto';
    newHand();
  });

  // Options
  document.getElementById('timerToggle').addEventListener('change', e => {
    if (!e.target.checked) stopTimer();
  });

  // Deal & next
  document.getElementById('newHandBtn').addEventListener('click', newHand);
  document.getElementById('fbNext').addEventListener('click', newHand);
  document.getElementById('resetBtn').addEventListener('click', resetStats);
  document.getElementById('clearHistoryBtn').addEventListener('click', clearHistory);

  // Keyboard shortcuts
  document.addEventListener('keydown', e => {
    if (!state.waiting) {
      if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); newHand(); }
      return;
    }
    const map = { f: 'fold', c: 'call', o: 'open', r: '3bet', '4': '4bet' };
    if (map[e.key]) submitAnswer(map[e.key]);
  });
}

// ── POSITION BUTTONS ─────────────────────────────────
function renderHeroButtons() {
  const wrap = document.getElementById('heroBtns');
  wrap.innerHTML = '';
  const positions = state.spot === 'RFI'
    ? state.config.rfi_positions
    : state.config.positions;

  positions.forEach(pos => {
    const btn = document.createElement('button');
    btn.className = 'pos-btn' + (pos === state.heroPos ? ' active' : '');
    btn.textContent = pos;
    btn.addEventListener('click', () => {
      state.heroPos = pos;
      renderHeroButtons();
      renderVillainSection();
      renderSeats();
      newHand();
    });
    wrap.appendChild(btn);
  });
}

function renderVillainSection() {
  const group = document.getElementById('villainGroup');
  if (state.spot === 'RFI') {
    group.style.display = 'none';
    state.villainPos = null;
    return;
  }
  group.style.display = 'flex';

  const optMap = state.spot === 'vs_RFI'
    ? state.config.vs_rfi_options
    : (state.config.vs_3bet_options || {});
  const available = optMap[state.heroPos] || [];

  if (!available.includes(state.villainPos)) {
    state.villainPos = available[0] || null;
  }

  const wrap = document.getElementById('villainBtns');
  wrap.innerHTML = '';
  available.forEach(pos => {
    const btn = document.createElement('button');
    btn.className = 'pos-btn' + (pos === state.villainPos ? ' active' : '');
    btn.textContent = pos;
    btn.addEventListener('click', () => {
      state.villainPos = pos;
      renderVillainSection();
      renderSeats();
      newHand();
    });
    wrap.appendChild(btn);
  });
}

// ── TABLE RENDERING ───────────────────────────────────
function renderSeats(context) {
  const wrap = document.getElementById('seats');
  wrap.innerHTML = '';

function renderSeats(context) {
  const wrap      = document.getElementById('seats');
  wrap.innerHTML  = '';
  const positions = getPositions();
  const { pos: slotArr } = getSlotArrays();

  positions.forEach(pos => {
    const isHero    = pos === state.heroPos;
    const isVillain = state.spot !== 'RFI' && pos === state.villainPos;
    const isDealer  = pos === 'BTN';
    const slot      = slotForPos(pos);
    const sp        = slotArr[slot] || { top: '50%', left: '50%' };

    const seat = document.createElement('div');
    seat.className   = 'seat';
    seat.dataset.pos = pos;
    seat.style.top   = sp.top;
    seat.style.left  = sp.left;

    const circle = document.createElement('div');
    circle.className = 'seat-circle'
      + (isHero    ? ' is-hero'    : '')
      + (isVillain ? ' is-villain' : '')
      + (isDealer  ? ' is-dealer'  : '');
    circle.textContent = pos;

    const name = document.createElement('div');
    name.className = 'seat-name' + (isHero ? ' is-hero' : '');
    name.textContent = isHero ? 'YOU' : (isVillain ? 'VILLAIN' : pos);

    const stack = document.createElement('div');
    stack.className = 'seat-stack';
    const stackBB = context?.stacks?.[pos] ?? 100;
    stack.textContent = stackBB.toFixed(1) + ' BB';

    seat.appendChild(circle);
    seat.appendChild(name);
    seat.appendChild(stack);
    wrap.appendChild(seat);
  });
}

function renderChips(context) {
  document.querySelectorAll('.bet-chip').forEach(c => c.remove());
  if (!context) return;

  const tableWrap = document.querySelector('.table-wrap');
  const W = 560, H = 360;
  const { pos: slotArr, chip: chipArr } = getSlotArrays();

  function addChip(pos, text, cls) {
    const slot  = slotForPos(pos);
    const sp    = slotArr[slot]  || { top: '50%', left: '50%' };
    const off   = chipArr[slot] || [0, 0];
    const top   = parseFloat(sp.top)  / 100 * H + off[1];
    const left  = parseFloat(sp.left) / 100 * W + off[0];

    const chip = document.createElement('div');
    chip.className   = `bet-chip ${cls}`;
    chip.textContent = text;
    chip.style.top   = top  + 'px';
    chip.style.left  = left + 'px';
    tableWrap.appendChild(chip);
  }

  addChip('SB', '0.5', 'chip-sb');
  addChip('BB', '1',   'chip-bb');
  if (context.open_raiser && context.open_size)
    addChip(context.open_raiser, context.open_size.toFixed(1), 'chip-open');
  if (context.threebet_raiser && context.threebet_size)
    addChip(context.threebet_raiser, context.threebet_size.toFixed(1), 'chip-3bet');
}

// ── CARDS ─────────────────────────────────────────────
function renderCards(card1, card2) {
  const c1 = document.getElementById('card1');
  const c2 = document.getElementById('card2');

  if (!card1) {
    c1.className = 'card card-back';
    c2.className = 'card card-back';
    c1.innerHTML = '';
    c2.innerHTML = '';
    return;
  }

  [{ el: c1, str: card1 }, { el: c2, str: card2 }].forEach(({ el, str }, i) => {
    const suit = str.slice(-1);
    const rank = str.slice(0, -1);
    const isRed = '♥♦'.includes(suit);
    el.className = `card card-front ${isRed ? 'red' : 'black'} deal-in`;
    el.style.animationDelay = i * 0.08 + 's';
    el.innerHTML = `
      <div class="card-corner">${rank}<br>${suit}</div>
      <div class="card-center">${suit}</div>
    `;
  });
}

// ── ACTION BUTTONS ────────────────────────────────────
function renderActionButtons(actions) {
  const bar = document.getElementById('actionBar');
  bar.innerHTML = '';
  const labels = { open: 'Open', fold: 'Fold', call: 'Call', '3bet': '3-Bet', '4bet': '4-Bet' };
  actions.forEach(action => {
    const btn = document.createElement('button');
    btn.className = `action-btn btn-${action}`;
    btn.textContent = labels[action] || action;
    btn.addEventListener('click', () => submitAnswer(action));
    bar.appendChild(btn);
  });
}

function setActionButtonsDisabled(disabled) {
  document.querySelectorAll('.action-btn').forEach(b => b.disabled = disabled);
}

// ── DEAL HAND ─────────────────────────────────────────
async function newHand() {
  stopTimer();
  clearAutoNext();
  hideFeedback();
  state.waiting = false;
  state.drillHand = null;

  renderCards(null, null);
  updateSpotLine();

  let url = `/api/drill/hand?spot=${state.spot}&hero_position=${state.heroPos}`;
  if (state.heroMode === 'random')   url += '&random_hero=true';
  if (state.spot !== 'RFI') {
    if (state.villainMode === 'random') url += '&random_villain=true';
    else if (state.villainPos)          url += `&villain_position=${state.villainPos}`;
  }
  if (state.selectedFile) url += `&file=${encodeURIComponent(state.selectedFile)}`;

  try {
    const res = await fetch(url);
    if (!res.ok) { console.warn('No range for this spot'); return; }
    state.drillHand = await res.json();

    // Sync positions if random was used
    if (state.heroMode   === 'random') state.heroPos    = state.drillHand.hero_position;
    if (state.villainMode === 'random' && state.drillHand.villain_position)
      state.villainPos = state.drillHand.villain_position;

    const ctx = state.drillHand.context || {};

    renderSeats(ctx);
    renderChips(ctx);
    renderCards(state.drillHand.card1, state.drillHand.card2);
    renderActionButtons(state.drillHand.available_actions);
    setActionButtonsDisabled(false);

    document.getElementById('potValue').textContent =
      (ctx.pot ? ctx.pot.toFixed(1) : '1.5') + ' BB';
    document.getElementById('actionLog').textContent =
      ctx.action_log?.join(' · ') || '';

    updateSpotLine();
    state.waiting = true;

    if (document.getElementById('timerToggle').checked) startTimer();
  } catch (e) {
    console.error('newHand error:', e);
  }
}

// ── SUBMIT ANSWER ─────────────────────────────────────
async function submitAnswer(action, isTimeout = false) {
  if (!state.waiting || !state.drillHand) return;
  state.waiting = false;
  stopTimer();
  setActionButtonsDisabled(true);

  try {
    const res = await fetch('/api/drill/answer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        drill_hand:    state.drillHand,
        player_action: isTimeout ? 'fold' : action,
        is_timeout:    isTimeout,
      }),
    });
    const result = await res.json();
    showFeedback(result);
    loadStats();
    loadHistory();

    if (document.getElementById('autoNextToggle').checked) {
      state.autoNext.id = setTimeout(newHand, 1400);
    }
  } catch (e) {
    console.error('submitAnswer error:', e);
  }
}

// ── FEEDBACK ──────────────────────────────────────────
function showFeedback(result) {
  const strip = document.getElementById('feedbackStrip');
  strip.style.display = 'flex';
  strip.className = 'feedback-strip ' + (result.correct ? 'correct' : 'wrong');

  document.getElementById('fbIcon').textContent = result.correct ? '✓' : '✗';
  document.getElementById('fbMsg').textContent  = result.message;

  const ev  = result.ev ?? 0;
  const evEl = document.getElementById('fbEv');
  evEl.textContent  = (ev >= 0 ? '+' : '') + ev + ' BB';
  evEl.className    = 'fb-ev ' + (ev >= 0 ? 'pos' : 'neg');

  const nextBtn = document.getElementById('fbNext');
  nextBtn.style.display = document.getElementById('autoNextToggle').checked ? 'none' : 'inline-block';
}

function hideFeedback() {
  document.getElementById('feedbackStrip').style.display = 'none';
}

// ── SPOT LINE ─────────────────────────────────────────
function updateSpotLine() {
  const v = state.villainPos ? ` · ${state.heroPos} vs ${state.villainPos}` : ` · ${state.heroPos}`;
  document.getElementById('spotLine').textContent = state.spot + v;
}

// ── TIMER ─────────────────────────────────────────────
const ARC_LEN = 1340; // approximate ellipse circumference in SVG units

function startTimer() {
  state.timer.left  = state.timer.total;
  const ring = document.getElementById('timerRing');
  const arc  = document.getElementById('timerArc');
  ring.style.display = 'block';
  arc.style.stroke = '#c9a84c';
  arc.setAttribute('stroke-dashoffset', '0');

  state.timer.id = setInterval(() => {
    state.timer.left--;
    const pct    = state.timer.left / state.timer.total;
    const offset = ARC_LEN * (1 - pct);
    arc.setAttribute('stroke-dashoffset', offset.toString());

    if (state.timer.left <= 3) arc.style.stroke = '#c0392b';

    if (state.timer.left <= 0) {
      stopTimer();
      submitAnswer('fold', true);
    }
  }, 1000);
}

function stopTimer() {
  clearInterval(state.timer.id);
  state.timer.id = null;
  const ring = document.getElementById('timerRing');
  if (ring) ring.style.display = 'none';
}

// ── STATS ─────────────────────────────────────────────
async function loadStats() {
  try {
    const res   = await fetch('/api/stats');
    const stats = await res.json();
    renderStats(stats);
  } catch { /* silent */ }
}

function renderStats(stats) {
  let total = 0, correct = 0;
  const rows = [];

  for (const spot in stats) {
    for (const key in stats[spot]) {
      const d = stats[spot][key];
      total   += d.total   || 0;
      correct += d.correct || 0;
      if (d.total > 0) {
        const pct = Math.round(d.correct / d.total * 100);
        rows.push({ label: key, pct, d });
      }
    }
  }

  const pct = total > 0 ? Math.round(correct / total * 100) : 0;
  document.getElementById('sessionPill').innerHTML =
    `${correct} / ${total} &nbsp;·&nbsp; ${total > 0 ? pct + '%' : '—'}`;

  // Summary
  const summary = document.getElementById('statsSummary');
  summary.innerHTML = `
    <div class="stat-row"><span class="stat-key">Hands</span><span class="stat-val">${total}</span></div>
    <div class="stat-row"><span class="stat-key">Correct</span><span class="stat-val">${correct}</span></div>
    <div class="stat-row">
      <span class="stat-key">Accuracy</span>
      <span class="stat-val ${pct >= 70 ? 'good' : total > 0 ? 'bad' : ''}">${total > 0 ? pct + '%' : '—'}</span>
    </div>
  `;

  // Breakdown
  const breakdown = document.getElementById('statsBreakdown');
  breakdown.innerHTML = rows.map(({ label, pct: p, d }) => `
    <div class="breakdown-row">
      <div>
        <div class="bd-key">${label}</div>
        <div class="bd-bar" style="width:${Math.min(p, 100)}px"></div>
      </div>
      <span class="bd-val ${p >= 70 ? 'good' : 'bad'}">${p}%</span>
    </div>
  `).join('');
}

async function resetStats() {
  await fetch('/api/stats/reset', { method: 'POST' });
  loadStats();
}

// ── AUTO-NEXT HELPER ─────────────────────────────────
function clearAutoNext() {
  if (state.autoNext.id) {
    clearTimeout(state.autoNext.id);
    state.autoNext.id = null;
  }
}

// ── REFRESH FILE LIST (called from editor after save) ─
async function drillRefreshFileList() {
  try {
    const res    = await fetch('/api/ranges/list');
    const server = await res.json();
    state._allFiles = [...server, ...UserStorage.allFileEntries()];
  } catch (e) {
    state._allFiles = UserStorage.allFileEntries();
  }
  drillRenderFormatSelectors();
}

// ── HISTORY ───────────────────────────────────────────
async function loadHistory() {
  try {
    const res     = await fetch('/api/history?limit=100');
    const entries = await res.json();
    renderHistory(entries);
  } catch { /* silent */ }
}

function renderHistory(entries) {
  const list = document.getElementById('historyList');
  if (!entries.length) {
    list.innerHTML = '<div style="color:var(--text-dim);font-size:12px;padding:8px;">No hands yet.</div>';
    return;
  }

  list.innerHTML = entries.map(e => {
    const isMatch   = e.correct;
    const isTimeout = e.is_timeout;
    const cls       = isTimeout ? 'h-timeout' : isMatch ? 'h-correct' : 'h-wrong';
    const evSign    = e.ev >= 0 ? '+' : '';
    const evCls     = e.ev >= 0 ? 'pos' : 'neg';
    const spot      = e.villain_position
      ? `${e.spot} · ${e.hero_position} vs ${e.villain_position}`
      : `${e.spot} · ${e.hero_position}`;

    const playerBadge = isMatch
      ? `<span class="h-action-badge badge-match">${e.player_action}</span>`
      : `<span class="h-action-badge badge-player-action">${e.player_action}</span>
         <span style="color:var(--text-dim);font-size:10px;">→</span>
         <span class="h-action-badge badge-correct-action">${e.correct_action}</span>`;

    const timeoutBadge = isTimeout
      ? '<span class="h-action-badge" style="background:rgba(230,126,34,.2);color:#e67e22">TIMEOUT</span>' : '';

    return `
      <div class="history-entry ${cls}">
        <div class="h-top">
          <span class="h-hand">${e.card1} ${e.card2}</span>
          <span class="h-ev ${evCls}">${evSign}${e.ev} BB</span>
        </div>
        <div class="h-detail">${spot} · ${e.ts}</div>
        <div class="h-actions">${playerBadge}${timeoutBadge}</div>
      </div>
    `;
  }).join('');
}

async function clearHistory() {
  await fetch('/api/history/clear', { method: 'POST' });
  loadHistory();
}

// ── START ─────────────────────────────────────────────
boot();
}