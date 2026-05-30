// ── Mobile bottom sheet (Track B.4, Stage 2) ──────────────────────────────
// Turns each .panel-left (the Format / Spot / Position settings panel) into a
// bottom sheet that pulls up on swipe-up or a tap of its grab handle, and
// closes on swipe-down, a tap on the handle, or a tap on the dimmed backdrop.
//
// Desktop is untouched: the handle is display:none above the breakpoint (see
// style.css) and the toggle classes never get applied because the handle —
// the only thing that opens the sheet — isn't visible to tap. We still wire
// listeners unconditionally (they're harmless) and close everything when the
// viewport grows back to desktop.
(function () {
  'use strict';

  var MQ = window.matchMedia('(max-width: 768px)');
  var backdrop = null;
  var dealFab = null;

  function getBackdrop() {
    if (backdrop) return backdrop;
    backdrop = document.createElement('div');
    backdrop.className = 'sheet-backdrop';
    backdrop.addEventListener('click', closeAll);
    document.body.appendChild(backdrop);
    return backdrop;
  }

  function panels() {
    return Array.prototype.slice.call(document.querySelectorAll('.panel-left'));
  }

  function open(p)  { p.classList.add('sheet-open');  getBackdrop().classList.add('show'); }
  function close(p) { p.classList.remove('sheet-open'); if (backdrop) backdrop.classList.remove('show'); }
  function toggle(p){ p.classList.contains('sheet-open') ? close(p) : open(p); }

  function closeAll() {
    panels().forEach(function (p) { p.classList.remove('sheet-open'); });
    if (backdrop) backdrop.classList.remove('show');
  }

  function attachHandle(p) {
    if (p.querySelector('.sheet-handle')) return;     // already wired

    var h = document.createElement('div');
    h.className = 'sheet-handle';
    h.innerHTML = '<span class="sheet-handle-label">Settings</span>';
    p.insertBefore(h, p.firstChild);

    // Tap toggles open/close.
    h.addEventListener('click', function () { toggle(p); });

    // Swipe: track vertical delta on the handle only, so swipes inside the
    // panel body still scroll its content normally.
    var y0 = null;
    h.addEventListener('touchstart', function (e) {
      y0 = e.touches[0].clientY;
    }, { passive: true });

    h.addEventListener('touchend', function (e) {
      if (y0 === null) return;
      var dy = e.changedTouches[0].clientY - y0;
      y0 = null;
      if (dy < -30) open(p);          // swipe up  → reveal
      else if (dy > 30) close(p);     // swipe down → hide
      // tiny moves fall through to the click handler (tap = toggle)
      else return;
      e.preventDefault();             // a real swipe shouldn't also fire click
    });
  }

  // ── Floating "Deal" button ──────────────────────────────────────────────
  // The real #newHandBtn (Deal Hand) lives inside the settings sheet, so on
  // mobile we surface a floating proxy that clicks it. We proxy rather than
  // move the element so all of drill.js's wiring keeps working untouched.
  function getDealFab() {
    if (dealFab) return dealFab;
    dealFab = document.createElement('button');
    dealFab.type = 'button';
    dealFab.className = 'mobile-deal-fab';
    dealFab.textContent = 'Deal';
    dealFab.addEventListener('click', function () {
      var real = document.getElementById('newHandBtn');
      if (real) real.click();
    });
    document.body.appendChild(dealFab);
    return dealFab;
  }

  function drillVisible() {
    var d = document.getElementById('drillMode');
    return !!d && getComputedStyle(d).display !== 'none';
  }

  function updateDealFab() {
    getDealFab().style.display = (MQ.matches && drillVisible()) ? 'flex' : 'none';
  }

  function setup() {
    panels().forEach(attachHandle);
    updateDealFab();
    if (!MQ.matches) closeAll();      // back on desktop → make sure nothing's stuck open
  }

  // Closing the sheet when switching tabs avoids a sheet from one mode lingering
  // open (and the backdrop staying up) when another mode is shown.
  function wireTabs() {
    document.querySelectorAll('.mode-tab').forEach(function (t) {
      t.addEventListener('click', function () {
        closeAll();
        // drill.js toggles mode visibility on the same click; defer so we read
        // the post-switch state when deciding whether to show the Deal FAB.
        setTimeout(updateDealFab, 0);
      });
    });
  }

  function init() { setup(); wireTabs(); }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
  // Re-evaluate on breakpoint change (e.g. device rotation, window resize).
  if (MQ.addEventListener) MQ.addEventListener('change', setup);
  else if (MQ.addListener) MQ.addListener(setup);   // older Safari
})();
