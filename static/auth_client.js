/* auth_client.js — Track D, D.2 frontend login gate.
 *
 * Loaded as the FIRST <script> in index.html (before drill.js / learn.js /
 * visualizer.js / editor.js). It has two jobs:
 *
 *   1. Synchronously wrap window.fetch so every PROTECTED same-origin /api/*
 *      request carries the logged-in user's Supabase access token as an
 *      `Authorization: Bearer <JWT>` header. Protected calls also wait for
 *      `authReady`, so they never fire before we have a token (they resolve the
 *      moment the user logs in, then populate their panels).
 *
 *   2. Drive the login lifecycle when auth is enabled: load supabase-js from the
 *      CDN, check for an existing session, show a full-screen login gate when
 *      logged out, keep the token fresh, and offer Sign out in the topbar.
 *
 * SOFT DEGRADATION (the hard project constraint — must never break prod):
 * when the backend reports auth is OFF (no SUPABASE_URL → /api/auth/config
 * returns {enabled:false}) this file does NOTHING visible — no overlay, no
 * supabase-js, no Authorization header. The current single-user prod/JSON setup
 * behaves exactly as before. The only cost is one extra local request
 * (/api/auth/config) whose result `authReady` waits on.
 *
 * WHY GATE ONLY THE PROTECTED ENDPOINTS, not all /api/*:
 * drill.js boots immediately and fetches the pack list through a 5s-abort
 * `fetchWithTimeout`. If we made open library calls wait for login, a user who
 * takes >5s to type a password would have that call aborted and the app would
 * boot broken. The open endpoints (ranges / config / drill-hand / db-health)
 * need no token, so we let them through at once — the app shell boots normally
 * BEHIND the overlay. Only the protected set waits, and those all use plain
 * fetch (no abort), so queuing them until login is safe. The list below mirrors
 * the backend's Depends(get_current_user) set.
 */
(function () {
  'use strict';

  // The REAL fetch, captured before we replace it. Used for our own ungated
  // config probe and as the underlying transport for every wrapped call.
  var rawFetch = window.fetch.bind(window);

  // authReady gates the protected /api/* calls. It resolves when we are ready
  // to talk to the protected API:
  //   * auth DISABLED  -> immediately (config says enabled:false);
  //   * auth ENABLED   -> once a session/token exists (i.e. after login).
  // While logged out in enabled mode it stays pending, so protected data calls
  // simply queue behind it and fire the instant login completes.
  var markReady;
  var authReady = new Promise(function (resolve) { markReady = resolve; });
  window.authReady = authReady;            // exposed for debugging / future use

  var accessToken = null;   // current JWT; refreshed via onAuthStateChange
  var sbClient = null;      // supabase-js client (created only in enabled mode)
  var authMode = 'signin';  // login-gate tab: 'signin' | 'signup'

  // Minimal public surface for the user menu (account.js → Progress dashboard):
  //   enabled — is login active (set once /api/auth/config resolves)
  //   email   — the signed-in user's email (for the menu header)
  //   signOut — trigger Supabase sign-out (the menu's Sign out item calls this)
  // Merged into an existing object, never blindly overwritten, so the load order
  // between this file and account.js does not matter.
  window.PRXAuth = window.PRXAuth || {};
  if (typeof window.PRXAuth.enabled === 'undefined') window.PRXAuth.enabled = false;
  if (typeof window.PRXAuth.email === 'undefined') window.PRXAuth.email = null;
  if (typeof window.PRXAuth.signOut !== 'function') window.PRXAuth.signOut = function () {};

  function setSessionUser(session) {
    window.PRXAuth.email = (session && session.user && session.user.email) || null;
  }

  // Protected endpoints (mirror of the backend's Depends(get_current_user)).
  // Matches /api/drill/answer, /api/stats(+/reset), /api/history(+/clear),
  // and any /api/srs/*. Does NOT match the open library endpoints
  // (/api/ranges*, /api/config, /api/drill/hand, /api/db/health,
  // /api/auth/config), nor cross-origin supabase.co URLs.
  function needsAuth(url) {
    return /\/api\/(?:drill\/answer|stats|history|srs|dashboard)(?:[\/?#]|$)/.test(url);
  }

  // ---- 1. Install the fetch wrapper SYNCHRONOUSLY --------------------------
  // Must be in place before drill.js runs boot() (next script), so its first
  // protected calls are gated and tokenized.
  window.fetch = function (input, init) {
    var url = typeof input === 'string' ? input
            : (input && input.url) ? input.url : '';
    if (!needsAuth(url)) {
      return rawFetch(input, init);        // open endpoint / non-API: passthrough
    }
    return authReady.then(function () {
      if (!accessToken) {
        return rawFetch(input, init);      // disabled mode (no token) — as before
      }
      var opts = Object.assign({}, init);
      var headers = new Headers((init && init.headers) || undefined);
      headers.set('Authorization', 'Bearer ' + accessToken);
      opts.headers = headers;
      return rawFetch(input, opts);
    });
  };

  // ---- 2. Decide the mode, then drive login if needed ----------------------
  rawFetch('/api/auth/config')
    .then(function (r) { return r.json(); })
    .then(function (cfg) {
      if (!cfg || !cfg.enabled) {                           // disabled → as before
        window.PRXAuth.enabled = false;
        markReady();
        return;
      }
      window.PRXAuth.enabled = true;
      window.PRXAuth.signOut = function () {
        if (sbClient) sbClient.auth.signOut();              // → SIGNED_OUT → reload
      };
      return startAuth(cfg);
    })
    .catch(function (e) {
      // Fail OPEN to current behaviour: a transient config blip must not brick
      // the UI. (If auth were truly required the protected calls would 401, but
      // the overlay is the gate — a missing config shouldn't hang the app.)
      console.warn('[auth] config probe failed, running without login:', e);
      markReady();
    });

  // ---- supabase-js init + session check -----------------------------------
  function startAuth(cfg) {
    showGate();              // cover the app immediately (we are in enabled mode)
    busy(true);              // login buttons inert until supabase-js is ready
    return loadSupabaseJs().then(function () {
      sbClient = window.supabase.createClient(cfg.url, cfg.anon_key, {
        auth: {
          persistSession: true,
          autoRefreshToken: true,
          detectSessionInUrl: true   // parse the #access_token after OAuth return
        }
      });

      // Single source of token freshness. Fires INITIAL_SESSION on setup, then
      // SIGNED_IN / TOKEN_REFRESHED / SIGNED_OUT over the session's life.
      sbClient.auth.onAuthStateChange(function (event, session) {
        if (session && session.access_token) {
          accessToken = session.access_token;
          setSessionUser(session);
          hideGate();
          markReady();             // unblock any queued protected /api/* calls
        } else {
          accessToken = null;
          if (event === 'SIGNED_OUT') {
            // Cleanest reset: reload so the whole app re-gates from scratch and
            // no stale per-user data lingers in memory.
            location.reload();
          }
        }
      });

      // Explicit initial check (returning user, or an OAuth redirect that just
      // landed). Idempotent with the INITIAL_SESSION event above.
      return sbClient.auth.getSession().then(function (res) {
        var session = res && res.data && res.data.session;
        if (session && session.access_token) {
          accessToken = session.access_token;
          setSessionUser(session);
          hideGate();
          markReady();
        } else {
          busy(false);             // logged out → enable the login buttons
        }
      });
    }).catch(function (e) {
      console.error('[auth] failed to initialise login:', e);
      busy(false);
      msg('Could not load the login service. Check your connection and reload.',
          'error');
    });
  }

  function loadSupabaseJs() {
    if (window.supabase && window.supabase.createClient) {
      return Promise.resolve();
    }
    return new Promise(function (resolve, reject) {
      var s = document.createElement('script');
      // v2 UMD build; exposes window.supabase.createClient.
      s.src = 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2';
      s.async = true;
      s.onload = function () { resolve(); };
      s.onerror = function () { reject(new Error('supabase-js CDN load failed')); };
      document.head.appendChild(s);
    });
  }

  // ---- Login gate UI -------------------------------------------------------
  // Built lazily, styled with the app's design tokens (var(--…)) so it matches
  // the dark-graphite + gold theme. Self-contained: the <style> is injected
  // only here, so disabled-mode prod never pays for it.
  var GOOGLE_SVG =
    '<svg viewBox="0 0 48 48" aria-hidden="true">' +
    '<path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>' +
    '<path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>' +
    '<path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.28-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>' +
    '<path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.46-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>' +
    '</svg>';

  function injectStyles() {
    if (document.getElementById('prxAuthStyle')) return;
    var css =
      '.prx-auth-overlay{position:fixed;inset:0;z-index:99999;' +
        'background:var(--bg,#0a0b0e);display:flex;align-items:center;' +
        'justify-content:center;padding:20px;' +
        "font-family:var(--font-ui,'Hanken Grotesk',sans-serif);}" +
      '.prx-auth-card{width:340px;max-width:90vw;background:var(--panel,#14161b);' +
        'border:1px solid var(--stroke,#2f333b);border-radius:14px;' +
        'padding:28px 26px;display:flex;flex-direction:column;gap:12px;' +
        'box-shadow:0 24px 70px rgba(0,0,0,.55);}' +
      '.prx-auth-logo{display:flex;align-items:center;gap:8px;' +
        'justify-content:center;font-size:20px;font-weight:700;' +
        'color:var(--text,#e6e8ec);margin-bottom:4px;}' +
      '.prx-auth-mark{display:inline-flex;align-items:center;' +
        'justify-content:center;width:30px;height:30px;border-radius:8px;' +
        'background:var(--gold,#c9a84c);color:#1a1206;font-weight:800;}' +
      '.prx-auth-accent{color:var(--gold,#c9a84c);}' +
      '.prx-auth-sub{font-size:12.5px;color:var(--text-dim,#79808c);' +
        'text-align:center;margin-bottom:4px;}' +
      '.prx-auth-tabs{display:flex;gap:6px;}' +
      '.prx-auth-tab{flex:1;padding:8px 0;border:1px solid var(--stroke,#2f333b);' +
        'background:transparent;color:var(--text-mid,#aab0bc);border-radius:8px;' +
        'cursor:pointer;font:inherit;font-size:13px;}' +
      '.prx-auth-tab.is-active{background:var(--surface-2,#1c1f26);' +
        'color:var(--text,#e6e8ec);border-color:var(--gold,#c9a84c);}' +
      '.prx-auth-input{padding:11px 12px;background:var(--recessed,#0e0f13);' +
        'border:1px solid var(--stroke,#2f333b);border-radius:8px;' +
        'color:var(--text,#e6e8ec);font:inherit;font-size:14px;}' +
      '.prx-auth-input::placeholder{color:var(--text-dim,#79808c);}' +
      '.prx-auth-input:focus{outline:none;border-color:var(--gold,#c9a84c);}' +
      '.prx-auth-primary{padding:12px;background:var(--gold,#c9a84c);' +
        'color:#1a1206;border:none;border-radius:8px;font:inherit;' +
        'font-weight:700;font-size:14px;cursor:pointer;}' +
      '.prx-auth-primary:disabled{opacity:.55;cursor:default;}' +
      '.prx-auth-or{display:flex;align-items:center;gap:10px;' +
        'color:var(--text-dim,#79808c);font-size:12px;}' +
      ".prx-auth-or::before,.prx-auth-or::after{content:'';flex:1;height:1px;" +
        'background:var(--stroke,#2f333b);}' +
      '.prx-auth-google{display:flex;align-items:center;justify-content:center;' +
        'gap:10px;padding:11px;background:#fff;color:#1f1f1f;border:none;' +
        'border-radius:8px;font:inherit;font-weight:600;font-size:14px;' +
        'cursor:pointer;}' +
      '.prx-auth-google:disabled{opacity:.55;cursor:default;}' +
      '.prx-auth-google svg{width:18px;height:18px;}' +
      '.prx-auth-msg{font-size:12.5px;line-height:1.5;' +
        'color:var(--text-mid,#aab0bc);min-height:16px;text-align:center;}' +
      '.prx-auth-msg.is-error{color:#e0654f;}' +
      '.prx-auth-msg.is-ok{color:#57b06f;}' +
      '.prx-signout{margin-left:10px;padding:5px 10px;background:transparent;' +
        'border:1px solid var(--stroke,#2f333b);border-radius:7px;' +
        'color:var(--text-mid,#aab0bc);font:inherit;font-size:11px;' +
        'cursor:pointer;}' +
      '.prx-signout:hover{color:var(--text,#e6e8ec);' +
        'border-color:var(--gold,#c9a84c);}';
    var st = document.createElement('style');
    st.id = 'prxAuthStyle';
    st.textContent = css;
    document.head.appendChild(st);
  }

  function buildGate() {
    injectStyles();
    var ov = document.createElement('div');
    ov.className = 'prx-auth-overlay';
    ov.id = 'prxAuthOverlay';
    ov.innerHTML =
      '<div class="prx-auth-card">' +
        '<div class="prx-auth-logo"><span class="prx-auth-mark">P</span>' +
          '<span>Preflop<span class="prx-auth-accent">Range</span></span></div>' +
        '<div class="prx-auth-sub">Sign in to train and save your progress</div>' +
        '<div class="prx-auth-tabs">' +
          '<button class="prx-auth-tab is-active" data-authtab="signin" type="button">Sign in</button>' +
          '<button class="prx-auth-tab" data-authtab="signup" type="button">Sign up</button>' +
        '</div>' +
        '<input class="prx-auth-input" id="prxEmail" type="email" placeholder="Email" autocomplete="email">' +
        '<input class="prx-auth-input" id="prxPass" type="password" placeholder="Password" autocomplete="current-password">' +
        '<button class="prx-auth-primary" id="prxSubmit" type="button">Sign in</button>' +
        '<div class="prx-auth-or"><span>or</span></div>' +
        '<button class="prx-auth-google" id="prxGoogle" type="button">' + GOOGLE_SVG +
          'Continue with Google</button>' +
        '<div class="prx-auth-msg" id="prxMsg"></div>' +
      '</div>';
    document.body.appendChild(ov);

    var tabs = ov.querySelectorAll('[data-authtab]');
    for (var i = 0; i < tabs.length; i++) {
      (function (tab) {
        tab.addEventListener('click', function () {
          setMode(tab.getAttribute('data-authtab'));
        });
      })(tabs[i]);
    }
    document.getElementById('prxSubmit').addEventListener('click', onSubmit);
    document.getElementById('prxGoogle').addEventListener('click', onGoogle);
    document.getElementById('prxPass').addEventListener('keydown', function (e) {
      if (e.key === 'Enter') onSubmit();
    });
    return ov;
  }

  function showGate(errMsg) {
    var ov = document.getElementById('prxAuthOverlay') || buildGate();
    ov.style.display = 'flex';
    if (errMsg) msg(errMsg, 'error');
  }

  function hideGate() {
    var ov = document.getElementById('prxAuthOverlay');
    if (ov) ov.style.display = 'none';
    showSignOut();
  }

  function showSignOut() {
    if (document.getElementById('prxSignOut')) return;
    // If account.js mounted the user menu, Sign out lives inside it (it calls
    // window.PRXAuth.signOut) — don't add a duplicate standalone button.
    if (document.getElementById('prxUserMenu')) return;
    var bar = document.querySelector('.topbar');
    if (!bar) return;
    injectStyles();
    var btn = document.createElement('button');
    btn.id = 'prxSignOut';
    btn.className = 'prx-signout';
    btn.type = 'button';
    btn.textContent = 'Sign out';
    btn.addEventListener('click', function () {
      if (sbClient) sbClient.auth.signOut();   // → SIGNED_OUT → location.reload()
    });
    bar.appendChild(btn);
  }

  // ---- Gate actions --------------------------------------------------------
  function onSubmit() {
    if (!sbClient) return;
    var email = val('prxEmail');
    var pass = val('prxPass');
    if (!email || !pass) { msg('Enter your email and password.', 'error'); return; }
    busy(true);
    var p = authMode === 'signup'
      ? sbClient.auth.signUp({ email: email, password: pass })
      : sbClient.auth.signInWithPassword({ email: email, password: pass });
    p.then(function (res) {
      busy(false);
      if (res.error) { msg(res.error.message, 'error'); return; }
      if (authMode === 'signup' && !(res.data && res.data.session)) {
        // Email confirmation is ON → no session yet. Tell them to confirm.
        // (If confirmation were OFF, a session would arrive and
        // onAuthStateChange would hide the gate instead.)
        msg('Account created. Check your email to confirm, then sign in.', 'ok');
        setMode('signin');
      }
      // Sign-in success (or confirm-off signup) → onAuthStateChange fires
      // SIGNED_IN → hideGate() + markReady().
    }).catch(function (e) {
      busy(false);
      msg(String((e && e.message) || e), 'error');
    });
  }

  function onGoogle() {
    if (!sbClient) return;
    busy(true);
    sbClient.auth.signInWithOAuth({
      provider: 'google',
      // Return to this exact origin after Google. Must be in Supabase's
      // Redirect URLs allowlist (URL Configuration).
      options: { redirectTo: window.location.origin }
    }).then(function (res) {
      if (res && res.error) { busy(false); msg(res.error.message, 'error'); }
      // else the browser is navigating to Google now.
    }).catch(function (e) {
      busy(false);
      msg(String((e && e.message) || e), 'error');
    });
  }

  function setMode(m) {
    authMode = m;
    var tabs = document.querySelectorAll('.prx-auth-tab');
    for (var i = 0; i < tabs.length; i++) {
      tabs[i].classList.toggle('is-active',
        tabs[i].getAttribute('data-authtab') === m);
    }
    var sub = document.getElementById('prxSubmit');
    if (sub) sub.textContent = m === 'signup' ? 'Create account' : 'Sign in';
    var pass = document.getElementById('prxPass');
    if (pass) pass.setAttribute('autocomplete',
      m === 'signup' ? 'new-password' : 'current-password');
    msg('');
  }

  // ---- small helpers -------------------------------------------------------
  function val(id) {
    var el = document.getElementById(id);
    return el ? el.value.trim() : '';
  }
  function msg(text, kind) {
    var el = document.getElementById('prxMsg');
    if (!el) return;
    el.textContent = text || '';
    el.className = 'prx-auth-msg' + (kind ? ' is-' + kind : '');
  }
  function busy(on) {
    ['prxSubmit', 'prxGoogle'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.disabled = !!on;
    });
  }
})();
