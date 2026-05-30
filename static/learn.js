// ============================================================================
// learn.js — Spaced Repetition Learn Mode
//
// Stage 3 (current): card screen — fetches /api/srs/next, renders the poker
// table (reusing drill.js's renderSeatsInto + renderCardsInto), wires action
// buttons to POST /api/srs/answer. After answering, immediately advances to
// the next card; no visible reveal yet (Stage 4 will insert that step).
//
// Roadmap:
//   Stage 4 — reveal: thin feedback strip with verdict + Next + Easy buttons,
//             same shape as drill's feedback-strip.
//   Stage 5 — end-of-session summary when queue_size hits 0.
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
  const actionBar   = document.getElementById('learnActionBar');
  const queueBadge  = document.getElementById('learnQueueBadge');
  const backBtn     = document.getElementById('learnBackBtn');
  // Reveal strip (Stage 4 — shown after each answer, holds Easy + Next)
  const feedbackStrip = document.getElementById('learnFeedbackStrip');
  const lfbVerdict    = document.getElementById('lfbVerdict');
  const learnEasyBtn  = document.getElementById('learnEasyBtn');
  const learnNextBtn  = document.getElementById('learnNextBtn');

  // Summary screen (Stage 5 — shown when the day's queue is empty)
  const summarySec        = document.getElementById('learnSummary');
  const summaryCloseBtn   = document.getElementById('learnSummaryCloseBtn');
  const summaryNums = {
    answered: document.getElementById('lsAnswered'),
    correct:  document.getElementById('lsCorrect'),
    accuracy: document.getElementById('lsAccuracy'),
    easy:     document.getElementById('lsEasy'),
  };

  // ── State ────────────────────────────────────────────────────────────────
  const state = {
    filesLoaded:    false,
    currentFile:    '',
    selectedScope:  'all',          // 'all' | 'RFI' | 'vs_RFI' | 'vs_3bet'
    initialized:    false,
    rangeConfigs:   {},             // file -> {positions: [...]} cache
    currentCard:    null,           // card payload from /api/srs/next
    // Reveal-state buffering: when the action is answered, we hold onto the
    // next card and the answered card's id until the user clicks Next (or
    // Easy → upgrade → Next). This is what lets the reveal strip persist.
    bufferedNext:        null,
    bufferedQueueSize:   0,
    lastAnsweredCardId:  null,
    lastAnswerCorrect:   false,
    // Session counters — reset every time the user clicks "Учить" from
    // entry. Used to populate the end-of-session summary screen.
    session: {
      answered:    0,
      correct:     0,
      easyClicks:  0,
    },
  };

  function resetSession() {
    state.session.answered   = 0;
    state.session.correct    = 0;
    state.session.easyClicks = 0;
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
        opt.textContent = f.label || f.filename;
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
      const url = `/api/srs/next?file=${encodeURIComponent(state.currentFile)}`;
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

    // Seats — delegates to drill.js's parameterized renderer
    window.renderSeatsInto({
      seatsId:    'learnSeats',
      positions:  positions,
      heroPos:    card.position,
      spot:       card.spot,
      villainPos: card.villain_position || null,
      stacks:     null,   // 100 BB default; learn doesn't model varied stacks
    });

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
    return card.spot;
  }

  function actionsForSpot(spot) {
    // Fold first, then the aggressive line, then passive call (where it exists)
    if (spot === 'RFI')      return ['fold', 'open'];
    if (spot === 'vs_RFI')   return ['fold', 'call', '3bet'];
    if (spot === 'vs_3bet')  return ['fold', 'call', '4bet'];
    return ['fold'];
  }

  const ACTION_LABELS = {
    fold: 'Fold', open: 'Open', call: 'Call', '3bet': '3-Bet', '4bet': '4-Bet',
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
  }

  async function handleAction(action) {
    if (!state.currentCard) return;
    setActionButtonsDisabled(true);
    try {
      const res = await fetch('/api/srs/answer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          file:        state.currentFile,
          card_id:     state.currentCard.card_id,
          user_action: action,
          marked_easy: false,    // Easy is now applied post-hoc via upgrade_easy
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      console.log('[learn.js] grade:', data.grading,
                  '· next queue:', data.queue_size);
      // Session tallies — feed the end-of-session summary
      state.session.answered += 1;
      if (data.grading.in_strategy) state.session.correct += 1;
      // Buffer the next card and reveal the verdict. Action buttons stay
      // disabled until the user clicks Next (or Easy → Next).
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

    if (grading.in_strategy) {
      const label = ACTION_LABELS[grading.user_action] || grading.user_action;
      lfbVerdict.textContent = `✓ ${label}`;
      lfbVerdict.className = 'lfb-verdict correct';
      learnEasyBtn.style.display = '';
      learnEasyBtn.disabled = false;
    } else {
      const correct = answeredCard.dominant_action;
      const label   = ACTION_LABELS[correct] || correct;
      lfbVerdict.textContent = `✗ Wrong — should be ${label}`;
      lfbVerdict.className = 'lfb-verdict wrong';
      learnEasyBtn.style.display = 'none';   // Easy only on correct answers
    }
    learnNextBtn.disabled = false;
    feedbackStrip.style.display = '';
  }

  function hideReveal() {
    feedbackStrip.style.display = 'none';
    learnEasyBtn.style.display  = 'none';
    lfbVerdict.textContent = '';
    lfbVerdict.className = 'lfb-verdict';
  }

  function advanceToBufferedNext() {
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

  // Easy click: upgrade the just-answered GOOD to EASY, then advance.
  // Easy is only visible after a correct answer, so we don't double-check.
  learnEasyBtn.addEventListener('click', async () => {
    if (!state.lastAnsweredCardId) return;
    learnEasyBtn.disabled = true;
    learnNextBtn.disabled = true;
    try {
      const res = await fetch('/api/srs/upgrade_easy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          file:    state.currentFile,
          card_id: state.lastAnsweredCardId,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      console.log('[learn.js] upgrade_easy:', data);
      state.session.easyClicks += 1;
    } catch (e) {
      // Non-fatal — log and still advance. Better to lose one Easy bump
      // than to strand the user on a card with no usable buttons.
      console.error('[learn.js] /api/srs/upgrade_easy failed:', e);
      showStatus(`Easy upgrade failed: ${e.message}`, true);
    }
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
    const { answered, correct, easyClicks } = state.session;
    summaryNums.answered.textContent = answered;
    summaryNums.correct.textContent  = correct;
    summaryNums.accuracy.textContent = answered
      ? `${Math.round((correct / answered) * 100)}%`
      : '—';
    summaryNums.easy.textContent     = easyClicks;
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
