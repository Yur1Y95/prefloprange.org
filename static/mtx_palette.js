/* mtx_palette.js — single source of truth for the 13×13 matrix palette.
   Resolves design.md §9.1: palette decided 2026-06-18, and the three hardcoded
   copies in visualizer.js / editor.js / drill.js collapse into this one module.

   Load BEFORE those files in index.html:
     <script src="/static/mtx_palette.js?v=20260618"></script>
     <script src="/static/visualizer.js?v=..."></script>  ...

   MODEL (decided): ONE coherent fill model for every spot — the horizontal
   split-bar (fill width left→right = frequency, full cell height). This is the
   existing live "полоска-бар" model (P-007), now applied to RFI too:
     • RFI / ISO  → one segment  [open, openFreq]   (NO more solid-colour buckets)
     • vs spots   → ordered segments per action, remainder = fold
   Mirror the COLORS into CSS :root tokens (--mtx-*) so legend swatches and any
   CSS fills track the JS.                                                       */
(function (global) {
  'use strict';

  // Muted to sit on the neutral-graphite chrome while keeping action families
  // distinguishable (raise = red/maroon, call = steel-blue, open = green).
  var COLORS = {
    fold: '#121a15',          // empty cell / fold remainder (= matrix empty bg)
    div:  '#0b100c',          // ~1px divider between adjacent segments
    act: { open: '#2f9152', call: '#3c78a8', '3bet': '#c8433a', '4bet': '#8e2f2a', allin: '#6e2622' }
  };

  // Horizontal split-bar, left→right, full height. `segs` = ordered
  // [color, fraction] pairs; remainder (<1) filled with fold.
  function splitGradient(segs, foldColor) {
    var DIV = COLORS.div, cum = 0, stops = [];
    for (var i = 0; i < segs.length; i++) {
      var color = segs[i][0], fr = segs[i][1];
      if (!fr || fr <= 0) continue;
      var p1 = cum * 100, p2 = (cum + fr) * 100;
      if (cum > 0) stops.push(DIV + ' ' + p1.toFixed(1) + '% ' + (p1 + 0.8).toFixed(1) + '%');
      stops.push(color + ' ' + (cum > 0 ? p1 + 0.8 : p1).toFixed(1) + '% ' + p2.toFixed(1) + '%');
      cum += fr;
    }
    if (cum < 1) {
      var p = cum * 100;
      if (cum > 0) stops.push(DIV + ' ' + p.toFixed(1) + '% ' + (p + 0.8).toFixed(1) + '%');
      stops.push((foldColor || COLORS.fold) + ' ' + (cum > 0 ? p + 0.8 : 0).toFixed(1) + '% 100%');
    }
    return stops.length ? 'linear-gradient(to right, ' + stops.join(', ') + ')' : (foldColor || COLORS.fold);
  }

  // Convenience for the RFI/ISO single-action case.
  function rfiFill(openFreq) {
    return splitGradient(openFreq > 0 ? [[COLORS.act.open, openFreq]] : [], COLORS.fold);
  }

  global.MTX = { COLORS: COLORS, splitGradient: splitGradient, rfiFill: rfiFill };
})(window);
