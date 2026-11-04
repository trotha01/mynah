/* J's expression engine, shared by every look (looks.js, anime.js, looks.html, index.html).
 A look supplies SVG, init() and apply(); the engine supplies the behaviour:
  - a small fixed expression set (neutral, listening, thinking, happy, speaking, surprised, concerned, sleep), as on a
    character expression sheet; a director picks ONE expression from the voice state;
  - no flicker: a state must last DEBOUNCE ms before it changes anything (a brief blip is ignored), and once an
    expression shows it is held for a minimum time long enough to read before the face may change again
    (surprised on a barge-in may cut in after a short beat); transitions themselves are quick (~120 ms);
  - natural blinks: every 3-6.5 s, ~170 ms, occasionally a double blink, never in the middle of a loud word;
  - glances every 1.6-3 s (thinking) / 1.8-3.5 s (otherwise); mouth openness follows the audio level (fast) and the
    mouth SHAPE (a/e/i/o/u) is picked once per syllable;
  - worker-news reactions, thinking dots, and an occasional emphasis squint while speaking. */
(function (g) {
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const rnd = (a, b) => a + Math.random() * (b - a);
  const KCOL = { waiting: '#6ee7a0', needs_you: '#ffb347', done: '#7fc8c4', blocked: '#ff6b6b' };

  // tilt: + = inner brow end down (stern/thinking), - = inner end up (worried). shape: c closed, D open smile, a e i o u.
  const BASE = { open: 1, squint: 0, browL: 0, browR: 0, tilt: 0, gx: 0, gy: 0, pup: 1, blush: .1, roll: 0, mouth: 0, smile: .35, alert: .3, dots: 0 };
  const EXPR = {
    neutral:   { ...BASE },
    listening: { ...BASE, open: 1.05, browL: .15, browR: .15, pup: 1.1, blush: .2, smile: .6, alert: .5, roll: 3 },
    thinking:  { ...BASE, open: .92, browL: .55, browR: -.05, tilt: .25, gx: -.7, gy: -.8, pup: .95, smile: -.05, roll: -3, dots: 1 },
    happy:     { ...BASE, squint: .9, browL: .5, browR: .5, blush: .6, smile: 1, mouth: .38, shape: 'D', alert: .8, roll: 2 },
    speaking:  { ...BASE, browL: .15, browR: .15, smile: .35, blush: .15, alert: .6 },
    surprised: { ...BASE, open: 1.25, browL: 1, browR: 1, pup: .6, blush: .2, smile: 0, mouth: .45, shape: 'o', alert: 1.3 },
    concerned: { ...BASE, open: .95, browL: .35, browR: .35, tilt: -.9, gy: .35, pup: 1.05, blush: 0, smile: -.6, alert: -.1, roll: -2 },
    sleep:     { ...BASE, open: .06, browL: -.3, browR: -.3, smile: .1, alert: -.6, blush: .1 }
  };
  // minimum time (ms) an expression is shown before the director may switch away from it (readable, no flash)
  const HOLD = { neutral: 400, listening: 500, thinking: 800, happy: 1400, speaking: 500, surprised: 1000, concerned: 1400, sleep: 400 };
  const DEBOUNCE = 300;   // ms a state must last before the face reacts to it
  const GLANCES = [[-1, -.9], [1, -.8], [0, -1.1], [-.8, -.2], [.9, -.3]];

  const CSS = `
  .cmp{overflow:visible}
  .cmp .bot{transform-box:fill-box;transform-origin:50% 100%}
  @keyframes cmp-breathe{50%{transform:scale(1.012,1.02)}}
  @keyframes cmp-bob{50%{transform:translateY(-4px)}}
  @keyframes cmp-lean{50%{transform:rotate(-2.5deg) translateY(2px)}}
  @keyframes cmp-jump{0%{transform:translateY(0) scale(1)}35%{transform:translateY(-26px) scale(1.05,.95)}100%{transform:translateY(0) scale(1)}}
  @keyframes cmp-talk{50%{transform:translateY(-1.5px)}}
  @keyframes cmp-hop{0%{transform:translateY(0)}30%{transform:translateY(-8px)}100%{transform:translateY(0)}}
  .cmp[data-s=listening] .bot,.cmp[data-s=loading] .bot,.cmp[data-s=waiting] .bot,.cmp[data-s=transcribing] .bot{animation:cmp-breathe 4.5s ease-in-out infinite}
  .cmp[data-s=hearing] .bot{animation:cmp-lean .7s ease-in-out infinite}
  .cmp[data-s=speaking] .bot{animation:cmp-bob .55s ease-in-out infinite}
  .cmp[data-s=barge] .bot{animation:cmp-jump .55s ease-out 1}
  /* calm looks (the anime options): no lean, a barely-there lift while talking, a small hop on a surprise */
  .cmp.calm[data-s=hearing] .bot{animation:cmp-breathe 4.5s ease-in-out infinite}
  .cmp.calm[data-s=speaking] .bot{animation:cmp-talk 1.8s ease-in-out infinite}
  .cmp.calm[data-s=barge] .bot{animation:cmp-hop .5s ease-out 1}`;

  let styled = false, count = 0; const lookCss = new Set();

  class Companion {
    /* opts: {viewBox, still}. still=true builds a sheet cell: no animation loop expected, use setPose(). */
    constructor(host, look, opts = {}) {
      if (!styled) { const s = document.createElement('style'); s.textContent = CSS; document.head.appendChild(s); styled = true; }
      if (look.css && !lookCss.has(look.name)) { lookCss.add(look.name); const s = document.createElement('style'); s.textContent = look.css; document.head.appendChild(s); }
      this.uid = 'c' + (++count);
      host.innerHTML = `<svg viewBox="${opts.viewBox || '0 0 200 215'}" class="cmp look-${look.name}${look.calm ? ' calm' : ''}" data-s="off">${look.svg.replaceAll('§', this.uid)}</svg>`;
      this.svg = host.firstChild; this.look = look;
      this.R = look.init(this.svg, this.uid) || {};
      this.P = { ...EXPR.sleep };
      const now = performance.now();
      this.blink = { t: 0, start: 0, dur: 170, next: now + 2500, last: now, dbl: false };
      this.sacc = { x: 0, y: 0, next: 0 }; this.glance = { i: 0, next: 0 };
      this.dir = { cur: null, since: 0 };
      this.env = 0; this.base = 0; this.emphT = -1e9; this.cueA = 0; this.lt = 0;
      this.shape = 'c'; this.lastLevel = 0; this.mouthV = 0; this.lastGaze = [0, 0];
    }

    _E(t, bl, st, cue, cueA) {
      const P = this.P, open = clamp(P.open, .05, 1.35) * (1 - bl * .95);
      return { t, bl, open, sx: 1 + Math.max(0, open - 1) * .18, sq: clamp(P.squint, 0, 1), gx: P.gx, gy: P.gy, pup: P.pup,
        browL: P.browL, browR: P.browR, tilt: P.tilt, blush: clamp(P.blush, 0, .8), mouth: clamp(P.mouth, 0, 1), smile: clamp(P.smile, -1, 1),
        shape: this.shape, alert: P.alert, dots: P.dots, st, cue, cueA, roll: P.roll };
    }

    /* freeze the character in a named expression (expression-sheet cells); over overrides parameters, e.g. {shape:'a', mouth:.6} */
    setPose(name, over = {}) {
      const e = { ...BASE, ...EXPR[name], ...over };
      Object.assign(this.P, e); this.shape = e.shape || 'c';
      const st = name === 'sleep' ? 'off' : (name === 'thinking' ? 'waiting' : name === 'surprised' ? 'barge' : name === 'speaking' ? 'speaking' : 'listening');
      this.svg.dataset.s = 'still-' + st;
      this.look.apply(this.R, this._E(1000, over.bl || 0, st, '', 0), this.svg);
    }

    /* IN: {state, level (0..1, already scaled), q, noteKind, noteUntil, bargeUntil} (times are performance.now()) */
    tick(t, IN) {
      const dt = this.lt ? Math.min(100, Math.max(1, t - this.lt)) : 16; this.lt = t;
      const P = this.P, D = this.dir, level = IN.level;
      // debounced state: a blip shorter than DEBOUNCE never reaches the face; a barge-in is speaking -> hearing/thinking that stuck
      if (this.cand === undefined) { this.cand = IN.state; this.candSince = t; this.stable = IN.state; this.bargeUntil = 0; }
      if (IN.state !== this.cand) { this.cand = IN.state; this.candSince = t; }
      if (this.cand !== this.stable && t - this.candSince >= DEBOUNCE) {
        const prev = this.stable; this.stable = this.cand;
        if (prev === 'speaking' && (this.stable === 'hearing' || this.stable === 'transcribing')) this.bargeUntil = t + 700;
      }
      const st = (t < this.bargeUntil) ? 'barge' : this.stable; this.shown = st;
      const quietish = ['listening', 'waiting', 'transcribing', 'loading'].includes(st);
      // 1. director: which single expression do we want, and may we switch yet?
      let want = 'neutral';
      if (st === 'off') want = 'sleep';
      else if (st === 'barge') want = 'surprised';
      else if (t < IN.noteUntil && quietish) want = IN.noteKind === 'needs_you' ? 'surprised' : IN.noteKind === 'blocked' ? 'concerned' : 'happy';
      else if (st === 'waiting' || st === 'transcribing') want = 'thinking';
      else if (st === 'speaking') want = 'speaking';
      else if (st === 'hearing' || st === 'listening') want = 'listening';
      if (!D.cur) { D.cur = want; D.since = t; }
      else if (want !== D.cur) {
        const urgent = st === 'barge' && want === 'surprised';
        if (urgent ? t - D.since > 200 : t - D.since >= (HOLD[D.cur] || 1200)) { D.cur = want; D.since = t; }
      }
      const X = EXPR[D.cur], T = { ...X };
      // 2. modifiers on top of the held expression (continuous, no switching)
      this.env += (level - this.env) * (1 - Math.exp(-dt / 160)); this.base += (level - this.base) * (1 - Math.exp(-dt / 2500));
      if (st === 'hearing') { T.pup += .12; T.alert += .3; T.open += .05; }
      if (st === 'speaking') {
        T.browL += this.env * .3; T.browR += this.env * .3; T.open += this.env * .1; T.alert += this.env * .4;
        if (IN.q) { T.browL += .3; T.browR += .22; T.roll += 3; }
        if (this.env > .38 && this.env > this.base * 1.6 && t - this.emphT > 2500) this.emphT = t;
        const age = t - this.emphT, e = age < 450 ? 1 : clamp(1 - (age - 450) / 350, 0, 1), s = e * e * (3 - 2 * e);   // an emphasis squint: on for ~0.5 s, then back
        T.squint += s * .45; T.blush += s * .2; T.browL += s * .2; T.browR += s * .2;
      }
      T.roll += Math.sin(t / 2600) * .8;
      // 3. gaze: slow glances
      let big = 0;
      if (D.cur === 'thinking') {
        const gl = this.glance;
        if (t > gl.next) { gl.i = (gl.i + 1 + Math.floor(Math.random() * 3)) % GLANCES.length; gl.next = t + rnd(1600, 3000); big = 1; }
        T.gx = GLANCES[gl.i][0]; T.gy = GLANCES[gl.i][1];
      } else if (D.cur === 'loading') { T.gx = Math.sin(t / 900) * .6; }
      else if (D.cur === 'sleep') { T.gx = 0; T.gy = 0; }
      else {
        if (t > this.sacc.next) { this.sacc.x = rnd(-.3, .3); this.sacc.y = rnd(-.2, .15); this.sacc.next = t + rnd(1800, 3500); big = Math.abs(this.sacc.x) > .22 ? 1 : 0; }
        T.gx += this.sacc.x * (D.cur === 'speaking' ? .5 : 1); T.gy += this.sacc.y * (D.cur === 'speaking' ? .5 : 1);
      }
      // 4. blinks
      const bk = this.blink; let bl = 0;
      if (!bk.t && st !== 'off' && D.cur !== 'surprised') {
        if (big && t - bk.last > 1200 && Math.random() < .5) bk.next = Math.min(bk.next, t + 60);       // a blink with a big glance
        if (t >= bk.next && (t - bk.last > 1500 || bk.dbl)) {
          if (st === 'speaking' && level > .2 && t - bk.last < 9000) bk.next = t + 250;                  // wait for a gap between words
          else { bk.t = 1; bk.start = t; bk.dur = rnd(150, 200); bk.last = t; const dbl = bk.dbl; bk.dbl = !dbl && Math.random() < .12;
                 bk.next = dbl ? t + rnd(3200, 6500) : (bk.dbl ? t + bk.dur + rnd(120, 200) : t + rnd(3200, 6500)); }
        }
      }
      if (bk.t) { const a = (t - bk.start) / bk.dur; bl = a < .4 ? Math.sin(a / .4 * Math.PI / 2) : Math.cos((a - .4) / .6 * Math.PI / 2); if (a >= 1) { bk.t = 0; bl = 0; } }
      // 5. mouth: openness follows the level quickly; the shape is chosen once per syllable
      let mT = X.mouth || 0;
      if (st === 'speaking') {
        mT = clamp(level, .04, 1);
        if (level > .12 && this.lastLevel <= .12) {
          const r = Math.random();
          this.shape = level > .55 ? (r < .6 ? 'a' : r < .85 ? 'o' : 'e') : level > .3 ? (r < .3 ? 'a' : r < .55 ? 'e' : r < .8 ? 'o' : 'u') : (r < .4 ? 'i' : r < .7 ? 'u' : 'e');
        }
        if (level <= .06) this.shape = 'e';
      } else this.shape = X.shape || 'c';
      this.lastLevel = level;
      // 6. ease everything toward the held expression
      const slow = D.cur === 'surprised' && t - D.since < 300 ? 70 : 120;
      for (const k in T) {
        if (k === 'shape' || k === 'mouth') continue;
        const tau = (k === 'gx' || k === 'gy') ? 140 : slow;
        P[k] += (T[k] - P[k]) * (1 - Math.exp(-dt / tau));
      }
      const mTau = st === 'speaking' ? (mT > P.mouth ? 55 : 110) : 120;
      P.mouth += (mT - P.mouth) * (1 - Math.exp(-dt / mTau));
      this.svg.dataset.s = st;
      const cueOn = t < IN.noteUntil && st !== 'speaking' && st !== 'barge';
      this.cueA += ((cueOn ? 1 : 0) - this.cueA) * (1 - Math.exp(-dt / 150));
      const E = this._E(t, bl, st, cueOn ? (KCOL[IN.noteKind] || '') : '', this.cueA);
      this.look.apply(this.R, E, this.svg);
      if (this.look.rollBody !== false && this.R.bot) this.R.bot.style.rotate = P.roll.toFixed(1) + 'deg';
    }
  }

  g.Companion = Companion; g.LOOKS = g.LOOKS || {}; g.CMP = { clamp, rnd, KCOL, EXPR };
})(window);
