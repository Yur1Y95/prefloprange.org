// ── CHIP DENOMINATIONS (cash, in BB) ──────────────────────────────────
// Shared chip-rendering helpers (single source of truth, like cards.js).
// A bet is a stack of denominated discs; the pot is the same discs grouped
// per denomination into stacks side by side. Colour encodes denomination,
// all discs share one diameter (like real casino chips). Each disc has an
// extruded side wall (CSS box-shadow in the disc's own --wall colour), so a
// stack shows each chip's colour as a band down the side — the "casino 3D"
// look (variant A, user 2026-06-15). Reference prototype:
// static/chips_preview.html. Rationale & decisions: docs/design.md "Фишки".
//
// Consumers: drill.js (renderChips — preflop bets in front of seats),
//            postflop.js (villain bet chip). Loaded before both in index.html.

const CHIP_DENOMS = [
  { v: 25,  cls: 'd-25', label: '25' },
  { v: 5,   cls: 'd-5',  label: '5'  },
  { v: 1,   cls: 'd-1',  label: '1'  },
  { v: 0.5, cls: 'd-05', label: '.5' },
  { v: 0.1, cls: 'd-01', label: '.1' },
];
const CHIP_W = 21, CHIP_H = 11, CHIP_T = 3;  // disc width, height, stacked offset (px)
// Discs are THIN: CSS draws an extra ~3px extruded wall below each disc
// (box-shadow ladder, scaled by --cs) = the visible edge. Offset 3px ≈ wall, so
// chips sit tight (a thin disc each, not fat pucks) and stacks stay short. The
// wall is purely visual overflow, NOT part of the .coins box math; .chip-amt
// carries a matching margin so the pill clears it.

// Greedy make-change → denom objs, largest first. Rounds to 0.1 (smallest chip)
// so float dust and sub-0.1 solver sizes don't break the loop. Never empty.
function chipMakeChange(amount) {
  let rem = Math.round(amount * 10) / 10;
  const out = [];
  for (const d of CHIP_DENOMS) {
    const k = Math.floor((rem + 1e-9) / d.v);
    for (let i = 0; i < k; i++) out.push(d);
    rem = Math.round((rem - k * d.v) * 10) / 10;
  }
  return out.length ? out : [CHIP_DENOMS[CHIP_DENOMS.length - 1]];
}
function chipFmt(a) { return Number.isInteger(a) ? String(a) : a.toFixed(1); }

// Chip scale, ported from the GG/PokerLay method (docs/design.md §7): size is
// proportional to the live table, measured off a reference width, with a floor
// so chips never vanish on tiny screens. GG uses a portrait 1080×1920 client as
// its reference; our table is the landscape stadium, so the reference is its
// desktop width (680px). At our mobile minimum (~560px) this yields ~0.82 —
// exactly the old hand-tuned `scale(.82)` mobile hack, now made continuous.
const CHIP_REF_W = 680;   // reference table width (desktop) → scale 1
const CHIP_SCALE_MIN = 0.6;
function chipScaleFor(tableWidth) {
  const w = tableWidth || CHIP_REF_W;
  return Math.max(CHIP_SCALE_MIN, Math.min(1, w / CHIP_REF_W));
}

// A column of discs from a denom list (bottom→top = largest→smallest).
// `scale` (default 1) sizes the stack; CSS reads it back via the --cs var the
// wrappers set, so disc size and stacking offset stay in lockstep.
function chipColumn(denoms, scale) {
  const s = scale || 1;
  const n = denoms.length;
  const coins = document.createElement('div');
  coins.className = 'coins';
  coins.style.width  = (CHIP_W * s) + 'px';
  coins.style.height = ((CHIP_H + (n - 1) * CHIP_T) * s) + 'px';
  denoms.forEach((d, i) => {
    const coin = document.createElement('div');
    coin.className = 'coin ' + d.cls + (i === n - 1 ? ' top' : '');
    coin.style.bottom = (i * CHIP_T * s) + 'px';
    coin.style.zIndex = i;
    coin.style.setProperty('--rot', (i * 23 % 60) + 'deg');  // stagger edge spots
    if (i === n - 1) coin.setAttribute('data-d', d.label);
    coins.appendChild(coin);
  });
  return coins;
}

// Player bet: one mixed stack + amount pill. Returns a .chip-stack element
// (CSS: position:absolute + translate(-50%,-50%)); caller sets top/left.
function chipBetStack(amount, scale) {
  const s = scale || 1;
  const a = parseFloat(amount);
  const wrap = document.createElement('div');
  wrap.className = 'chip-stack';
  wrap.style.setProperty('--cs', s);   // CSS sizes disc + font off this
  wrap.appendChild(chipColumn(chipMakeChange(a), s));
  const amt = document.createElement('div');
  amt.className = 'chip-amt';
  amt.textContent = chipFmt(a);
  wrap.appendChild(amt);
  return wrap;
}

// Pot: group make-change by denomination → one stack each, side by side.
// Returns a .chip-pot element; caller sets top/left.
function chipPotStacks(amount, scale) {
  const s = scale || 1;
  const groups = [];
  chipMakeChange(parseFloat(amount)).forEach(d => {
    const g = groups.find(x => x.cls === d.cls);
    g ? g.count++ : groups.push({ ...d, count: 1 });
  });
  const wrap = document.createElement('div');
  wrap.className = 'chip-pot';
  wrap.style.setProperty('--cs', s);
  const row = document.createElement('div');
  row.className = 'pot-row';
  groups.forEach(g => row.appendChild(chipColumn(Array.from({ length: g.count }, () => g), s)));
  wrap.appendChild(row);
  return wrap;
}
