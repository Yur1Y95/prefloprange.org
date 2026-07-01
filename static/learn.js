// ============================================================================
// learn.js — Spaced Repetition Learn Mode
//
// Stage 3 (current): card screen — fetches /api/srs/next, renders the poker
// table (reusing drill.js's renderSeatsInto + renderCardsInto), wires action
// buttons to POST /api/srs/answer. After answering, immediately advances to
// the next card; no visible reveal yet (Stage 4 will insert that step).
//
// Roadmap:
//   Stage 4 — reveal: thin feedback strip with verdict + Next, same shape as
//             drill's feedback-strip.
//   Stage 5 — end-of-session summary when queue_size hits 0.
//
// Answer options: the committed poker actions (fold/open/call/3bet/4bet/allin/
// raise — the aggressive name varies by spot) plus
// "Показать ответ" — an honest "I don't know" that reveals the answer and
// grades AGAIN, so a forced 50/50 guess can't register as correct. The old
// Anki-style Easy button was removed (CLAUDE.md decision #6).
// ============================================================================

(() => {
  'use strict';

  const learnMode = document.getElementById('learnMode');
  if (!learnMode) {
    console.warn('[learn.js] #learnMode not found — index.html out of sync?');
    return;
  }

  // ── DOM references ───────────────────────────────────────────────────────
  // Entry screen
  const entrySec   = document.getElementById('learnEntry');
  const cardSec    = document.getElementById('learnCard');
  const revealSec  = document.getElementById('learnReveal');
  const fileSelect = document.getElementById('learnFileSelect');
  const scopeBtns  = document.querySelectorAll('#learnScopeBtns [data-lscope]');
  const scopeLockedHint = document.getElementById('learnScopeLockedHint');
  const limitBtns  = document.querySelectorAll('#learnLimitBtns [data-llimit]');
  const autoNextToggle = document.getElementById('learnAutoNextToggle');
  const counters   = document.getElementById('learnCounters');
  const startBtn   = document.getElementById('learnStartBtn');
  const resetBtn   = document.getElementById('learnResetBtn');
  const statusMsg  = document.getElementById('learnStatusMsg');
  const numEls = {
    total:   document.getElementById('lcTotal'),
    due:     document.getElementById('lcDue'),
    new:     document.getElementById('lcNew'),
    learned: document.getElementById('lcLearned'),
  };

  // Card screen
  const spotLine    = document.getElementById('learnSpotLine');
  const potValue    = document.getElementById('learnPotValue');
  const actionBar   = document.getElementById('learnActionBar');
  const queueBadge  = document.getElementById('learnQueueBadge');
  const backBtn     = document.getElementById('learnBackBtn');
  const endBtn      = document.getElementById('learnEndBtn');
  // Reveal strip (shown after each answer, holds the verdict + Next)
  const feedbackStrip = document.getElementById('learnFeedbackStrip');
  const lfbVerdict    = document.getElementById('lfbVerdict');
  const learnNextBtn  = document.getElementById('learnNextBtn');

  // Summary screen (Stage 5 — shown when the day's queue is empty)
  const summarySec        = document.getElementById('learnSummary');
  const summaryCloseBtn   = document.getElementById('learnSummaryCloseBtn');
  const summaryNums = {
    answered: document.getElementById('lsAnswered'),
    correct:  document.getElementById('lsCorrect'),
    accuracy: document.getElementById('lsAccuracy'),
    shown:    document.getElementById('lsShown'),
  };

  // Auto-Next delay (ms): how long the verdict stays visible before auto-advancing.
  const AUTO_NEXT_MS = 1000;

  // ── State ────────────────────────────────────────────────────────────────
  const state = {
    filesLoaded:    false,
    currentFile:    '',
    selectedScope:  'all',          // 'all' | 'RFI' | 'vs_RFI' | 'vs_3bet'
    newLimit:       15,             // new cards/day; 0 = unlimited (sent as a big number)
    autoNext:       true,           // auto-advance to the next card after a normal answer
    autoNextTimer:  null,           // pending setTimeout id for the auto-advance (so we can cancel it)
    initialized:    false,
    rangeConfigs:   {},             // file -> {positions: [...]} cache
    currentCard:    null,           // card payload from /api/srs/next
    // Reveal-state buffering: when the action is answered, we hold onto the
    // next card and the answered card's id until the user clicks Next. This
    // is what lets the reveal strip persist.
    bufferedNext:        null,
    bufferedQueueSize:   0,
    lastAnsweredCardId:  null,
    lastAnswerCorrect:   false,
    // Session counters — reset every time the user clicks "Учить" from
    // entry. Used to populate the end-of-session summary screen.
    session: {
      answered: 0,
      correct:  0,
      shown:    0,   // times the user pressed "Показать ответ" (didn't know)
    },
  };

  function resetSession() {
    state.session.answered = 0;
    state.session.correct  = 0;
    state.session.shown    = 0;
  }

  // The daily new-card cap to send to the API. The "∞" button is stored as 0;
  // translate it to a number large enough to never clip any deck (max ~5915).
  function effectiveNewLimit() {
    return state.newLimit === 0 ? 100000 : state.newLimit;
  }

  // ── Tab switching ────────────────────────────────────────────────────────
  document.querySelectorAll('.mode-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      const mode = btn.dataset.mode;
      learnMode.style.display = (mode === 'learn') ? 'grid' : 'none';
      if (mode === 'learn') onLearnShow();
    });
  });

  async function onLearnShow() {
    if (!state.filesLoaded) {
      await loadFiles();
    }
    if (state.currentFile) {
      await refreshStatus();
    }
    showEntryScreen();
  }

  // ── File list ────────────────────────────────────────────────────────────
  async function loadFiles() {
    try {
      const res = await fetch('/api/ranges/list');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const files = await res.json();
      fileSelect.innerHTML = '';
      if (!files.length) {
        const opt = document.createElement('option');
        opt.value = ''; opt.textContent = '— no range files in data/ —';
        fileSelect.appendChild(opt);
        fileSelect.disabled = true;
        startBtn.disabled = true;
        startBtn.textContent = 'No deck available';
        return;
      }
      for (const f of files) {
        const opt = document.createElement('option');
        opt.value = f.filename;
        // Show "filename · label" to match Drill/Visualizer (P-008): the label
        // alone is ambiguous (several packs auto-label "Cash 6max 100bb").
        const name = f.filename.replace(/\.json$/, '');
        const meta = (f.label && f.label !== name) ? f.label : (f.stack_depth || '');
        opt.textContent = (meta && meta !== name) ? `${name} · ${meta}` : name;
        fileSelect.appendChild(opt);
      }
      state.currentFile = files[0].filename;
      state.filesLoaded = true;
      fileSelect.disabled = false;
    } catch (e) {
      console.error('[learn.js] /api/ranges/list failed:', e);
      showStatus(`Failed to load range list: ${e.message}`, true, true);
      startBtn.disabled = true;
      startBtn.textContent = 'Error — see console';
    }
  }

  // ── Status fetch + entry-screen render ───────────────────────────────────
  async function refreshStatus() {
    clearStatus();
    try {
      const url = `/api/srs/status?file=${encodeURIComponent(state.currentFile)}`;
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status} — is srs_router mounted in main.py? Did you restart the server?`);
      const data = await res.json();
      state.initialized = !!data.initialized;
      renderEntryState(data);
    } catch (e) {
      console.error('[learn.js] /api/srs/status failed:', e);
      startBtn.disabled = true;
      startBtn.textContent = `Error: ${e.message}`;
      showStatus(`Status fetch failed: ${e.message}`, true, true);
    }
  }

  function renderEntryState(status) {
    if (status.initialized) {
      counters.style.display = 'grid';
      numEls.total.textContent   = status.total   ?? '—';
      numEls.due.textContent     = status.due_today ?? '—';
      numEls.new.textContent     = status.new     ?? '—';
      numEls.learned.textContent = status.learned ?? '—';
      startBtn.disabled    = false;
      startBtn.textContent = 'Учить';
      resetBtn.style.display = '';
      lockScopePicker(true);
    } else {
      counters.style.display = 'none';
      startBtn.disabled    = false;
      startBtn.textContent = 'Начать обучение';
      resetBtn.style.display = 'none';
      lockScopePicker(false);
    }
  }

  function lockScopePicker(locked) {
    scopeBtns.forEach(b => {
      b.disabled = locked;
      b.style.opacity = locked ? '0.4'  : '';
      b.style.cursor  = locked ? 'not-allowed' : '';
    });
    scopeLockedHint.style.display = locked ? '' : 'none';
  }

  // ── Scope picker clicks ──────────────────────────────────────────────────
  scopeBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      if (btn.disabled) return;
      scopeBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.selectedScope = btn.dataset.lscope;
    });
  });

  // ── New-cards/day picker ─────────────────────────────────────────────────
  // Not locked after init (unlike scope): it's a cap on today's queue, not part
  // of the deck, so the user can change it between sessions freely.
  limitBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      limitBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.newLimit = parseInt(btn.dataset.llimit, 10);
    });
  });

  // ── Auto-Next toggle (lives on the card screen, flip during a session) ────
  // Auto-advance to the next card after a normal answer. Off = old behaviour
  // (manual "Дальше"). Button label + .is-on class reflect the state.
  function renderAutoNextToggle() {
    if (!autoNextToggle) return;
    autoNextToggle.textContent = `Auto-Next: ${state.autoNext ? 'On' : 'Off'}`;
    autoNextToggle.classList.toggle('is-on', state.autoNext);
  }
  if (autoNextToggle) {
    autoNextToggle.addEventListener('click', () => {
      state.autoNext = !state.autoNext;
      if (!state.autoNext) clearAutoNext();   // turning it off cancels a pending advance
      renderAutoNextToggle();
    });
    renderAutoNextToggle();
  }

  // ── File dropdown changes ────────────────────────────────────────────────
  fileSelect.addEventListener('change', async () => {
    state.currentFile = fileSelect.value;
    await refreshStatus();
  });

  // ── Start button ─────────────────────────────────────────────────────────
  startBtn.addEventListener('click', async () => {
    if (!state.currentFile) return;
    clearStatus();
    startBtn.disabled = true;
    if (!state.initialized) {
      const ok = await initDeck();
      if (!ok) { startBtn.disabled = false; return; }
      await refreshStatus();
    }
    await ensureRangeConfig(state.currentFile);
    resetSession();              // fresh counters for the summary screen
    await goToNextCard();
    startBtn.disabled = false;
  });

  async function initDeck() {
    try {
      const body = { file: state.currentFile };
      if (state.selectedScope !== 'all') body.scope = [state.selectedScope];
      const res = await fetch('/api/srs/init', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail || `HTTP ${res.status}`);
      }
      return true;
    } catch (e) {
      console.error('[learn.js] /api/srs/init failed:', e);
      showStatus(`Init failed: ${e.message}`, true, true);
      return false;
    }
  }

  // ── Reset button ─────────────────────────────────────────────────────────
  resetBtn.addEventListener('click', async () => {
    if (!state.currentFile) return;
    const ok = window.confirm(
      `Сбросить весь прогресс по этой колоде? Все ответы и интервалы будут стёрты.\n\nФайл: ${state.currentFile}`
    );
    if (!ok) return;
    try {
      const url = `/api/srs/reset?file=${encodeURIComponent(state.currentFile)}`;
      const res = await fetch(url, { method: 'POST' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      showStatus('Progress reset.');
      await refreshStatus();
    } catch (e) {
      console.error('[learn.js] /api/srs/reset failed:', e);
      showStatus(`Reset failed: ${e.message}`, true, true);
    }
  });

  // ── Range config (positions list) — cached per file ──────────────────────
  // The card screen needs to know what positions exist around the table to
  // place seats. Fetched lazily on first Start click for each file.
  async function ensureRangeConfig(file) {
    if (state.rangeConfigs[file]) return;
    try {
      const res = await fetch(`/api/ranges?file=${encodeURIComponent(file)}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const positions = data?.config?.positions
                     || ['UTG', 'MP', 'CO', 'BTN', 'SB', 'BB'];
      state.rangeConfigs[file] = { positions };
    } catch (e) {
      console.error('[learn.js] /api/ranges failed:', e);
      // Fall back to 6-max defaults — better than crashing
      state.rangeConfigs[file] = { positions: ['UTG', 'MP', 'CO', 'BTN', 'SB', 'BB'] };
      showStatus(`Range config fetch failed (${e.message}); using defaults`, true);
    }
  }

  // ── Card flow: fetch next, render, handle action ─────────────────────────
  async function goToNextCard() {
    try {
      const url = `/api/srs/next?file=${encodeURIComponent(state.currentFile)}`
                + `&new_limit=${effectiveNewLimit()}`;
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const card = data.card;
      if (!card) {
        showEndOfSession();
        return;
      }
      state.currentCard = card;
      renderCardScreen(card, data.queue_size);
      showCardScreen();
    } catch (e) {
      console.error('[learn.js] /api/srs/next failed:', e);
      showStatus(`Next card fetch failed: ${e.message}`, true, true);
      showEntryScreen();
    }
  }

  function renderCardScreen(card, queueSize) {
    // Defensive cleanup: any stale reveal from a previous card must go,
    // and action buttons must be live again. Cheap to do on every render.
    hideReveal();
    setActionButtonsDisabled(false);

    const positions = state.rangeConfigs[state.currentFile]?.positions
                   || ['UTG', 'MP', 'CO', 'BTN', 'SB', 'BB'];

    // Preflop money context (posted blinds, reduced stacks, raiser bets, pot) so
    // the Learn table matches Drill. Drill gets this from the server; Learn has
    // only the SRS card (spot/position/villain) and recomputes it client-side.
    const ctx = buildLearnContext(positions, card.position, card.spot,
                                  card.villain_position || null);

    // Seats — delegates to drill.js's parameterized renderer
    window.renderSeatsInto({
      seatsId:    'learnSeats',
      positions:  positions,
      heroPos:    card.position,
      spot:       card.spot,
      villainPos: card.villain_position || null,
      stacks:     ctx.stacks,
    });

    // Posted blinds + raiser chips on Learn's own felt (same renderer as Drill).
    window.renderChipsInto({
      seatsId:   'learnSeats',
      positions: positions,
      heroPos:   card.position,
      context:   ctx,
    });

    // Pot pill — real per-spot size, not the static 1.5 default.
    if (potValue) potValue.textContent = ctx.pot.toFixed(1) + ' BB';

    // Cards — sample a concrete two-card combo from the hand notation
    const [c1, c2] = sampleCombo(card.hand);
    window.renderCardsInto(c1, c2, 'learnCard1', 'learnCard2');

    // Spot line
    spotLine.textContent = formatSpotLine(card);

    // Action buttons (Fold first, then aggressive)
    renderActionButtons(card.spot);

    // Queue badge
    queueBadge.textContent = `${queueSize} in queue`;
  }

  function formatSpotLine(card) {
    if (card.spot === 'RFI')
      return `RFI · ${card.position}`;
    if (card.spot === 'vs_RFI')
      return `vs RFI · ${card.position} vs ${card.villain_position}`;
    if (card.spot === 'vs_3bet')
      return `vs 3-Bet · ${card.position} vs ${card.villain_position}`;
    if (card.spot === 'vs_4bet')
      return `vs 4-Bet · ${card.position} vs ${card.villain_position}`;
    if (card.spot === 'iso')
      return `ISO · ${card.position} vs ${card.villain_position}`;
    return card.spot;
  }

  // Build the preflop money context for a Learn card — posted blinds, reduced
  // stacks, raiser bets, and pot — so the table matches Drill. This MIRRORS the
  // per-spot math in drill_engine.py (get_drill_hand_*). Drill receives this
  // from the server; Learn only has the SRS card (spot/position/villain), so it
  // is recomputed here. The bet sizes MUST stay in sync with drill_engine's
  // constants (OPEN_SIZE / THREEBET_MULT / FOURBET_MULT / ISO_SIZE). Verified
  // numerically against the engine in test_drill_blinds.py.
  function buildLearnContext(positions, heroPos, spot, villainPos) {
    const SB = 0.5, BB = 1, OPEN = 2.5, TB_MULT = 3.5, FB_MULT = 2.5;
    const r1 = x => Math.round(x * 10) / 10;   // round to 0.1, like the engine

    const stacks = {};
    positions.forEach(p => { stacks[p] = 100; });
    if ('SB' in stacks) stacks.SB = r1(stacks.SB - SB);
    if ('BB' in stacks) stacks.BB = r1(stacks.BB - BB);
    let pot = r1(SB + BB);
    const ctx = { stacks, pot, open_raiser: null, open_size: 0 };

    if (spot === 'vs_RFI' && villainPos) {
      stacks[villainPos] = r1(stacks[villainPos] - OPEN);          // villain opens
      pot = r1(pot + OPEN);
      ctx.open_raiser = villainPos; ctx.open_size = OPEN;
    } else if (spot === 'vs_3bet' && villainPos) {
      stacks[heroPos]    = r1(stacks[heroPos] - OPEN);             // hero opened
      pot = r1(pot + OPEN);
      const tb = r1(OPEN * TB_MULT);
      stacks[villainPos] = r1(stacks[villainPos] - tb);            // villain 3-bets
      pot = r1(pot + tb);
      ctx.open_raiser = heroPos;     ctx.open_size = OPEN;
      ctx.threebet_raiser = villainPos; ctx.threebet_size = tb;
    } else if (spot === 'vs_4bet' && villainPos) {
      stacks[villainPos] = r1(stacks[villainPos] - OPEN);          // villain opens
      pot = r1(pot + OPEN);
      const tb = r1(OPEN * TB_MULT);
      stacks[heroPos]    = r1(stacks[heroPos] - tb);               // hero 3-bets
      pot = r1(pot + tb);
      const fb = r1(OPEN * TB_MULT * FB_MULT);
      const fbAdd = r1(fb - OPEN);
      stacks[villainPos] = r1(stacks[villainPos] - fbAdd);         // villain 4-bets
      pot = r1(pot + fbAdd);
      ctx.open_raiser = heroPos;        ctx.open_size = OPEN;
      ctx.threebet_raiser = heroPos;    ctx.threebet_size = tb;
      ctx.fourbet_raiser = villainPos;  ctx.fourbet_size = fb;
    } else if (spot === 'iso' && villainPos) {
      stacks[villainPos] = r1(stacks[villainPos] - BB);            // villain limps
      pot = r1(pot + BB);
      ctx.open_raiser = villainPos; ctx.open_size = BB;
    }
    ctx.pot = pot;
    return ctx;
  }

  function actionsForSpot(spot) {
    // Fold first, then the aggressive line, then passive call (where it exists).
    // Aggressive action name per spot mirrors the range JSON keys (CLAUDE.md):
    // vs_4bet uses "allin" (Raise+Allin collapse), iso uses "raise".
    if (spot === 'RFI')      return ['fold', 'open'];
    if (spot === 'vs_RFI')   return ['fold', 'call', '3bet'];
    if (spot === 'vs_3bet')  return ['fold', 'call', '4bet'];
    if (spot === 'vs_4bet')  return ['fold', 'call', 'allin'];
    if (spot === 'iso')      return ['fold', 'call', 'raise'];
    return ['fold'];
  }

  const ACTION_LABELS = {
    fold: 'Fold', open: 'Open', call: 'Call', '3bet': '3-Bet', '4bet': '4-Bet',
    allin: 'All-in', raise: 'Raise',
  };

  function renderActionButtons(spot) {
    actionBar.innerHTML = '';
    actionsForSpot(spot).forEach(action => {
      const btn = document.createElement('button');
      btn.className   = `action-btn btn-${action}`;
      btn.textContent = ACTION_LABELS[action] || action;
      btn.addEventListener('click', () => handleAction(action));
      actionBar.appendChild(btn);
    });
    // "Показать ответ" — the honest "I don't know" escape from the forced
    // binary. Pressing it reveals the answer and grades AGAIN, so a guess the
    // user couldn't actually make never registers as a correct answer.
    const revealBtn = document.createElement('button');
    revealBtn.className   = 'action-btn btn-reveal';
    revealBtn.textContent = 'Показать ответ';
    revealBtn.addEventListener('click', handleReveal);
    actionBar.appendChild(revealBtn);
  }

  // A committed poker action (fold/open/call/3bet/4bet).
  function handleAction(action) {
    return submitAnswer({ user_action: action });
  }

  // "Показать ответ" — user didn't know; reveal + grade AGAIN.
  function handleReveal() {
    return submitAnswer({ reveal: true });
  }

  async function submitAnswer(extra) {
    if (!state.currentCard) return;
    setActionButtonsDisabled(true);
    try {
      const res = await fetch('/api/srs/answer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          file:      state.currentFile,
          card_id:   state.currentCard.card_id,
          new_limit: effectiveNewLimit(),
          ...extra,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      console.log('[learn.js] grade:', data.grading,
                  '· next queue:', data.queue_size);
      // Session tallies — feed the end-of-session summary
      state.session.answered += 1;
      if (data.grading.in_strategy)  state.session.correct += 1;
      if (data.grading.revealed)     state.session.shown   += 1;
      // Buffer the next card and reveal the verdict. Action buttons stay
      // disabled until the user clicks Next.
      showReveal(data.grading, data.card, data.next, data.queue_size);
    } catch (e) {
      console.error('[learn.js] /api/srs/answer failed:', e);
      showStatus(`Answer submit failed: ${e.message}`, true, true);
      setActionButtonsDisabled(false);
    }
  }

  function showReveal(grading, answeredCard, nextCard, queueSize) {
    state.bufferedNext       = nextCard;
    state.bufferedQueueSize  = queueSize;
    state.lastAnsweredCardId = answeredCard.card_id;
    state.lastAnswerCorrect  = !!grading.in_strategy;

    const correct = answeredCard.dominant_action;
    const correctLabel = ACTION_LABELS[correct] || correct;
    if (grading.revealed) {
      // Honest "don't know": neutral framing, no ✗ shame. Graded AGAIN.
      lfbVerdict.textContent = `Answer: ${correctLabel}`;
      lfbVerdict.className = 'lfb-verdict revealed';
    } else if (grading.in_strategy) {
      const label = ACTION_LABELS[grading.user_action] || grading.user_action;
      lfbVerdict.textContent = `✓ ${label}`;
      lfbVerdict.className = 'lfb-verdict correct';
    } else {
      lfbVerdict.textContent = `✗ Wrong — should be ${correctLabel}`;
      lfbVerdict.className = 'lfb-verdict wrong';
    }
    learnNextBtn.disabled = false;
    feedbackStrip.style.display = '';

    // Auto-Next: after a CORRECT answer, advance on a timer so the user sees the
    // verdict but doesn't have to click. NOT on a wrong answer (hold so they can
    // study the right action and click Next themselves), and NOT after
    // "Показать ответ" (revealed) — there they pressed reveal to study it.
    clearAutoNext();
    if (state.autoNext && grading.in_strategy && !grading.revealed) {
      state.autoNextTimer = setTimeout(advanceToBufferedNext, AUTO_NEXT_MS);
    }
  }

  function hideReveal() {
    feedbackStrip.style.display = 'none';
    lfbVerdict.textContent = '';
    lfbVerdict.className = 'lfb-verdict';
  }

  function clearAutoNext() {
    if (state.autoNextTimer) {
      clearTimeout(state.autoNextTimer);
      state.autoNextTimer = null;
    }
  }

  function advanceToBufferedNext() {
    // Double-fire guard: a manual "Дальше" click and the auto-advance timer can
    // race. Once we've advanced, the reveal strip is hidden — bail on the second
    // call so it doesn't see bufferedNext=null and wrongly end the session.
    if (feedbackStrip.style.display === 'none') return;
    clearAutoNext();
    hideReveal();
    setActionButtonsDisabled(false);
    if (!state.bufferedNext) {
      showEndOfSession();
      return;
    }
    state.currentCard = state.bufferedNext;
    renderCardScreen(state.bufferedNext, state.bufferedQueueSize);
    state.bufferedNext       = null;
    state.lastAnsweredCardId = null;
  }

  // Next click: drop the buffer, render the next card.
  learnNextBtn.addEventListener('click', () => {
    advanceToBufferedNext();
  });

  function setActionButtonsDisabled(disabled) {
    actionBar.querySelectorAll('button').forEach(b => b.disabled = disabled);
  }

  // ── Screen transitions ───────────────────────────────────────────────────
  // Four sections inside #learnMode: entry / card / reveal / summary.
  // Exactly one is visible at a time. Helper below toggles them centrally so
  // we can never get into a state where two screens overlap.
  function showSection(which) {
    clearAutoNext();   // any screen change cancels a pending auto-advance
    entrySec.style.display    = (which === 'entry')   ? '' : 'none';
    cardSec.style.display     = (which === 'card')    ? '' : 'none';
    revealSec.style.display   = (which === 'reveal')  ? '' : 'none';
    summarySec.style.display  = (which === 'summary') ? '' : 'none';
  }
  function showCardScreen()    { showSection('card'); }
  function showEntryScreen()   { showSection('entry'); }
  function showSummaryScreen() { showSection('summary'); }

  function showEndOfSession() {
    // Populate counters from the just-ended session, then show the screen.
    const { answered, correct, shown } = state.session;
    summaryNums.answered.textContent = answered;
    summaryNums.correct.textContent  = correct;
    summaryNums.accuracy.textContent = answered
      ? `${Math.round((correct / answered) * 100)}%`
      : '—';
    summaryNums.shown.textContent    = shown;
    showSummaryScreen();
    // Refresh entry counters in the background so they're fresh when the
    // user clicks Close.
    refreshStatus();
  }

  if (backBtn) {
    backBtn.addEventListener('click', () => {
      showEntryScreen();
      refreshStatus();
    });
  }

  // "End Session" — finish now and show the session summary (vs. the quiet
  // "Back to deck overview" which just abandons to the entry screen). Reuses
  // the same summary screen that pops when the day's queue empties.
  if (endBtn) {
    endBtn.addEventListener('click', () => {
      clearAutoNext();
      showEndOfSession();
    });
  }

  if (summaryCloseBtn) {
    summaryCloseBtn.addEventListener('click', () => {
      showEntryScreen();
      // Status was already refreshed when summary appeared, but re-run in
      // case Easy upgrades resolved after that (negligible cost).
      refreshStatus();
    });
  }

  // ── Combo sampling ───────────────────────────────────────────────────────
  // Turns "AKs" / "AKo" / "AA" into a concrete two-card combo with suits.
  // Suits don't affect strategy in our model — purely cosmetic.
  const SUITS = ['♠', '♥', '♦', '♣'];

  function sampleCombo(hand) {
    if (hand.length === 2) {
      // Pair: two different suits, same rank
      const r = hand[0];
      const [s1, s2] = shuffle([...SUITS]).slice(0, 2);
      return [r + s1, r + s2];
    }
    const r1 = hand[0];
    const r2 = hand[1];
    const type = hand[2];
    if (type === 's') {
      const s = SUITS[Math.floor(Math.random() * 4)];
      return [r1 + s, r2 + s];
    }
    // Offsuit: two different suits, different ranks
    const [s1, s2] = shuffle([...SUITS]).slice(0, 2);
    return [r1 + s1, r2 + s2];
  }

  function shuffle(arr) {
    for (let i = arr.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [arr[i], arr[j]] = [arr[j], arr[i]];
    }
    return arr;
  }

  // ── Small UI helpers ─────────────────────────────────────────────────────
  let statusTimer = null;
  function showStatus(msg, isError = false, sticky = false) {
    statusMsg.textContent = msg;
    statusMsg.classList.toggle('error', isError);
    if (statusTimer) clearTimeout(statusTimer);
    if (!sticky) statusTimer = setTimeout(clearStatus, 4000);
  }
  function clearStatus() {
    statusMsg.textContent = '';
    statusMsg.classList.remove('error');
  }
})();
