/* J's expression engine, shared by every look (see looks.js and looks.html).
 A look supplies SVG plus apply(); the engine supplies the same states, blinks, glances, emphasis squint, brows,
 mouth openness (from the audio level), thinking dots, worker-news reactions and calm waiting for all of them.
 Eyelid/brow/glance ideas follow RoboEyes-style displays: parameters ease toward per-state targets every frame. */
(function (g) {
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const rnd = (a, b) => a + Math.random() * (b - a);
  const GLANCES = [[-1, -.9], [1, -.8], [0, -1.1], [-.8, -.2], [.9, -.3]];
  const KCOL = { waiting: '#6ee7a0', needs_you: '#ffb347', done: '#7fc8c4', blocked: '#ff6b6b' };

  const CSS = `
  .cmp{overflow:visible}
  .cmp .bot{transform-box:fill-box;transform-origin:50% 100%}
  @keyframes cmp-breathe{50%{transform:scale(1.012,1.02)}}
  @keyframes cmp-bob{50%{transform:translateY(-4px)}}
  @keyframes cmp-lean{50%{transform:rotate(-2.5deg) translateY(2px)}}
  @keyframes cmp-jump{0%{transform:translateY(0) scale(1)}35%{transform:translateY(-26px) scale(1.05,.95)}100%{transform:translateY(0) scale(1)}}
  .cmp[data-s=listening] .bot,.cmp[data-s=loading] .bot,.cmp[data-s=waiting] .bot,.cmp[data-s=transcribing] .bot{animation:cmp-breathe 4.5s ease-in-out infinite}
  .cmp[data-s=hearing] .bot{animation:cmp-lean .7s ease-in-out infinite}
  .cmp[data-s=speaking] .bot{animation:cmp-bob .55s ease-in-out infinite}
  .cmp[data-s=barge] .bot{animation:cmp-jump .55s ease-out 1}`;

  let styled = false, count = 0;

  class Companion {
    constructor(host, look) {
      if (!styled) { const s = document.createElement('style'); s.textContent = CSS; document.head.appendChild(s); styled = true; }
      this.uid = 'c' + (++count);
      host.innerHTML = `<svg viewBox="0 0 200 215" class="cmp look-${look.name}" data-s="off">${look.svg.replaceAll('§', this.uid)}</svg>`;
      this.svg = host.firstChild;
      this.look = look;
      this.R = look.init(this.svg, this.uid) || {};
      this.P = { open: 0, squint: 0, browL: 0, browR: 0, tilt: 0, gx: 0, gy: 0, pup: 1, blush: 0, roll: 0, mouth: 0, smile: 0, alert: 0, dots: 0 };
      this.blink = { t: 0, start: 0, next: performance.now() + 2500, dbl: false };
      this.sacc = { x: 0, y: 0, next: 0 };
      this.glance = { i: 0, next: 0 };
      this.env = 0; this.base = 0; this.emphT = -1e9; this.quietSince = 0; this.cueA = 0;
    }

    /* IN: {state, level (0..1, already scaled), q, noteKind, noteUntil, bargeUntil} (times are performance.now()) */
    tick(t, IN) {
      const P = this.P, st = (t < IN.bargeUntil) ? 'barge' : IN.state, level = IN.level;
      const T = { open: 1, squint: 0, browL: .05, browR: .05, tilt: 0, gx: 0, gy: 0, pup: 1, blush: 0, roll: 0, mouth: 0, smile: .3, alert: .3, dots: 0 };
      let rate = .14;
      const bk = this.blink;
      if (t > bk.next && st !== 'off' && st !== 'barge' && !bk.t) { bk.t = 1; bk.start = t; bk.next = t + (bk.dbl ? 180 : rnd(2200, 5500)); bk.dbl = !bk.dbl && Math.random() < .2; }
      let bl = 0;
      if (bk.t) { const a = (t - bk.start) / 230; bl = a < .45 ? a / .45 : Math.max(0, 1 - (a - .45) / .55); if (a >= 1) bk.t = 0; }
      if (t > this.sacc.next) { this.sacc.x = rnd(-.35, .35); this.sacc.y = rnd(-.25, .2); this.sacc.next = t + rnd(1100, 2800); }
      switch (st) {
        case 'off': T.open = .07; T.browL = T.browR = -.3; T.smile = .1; T.alert = -.6; rate = .08; break;
        case 'loading': T.gx = Math.sin(t / 500) * .9; T.browL = T.browR = .15; T.tilt = .15; T.smile = .2; T.alert = 0; break;
        case 'listening': T.gx = this.sacc.x; T.gy = this.sacc.y; T.browL = .1; T.browR = .15; T.pup = 1.1; T.squint = .08; T.blush = .15; T.smile = .6; T.alert = .4; break;
        case 'hearing': T.open = 1.12; T.browL = T.browR = .55 + Math.sin(t / 180) * .06; T.pup = 1.35; T.gx = this.sacc.x * .3; T.gy = -.1; T.mouth = .12; T.smile = 0; T.alert = 1; break;
        case 'waiting': case 'transcribing': {
          const gl = this.glance;
          if (t > gl.next) { gl.i = (gl.i + 1 + Math.floor(Math.random() * 3)) % GLANCES.length; gl.next = t + rnd(900, 1700); }
          const gg = GLANCES[gl.i]; T.gx = gg[0]; T.gy = gg[1]; T.open = .92; T.browL = .55; T.browR = -.05; T.tilt = .25; T.pup = .95; T.smile = -.1; T.alert = .3; T.dots = 1; rate = .2; break; }
        case 'speaking': {
          this.env += (level - this.env) * .5; this.base += (level - this.base) * .012;
          if (level < .03) { if (!this.quietSince) this.quietSince = t; } else this.quietSince = 0;
          if (this.env > .38 && this.env > this.base * 1.5 && t - this.emphT > 650) this.emphT = t;
          const e = clamp(1 - (t - this.emphT) / 380, 0, 1);
          if (this.quietSince && t - this.quietSince > 260 && !bk.t && t > bk.next - 1500) bk.next = t;
          T.open = .95 + this.env * .28; T.browL = T.browR = .1 + this.env * 1.1 + e * .5;
          T.squint = e * .62; T.blush = e * .5; T.pup = 1.05; T.mouth = clamp(level, .04, 1); T.smile = .3; T.alert = .5 + this.env * .6;
          T.gx = this.sacc.x * .5 + Math.sin(t / 900) * .2; T.gy = this.sacc.y * .5;
          if (IN.q) { T.browL += .35; T.browR += .25; T.open += .1; T.roll = 3; T.tilt = -.1; T.alert += .3; }
          break; }
        case 'barge': T.open = 1.3; T.browL = T.browR = 1; T.pup = .6; T.mouth = .7; T.smile = 0; T.alert = 1.3; rate = .35; break;
      }
      if (t < IN.noteUntil && ['listening', 'waiting', 'transcribing', 'loading'].includes(st)) {   // worker news
        const k = IN.noteKind;
        if (k === 'needs_you') { T.open = 1.12; T.browL = T.browR = .9; T.pup = 1.2; T.gx = 0; T.gy = -.1; T.tilt = 0; T.alert = 1; T.mouth = .1; T.smile = 0; }
        else if (k === 'blocked') { T.browL = .2; T.browR = .2; T.tilt = .7; T.open = .9; T.gy = .5; T.squint = 0; T.smile = -.6; T.alert = -.2; }
        else { T.squint = .5; T.browL = T.browR = .7; T.blush = .5; T.tilt = 0; T.gx = 0; T.gy = 0; T.smile = 1; T.alert = .8; }
      }
      if (st !== 'speaking') { this.env *= .8; this.base *= .95; this.quietSince = 0; }
      for (const k in T) P[k] += (T[k] - P[k]) * (k === 'mouth' ? (st === 'speaking' ? .55 : .25) : rate);
      this.svg.dataset.s = st;
      const cueOn = t < IN.noteUntil && st !== 'speaking' && st !== 'barge';
      this.cueA += ((cueOn ? 1 : 0) - this.cueA) * .2;
      const open = clamp(P.open, .05, 1.35) * (1 - bl * .95);
      const E = { t, bl, open, sx: 1 + Math.max(0, open - 1) * .18, sq: clamp(P.squint, 0, 1), gx: P.gx, gy: P.gy, pup: P.pup,
        browL: P.browL, browR: P.browR, tilt: P.tilt, blush: clamp(P.blush, 0, .7), mouth: clamp(P.mouth, 0, 1), smile: clamp(P.smile, -1, 1),
        alert: P.alert, dots: P.dots, st, cue: cueOn ? (KCOL[IN.noteKind] || '') : '', cueA: this.cueA, roll: P.roll };
      this.look.apply(this.R, E, this.svg);
      const bot = this.R.bot; if (bot) bot.style.rotate = P.roll.toFixed(1) + 'deg';
    }
  }

  const eye = (el, cx, cy, sx, sy) => el.setAttribute('transform', `translate(${cx} ${cy}) scale(${sx.toFixed(3)} ${sy.toFixed(3)}) translate(${-cx} ${-cy})`);
  g.Companion = Companion; g.LOOKS = g.LOOKS || {}; g.CMP = { clamp, rnd, eye, KCOL };
})(window);
