/* test_account_frontend.js — Track D, Stage 2 frontend checks (node, no browser).
 *
 * Runs the REAL static/account.js inside a minimal DOM stub and asserts:
 *   1. the pure model helpers (mondayIdx / cellLevel / buildCalendar /
 *      aggregateWeeks) that lay out the heatmap + bars;
 *   2. buildBody() renders all three states (degraded / empty / full) without
 *      throwing and emits the expected panels;
 *   3. the protected-endpoint classifier in static/auth_client.js now routes
 *      /api/dashboard through auth (so the dashboard fetch carries the JWT),
 *      while the open library endpoints stay token-free.
 *
 * Run:  node test_account_frontend.js
 */
'use strict';
const vm = require('vm');
const fs = require('fs');
const path = require('path');

const HERE = __dirname;
let failed = 0;
function ok(name, cond) {
  if (cond) { console.log('  PASS  ' + name); }
  else { failed++; console.log('  FAIL  ' + name); }
}

// ---------------------------------------------------------------------------
// Load static/account.js in a DOM stub. readyState 'complete' so init() runs
// (exercising buildUserMenu/wireModeTabs against an empty DOM — must not throw).
// ---------------------------------------------------------------------------
function loadAccount() {
  const stubEl = {
    style: {}, classList: { add() {}, remove() {}, toggle() {} },
    addEventListener() {}, appendChild() {}, contains() { return false; },
    innerHTML: '', textContent: '', getAttribute() { return null; },
    setAttribute() {}
  };
  const document = {
    readyState: 'complete',
    addEventListener() {},
    getElementById() { return null; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    createElement() { return Object.assign({}, stubEl); }
  };
  const window = {};
  const sandbox = { window, document, console, Date, JSON, Math, setTimeout };
  window.document = document;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(HERE, 'static/account.js'), 'utf8'), sandbox);
  return window.PRXDash;
}

const D = loadAccount();
ok('account.js loads + exposes PRXDash', D && typeof D.buildBody === 'function');

// ---- 1. pure helpers -------------------------------------------------------
// 2026-06-22 is a Monday, 06-23 a Tuesday (env), 06-28 a Sunday.
ok('mondayIdx: Monday->0', D.mondayIdx('2026-06-22') === 0);
ok('mondayIdx: Tuesday->1', D.mondayIdx('2026-06-23') === 1);
ok('mondayIdx: Sunday->6', D.mondayIdx('2026-06-28') === 6);

ok('cellLevel: 0 hands -> 0', D.cellLevel(0, 20) === 0);
ok('cellLevel: <half -> 1', D.cellLevel(5, 20) === 1);
ok('cellLevel: >=half -> 2', D.cellLevel(10, 20) === 2);
ok('cellLevel: >=threshold -> 3 (trained)', D.cellLevel(20, 20) === 3 && D.cellLevel(25, 20) === 3);

// buildCalendar: a Monday start needs no leading pad; 14 days -> 2 full columns.
const mk = (start, n) => {
  const out = [];
  const base = new Date(start + 'T00:00:00Z');
  for (let i = 0; i < n; i++) {
    const dt = new Date(base); dt.setUTCDate(base.getUTCDate() + i);
    out.push({ day: dt.toISOString().slice(0, 10), hands: (i % 3) * 9, correct: i, trained: (i % 3) === 2 });
  }
  return out;
};
const calMon = D.buildCalendar(mk('2026-06-22', 14));
ok('buildCalendar: Monday start -> 2 columns', calMon.length === 2);
ok('buildCalendar: col0 row0 is the first day', calMon[0][0] && calMon[0][0].day === '2026-06-22');

// A Tuesday start -> 1 leading null so the day still lands on its weekday row.
const calTue = D.buildCalendar(mk('2026-06-23', 7));
ok('buildCalendar: Tuesday start pads 1 leading null', calTue[0][0] === null && calTue[0][1].day === '2026-06-23');

// aggregateWeeks: 14 consecutive days -> 2 weekly buckets, hands summed.
const weeks = D.aggregateWeeks(mk('2026-06-22', 14));
const totalDaily = mk('2026-06-22', 14).reduce((s, x) => s + x.hands, 0);
const totalWeekly = weeks.reduce((s, w) => s + w.hands, 0);
ok('aggregateWeeks: 2 weeks', weeks.length === 2);
ok('aggregateWeeks: conserves total hands', totalDaily === totalWeekly);

ok('pct: rounds to 0.1', D.pct(1, 3) === 33.3 && D.pct(0, 0) === null);

// ---- 2. buildBody — three states ------------------------------------------
const degraded = D.buildBody({ available: false });
ok('buildBody degraded: shows the needs-DB note',
   /dash-note-big/.test(degraded) && /lights up/.test(degraded));

const empty = D.buildBody({ available: true, threshold: 20,
  totals: { hands: 0, correct: 0, accuracy: null, drill_hands: 0, learn_hands: 0, cards_total: 0, learned: 0 },
  streak: { current: 0, longest: 0 }, days: [], by_spot: [] });
ok('buildBody empty: counters + "no training" note',
   /dash-counters/.test(empty) && /No training logged yet/.test(empty));

const full = {
  available: true, today: '2026-06-23', threshold: 20,
  totals: { hands: 1234, correct: 900, accuracy: 72.9, drill_hands: 1000, learn_hands: 234, cards_total: 1800, learned: 420 },
  streak: { current: 5, longest: 9 },
  days: mk('2026-05-20', 35),
  by_spot: [
    { spot: 'RFI', hands: 600, correct: 480, accuracy: 80.0, rows: [
      { key: 'UTG', position: 'UTG', villain: null, hands: 300, correct: 250, accuracy: 83.3 },
      { key: 'BTN', position: 'BTN', villain: null, hands: 300, correct: 230, accuracy: 76.7 } ] },
    { spot: 'vs_RFI', hands: 200, correct: 120, accuracy: 60.0, rows: [
      { key: 'BTN_vs_MP', position: 'BTN', villain: 'MP', hands: 200, correct: 120, accuracy: 60.0 } ] }
  ]
};
const body = D.buildBody(full);
ok('buildBody full: counters present', /dash-counters/.test(body) && /1,234/.test(body));
ok('buildBody full: streak rendered', /🔥 5/.test(body) && /best 9/.test(body));
ok('buildBody full: calendar cells present', /cal-cols/.test(body) && /cal-cell/.test(body));
ok('buildBody full: bars present', /dash-bars/.test(body) && /bar-correct/.test(body));
ok('buildBody full: spot cards present', /spot-card/.test(body) && /BTN_vs_MP/.test(body));

// weekly bar view still renders.
D.setBarView('weekly');
const weekly = D.buildBody(full);
ok('buildBody full (weekly view): renders bars', /dash-bars/.test(weekly) && /bar-correct/.test(weekly));
D.setBarView('daily');

// ---- 3. auth_client.js protected-endpoint classifier ----------------------
const authSrc = fs.readFileSync(path.join(HERE, 'static/auth_client.js'), 'utf8');
const m = authSrc.match(/return\s+(\/.*?\/)\.test\(url\)/);
ok('auth_client: found needsAuth regex', !!m);
const re = new Function('return ' + m[1])();   // the real /…/ literal from the file
const needsAuth = (u) => re.test(u);

const protectedUrls = ['/api/drill/answer', '/api/stats', '/api/stats/reset',
  '/api/history', '/api/history/clear', '/api/srs/next', '/api/dashboard/overview'];
const openUrls = ['/api/ranges/list', '/api/ranges', '/api/config',
  '/api/drill/hand', '/api/db/health', '/api/auth/config'];
ok('needsAuth: /api/dashboard is PROTECTED', needsAuth('/api/dashboard/overview') === true);
ok('needsAuth: all protected match', protectedUrls.every(u => needsAuth(u) === true));
ok('needsAuth: all open endpoints pass through', openUrls.every(u => needsAuth(u) === false));
// guard the easy-to-break neighbour: drill/hand must NOT be gated, drill/answer must.
ok('needsAuth: drill/hand open, drill/answer protected',
   needsAuth('/api/drill/hand') === false && needsAuth('/api/drill/answer') === true);

console.log();
if (failed) { console.log(failed + ' check(s) FAILED'); process.exit(1); }
console.log('All account/auth frontend checks passed');
