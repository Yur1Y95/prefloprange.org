// ── CHIP DENOMINATIONS (cash, in BB) ──────────────────────────────────
// Shared chip-rendering helpers (single source of truth, like cards.js).
// A bet is a stack of denominated discs; the pot is the same discs grouped
// per denomination into stacks side by side. Colour encodes denomination,
// all discs share one diameter (like real casino chips). Reference prototype:
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
const CHIP_W = 19, CHIP_H = 8, CHIP_T = 4;   // disc width, height, stacked offset (px)

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

// A column of discs from a denom list (bottom→top = largest→smallest).
function chipColumn(denoms) {
  const n = denoms.length;
  const coins = document.createElement('div');
  coins.className = 'coins';
  coins.style.width  = CHIP_W + 'px';
  coins.style.height = (CHIP_H + (n - 1) * CHIP_T) + 'px';
  denoms.forEach((d, i) => {
    const coin = document.createElement('div');
    coin.className = 'coin ' + d.cls + (i === n - 1 ? ' top' : '');
    coin.style.bottom = (i * CHIP_T) + 'px';
    coin.style.zIndex = i;
    coin.style.setProperty('--rot', (i * 23 % 60) + 'deg');  // stagger edge spots
    if (i === n - 1) coin.setAttribute('data-d', d.label);
    coins.appendChild(coin);
  });
  return coins;
}

// Player bet: one mixed stack + amount pill. Returns a .chip-stack element
// (CSS: position:absolute + translate(-50%,-50%)); caller sets top/left.
function chipBetStack(amount) {
  const a = parseFloat(amount);
  const wrap = document.createElement('div');
  wrap.className = 'chip-stack';
  wrap.appendChild(chipColumn(chipMakeChange(a)));
  const amt = document.createElement('div');
  amt.className = 'chip-amt';
  amt.textContent = chipFmt(a);
  wrap.appendChild(amt);
  return wrap;
}

// Pot: group make-change by denomination → one stack each, side by side.
// Returns a .chip-pot element; caller sets top/left.
function chipPotStacks(amount) {
  const groups = [];
  chipMakeChange(parseFloat(amount)).forEach(d => {
    const g = groups.find(x => x.cls === d.cls);
    g ? g.count++ : groups.push({ ...d, count: 1 });
  });
  const wrap = document.createElement('div');
  wrap.className = 'chip-pot';
  const row = document.createElement('div');
  row.className = 'pot-row';
  groups.forEach(g => row.appendChild(chipColumn(Array.from({ length: g.count }, () => g))));
  wrap.appendChild(row);
  return wrap;
}
