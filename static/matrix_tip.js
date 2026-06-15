/* matrix_tip.js — floating action-frequency tooltip for the 13×13 matrices.

   ONE JOB: when the cursor is over a .matrix-cell, show a small card next to the
   cursor with the hand and its action breakdown (Open / Call / 3-Bet / … + Fold),
   exactly like the matrix_preview.html prototype (variant C). This replaces the
   cramped "frequency line" that used to sit above the matrix — the user found it
   inconvenient to glance up at (2026-06-15). Shared by Visualizer + Editor; the
   Practice hint-grid can opt in later the same way.

   USAGE:
     MatrixTip.attach(gridEl, cell => ({ hand: cell.dataset.hand, value: <strategy> }));
   The resolver runs on every mousemove, so it always reads CURRENT data — grid
   rebuilds / recolors don't matter. <strategy> may be:
     • a number           → legacy RFI open frequency, treated as { open: n }
     • an object          → { action: freq, ... } (open/call/3bet/4bet/squeeze/allin)
     • null / undefined   → empty cell → shows Fold 100%
   Fold is always derived as the remainder (1 − Σ shown actions) and appended last,
   mirroring the prototype. */
(function (global) {
  'use strict';

  let tip = null, handEl = null, rowsEl = null;

  function ensure() {
    if (tip) return;
    tip = document.createElement('div');
    tip.className = 'matrix-tip';
    handEl = document.createElement('div');
    handEl.className = 'mtip-hand';
    rowsEl = document.createElement('div');
    rowsEl.className = 'mtip-rows';
    tip.appendChild(handEl);
    tip.appendChild(rowsEl);
    document.body.appendChild(tip);
  }

  // Display order + labels for known actions. Fold is handled separately (last).
  const ORDER  = ['open', 'raise', 'call', '3bet', '4bet', 'squeeze', 'allin'];
  const LABELS = { open: 'Open', raise: 'Raise', call: 'Call', '3bet': '3-Bet',
                   '4bet': '4-Bet', squeeze: 'Squeeze', allin: 'All-In', fold: 'Fold' };

  function normalize(value) {
    if (value == null) return {};
    if (typeof value === 'number') return { open: value };   // legacy single-freq RFI
    return value;
  }

  function show(hand, value, x, y) {
    ensure();
    const s = normalize(value);
    const rows = [];
    let sum = 0;
    for (const a of ORDER) {
      const f = s[a];
      if (f > 0) { rows.push([LABELS[a] || a, Math.round(f * 100)]); sum += f; }
    }
    // Any non-standard action keys (defensive — keep generic, fold stays separate).
    for (const a in s) {
      if (a !== 'fold' && ORDER.indexOf(a) === -1 && s[a] > 0) {
        rows.push([LABELS[a] || a, Math.round(s[a] * 100)]); sum += s[a];
      }
    }
    const fold = Math.max(0, 1 - sum);
    rows.push(['Fold', Math.round(fold * 100)]);

    handEl.textContent = hand;
    rowsEl.innerHTML = rows.map(function (kv) {
      return '<div class="mtip-row"><span class="mtip-k">' + kv[0] +
             '</span><span class="mtip-v">' + kv[1] + '%</span></div>';
    }).join('');

    tip.style.display = 'block';
    // Position next to the cursor; flip away from the right/bottom viewport edges
    // (the editor matrix sits near the right side, so naive +x would clip).
    const tw = tip.offsetWidth, th = tip.offsetHeight, pad = 8, off = 14;
    let nx = x + off, ny = y + off;
    if (nx + tw > global.innerWidth  - pad) nx = x - tw - off;
    if (ny + th > global.innerHeight - pad) ny = y - th - off;
    tip.style.left = Math.max(pad, nx) + 'px';
    tip.style.top  = Math.max(pad, ny) + 'px';
  }

  function hide() { if (tip) tip.style.display = 'none'; }

  function attach(grid, resolve) {
    if (!grid || grid._mtipAttached) return;   // grid element persists across rebuilds
    grid._mtipAttached = true;
    grid.addEventListener('mousemove', function (e) {
      const cell = e.target.closest('.matrix-cell');
      if (!cell) { hide(); return; }
      const d = resolve(cell);
      if (!d) { hide(); return; }
      show(d.hand, d.value, e.clientX, e.clientY);
    });
    grid.addEventListener('mouseleave', hide);
  }

  global.MatrixTip = { attach: attach, show: show, hide: hide };
})(window);
