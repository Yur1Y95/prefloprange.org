/* account.js — Track D, Stage 2: user menu + per-user Progress dashboard.
 *
 * Two jobs:
 *   1. Mount a user menu in the topbar (avatar → dropdown). The dropdown opens
 *      the Progress page and offers Sign out (delegated to auth_client via
 *      window.PRXAuth.signOut). The menu is the dashboard's entry point — there
 *      is no extra mode-tab (decision: cabinet lives in the user menu).
 *   2. Render the Progress page (#accountMode) from GET /api/dashboard/overview:
 *      counters (streaks + totals), an activity calendar heatmap, volume/accuracy
 *      bars, and accuracy by spot/position.
 *
 * The dashboard is per-user and DB-only: when the backend reports
 * {available:false} (no DATABASE_URL) we show a clean "needs the database"
 * state rather than a half-built reconstruction (history.json has no dates).
 *
 * The fetch is auto-tokenized + queued-until-login by auth_client.js (the
 * /api/dashboard path is in its protected set), so this file never touches auth
 * beyond reading window.PRXAuth for the menu chrome.
 *
 * Pure model helpers (calendar columns, weekly aggregation, cell level) are
 * exposed on window.PRXDash for the node DOM-stub test.
 */
(function () {
  'use strict';

  var overview = null;     // last payload (cached so re-opening is instant)
  var barView = 'daily';   // 'daily' | 'weekly'

  // ---- spot display names (match the trainers) ----------------------------
  var SPOT_LABEL = {
    RFI: 'RFI', vs_RFI: 'vs RFI', vs_3bet: 'vs 3-Bet', vs_4bet: 'vs 4-Bet',
    iso: 'ISO', squeeze: 'Squeeze', vs_squeeze: 'vs Squeeze'
  };

  // ---- the other full-page modes we hide when showing the dashboard -------
  var MODE_IDS = ['drillMode', 'vizMode', 'learnMode', 'postflopMode',
                  'analyzerMode', 'editorMode'];

  // =========================================================================
  // Pure model helpers (no DOM) — unit-tested via window.PRXDash.
  // =========================================================================

  // Mon-first weekday index (0=Mon … 6=Sun) for an ISO 'YYYY-MM-DD'.
  function mondayIdx(iso) {
    var js = new Date(iso + 'T00:00:00Z').getUTCDay();   // 0=Sun … 6=Sat
    return (js + 6) % 7;
  }

  // Heatmap intensity level 0..3 from a day's hands vs the anti-farm threshold.
  // 0 = none; 3 = a qualified "training" day (>= threshold) — the brightest.
  function cellLevel(hands, threshold) {
    if (!hands) return 0;
    if (hands >= threshold) return 3;
    if (hands >= threshold / 2) return 2;
    return 1;
  }

  // Lay days out into week-columns (each 7 cells, Mon→Sun). Leading/trailing
  // nulls pad partial weeks so row r is always weekday r.
  function buildCalendar(days) {
    if (!days || !days.length) return [];
    var cells = [];
    var firstWd = mondayIdx(days[0].day);
    for (var i = 0; i < firstWd; i++) cells.push(null);
    days.forEach(function (d) { cells.push(d); });
    while (cells.length % 7 !== 0) cells.push(null);
    var cols = [];
    for (var j = 0; j < cells.length; j += 7) cols.push(cells.slice(j, j + 7));
    return cols;
  }

  // Aggregate the daily series into Mon-started weeks: {week, hands, correct}.
  function aggregateWeeks(days) {
    var map = {};
    var order = [];
    (days || []).forEach(function (d) {
      var dt = new Date(d.day + 'T00:00:00Z');
      dt.setUTCDate(dt.getUTCDate() - mondayIdx(d.day));   // back to Monday
      var key = dt.toISOString().slice(0, 10);
      if (!map[key]) { map[key] = { week: key, hands: 0, correct: 0 }; order.push(key); }
      map[key].hands += d.hands;
      map[key].correct += d.correct;
    });
    return order.map(function (k) { return map[k]; });
  }

  function pct(correct, hands) {
    return hands ? Math.round(1000 * correct / hands) / 10 : null;
  }
  function accText(correct, hands) {
    var p = pct(correct, hands);
    return p === null ? '—' : p + '%';
  }
  function num(n) { return (n || 0).toLocaleString('en-US'); }
  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  // =========================================================================
  // User menu
  // =========================================================================

  var PERSON_SVG =
    '<svg viewBox="0 0 24 24" aria-hidden="true">' +
    '<circle cx="12" cy="8" r="4"></circle>' +
    '<path d="M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7"></path></svg>';

  function buildUserMenu() {
    var bar = document.querySelector('.topbar');
    if (!bar || document.getElementById('prxUserMenu')) return;
    var wrap = document.createElement('div');
    wrap.className = 'user-menu';
    wrap.id = 'prxUserMenu';
    wrap.innerHTML =
      '<button class="user-menu-btn" id="userMenuBtn" type="button" ' +
        'aria-label="Account menu">' + PERSON_SVG + '</button>' +
      '<div class="user-menu-pop" id="userMenuPop">' +
        '<div class="user-menu-email" id="userMenuEmail"></div>' +
        '<button class="user-menu-item" id="userMenuProgress" type="button">' +
          'Progress</button>' +
        '<button class="user-menu-item user-menu-signout" id="userMenuSignout" ' +
          'type="button">Sign out</button>' +
      '</div>';
    bar.appendChild(wrap);

    document.getElementById('userMenuBtn').addEventListener('click', function (e) {
      e.stopPropagation();
      toggleMenu();
    });
    document.getElementById('userMenuProgress').addEventListener('click', function () {
      closeMenu();
      showDashboard();
    });
    document.getElementById('userMenuSignout').addEventListener('click', function () {
      closeMenu();
      if (window.PRXAuth && typeof window.PRXAuth.signOut === 'function') {
        window.PRXAuth.signOut();
      }
    });
    document.addEventListener('click', function (e) {
      if (!wrap.contains(e.target)) closeMenu();
    });
  }

  function refreshMenu() {
    var enabled = !!(window.PRXAuth && window.PRXAuth.enabled);
    var email = (window.PRXAuth && window.PRXAuth.email) || '';
    var emEl = document.getElementById('userMenuEmail');
    if (emEl) {
      emEl.textContent = email || 'Account';
      emEl.style.display = email ? 'block' : 'none';
    }
    var so = document.getElementById('userMenuSignout');
    if (so) so.style.display = enabled ? 'block' : 'none';
  }

  function toggleMenu() {
    refreshMenu();
    var p = document.getElementById('userMenuPop');
    if (p) p.classList.toggle('open');
  }
  function closeMenu() {
    var p = document.getElementById('userMenuPop');
    if (p) p.classList.remove('open');
  }

  // =========================================================================
  // Show / hide the dashboard page
  // =========================================================================

  function showDashboard() {
    MODE_IDS.forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.style.display = 'none';
    });
    var tabs = document.querySelectorAll('.mode-tab');
    for (var i = 0; i < tabs.length; i++) tabs[i].classList.remove('active');
    var page = document.getElementById('accountMode');
    if (page) page.style.display = 'grid';
    loadDashboard(false);
  }

  function hideDashboard() {
    var page = document.getElementById('accountMode');
    if (page) page.style.display = 'none';
  }

  // Leaving the dashboard via any top-nav tab hides it (the tab's own handler
  // shows its mode; we only need to hide ours).
  function wireModeTabs() {
    var tabs = document.querySelectorAll('.mode-tab');
    for (var i = 0; i < tabs.length; i++) {
      tabs[i].addEventListener('click', hideDashboard);
    }
  }

  // =========================================================================
  // Data
  // =========================================================================

  function loadDashboard(force) {
    var host = document.getElementById('dashBody');
    if (!host) return;
    if (overview && !force) { render(overview); return; }
    host.innerHTML = '<div class="dash-note">Loading your progress…</div>';
    fetch('/api/dashboard/overview')
      .then(function (r) { return r.json(); })
      .then(function (d) { overview = d; render(d); })
      .catch(function () {
        host.innerHTML =
          '<div class="dash-note">Couldn’t load your progress. ' +
          '<button class="dash-retry" id="dashRetry" type="button">Retry</button></div>';
        var b = document.getElementById('dashRetry');
        if (b) b.addEventListener('click', function () { loadDashboard(true); });
      });
  }

  // Pure: payload -> the page's inner HTML (all three branches). No DOM, so the
  // node DOM-stub test can exercise every builder without a browser.
  function buildBody(d) {
    if (!d || d.available === false) return degradedHTML();
    var html = countersHTML(d);
    if (!d.totals || d.totals.hands === 0) {
      return html +
        '<div class="dash-note">No training logged yet — play some hands in ' +
        '<b>Drill</b> or <b>Learn</b> and your progress shows up here.</div>';
    }
    return html + calendarHTML(d) + barsHTML(d) + spotsHTML(d);
  }

  function hasData(d) {
    return d && d.available !== false && d.totals && d.totals.hands > 0;
  }

  function render(d) {
    var host = document.getElementById('dashBody');
    if (!host) return;
    host.innerHTML = buildBody(d);
    if (hasData(d)) wireBars();    // bar view toggle only exists when there's data
  }

  function degradedHTML() {
    return '<div class="dash-note dash-note-big">' +
      'Your progress dashboard lights up once training is saved to your ' +
      'account.<br><span class="dash-note-dim">(Connect the database to enable ' +
      'cross-session stats, streaks and the activity calendar.)</span></div>';
  }

  // =========================================================================
  // Panel A — counters
  // =========================================================================

  function counter(value, label, extra) {
    return '<div class="dash-counter">' +
      '<div class="dc-num">' + value + '</div>' +
      '<div class="dc-label">' + label + '</div>' +
      (extra ? '<div class="dc-extra">' + extra + '</div>' : '') +
      '</div>';
  }

  function countersHTML(d) {
    var t = d.totals || {}, s = d.streak || {};
    var acc = t.accuracy == null ? '—' : t.accuracy + '%';
    return '<section class="dash-panel"><div class="dash-counters">' +
      counter('🔥 ' + (s.current || 0), 'Day streak',
              'best ' + (s.longest || 0)) +
      counter(num(t.hands), 'Hands total',
              num(t.drill_hands) + ' drill · ' + num(t.learn_hands) + ' learn') +
      counter(acc, 'Accuracy', 'all answers') +
      counter(num(t.learned), 'Cards learned',
              'of ' + num(t.cards_total)) +
      '</div></section>';
  }

  // =========================================================================
  // Panel B — calendar heatmap
  // =========================================================================

  function calendarHTML(d) {
    var cols = buildCalendar(d.days);
    var threshold = d.threshold || 20;

    // Month labels aligned to columns: label the first column of each month.
    var monthsRow = '<span class="cal-spacer"></span>';
    var lastMonth = -1;
    var MN = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep',
              'Oct', 'Nov', 'Dec'];
    cols.forEach(function (col) {
      var first = null;
      for (var r = 0; r < col.length; r++) { if (col[r]) { first = col[r]; break; } }
      var label = '';
      if (first) {
        var m = new Date(first.day + 'T00:00:00Z').getUTCMonth();
        if (m !== lastMonth) { label = MN[m]; lastMonth = m; }
      }
      monthsRow += '<span class="cal-mon">' + label + '</span>';
    });

    var wd = ['Mon', '', 'Wed', '', 'Fri', '', ''];
    var wdays = wd.map(function (w) { return '<span>' + w + '</span>'; }).join('');

    var colsHTML = cols.map(function (col) {
      var cells = col.map(function (c) {
        if (!c) return '<i class="cal-cell cal-empty"></i>';
        var lvl = cellLevel(c.hands, threshold);
        var title = c.day + ': ' + c.hands + ' hand' + (c.hands === 1 ? '' : 's') +
          (c.hands ? ', ' + accText(c.correct, c.hands) + ' acc' : '') +
          (c.trained ? ' · trained' : '');
        return '<i class="cal-cell l' + lvl + '" title="' + esc(title) + '"></i>';
      }).join('');
      return '<div class="cal-col">' + cells + '</div>';
    }).join('');

    return '<section class="dash-panel">' +
      '<div class="dash-panel-head"><h3>Activity</h3>' +
        '<div class="cal-legend">Less ' +
          '<i class="cal-cell l0"></i><i class="cal-cell l1"></i>' +
          '<i class="cal-cell l2"></i><i class="cal-cell l3"></i> More' +
          '<span class="cal-legend-sep">·</span>' +
          '<i class="cal-cell l3"></i> training day (≥' + threshold + ')</div>' +
      '</div>' +
      '<div class="cal-wrap">' +
        '<div class="cal-months">' + monthsRow + '</div>' +
        '<div class="cal-body">' +
          '<div class="cal-wdays">' + wdays + '</div>' +
          '<div class="cal-cols">' + colsHTML + '</div>' +
        '</div>' +
      '</div></section>';
  }

  // =========================================================================
  // Panel C — volume + accuracy bars
  // =========================================================================

  function barsHTML(d) {
    var series = barView === 'weekly'
      ? aggregateWeeks(d.days).slice(-14)
      : (d.days || []).slice(-30);
    var maxH = series.reduce(function (m, x) { return Math.max(m, x.hands); }, 0) || 1;

    var bars = series.map(function (x) {
      var label = barView === 'weekly' ? weekLabel(x.week) : dayLabel(x.day);
      var cH = Math.round(100 * x.correct / maxH);
      var wH = Math.round(100 * (x.hands - x.correct) / maxH);
      var title = label + ': ' + x.hands + ' hands' +
        (x.hands ? ', ' + accText(x.correct, x.hands) + ' acc' : '');
      return '<div class="bar" title="' + esc(title) + '">' +
        '<div class="bar-stack">' +
          '<div class="bar-seg bar-wrong" style="height:' + wH + '%"></div>' +
          '<div class="bar-seg bar-correct" style="height:' + cH + '%"></div>' +
        '</div></div>';
    }).join('');

    var toggle =
      '<div class="seg-buttons dash-bartoggle">' +
        '<button class="seg' + (barView === 'daily' ? ' active' : '') +
          '" data-barview="daily" type="button">Daily</button>' +
        '<button class="seg' + (barView === 'weekly' ? ' active' : '') +
          '" data-barview="weekly" type="button">Weekly</button>' +
      '</div>';

    return '<section class="dash-panel">' +
      '<div class="dash-panel-head"><h3>Volume &amp; accuracy</h3>' + toggle + '</div>' +
      '<div class="dash-bars">' + (bars || '<div class="dash-note">No data.</div>') +
      '</div>' +
      '<div class="dash-bars-legend">' +
        '<span><i class="sw sw-correct"></i> correct</span>' +
        '<span><i class="sw sw-wrong"></i> incorrect</span></div>' +
      '</section>';
  }

  function wireBars() {
    var btns = document.querySelectorAll('[data-barview]');
    for (var i = 0; i < btns.length; i++) {
      btns[i].addEventListener('click', function () {
        barView = this.getAttribute('data-barview');
        if (overview) render(overview);
      });
    }
  }

  function dayLabel(iso) {
    var dt = new Date(iso + 'T00:00:00Z');
    return ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep',
            'Oct', 'Nov', 'Dec'][dt.getUTCMonth()] + ' ' + dt.getUTCDate();
  }
  function weekLabel(iso) { return 'wk ' + dayLabel(iso); }

  // =========================================================================
  // Panel D — accuracy by spot / position
  // =========================================================================

  function spotsHTML(d) {
    var spots = (d.by_spot || []).filter(function (s) { return s.hands > 0; });
    if (!spots.length) return '';
    var cards = spots.map(function (s) {
      var rows = s.rows.slice().sort(function (a, b) { return b.hands - a.hands; })
        .map(function (r) {
          var p = r.accuracy == null ? 0 : r.accuracy;
          return '<div class="spot-row">' +
            '<span class="spot-key">' + esc(r.key) + '</span>' +
            '<span class="spot-acc-bar"><span class="spot-acc-fill" style="width:' +
              p + '%"></span></span>' +
            '<span class="spot-acc-val">' + accText(r.correct, r.hands) + '</span>' +
            '<span class="spot-hands">' + num(r.hands) + '</span>' +
          '</div>';
        }).join('');
      return '<div class="spot-card">' +
        '<div class="spot-card-head">' +
          '<span class="spot-name">' + (SPOT_LABEL[s.spot] || esc(s.spot)) + '</span>' +
          '<span class="spot-overall">' + accText(s.correct, s.hands) +
            ' · ' + num(s.hands) + ' hands</span>' +
        '</div>' + rows + '</div>';
    }).join('');

    return '<section class="dash-panel">' +
      '<div class="dash-panel-head"><h3>Accuracy by spot</h3></div>' +
      '<div class="spot-grid">' + cards + '</div></section>';
  }

  // =========================================================================
  // Boot
  // =========================================================================

  function init() {
    buildUserMenu();
    wireModeTabs();
    var rf = document.getElementById('dashRefresh');
    if (rf) rf.addEventListener('click', function () { loadDashboard(true); });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // Pure helpers for the node DOM-stub test.
  window.PRXDash = {
    buildCalendar: buildCalendar,
    aggregateWeeks: aggregateWeeks,
    cellLevel: cellLevel,
    mondayIdx: mondayIdx,
    pct: pct,
    buildBody: buildBody,
    setBarView: function (v) { barView = v; }
  };
})();
