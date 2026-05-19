/* ============================================================
   postflop.js — Postflop cash trainer (fold/call vs villain type)
   Mirrors drill.js conventions. Reuses existing CSS:
   .card-front / .card-corner / .card-center / .feedback-strip / .seg
   Talks to: GET /api/postflop/spot , POST /api/postflop/answer
   ============================================================ */
   (function () {
    'use strict';
  
    const SUIT = { s: '\u2660', h: '\u2665', d: '\u2666', c: '\u2663' };
    const RED  = '\u2665\u2666';
  
    const pf = {
      token: null,
      villainType: '',
      answered: false,
      sess: { ok: 0, total: 0 },
    };
  
    // ---- card rendering: API gives "AhKs", reuse drill.js card markup ----
    function renderInto(containerId, cardStr) {
      const box = document.getElementById(containerId);
      if (!box) return;
      box.innerHTML = '';
      for (let i = 0; i < cardStr.length; i += 2) {
        const rank = cardStr[i] === 'T' ? '10' : cardStr[i];
        const sc = cardStr[i + 1].toLowerCase();
        const sym = SUIT[sc];
        const isRed = RED.includes(sym);
        const el = document.createElement('div');
        el.className = `card card-front ${isRed ? 'red' : 'black'} deal-in`;
        el.style.animationDelay = (i / 2) * 0.07 + 's';
        el.innerHTML =
          `<div class="card-corner">${rank}<br>${sym}</div>` +
          `<div class="card-center">${sym}</div>`;
        box.appendChild(el);
      }
    }
  
    function renderPfSeats(heroPos, villainPos, toCall) {
      const seats = document.getElementById('pfSeats');
      if (!seats) return;
      seats.innerHTML = '';

      // ── Villain: cards above table rim, VILLAIN label under cards, circle at rim ──
      const vSeat = document.createElement('div');
      vSeat.className = 'seat';
      vSeat.style.top  = '-2%';   // pushes cards above the table-wrap top
      vSeat.style.left = '50%';
      vSeat.innerHTML =
        '<div style="display:flex;gap:5px;margin-bottom:3px">' +
          '<div class="card card-back" style="width:30px;height:43px"></div>' +
          '<div class="card card-back" style="width:30px;height:43px"></div>' +
        '</div>' +
        '<div class="seat-name" style="margin-bottom:2px">VILLAIN</div>' +
        `<div class="seat-circle is-villain">${villainPos}</div>`;
      seats.appendChild(vSeat);

      // ── Villain bet chip — in the gap between villain circle and board cards ──
      const chip = document.createElement('div');
      chip.className   = 'bet-chip chip-open';
      chip.textContent = toCall;
      chip.style.top   = '20%';
      chip.style.left  = '50%';
      seats.appendChild(chip);

      // ── Hero seat (bottom center, inside table) ────────
      const hSeat = document.createElement('div');
      hSeat.className = 'seat';
      hSeat.style.top  = '84%';
      hSeat.style.left = '50%';
      hSeat.innerHTML =
        `<div class="seat-circle is-hero">${heroPos}</div>` +
        '<div class="seat-name is-hero">YOU</div>';
      seats.appendChild(hSeat);
    }

    function setButtonsEnabled(on) {
      document.getElementById('pfFold').disabled = !on;
      document.getElementById('pfCall').disabled = !on;
      document.getElementById('pfFold').style.opacity = on ? '1' : '.4';
      document.getElementById('pfCall').style.opacity = on ? '1' : '.4';
    }
  
    function clearVerdict() {
      document.getElementById('pfFeedback').style.display = 'none';
      document.getElementById('pfFeedback').className = 'feedback-strip';
      const bw = document.getElementById('pfBreakdownWrap');
      if (bw) bw.style.display = 'none';
      ['pfEq', 'pfNeed', 'pfCorrect'].forEach(
        id => (document.getElementById(id).textContent = '\u2014'));
    }
  
    async function dealSpot() {
      pf.answered = false;
      clearVerdict();
      setButtonsEnabled(false);
      document.getElementById('pfCall').textContent = 'Call';
      document.getElementById('pfVillainLine').textContent = 'Dealing\u2026';
      try {
        const q = pf.villainType ? `?villain_type=${pf.villainType}` : '';
        const res = await fetch(`/api/postflop/spot${q}`);
        if (!res.ok) throw new Error('spot request failed');
        const s = await res.json();
        pf.token = s.token;
        document.getElementById('pfVillainLine').textContent =
          `${s.villain_label} \u2014 ${s.villain_desc}`;
        document.getElementById('pfSpotLine').textContent =
          `Postflop \u00b7 Cash \u00b7 ${s.hero_pos} vs ${s.villain_pos}`;
        document.getElementById('pfPot').textContent = s.pot + ' BB';
        document.getElementById('pfToCall').textContent = s.to_call + ' BB';
        document.getElementById('pfCall').textContent = `Call ${s.to_call} BB`;
        renderInto('pfBoard', s.board);
        renderInto('pfHole', s.hero);
        renderPfSeats(s.hero_pos, s.villain_pos, s.to_call);
        setButtonsEnabled(true);
      } catch (e) {
        document.getElementById('pfVillainLine').textContent =
          'Could not load a spot \u2014 is the server running?';
      }
    }
  
    async function answer(action) {
      if (!pf.token || pf.answered) return;
      pf.answered = true;
      setButtonsEnabled(false);
      try {
        const res = await fetch('/api/postflop/answer', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token: pf.token, action }),
        });
        if (!res.ok) {
          const j = await res.json().catch(() => ({}));
          throw new Error(j.detail || 'grade failed');
        }
        showVerdict(await res.json());
      } catch (e) {
        pf.answered = false;
        setButtonsEnabled(true);
        document.getElementById('pfVillainLine').textContent = e.message;
      }
    }
  
    function renderBreakdown(el, made, draws) {
      el.innerHTML = '';
      const rows = [];
      // made: either a single label (hero) or list of {label,combos,pct}
      if (Array.isArray(made)) {
        made.forEach(m => rows.push([m.label, m.combos, m.pct, false]));
      } else if (made) {
        rows.push([made, null, null, false]);
      }
      const dlist = Array.isArray(draws) ? draws : [];
      dlist.forEach(d => {
        if (typeof d === 'string') rows.push([d, null, null, true]);
        else rows.push([d.label, d.combos, d.pct, true]);
      });
      if (rows.length === 0) {
        el.innerHTML = '<div class="pf-break-empty">\u2014</div>';
        return;
      }
      rows.forEach(([lbl, combos, pct, isDraw]) => {
        const row = document.createElement('div');
        row.className = 'pf-break-row' + (isDraw ? ' is-draw' : '');
        const bar = pct != null
          ? `<div class="pf-bar" style="width:${Math.min(pct,100)}%"></div>`
          : '';
        const num = pct != null
          ? `<span class="pf-num">${combos} \u00b7 ${pct}%</span>`
          : '<span class="pf-num"></span>';
        row.innerHTML =
          bar +
          `<span class="pf-lbl">${lbl}</span>` + num;
        el.appendChild(row);
      });
    }

    function showVerdict(v) {
      pf.sess.total += 1;
      if (v.is_correct) pf.sess.ok += 1;
  
      const strip = document.getElementById('pfFeedback');
      strip.style.display = 'flex';
      strip.className = 'feedback-strip ' + (v.is_correct ? 'correct' : 'wrong');
      document.getElementById('pfFbIcon').textContent =
        v.is_correct ? '\u2713' : '\u2717';
      document.getElementById('pfFbMsg').textContent = v.explain;
  
      // EV of the player's actual decision (right choice → positive,
      // wrong choice → negative). Prefer the server-computed value, but
      // derive it client-side from ev_call/player_action if missing — that
      // way an older cached Python server still gives the correct sign.
      let evVal;
      if (v.ev_decision !== undefined && v.ev_decision !== null) {
        evVal = v.ev_decision;
      } else {
        const evCall = v.ev_call ?? 0;
        evVal = (v.player_action === 'call') ? evCall : -evCall;
      }
      const ev = document.getElementById('pfFbEv');
      ev.textContent = (evVal >= 0 ? '+' : '') + evVal.toFixed(2) + ' BB';
      ev.className = 'fb-ev ' + (evVal >= 0 ? 'pos' : 'neg');
  
      document.getElementById('pfEq').textContent =
        (v.hero_equity * 100).toFixed(1) + '%';
      document.getElementById('pfNeed').textContent =
        (v.required_equity * 100).toFixed(1) + '%';
      document.getElementById('pfCorrect').textContent =
        v.correct_action.toUpperCase();
  
      document.getElementById('pfSessOk').textContent =
        `${pf.sess.ok} / ${pf.sess.total}`;
      document.getElementById('pfSessPct').textContent =
        Math.round((pf.sess.ok / pf.sess.total) * 100) + '%';

      // --- equity.poker-style breakdown panels ---
      if (v.hero_breakdown && v.villain_breakdown) {
        document.getElementById('pfBreakdownWrap').style.display = 'block';
        renderBreakdown(
          document.getElementById('pfHeroBreak'),
          v.hero_breakdown.made, v.hero_breakdown.draws);
        renderBreakdown(
          document.getElementById('pfVillBreak'),
          v.villain_breakdown.made, v.villain_breakdown.draws);
      }

      if (document.getElementById('pfAutoNext').checked) {
        document.getElementById('pfFbNext').style.display = 'none';
        setTimeout(dealSpot, 2200);
      } else {
        document.getElementById('pfFbNext').style.display = 'inline-block';
      }
    }
  
    function bind() {
      document.getElementById('pfVillainBtns')
        .addEventListener('click', e => {
          const b = e.target.closest('.seg');
          if (!b) return;
          document.querySelectorAll('#pfVillainBtns .seg')
            .forEach(x => x.classList.remove('active'));
          b.classList.add('active');
          pf.villainType = b.dataset.pfvt;
          dealSpot();
        });
      document.getElementById('pfFold').onclick = () => answer('fold');
      document.getElementById('pfCall').onclick = () => answer('call');
      document.getElementById('pfFbNext').onclick = dealSpot;
      document.getElementById('pfDealBtn').onclick = dealSpot;
    }
  
    // Public hook called by drill.js when the Postflop tab opens
    window.PostflopTrainer = {
      onShow() {
        if (!pf.token) dealSpot();
      },
    };
  
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', bind);
    } else {
      bind();
    }
  })();