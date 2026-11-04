/* The robot (ported to the shared engine) and three female anime-style looks for J: Hana, Mio, Yuki.
 They are original designs. The construction follows common character/expression-sheet practice: layered parts
 (hair back, face, eyes, brows, mouth, blush, hair front), big simple eyes with a thick upper lash and two highlights,
 a small mouth set (closed, a/e/i/o/u, open smile), brow tilt and raise, blush, and a slight head tilt. */
(function (g) {
  const { clamp } = g.CMP;
  const $ = (svg, sel) => svg.querySelector(sel);
  const A = (el, o) => { for (const k in o) el.setAttribute(k, typeof o[k] === 'number' ? +o[k].toFixed(2) : o[k]); };
  const eyeT = (el, cx, cy, sx, sy, dx = 0, dy = 0) => el.setAttribute('transform', `translate(${dx.toFixed(2)} ${dy.toFixed(2)}) translate(${cx} ${cy}) scale(${sx.toFixed(3)} ${sy.toFixed(3)}) translate(${-cx} ${-cy})`);
  const refs = (svg, names) => { const R = { bot: $(svg, '.bot') }; names.split(' ').forEach(n => R[n] = $(svg, '.' + n)); return R; };
  const dotsAnim = (G, E) => { G.setAttribute('opacity', E.dots); [...G.children].forEach((c, i) => c.setAttribute('transform', `translate(0 ${(Math.sin(E.t / 260 + i * .9) * -2.5).toFixed(1)})`)); };

  /* ---------- the robot, as it was, on the shared engine ---------- */
  g.LOOKS.robot = {
    name: 'robot', title: 'J, little robot', card: { bg: '#f4efe6', fg: '#3a2f2a' },
    blurb: 'The current J: a teal robot with a screen face and an equalizer mouth.',
    svg: `<defs><clipPath id="§cl"><rect x="64" y="82" width="26" height="24" rx="10"/></clipPath><clipPath id="§cr"><rect x="110" y="82" width="26" height="24" rx="10"/></clipPath></defs>
     <g class="bot"><line x1="100" y1="34" x2="100" y2="58" stroke="#5b6b73" stroke-width="5"/><circle class="led" cx="100" cy="29" r="9" fill="#5b6b73"/>
      <rect x="38" y="58" width="124" height="104" rx="30" fill="#7fc8c4"/><rect x="22" y="94" width="14" height="30" rx="7" fill="#5b6b73"/><rect x="164" y="94" width="14" height="30" rx="7" fill="#5b6b73"/>
      <rect x="62" y="162" width="76" height="30" rx="12" fill="#5fa8a4"/><rect x="50" y="70" width="100" height="72" rx="20" fill="#1e2b30"/>
      <g class="scr"><ellipse class="chL" cx="62" cy="116" rx="7" ry="4" fill="#ff9aa8" opacity="0"/><ellipse class="chR" cx="138" cy="116" rx="7" ry="4" fill="#ff9aa8" opacity="0"/>
       <g class="eyeL"><g clip-path="url(#§cl)"><rect x="64" y="82" width="26" height="24" rx="10" fill="#9ff3ea"/><circle class="pupL" cx="77" cy="94" r="6" fill="#1e2b30"/><rect class="topL" x="54" y="36" width="46" height="44" fill="#1e2b30"/><ellipse class="botL" cx="77" cy="124" rx="20" ry="16" fill="#1e2b30"/></g></g>
       <g class="eyeR"><g clip-path="url(#§cr)"><rect x="110" y="82" width="26" height="24" rx="10" fill="#9ff3ea"/><circle class="pupR" cx="123" cy="94" r="6" fill="#1e2b30"/><rect class="topR" x="100" y="36" width="46" height="44" fill="#1e2b30"/><ellipse class="botR" cx="123" cy="124" rx="20" ry="16" fill="#1e2b30"/></g></g>
       <line class="browL" x1="64" y1="77" x2="90" y2="77" stroke="#9ff3ea" stroke-width="4" stroke-linecap="round"/><line class="browR" x1="110" y1="77" x2="136" y2="77" stroke="#9ff3ea" stroke-width="4" stroke-linecap="round"/>
       <path class="smile" d="M84 124q16 12 32 0" stroke="#9ff3ea" stroke-width="5" fill="none" stroke-linecap="round"/>
       <g class="bars" fill="#9ff3ea" opacity="0"><rect x="72" y="124" width="9" height="6" rx="4.5"/><rect x="85" y="124" width="9" height="6" rx="4.5"/><rect x="96" y="124" width="9" height="6" rx="4.5"/><rect x="107" y="124" width="9" height="6" rx="4.5"/><rect x="120" y="124" width="9" height="6" rx="4.5"/></g>
       <g class="dots" fill="#9ff3ea" opacity="0"><circle cx="86" cy="130" r="4"/><circle cx="100" cy="130" r="4"/><circle cx="114" cy="130" r="4"/></g>
       <text class="bang" x="100" y="138" text-anchor="middle" font-size="24" font-weight="700" fill="#ffb347" opacity="0">!</text></g>
      <g class="zzz" fill="#5b6b73" font-weight="700" font-size="16" opacity="0"><text x="158" y="48">z</text><text x="170" y="34" font-size="12">z</text></g></g>`,
    init(s) { const R = refs(s, 'led scr chL chR eyeL eyeR pupL pupR topL topR botL botR browL browR smile bars dots bang zzz'); R.rects = [...s.querySelectorAll('.bars rect')]; return R; },
    apply(R, E) {
      for (const [side, cx, dir] of [['L', 77, 1], ['R', 123, -1]]) {
        eyeT(R['eye' + side], cx, 94, E.sx, E.open);
        A(R['pup' + side], { cx: cx + E.gx * 5, cy: 94 + E.gy * 4.5, r: 6 * E.pup });
        R['top' + side].setAttribute('transform', `rotate(${(E.tilt * 18 * dir).toFixed(1)} ${cx} 88) translate(0 ${(clamp(E.tilt * .35, 0, .6) * 24).toFixed(1)})`);
        R['bot' + side].setAttribute('cy', (128 - E.sq * 34).toFixed(1));
        const by = 77 - (side === 'L' ? E.browL : E.browR) * 5.5, inner = E.tilt * 3;
        const x1 = side === 'L' ? 64 : 110, yA = side === 'L' ? by - inner : by + inner, yB = side === 'L' ? by + inner : by - inner;
        A(R['brow' + side], { y1: yA, y2: yB, opacity: E.open < .2 ? 0 : .9 });
      }
      const sp = E.st === 'speaking';
      R.bars.setAttribute('opacity', sp ? 1 : 0);
      if (sp) R.rects.forEach((b, i) => { const h = 6 + E.mouth * [.9, .6, 1, .7, .85][i] * (.5 + .5 * (.55 + .45 * Math.sin(E.t / 90 * (i + 1.3) + i * 2))) * 46; A(b, { height: h, y: 127 - h / 2 }); });
      R.smile.setAttribute('opacity', (E.st === 'listening' || E.st === 'hearing' || E.st === 'loading') ? 1 : 0);
      R.bang.setAttribute('opacity', E.st === 'barge' ? 1 : 0); R.zzz.setAttribute('opacity', E.st === 'off' ? 1 : 0); R.scr.setAttribute('opacity', E.st === 'off' ? .35 : 1);
      dotsAnim(R.dots, E);
      const bl = clamp(E.blush, 0, .7); R.chL.setAttribute('opacity', bl); R.chR.setAttribute('opacity', bl);
      const col = { loading: '#ffb347', waiting: '#ffb347', transcribing: '#ffb347', listening: '#6ee7a0', hearing: '#6ee7a0', speaking: '#9ff3ea', barge: '#ff6b6b' }[E.st] || '#5b6b73';
      R.led.setAttribute('fill', E.cueA > .05 && E.cue ? E.cue : col);
      R.led.setAttribute('opacity', (E.st === 'hearing' || E.st === 'loading' || E.st === 'waiting' || E.st === 'transcribing') ? .65 + .35 * Math.sin(E.t / (E.st === 'hearing' ? 80 : 160)) : 1);
    }
  };

  /* ---------- anime builder ---------- */
  const MOUTH = { a: [4.5, 3.5, 2, 8], e: [6, 3, 1.5, 5], i: [7, 3, 1, 2.5], o: [3.5, 2, 3, 5], u: [3, 1.5, 2.5, 3.5] };
  function animeMouth(R, E, cy) {
    const m = E.mouth, sh = E.shape, ell = MOUTH[sh];
    const openA = ell ? clamp((m - .05) * 12, 0, 1) : 0, dA = sh === 'D' ? 1 : 0;
    if (ell) { A(R.mo, { rx: ell[0] + ell[1] * m, ry: ell[2] + ell[3] * m, cy: cy + 1.5 + (ell[2] + ell[3] * m) * .35 }); A(R.mt, { rx: (ell[0] + ell[1] * m) * .6, ry: Math.max(.4, (ell[2] + ell[3] * m) * .38), cy: cy + 1.5 + (ell[2] + ell[3] * m) * .85 }); }
    R.mo.setAttribute('opacity', openA); R.mt.setAttribute('opacity', openA * (m > .25 ? .9 : 0));
    const h = 8 + m * 10;
    R.md.setAttribute('d', `M88 ${cy - 3} Q100 ${cy - 1} 112 ${cy - 3} Q110 ${cy + h} 100 ${cy + h + 1} Q90 ${cy + h} 88 ${cy - 3}Z`);
    R.md.setAttribute('opacity', dA);
    R.mc.setAttribute('d', `M91 ${cy} Q100 ${cy + E.smile * 6 + 1.2} 109 ${cy}`);
    R.mc.setAttribute('opacity', clamp(1 - Math.max(openA, dA), 0, 1));
  }
  function build(cfg) {
    const ex = cfg.eye, L = [73, 112], Rr = [127, 112];
    // The eye is one closed shape: the upper boundary IS the lash curve, the lower boundary is a soft curve below. The eye white,
    // iris, pupil and highlights are all clipped to it, so nothing can ever cross the lash or the lid (any gaze, blink or squint).
    const eye = (s, cx, cy) => {
      const xl = cx - ex.rx - 1.5, xr = cx + ex.rx + 1.5, y0 = cy - 1, up = cy - 2 * ex.ry - 1, lo = cy + 2 * ex.ry + 1;
      const upper = `M${xl} ${y0} Q${cx} ${up} ${xr} ${y0}`, shape = `${upper} Q${cx} ${lo} ${xl} ${y0}Z`;
      return `<clipPath id="§c${s}"><path d="${shape}"/></clipPath>
      <g class="e${s}"><path d="${shape}" fill="#fff"/>
       <g clip-path="url(#§c${s})"><g class="ir${s}"><ellipse cx="${cx}" cy="${cy + 1}" rx="${ex.rx * .8}" ry="${ex.ry * 1.0}" fill="url(#§ig)"/>
        <ellipse class="pl${s}" cx="${cx}" cy="${cy + 1}" rx="${ex.rx * .34}" ry="${ex.ry * .42}" fill="#1b1630"/>
        <ellipse cx="${cx}" cy="${cy - ex.ry * .5}" rx="${ex.rx * .75}" ry="${ex.ry * .38}" fill="#000" opacity=".2"/>
        <circle cx="${cx - ex.rx * .3}" cy="${cy - ex.ry * .3}" r="${ex.rx * .26}" fill="#fff"/><circle cx="${cx + ex.rx * .32}" cy="${cy + ex.ry * .38}" r="${ex.rx * .12}" fill="#fff" opacity=".9"/></g></g>
       <path d="${upper}" stroke="${cfg.lash}" stroke-width="3.8" fill="none" stroke-linecap="round"/>
       <path d="M${cx - ex.rx * .6} ${cy + ex.ry - 1} Q${cx} ${cy + ex.ry + 1.5} ${cx + ex.rx * .6} ${cy + ex.ry - 1}" stroke="${cfg.lash}" stroke-width="1.2" fill="none" opacity=".35"/></g>
      <path class="sq${s}" d="M${cx - ex.rx} ${cy + 3} Q${cx} ${cy - ex.ry * .95} ${cx + ex.rx} ${cy + 3}" stroke="${cfg.lash}" stroke-width="3.8" fill="none" stroke-linecap="round" opacity="0"/>`; };
    const svg = `<defs><linearGradient id="§ig" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${ex.i1}"/><stop offset="1" stop-color="${ex.i2}"/></linearGradient></defs>
     <g class="bot"><ellipse cx="100" cy="209" rx="52" ry="5" fill="#0000001a"/>
      ${cfg.body}
      ${cfg.neck || `<path d="M86 148 L86 176 Q100 188 114 176 L114 148Z" fill="${cfg.shade}"/>`}
      <g class="head">
       <g class="hairB">${cfg.hairBack || ''}</g>${cfg.shell || ''}
       <path d="${cfg.facePath || 'M50 104 C50 66 72 46 100 46 C128 46 150 66 150 104 C150 134 132 158 100 162 C68 158 50 134 50 104Z'}" fill="${cfg.skin}"${cfg.faceStroke ? ` stroke="${cfg.faceStroke}" stroke-width="3"` : ''}/>${cfg.seams || ''}
       <ellipse class="chL" cx="66" cy="132" rx="11" ry="6" fill="${cfg.blush}" opacity=".3"/><ellipse class="chR" cx="134" cy="132" rx="11" ry="6" fill="${cfg.blush}" opacity=".3"/>
       <g class="hatch" stroke="${cfg.blush}" stroke-width="1.6" stroke-linecap="round" opacity="0"><path d="M58 130l4-5M64 132l4-5M70 133l4-5M130 133l4-5M136 132l4-5M142 130l4-5"/></g>
       ${eye('L', L[0], L[1])}${eye('R', Rr[0], Rr[1])}
       <path class="bL" d="" stroke="${cfg.brow}" stroke-width="2.9" fill="none" stroke-linecap="round"/><path class="bR" d="" stroke="${cfg.brow}" stroke-width="2.9" fill="none" stroke-linecap="round"/>
       <path d="M99 130 q1.2 2.2 2.4 0" stroke="${cfg.shade}" stroke-width="1.6" fill="none" stroke-linecap="round"/>
       <path class="mc" d="" stroke="${cfg.mouth}" stroke-width="2.6" fill="none" stroke-linecap="round"/>
       <path class="md" d="" fill="${cfg.mouthIn}" opacity="0"/>
       <ellipse class="mo" cx="100" cy="144" rx="4" ry="3" fill="${cfg.mouthIn}" opacity="0"/><ellipse class="mt" cx="100" cy="147" rx="3" ry="1.5" fill="#f08a98" opacity="0"/>
       <g class="hairF">${cfg.hairFront || ''}</g>${cfg.front || ''}
      </g>
      <g class="dots" fill="${cfg.dot}" opacity="0"><circle cx="150" cy="40" r="3.6"/><circle cx="161" cy="40" r="3.6"/><circle cx="172" cy="40" r="3.6"/></g></g>`;
    return {
      name: cfg.name, title: cfg.title, blurb: cfg.blurb, card: cfg.card, svg, calm: true, rollBody: false, sheet: true,
      init(s) {
        const R = refs(s, 'eL eR irL irR plL plR sqL sqR bL bR mc md mo mt chL chR hatch hairB hairF head dots');
        R.tails = [...s.querySelectorAll('.tail')]; R.cues = [...s.querySelectorAll('.cue')]; R.leds = [...s.querySelectorAll('.led')];
        R.cues.forEach(c => { c.dataset.attr = c.getAttribute('fill') === 'none' ? 'stroke' : 'fill'; c.dataset.def = c.getAttribute(c.dataset.attr); });
        return R;
      },
      apply(R, E) {
        for (const [s, cx, side] of [['L', L[0], 1], ['R', Rr[0], 0]]) {
          const cy = L[1], gsx = E.gx * ex.rx * .3, gsy = E.gy * ex.ry * .25, a = clamp((E.sq - .3) * 5, 0, 1);
          eyeT(R['e' + s], cx, cy - ex.ry + 3, E.sx, E.open * (1 - E.sq * .15));
          R['ir' + s].setAttribute('transform', `translate(${gsx.toFixed(2)} ${gsy.toFixed(2)})`);
          A(R['pl' + s], { rx: ex.rx * .34 * E.pup, ry: ex.ry * .42 * E.pup });
          R['e' + s].setAttribute('opacity', 1 - a); R['sq' + s].setAttribute('opacity', a);
          const v = side ? E.browL : E.browR, by = 91 - v * 5.5, tt = E.tilt, xo = side ? cx - ex.rx - 1 : cx + ex.rx + 1, xi = side ? cx + ex.rx - 3 : cx - ex.rx + 3;
          const yo = by - tt * 2, yi = by + tt * 3.4, xm = (xo + xi) / 2;
          R['b' + s].setAttribute('d', `M${xo.toFixed(1)} ${yo.toFixed(1)} Q${xm.toFixed(1)} ${(Math.min(yo, yi) - 2.2).toFixed(1)} ${xi.toFixed(1)} ${yi.toFixed(1)}`);
          R['b' + s].setAttribute('opacity', E.open < .2 ? .25 : 1);
        }
        animeMouth(R, E, 143);
        const bo = clamp(.25 + E.blush * .7, 0, .85); R.chL.setAttribute('opacity', bo); R.chR.setAttribute('opacity', bo); R.hatch.setAttribute('opacity', clamp((E.blush - .45) * 3, 0, .8));
        const sw = Math.sin(E.t / 1700) * cfg.sway + ((E.st === 'waiting' || E.st === 'transcribing') ? Math.sin(E.t / 1100) * cfg.sway * .6 : 0);
        R.head.setAttribute('transform', `rotate(${(E.roll * .9).toFixed(2)} 100 168)`);
        R.hairB.setAttribute('transform', `rotate(${(sw + E.roll * .25).toFixed(2)} 100 48)`); R.hairF.setAttribute('transform', `rotate(${(sw * .25).toFixed(2)} 100 48)`);
        R.tails.forEach((t, i) => t.setAttribute('transform', `rotate(${((i ? -1 : 1) * (Math.sin(E.t / 1300 + i) * 2 + E.alert * 2.5) + sw * .4).toFixed(2)} ${i ? 150 : 50} 96)`));
        R.cues.forEach(c => { const at = c.dataset.attr; c.setAttribute(at, (E.cueA > .05 && E.cue) ? E.cue : c.dataset.def); });
        if (R.leds.length) {   // robot LEDs show the voice state (the news colour wins while it is active)
          const col = { loading: '#ffb347', waiting: '#ffb347', transcribing: '#ffb347', listening: '#6ee7a0', hearing: '#6ee7a0', speaking: '#9ff3ea', barge: '#ff6b6b' }[E.st] || '#8a9aa2';
          const pulse = (E.st === 'hearing' || E.st === 'loading' || E.st === 'waiting' || E.st === 'transcribing') ? .65 + .35 * Math.sin(E.t / (E.st === 'hearing' ? 80 : 160)) : 1;
          R.leds.forEach(l => { l.setAttribute('fill', (E.cueA > .05 && E.cue) ? E.cue : col); l.setAttribute('opacity', pulse); });
        }
        dotsAnim(R.dots, E);
      }
    };
  }

  const SKIN = { skin: '#ffe2d0', shade: '#f2c7b0', blush: '#ff9aa0' };

  /* 1. Hana: calm and tidy: navy bob with straight bangs, teal eyes, sailor-style collar, a star hairpin */
  g.LOOKS.hana = build({ ...SKIN, name: 'hana', title: 'Hana', card: { bg: '#e6f0f7', fg: '#22405c' },
    blurb: 'Calm and tidy. Navy bob with straight bangs, teal eyes, a sailor-style collar and a little star hairpin that lights up with news.',
    lash: '#1d2438', brow: '#2b3550', mouth: '#a8434f', mouthIn: '#8e2f3b', dot: '#5a8fb8', sway: 1.1,
    eye: { rx: 13, ry: 14.5, i1: '#1d6f78', i2: '#58d0c4' },
    body: `<path d="M30 215 C30 182 58 168 100 168 C142 168 170 182 170 215Z" fill="#2b3a5c"/><path d="M72 169 L100 200 L128 169 L118 167 L100 186 L82 167Z" fill="#f6f8fb"/><path d="M92 190 L100 198 L108 190 L100 186Z" fill="#d9485b"/>`,
    hairBack: `<path d="M44 106 C38 54 70 32 100 32 C130 32 162 54 156 106 L158 152 C158 164 148 166 142 160 L138 122 L62 122 L58 160 C52 166 42 164 42 152Z" fill="#26324f"/>`,
    hairFront: `<path d="M47 102 C42 54 72 35 100 35 C128 35 158 54 153 102 L148 98 L141 84 L131 93 L120 82 L109 91 L99 80 L89 91 L79 82 L68 93 L59 84 L52 98Z" fill="#2e3c5e"/>
      <path d="M51 100 L49 140 Q52 148 59 143 L63 104Z" fill="#2e3c5e"/><path d="M149 100 L151 140 Q148 148 141 143 L137 104Z" fill="#2e3c5e"/>
      <path d="M70 56 Q100 40 130 56" stroke="#5a6d98" stroke-width="3.5" fill="none" opacity=".45" stroke-linecap="round"/>`,
    front: `<path class="cue" d="M0 -8 L2.4 -2.5 L8 -2.5 L3.6 1.2 L5.2 7 L0 3.6 L-5.2 7 L-3.6 1.2 L-8 -2.5 L-2.4 -2.5Z" transform="translate(126 64)" fill="#ffd34e"/>` });

  /* 2. Mio: bright and bouncy: warm brown twin tails with orange bows, big amber eyes, a cream cardigan */
  g.LOOKS.mio = build({ ...SKIN, name: 'mio', title: 'Mio', card: { bg: '#fff0de', fg: '#6a3b1d' },
    blurb: 'Bright and friendly. Warm brown twin tails with orange bows, big amber eyes and a cream cardigan. The tails swing; the bows light up with news.',
    lash: '#4a2a18', brow: '#6a3f22', mouth: '#b4474f', mouthIn: '#92323c', dot: '#e09040', sway: 1.4,
    eye: { rx: 14.5, ry: 16.5, i1: '#a8541a', i2: '#ffbf5a' },
    body: `<path d="M30 215 C30 184 58 170 100 170 C142 170 170 184 170 215Z" fill="#f2e6d3"/><path d="M80 170 L100 196 L120 170Z" fill="#fff"/><circle cx="100" cy="204" r="2.6" fill="#e9a23b"/><path d="M100 196 V215" stroke="#e1d1b6" stroke-width="2"/>`,
    hairBack: `<path d="M46 106 C42 56 72 34 100 34 C128 34 158 56 154 106 L152 124 L48 124Z" fill="#7a4a2c"/>
      <g class="tail"><path d="M52 92 C26 100 16 142 24 178 C32 188 46 180 46 168 C42 142 48 122 58 108Z" fill="#7a4a2c"/><path d="M30 130 q-2 20 2 36" stroke="#a46a3f" stroke-width="3" fill="none" opacity=".5" stroke-linecap="round"/></g>
      <g class="tail"><path d="M148 92 C174 100 184 142 176 178 C168 188 154 180 154 168 C158 142 152 122 142 108Z" fill="#7a4a2c"/><path d="M170 130 q2 20 -2 36" stroke="#a46a3f" stroke-width="3" fill="none" opacity=".5" stroke-linecap="round"/></g>`,
    hairFront: `<path d="M46 104 C42 56 72 38 100 38 C130 38 158 58 154 104 C146 88 134 76 112 72 C102 84 84 84 70 74 C60 82 52 92 46 104Z" fill="#855230"/>
      <path d="M52 100 L50 138 Q53 146 60 141 L63 104Z" fill="#855230"/><path d="M148 100 L150 138 Q147 146 140 141 L137 104Z" fill="#855230"/>
      <path d="M72 58 Q100 42 128 58" stroke="#b97c4c" stroke-width="3.5" fill="none" opacity=".5" stroke-linecap="round"/>`,
    front: `<g transform="translate(54 70)"><path class="cue" d="M0 0 L-13 -8 L-13 8Z M0 0 L13 -8 L13 8Z" fill="#ff8a3d"/><circle class="cue" r="3.4" fill="#ff8a3d"/></g>
            <g transform="translate(146 70)"><path class="cue" d="M0 0 L-13 -8 L-13 8Z M0 0 L13 -8 L13 8Z" fill="#ff8a3d"/><circle class="cue" r="3.4" fill="#ff8a3d"/></g>` });

  /* 3. Yuki: quiet and a little sleepy: long silver-lilac hair, violet eyes, headphones, a dark hoodie */
  g.LOOKS.yuki = build({ ...SKIN, name: 'yuki', title: 'Yuki', card: { bg: '#1c1b33', fg: '#d6d0ff' },
    blurb: 'Quiet and a bit sleepy. Long silver-lilac hair, violet eyes, headphones and a dark hoodie. The headphone lights glow with news. Looks best on a dark panel.',
    lash: '#2c2250', brow: '#8a7cc0', mouth: '#b4566a', mouthIn: '#8e2f4b', dot: '#b8a8ff', sway: 1.8,
    eye: { rx: 14, ry: 12.5, i1: '#4a2a9a', i2: '#b48cff' },
    body: `<path d="M28 215 C28 180 58 168 100 168 C142 168 172 180 172 215Z" fill="#3b3f63"/><path d="M76 168 Q100 190 124 168" stroke="#2c2f4d" stroke-width="5" fill="none"/><path d="M90 182 V206M110 182 V206" stroke="#d6d0ff" stroke-width="1.6" opacity=".6"/>`,
    hairBack: `<path d="M42 106 C36 52 70 30 100 30 C130 30 164 52 158 106 L168 198 C168 210 152 210 148 198 L140 132 L60 132 L52 198 C48 210 32 210 32 198Z" fill="#cfc6f0"/><path d="M44 150 L40 196 M156 150 L160 196" stroke="#a99ad8" stroke-width="3" opacity=".55" stroke-linecap="round"/>`,
    hairFront: `<path d="M47 104 C42 52 72 33 100 33 C128 33 158 52 153 104 C148 94 142 86 134 80 C122 92 106 96 92 84 C82 92 62 96 47 104Z" fill="#dcd4f7"/>
      <path d="M100 35 q-9 -17 6 -23 q-2 9 5 15z" fill="#dcd4f7"/>
      <path d="M52 104 L50 150 Q53 158 60 152 L63 108Z" fill="#dcd4f7"/><path d="M148 104 L150 150 Q147 158 140 152 L137 108Z" fill="#dcd4f7"/>
      <path d="M70 54 Q100 38 130 54" stroke="#fff" stroke-width="3.5" fill="none" opacity=".55" stroke-linecap="round"/>`,
    front: `<path d="M44 104 C38 18 162 18 156 104" stroke="#3a3f5c" stroke-width="6" fill="none" stroke-linecap="round"/>
      <circle cx="46" cy="110" r="13" fill="#3a3f5c"/><circle cx="154" cy="110" r="13" fill="#3a3f5c"/>
      <circle class="cue" cx="46" cy="110" r="6.5" fill="none" stroke="#7df9ff" stroke-width="3"/><circle class="cue" cx="154" cy="110" r="6.5" fill="none" stroke="#7df9ff" stroke-width="3"/>` });

  /* ---------- robot + anime blends: Hana's eyes and expressions with J's robot parts ---------- */
  const NAVY = '#2e3c5e', TEAL = '#7fc8c4', TEAL2 = '#5fa8a4', METAL = '#5b6b73';
  const BOB = `<path d="M44 106 C38 54 70 32 100 32 C130 32 162 54 156 106 L158 152 C158 164 148 166 142 160 L138 122 L62 122 L58 160 C52 166 42 164 42 152Z" fill="#26324f"/>`;
  const BANGS = `<path d="M47 102 C42 54 72 35 100 35 C128 35 158 54 153 102 L148 98 L141 84 L131 93 L120 82 L109 91 L99 80 L89 91 L79 82 L68 93 L59 84 L52 98Z" fill="${NAVY}"/>
      <path d="M51 100 L49 140 Q52 148 59 143 L63 104Z" fill="${NAVY}"/><path d="M149 100 L151 140 Q148 148 141 143 L137 104Z" fill="${NAVY}"/>
      <path d="M70 56 Q100 40 130 56" stroke="#5a6d98" stroke-width="3.5" fill="none" opacity=".45" stroke-linecap="round"/>`;
  const SAILOR = (fill) => `<path d="M64 174 L100 204 L136 174 L124 170 L100 190 L76 170Z" fill="${fill}"/><path d="M92 192 L100 200 L108 192 L100 188Z" fill="#d9485b"/>`;

  /* Hana-01: mostly human. Hana's hair and face with a small antenna, robot ear modules and faint seams. */
  g.LOOKS.hana01 = build({ ...SKIN, name: 'hana01', title: 'Hana-01: human with robot touches', card: { bg: '#e6f0f7', fg: '#22405c' },
    blurb: 'Mostly human: Hana with a small antenna on her hair, teal ear modules and a few faint panel seams. The antenna LED shows what J is doing.',
    lash: '#1d2438', brow: '#2b3550', mouth: '#a8434f', mouthIn: '#8e2f3b', dot: '#5a8fb8', sway: 1.1,
    eye: { rx: 13, ry: 14.5, i1: '#1d6f78', i2: '#58d0c4' },
    body: `<path d="M30 215 C30 182 58 168 100 168 C142 168 170 182 170 215Z" fill="#2b3a5c"/><path d="M46 200 L74 178 M154 200 L126 178" stroke="#5fc8c4" stroke-width="2.4" stroke-linecap="round"/>${SAILOR('#f6f8fb')}<circle class="led" cx="100" cy="209" r="3" fill="#6ee7a0"/>`,
    hairBack: BOB, hairFront: BANGS,
    seams: `<path d="M60 150 L72 158 M140 150 L128 158 M96 62 H104" stroke="#d3ad97" stroke-width="1.5" fill="none" stroke-linecap="round" opacity=".8"/>`,
    front: `<path d="M104 36 Q110 22 104 13" stroke="${METAL}" stroke-width="3.2" fill="none" stroke-linecap="round"/><circle class="led" cx="104" cy="10" r="5.5" fill="#6ee7a0"/>
      <circle cx="47" cy="112" r="10" fill="${TEAL2}"/><circle class="cue" cx="47" cy="112" r="5" fill="none" stroke="#9ff3ea" stroke-width="2.6"/>
      <circle cx="153" cy="112" r="10" fill="${TEAL2}"/><circle class="cue" cx="153" cy="112" r="5" fill="none" stroke="#9ff3ea" stroke-width="2.6"/>` });

  /* Hana-02: half and half. A robot head shell with a skin-tone face plate in it, Hana's eyes, bangs as hair plates. */
  g.LOOKS.hana02 = build({ ...SKIN, name: 'hana02', title: 'Hana-02: half and half', card: { bg: '#e3f1ef', fg: '#1f4a4a' },
    blurb: 'Half and half: a teal robot head with a face plate that carries Hana\'s eyes and expressions, navy bangs as hair plates, ear pods and a state-colored antenna.',
    lash: '#1d2438', brow: '#2b3550', mouth: '#a8434f', mouthIn: '#8e2f3b', dot: '#3f9a96', sway: .5,
    eye: { rx: 13, ry: 14.5, i1: '#1d6f78', i2: '#58d0c4' },
    facePath: 'M52 88 Q52 58 84 58 L116 58 Q148 58 148 88 L148 132 Q148 160 116 160 L84 160 Q52 160 52 132Z', faceStroke: '#d9ad94',
    neck: `<rect x="86" y="160" width="28" height="18" rx="5" fill="${METAL}"/>`,
    body: `<path d="M32 215 C32 184 62 172 100 172 C138 172 168 184 168 215Z" fill="${TEAL2}"/><path d="M48 204 H76 M124 204 H152" stroke="#3f8582" stroke-width="2.4" stroke-linecap="round"/>${SAILOR('#2b3a5c')}<circle class="led" cx="100" cy="209" r="3" fill="#6ee7a0"/>`,
    shell: `<line x1="100" y1="42" x2="100" y2="18" stroke="${METAL}" stroke-width="4" stroke-linecap="round"/><circle class="led" cx="100" cy="13" r="6.5" fill="#6ee7a0"/>
      <rect x="25" y="94" width="18" height="40" rx="9" fill="${METAL}"/><rect x="157" y="94" width="18" height="40" rx="9" fill="${METAL}"/>
      <circle class="cue" cx="34" cy="114" r="4.6" fill="none" stroke="#9ff3ea" stroke-width="2.6"/><circle class="cue" cx="166" cy="114" r="4.6" fill="none" stroke="#9ff3ea" stroke-width="2.6"/>
      <rect x="38" y="42" width="124" height="132" rx="40" fill="${TEAL}"/>
      <path d="M62 174 H138 M38 112 H46 M154 112 H162" stroke="${TEAL2}" stroke-width="2.4" stroke-linecap="round"/>
      <circle cx="49" cy="53" r="2.2" fill="${TEAL2}"/><circle cx="151" cy="53" r="2.2" fill="${TEAL2}"/><circle cx="49" cy="163" r="2.2" fill="${TEAL2}"/><circle cx="151" cy="163" r="2.2" fill="${TEAL2}"/>`,
    hairFront: `<path d="M50 94 C48 60 70 54 100 54 C130 54 152 60 150 94 L146 90 L140 78 L130 87 L120 76 L109 85 L99 74 L89 85 L79 76 L68 87 L60 78 L54 90Z" fill="${NAVY}"/>
      <path d="M72 62 Q100 50 128 62" stroke="#5a6d98" stroke-width="3" fill="none" opacity=".45" stroke-linecap="round"/>` });

  /* Hana-03: mostly robot. J's robot head and visor screen, with Hana's anime eyes, brows, blush and small mouth on it. */
  g.LOOKS.hana03 = build({ skin: '#1e2b30', shade: '#2f4650', blush: '#ff8fb0', name: 'hana03', title: 'Hana-03: robot with an anime face', card: { bg: '#e8efe9', fg: '#25403f' },
    blurb: 'Mostly robot: J\'s teal head and dark screen, with Hana\'s big anime eyes, brows, blush and small mouth shown on the screen, plus a navy band and a sailor collar.',
    lash: '#8ff3e8', brow: '#9ff3ea', mouth: '#9ff3ea', mouthIn: '#ff7f9a', dot: '#2f8f8a', sway: 0,
    eye: { rx: 13, ry: 14.5, i1: '#1d9aa8', i2: '#8ff3e8' },
    facePath: 'M52 84 Q52 58 80 58 L120 58 Q148 58 148 84 L148 134 Q148 158 120 158 L80 158 Q52 158 52 134Z',
    neck: `<rect x="86" y="160" width="28" height="18" rx="5" fill="${METAL}"/>`,
    body: `<path d="M32 215 C32 184 62 172 100 172 C138 172 168 184 168 215Z" fill="${TEAL2}"/><path d="M50 204 H78 M122 204 H150" stroke="#3f8582" stroke-width="2.4" stroke-linecap="round"/>${SAILOR('#2b3a5c')}<circle class="led" cx="100" cy="209" r="3" fill="#6ee7a0"/>`,
    shell: `<line x1="100" y1="42" x2="100" y2="16" stroke="${METAL}" stroke-width="4.4" stroke-linecap="round"/><circle class="led" cx="100" cy="11" r="8" fill="#6ee7a0"/>
      <rect x="20" y="92" width="20" height="44" rx="10" fill="${METAL}"/><rect x="160" y="92" width="20" height="44" rx="10" fill="${METAL}"/>
      <circle class="cue" cx="30" cy="114" r="5" fill="none" stroke="#9ff3ea" stroke-width="2.8"/><circle class="cue" cx="170" cy="114" r="5" fill="none" stroke="#9ff3ea" stroke-width="2.8"/>
      <rect x="38" y="42" width="124" height="130" rx="42" fill="${TEAL}"/>
      <path d="M44 74 Q100 48 156 74" stroke="#2b3a5c" stroke-width="7" fill="none" stroke-linecap="round" opacity=".9"/>`,
    seams: `<path d="M62 70 L90 62" stroke="#fff" stroke-width="5" opacity=".07" stroke-linecap="round"/>` });
})(window);
