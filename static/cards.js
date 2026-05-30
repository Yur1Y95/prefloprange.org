// Shared SVG card-asset helper. Loaded BEFORE drill.js / postflop.js so both
// modules can rely on cardSvgUrl / renderSvgCard as plain globals — no build
// step, no module loader, matches the rest of static/.
//
// Accepts two input shapes for the card string:
//   - drill-style    "A♥"   (rank + unicode suit character)
//   - postflop-style "Ah"   (rank + lowercase suit letter, as the API returns)
//
// SVG assets live in /cards/ — see docs/roadmap.md B.1-cards for the source.

const _CARD_SUIT_UNICODE = { '♠': 'spade', '♥': 'heart', '♦': 'diamond', '♣': 'club' };
const _CARD_SUIT_LETTER  = { s: 'spade',   h: 'heart',   d: 'diamond',   c: 'club'   };
const _CARD_RANK         = { A: 'Ace', K: 'King', Q: 'Queen', J: 'Jack', T: '10' };

// Returns /cards/<suit><rank>.svg URL, or null when the input can't be mapped
// (caller can fall back to the legacy CSS-drawn card markup).
function cardSvgUrl(str) {
  if (!str || str.length < 2) return null;
  const last    = str.slice(-1);
  const rankRaw = str.slice(0, -1);
  const suit    = _CARD_SUIT_UNICODE[last] || _CARD_SUIT_LETTER[last.toLowerCase()];
  if (!suit || !rankRaw) return null;
  const rank    = _CARD_RANK[rankRaw.toUpperCase()] || rankRaw;  // 2..9 stay as-is
  return `/cards/${suit}${rank}.svg`;
}

// Render an SVG card face into ``el``. Returns true on success so callers can
// fall back to their own CSS markup when the input can't be mapped.
//
//   opts.delayIndex — staggers the deal-in animation across multiple cards.
function renderSvgCard(el, str, opts) {
  const url = cardSvgUrl(str);
  if (!url) return false;
  const delayIndex = (opts && opts.delayIndex) || 0;
  el.className = 'card card-svg deal-in';
  el.style.animationDelay = (delayIndex * 0.08) + 's';
  el.innerHTML = `<img src="${url}" alt="${str}" draggable="false">`;
  return true;
}
