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
// Slot 0 = hero (bottom center); rest mirrored left↔right around 50%.
// Tuned for the elongated stadium table: side seats pushed out toward the
// rounded ends, top/bottom seats on the straight long edges.
// Verified visually against GG references for 6 / 8 / 9-max.
// Topmost seats kept at >=16% so the cards tucked ABOVE them stay inside the
// table (clear of the spot-line title above it). See P-004 / card layout notes.
const SLOT_POS = {
  6: [
    { top: '91%', left: '50%' },
    { top: '80%', left: '83%' },
    { top: '22%', left: '83%' },
    { top: '16%', left: '50%' },
    { top: '22%', left: '17%' },
    { top: '80%', left: '17%' },
  ],
  8: [
    { top: '91%', left: '50%' },
    { top: '82%', left: '80%' },
    { top: '50%', left: '95%' },
    { top: '18%', left: '80%' },
    { top: '16%', left: '50%' },
    { top: '18%', left: '20%' },
    { top: '50%', left: '5%'  },
    { top: '82%', left: '20%' },
  ],
  9: [
    { top: '92%', left: '50%' },
    { top: '86%', left: '82%' },
    { top: '55%', left: '94%' },
    { top: '22%', left: '84%' },
    { top: '16%', left: '60%' },
    { top: '16%', left: '40%' },
    { top: '22%', left: '16%' },
    { top: '55%', left: '6%'  },
    { top: '86%', left: '18%' },
  ],
};

// Offsets push the posted-blind / bet chip onto open felt in front of a seat,
// toward the pot. Top seats render their stack pill BELOW the circle (toward
// center), so their chips need a larger inward (downward) offset to clear it.
const SLOT_CHIP = {
  6: [
    [   0, -38], [ -28, -28], [ -30,  44],
    [   0,  50], [  30,  44], [  28, -28],
  ],
  8: [
    [   0, -35], [ -28, -28], [ -42,   0],
    [ -30,  42], [   0,  48], [  30,  42],
    [  42,   0], [  28, -28],
  ],
  9: [
    [   0, -35], [ -25, -25], [ -42,   0],
    [ -34,  40], [ -14,  48], [  14,  48],
    [  34,  40], [  42,   0], [  25, -25],
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
    // Step 1: file list (server is the only source — UserStorage path
    // was removed in the P-001 fix; see docs/problems.md).
    try {
      const listRes   = await fetchWithTimeout('/api/ranges/list');
      state._allFiles = await listRes.json();
    } catch (e) {
      console.warn('Could not load file list:', e);
      state._allFiles = [];
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
  // All ranges live on the server now (P-001 fix). Prefer /api/ranges —
  // it returns the full normalized file with a real `spots` dict.
  // /api/config used to overwrite `spots` with a string list which broke
  // the Show Range modal, so we fall back to it only if /api/ranges fails.
  const url = filename
    ? `/api/ranges?file=${encodeURIComponent(filename)}`
    : '/api/ranges';
  let data;
  try {
    const res = await fetchWithTimeout(url);
    if (!res.ok) throw new Error('ranges endpoint not ok');
    data = await res.json();
  } catch (e) {
    console.warn('Falling back to /api/config:', e);
    const cfgUrl = filename
      ? `/api/config?file=${encodeURIComponent(filename)}`
      : '/api/config';
    const res = await fetchWithTimeout(cfgUrl);
    data = await res.json();
  }
  state.config       = data.config || data;
  state.rangeData    = data;
  state.selectedFile = filename;

  // Defensive: if the server returned `spots` as a list (legacy /api/config
  // shape), the Show Range modal would render empty. Surface a clear warning
  // and try to recover from `data.ranges` (the legacy key) if present.
  if (state.rangeData && !isPlainSpots(state.rangeData.spots)) {
    if (isPlainSpots(state.rangeData.ranges)) {
      console.warn('drillLoadConfig: spots missing/malformed, using ranges fallback.');
      state.rangeData.spots = state.rangeData.ranges;
    } else {
      console.warn('drillLoadConfig: range data lacks a usable spots dict — '
                 + 'Show Range will be empty. Restart the server so main.py reloads.');
    }
  }
}

function isPlainSpots(s) {
  return s && typeof s === 'object' && !Array.isArray(s)
      && (s.RFI || s.vs_RFI || s.vs_3bet);
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
    ? filtered.map(f => {
        // Filename is the user's chosen identity — lead with it; the
        // auto-generated label is secondary. Mirrors vizRefreshDepthOptions.
        const name = f.filename.replace(/\.json$/, '');
        const meta = (f.label && f.label !== name) ? f.label : (f.stack_depth || '');
        const text = (meta && meta !== name) ? `${name} · ${meta}` : name;
        return `<option value="${f.filename}">${text}</option>`;
      }).join('')
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
      const pfEl = document.getElementById('postflopMode');
      if (pfEl) pfEl.style.display = mode === 'postflop' ? 'grid' : 'none';
      if (mode === 'visualizer') showVisualizer();
      if (mode === 'postflop' && window.PostflopTrainer) window.PostflopTrainer.onShow();
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

  // Hint modal
  document.getElementById('fbHint').addEventListener('click', showHint);
  document.getElementById('hintCloseBtn').addEventListener('click', closeHint);
  document.getElementById('hintBackdrop').addEventListener('click', closeHint);
  // Keyboard shortcuts (Escape closes hint, Space/Enter deals, f/c/o/r/4 answer)
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') { closeHint(); return; }
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
//
// `renderSeats` is the back-compatible drill entry point — pulls everything
// it needs from drill's module state. `renderSeatsInto` is the parameterized
// engine underneath it: takes a full spec and writes to an arbitrary container.
// learn.js reuses `renderSeatsInto` so Learn Mode gets the same visual table
// without dragging in drill's state. Both share SLOT_POS / SLOT_CHIP tables.

function renderSeats(context) {
  renderSeatsInto({
    seatsId:    'seats',
    positions:  getPositions(),
    heroPos:    state.heroPos,
    spot:       state.spot,
    villainPos: state.villainPos,
    stacks:     context?.stacks,
  });
}

function renderSeatsInto(spec) {
  const wrap = document.getElementById(spec.seatsId);
  if (!wrap) return;
  wrap.innerHTML = '';
  const positions = spec.positions;
  const n = positions.length;
  const heroIdx = positions.indexOf(spec.heroPos);
  const slotArr = SLOT_POS[n] || SLOT_POS[6];

  // Optional set of folded positions. When absent, every opponent is active
  // (shows card-backs). Engine-driven fold state is a later step.
  const folded = spec.folded instanceof Set ? spec.folded : null;

  positions.forEach(pos => {
    const isHero    = pos === spec.heroPos;
    const isVillain = spec.spot !== 'RFI' && pos === spec.villainPos;
    const isDealer  = pos === 'BTN';
    const isFolded  = !isHero && folded?.has(pos);
    const posIdx    = positions.indexOf(pos);
    const slot      = (heroIdx - posIdx + n) % n;
    const sp        = slotArr[slot] || { top: '50%', left: '50%' };

    const seat = document.createElement('div');
    seat.className   = 'seat' + (isFolded ? ' is-folded' : '');
    seat.dataset.pos = pos;
    seat.style.top   = sp.top;
    seat.style.left  = sp.left;

    // Universal layout: hole cards tucked behind the avatar ABOVE the position
    // token, stack BELOW it — same for every seat. Hero's hand is the separate
    // .hero-cards element below the table, so hero has no cards on the seat.
    const avatar = document.createElement('div');
    avatar.className = 'seat-avatar';
    if (!isHero) {
      const cardsEl = document.createElement('div');
      cardsEl.className = 'seat-cards';
      cardsEl.innerHTML = '<div class="mini-back b1"></div><div class="mini-back b2"></div>';
      avatar.appendChild(cardsEl);
    }
    const circle = document.createElement('div');
    circle.className = 'seat-circle'
      + (isHero    ? ' is-hero'    : '')
      + (isVillain ? ' is-villain' : '')
      + (isDealer  ? ' is-dealer'  : '');
    circle.textContent = pos;   // position is the player's identity (no avatar art)
    avatar.appendChild(circle);

    const stack = document.createElement('div');
    stack.className = 'seat-stack';
    const stackBB = spec.stacks?.[pos] ?? 100;
    stack.textContent = stackBB.toFixed(1) + ' BB';

    // Hero gets a label; opponents are identified by the position in the token,
    // so no redundant position label under them.
    seat.appendChild(avatar);
    if (isHero) {
      const nameEl = document.createElement('div');
      nameEl.className = 'seat-name is-hero';
      nameEl.textContent = 'Hero';
      seat.appendChild(nameEl);
    }
    seat.appendChild(stack);
    wrap.appendChild(seat);
  });
}

// Chip helpers (chipBetStack, chipMakeChange, …) live in chips.js, loaded
// before this file — shared with postflop.js (single source of truth).
function renderChips(context) {
  document.querySelectorAll('.chip-stack, .chip-pot').forEach(c => c.remove());
  if (!context) return;

  const tableWrap = document.querySelector('.table-wrap');
  // Measure the live table so chips track it when scaled down on mobile.
  // SLOT_CHIP offsets were tuned for the 680x330 desktop table, so we scale
  // those px nudges by the same factor. On desktop rect == 680x330 → scale 1.
  const rect = tableWrap.getBoundingClientRect();
  const W = rect.width  || 680;
  const H = rect.height || 330;
  const sx = W / 680, sy = H / 330;
  const { pos: slotArr, chip: chipArr } = getSlotArrays();

  // Place a bet stack on the open felt in front of `pos`.
  function addBet(pos, amount) {
    const slot = slotForPos(pos);
    const sp   = slotArr[slot] || { top: '50%', left: '50%' };
    const off  = chipArr[slot] || [0, 0];
    const stack = chipBetStack(amount);
    stack.style.top  = (parseFloat(sp.top)  / 100 * H + off[1] * sy) + 'px';
    stack.style.left = (parseFloat(sp.left) / 100 * W + off[0] * sx) + 'px';
    tableWrap.appendChild(stack);
  }

  // Preflop: money is still IN FRONT of players (blinds + open + 3bet) — it
  // hasn't been collected into a central pot yet, so we do NOT also draw pot
  // chips in the middle (that would double-count the blinds). The pot SIZE is
  // shown by the .pot-block text. Centre chip stacks belong to postflop, where
  // previous-street bets are actually gathered into the pot.
  addBet('SB', 0.5);
  addBet('BB', 1);
  if (context.open_raiser && context.open_size)
    addBet(context.open_raiser, context.open_size);
  if (context.threebet_raiser && context.threebet_size)
    addBet(context.threebet_raiser, context.threebet_size);
}

// ── CARDS ─────────────────────────────────────────────
// Back-compat drill entry point. `renderCardsInto` underneath accepts target
// IDs so learn.js can render into its own card DOM.
function renderCards(card1, card2) {
  renderCardsInto(card1, card2, 'card1', 'card2');
}

function renderCardsInto(card1, card2, c1Id, c2Id) {
  const c1 = document.getElementById(c1Id);
  const c2 = document.getElementById(c2Id);
  if (!c1 || !c2) return;

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
    const url = cardSvgUrl(str);
    el.style.animationDelay = i * 0.08 + 's';

    if (url) {
      // Recolored 4-color SVG asset (see docs/roadmap.md B.1-cards).
      el.className = 'card card-svg deal-in';
      el.innerHTML = `<img src="${url}" alt="${str}" draggable="false">`;
      return;
    }
    // Fallback: legacy CSS-drawn card if the code can't be mapped.
    const isRed = '♥♦'.includes(suit);
    el.className = `card card-front ${isRed ? 'red' : 'black'} deal-in`;
    el.innerHTML = `
      <div class="card-corner">${rank}<br>${suit}</div>
      <div class="card-center">${suit}</div>
    `;
  });
}

// cardSvgUrl() now lives in cards.js (loaded before this file) — shared with
// postflop.js so the SVG asset mapping has a single source of truth.

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

    // Auto-next only fires on a correct answer. On a wrong answer the user
    // needs time to inspect the range via "Show Range" — silently advancing
    // would defeat the point of the hint button.
    if (document.getElementById('autoNextToggle').checked && result.correct) {
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

  document.getElementById('fbHint').style.display = result.correct ? 'none' : 'inline-block';

  // Show the Next button when auto-next is off, OR when the answer is wrong
  // (we paused auto-next on wrong answers so the user can read the range).
  const autoOn = document.getElementById('autoNextToggle').checked;
  const nextBtn = document.getElementById('fbNext');
  nextBtn.style.display = (autoOn && result.correct) ? 'none' : 'inline-block';
}

function hideFeedback() {
  document.getElementById('feedbackStrip').style.display = 'none';
  document.getElementById('fbHint').style.display = 'none';
}

// ── HINT (Show Range modal) ───────────────────────────
// Self-contained helpers so the modal renders independently of
// visualizer.js / editor.js script-load order or parse errors.

const HINT_RANKS     = ['A','K','Q','J','T','9','8','7','6','5','4','3','2'];
const HINT_RANKS_ASC = ['2','3','4','5','6','7','8','9','T','J','Q','K','A'];

function _hintRankVal(r) { return HINT_RANKS_ASC.indexOf(r); }

function _hintNormalize(a, b, suffix) {
  if (a === b) return a + b;
  return _hintRankVal(a) > _hintRankVal(b) ? a + b + suffix : b + a + suffix;
}

function _hintExpandNotation(notation) {
  notation = notation.trim();
  if (notation.length === 2 && notation[0] === notation[1]) return [notation];
  if (notation.length === 3 && 'so'.includes(notation[2])) return [notation];

  // 55+
  if (notation.length === 3 && notation[0] === notation[1] && notation[2] === '+') {
    const start = _hintRankVal(notation[0]);
    return HINT_RANKS_ASC.filter(r => _hintRankVal(r) >= start).map(r => r + r);
  }
  // A2s+ / A2o+
  if (notation.length === 4 && notation[3] === '+') {
    const hi = notation[0], lo = notation[1], sfx = notation[2];
    const loVal = _hintRankVal(lo), hiVal = _hintRankVal(hi);
    return HINT_RANKS_ASC
      .filter(r => _hintRankVal(r) >= loVal && _hintRankVal(r) < hiVal)
      .map(r => _hintNormalize(hi, r, sfx));
  }
  // ranges with dash
  if (notation.includes('-')) {
    const [start, end] = notation.split('-');
    if (start.length === 2 && end.length === 2) {
      const lo = Math.min(_hintRankVal(start[0]), _hintRankVal(end[0]));
      const hi = Math.max(_hintRankVal(start[0]), _hintRankVal(end[0]));
      return HINT_RANKS_ASC.filter(r => _hintRankVal(r) >= lo && _hintRankVal(r) <= hi).map(r => r + r);
    }
    if (start.length === 3 && end.length === 3) {
      const hiCard = start[0], sfx = start[2];
      const lo = Math.min(_hintRankVal(start[1]), _hintRankVal(end[1]));
      const hi = Math.max(_hintRankVal(start[1]), _hintRankVal(end[1]));
      return HINT_RANKS_ASC
        .filter(r => _hintRankVal(r) >= lo && _hintRankVal(r) <= hi)
        .map(r => _hintNormalize(hiCard, r, sfx));
    }
  }
  return [];
}

function _hintExpandRFI(raw) {
  const out = {};
  for (const [notation, value] of Object.entries(raw || {})) {
    for (const hand of _hintExpandNotation(notation)) {
      if (value && typeof value === 'object') {
        if (!out[hand]) out[hand] = {};
        for (const [act, freq] of Object.entries(value)) {
          out[hand][act] = Math.max(out[hand][act] || 0, freq);
        }
      } else {
        out[hand] = Math.max(out[hand] || 0, value || 0);
      }
    }
  }
  return out;
}

function _hintExpandActions(raw) {
  const out = {};
  for (const [notation, actions] of Object.entries(raw || {})) {
    for (const hand of _hintExpandNotation(notation)) {
      if (!out[hand]) out[hand] = {};
      for (const [act, freq] of Object.entries(actions || {})) {
        out[hand][act] = Math.max(out[hand][act] || 0, freq);
      }
    }
  }
  return out;
}

function _hintRfiColor(freq) {
  if (freq >= 1.0)  return ['#2E7D32', '#fff'];
  if (freq >= 0.75) return ['#66BB6A', '#000'];
  if (freq >= 0.5)  return ['#D4E157', '#000'];
  if (freq >  0)    return ['#FFA726', '#000'];
  return ['#1e2a22', '#3a5a44'];
}

function showHint() {
  if (!state.drillHand) return;
  const dh = state.drillHand;

  const title = dh.villain_position
    ? `${dh.spot} · ${dh.hero_position} vs ${dh.villain_position}`
    : `${dh.spot} · ${dh.hero_position}`;
  document.getElementById('hintTitle').textContent = title;

  const { range, type } = getHintRange();

  // Legend
  const legend = document.getElementById('hintLegend');
  if (type === 'RFI') {
    legend.innerHTML = [
      ['#2E7D32', '100% Open'], ['#66BB6A', '75%+'], ['#D4E157', '50%+'],
      ['#FFA726', '<50%'], ['#1e2a22;border:1px solid #2a3a2a', 'Fold'],
    ].map(([bg, label]) =>
      `<div class="hint-legend-item"><div class="hint-legend-swatch" style="background:${bg}"></div>${label}</div>`
    ).join('');
  } else {
    const isVs3bet = dh.spot === 'vs_3bet';
    legend.innerHTML = [
      [isVs3bet ? '#c0392b' : '#F44336', isVs3bet ? '4-Bet' : '3-Bet'],
      ['#3F7FB5', 'Call'],
      ['#1e2a22;border:1px solid #2a3a2a', 'Fold'],
    ].map(([bg, label]) =>
      `<div class="hint-legend-item"><div class="hint-legend-swatch" style="background:${bg}"></div>${label}</div>`
    ).join('');
  }

  // Build 13×13 grid — force inline grid layout so it can't be broken by CSS issues
  const grid = document.getElementById('hintGrid');
  grid.innerHTML = '';
  grid.style.display             = 'grid';
  grid.style.gridTemplateColumns = 'repeat(13, 1fr)';
  grid.style.gridTemplateRows    = 'repeat(13, 1fr)';
  grid.style.gap                 = '3px';
  grid.style.width               = '100%';
  grid.style.aspectRatio         = '1 / 1';

  for (let r = 0; r < 13; r++) {
    for (let c = 0; c < 13; c++) {
      const h = r === c ? HINT_RANKS[r]+HINT_RANKS[c]
              : r < c   ? HINT_RANKS[r]+HINT_RANKS[c]+'s'
              :           HINT_RANKS[c]+HINT_RANKS[r]+'o';

      const cell = document.createElement('div');
      cell.className     = 'matrix-cell';
      cell.dataset.hand  = h;

      // Inline backup styles in case .matrix-cell CSS isn't applied
      cell.style.aspectRatio    = '1 / 1';
      cell.style.display        = 'flex';
      cell.style.alignItems     = 'center';
      cell.style.justifyContent = 'center';
      cell.style.borderRadius   = '4px';
      cell.style.border         = '1px solid rgba(255,255,255,.06)';
      cell.style.overflow       = 'hidden';
      cell.style.position       = 'relative';
      cell.style.minWidth       = '0';
      cell.style.minHeight      = '0';

      if (h === dh.hand) cell.classList.add('hint-cell-current');
      colorHintCell(cell, range[h], type, dh.spot);

      const label = document.createElement('span');
      label.className   = 'cell-label';
      label.textContent = h;
      label.style.fontFamily    = 'var(--font-ui, system-ui, sans-serif)';
      label.style.fontSize      = 'clamp(7px, 1vw, 11px)';
      label.style.fontWeight    = '700';
      label.style.letterSpacing = '.3px';
      label.style.pointerEvents = 'none';
      label.style.position      = 'relative';
      label.style.zIndex        = '1';
      label.style.textShadow    = '0 1px 3px rgba(0,0,0,.7)';
      cell.appendChild(label);
      grid.appendChild(cell);
    }
  }

  document.getElementById('hintHandNote').innerHTML =
    `Dealt hand: <strong style="color:var(--gold);font-size:13px">${dh.hand}</strong>` +
    ` &nbsp;·&nbsp; ${dh.card1} ${dh.card2}`;

  document.getElementById('hintOverlay').classList.add('open');
}

function closeHint() {
  document.getElementById('hintOverlay').classList.remove('open');
}

function getHintRange() {
  if (!state.rangeData?.spots) return { range: {}, type: 'RFI' };
  const spots = state.rangeData.spots;
  const dh    = state.drillHand;
  if (dh.spot === 'RFI') {
    return { range: _hintExpandRFI(spots.RFI?.[dh.hero_position] || {}), type: 'RFI' };
  }
  const key = `vs_${dh.villain_position}`;
  if (dh.spot === 'vs_RFI') {
    return { range: _hintExpandActions(spots.vs_RFI?.[dh.hero_position]?.[key] || {}), type: 'vs' };
  }
  if (dh.spot === 'vs_3bet') {
    return { range: _hintExpandActions(spots.vs_3bet?.[dh.hero_position]?.[key] || {}), type: 'vs' };
  }
  return { range: {}, type: 'RFI' };
}

function colorHintCell(cell, value, type, spot) {
  if (value == null || (typeof value === 'object' && Object.keys(value).length === 0)) {
    cell.style.background = '#1e2a22';
    cell.style.color      = '#3a5a44';
    return;
  }

  if (type === 'RFI') {
    if (typeof value === 'number') {
      const [bg, fg] = _hintRfiColor(value);
      cell.style.background = bg;
      cell.style.color      = fg;
    } else {
      cell.style.background = _hintGradient(value, { open:'#2E7D32', call:'#3F7FB5', fold:'#1e2a22' }, ['open','call','fold']);
      cell.style.color      = '#fff';
    }
  } else {
    const colors = { '3bet':'#F44336', call:'#3F7FB5', '4bet':'#c0392b', fold:'#1e2a22' };
    const order  = spot === 'vs_3bet' ? ['4bet','call','fold'] : ['3bet','call','fold'];
    cell.style.background = _hintGradient(value, colors, order);
    cell.style.color      = '#fff';
  }
}

function _hintGradient(value, colorMap, order) {
  let cum = 0; const stops = [];
  for (const a of order) {
    const isLast = a === order[order.length - 1];
    const f = value[a] ?? (isLast ? Math.max(0, 1 - Object.values(value).reduce((s,v)=>s+v, 0)) : 0);
    if (f <= 0) continue;
    stops.push(`${colorMap[a]||'#333'} ${Math.round(cum*100)}% ${Math.round((cum+f)*100)}%`);
    cum += f;
  }
  return stops.length ? `linear-gradient(to right,${stops.join(',')})` : '#1e2a22';
}

// ── SPOT LINE ─────────────────────────────────────────
function updateSpotLine() {
  const v = state.villainPos ? ` · ${state.heroPos} vs ${state.villainPos}` : ` · ${state.heroPos}`;
  document.getElementById('spotLine').textContent = state.spot + v;
}

// ── TIMER ─────────────────────────────────────────────
const ARC_LEN = 1624; // stadium-ring perimeter in SVG units (matches #timerArc rect)

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
    state._allFiles = await res.json();
  } catch (e) {
    state._allFiles = [];
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