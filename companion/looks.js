/* Five alternative looks for J. Each look = SVG markup (viewBox 0 0 200 215) + init() + apply(refs, E): the engine
 (engine.js) gives every look the same states, blinks, glances, emphasis squint, brows, mouth openness and worker-news
 reactions; a look only decides how those numbers are drawn. */
(function (g) {
  const { clamp } = g.CMP;
  const $ = (svg, sel) => svg.querySelector(sel);
  const A = (el, o) => { for (const k in o) el.setAttribute(k, typeof o[k] === 'number' ? +o[k].toFixed(2) : o[k]); };
  const eyeT = (el, cx, cy, sx, sy, dx = 0, dy = 0) => el.setAttribute('transform', `translate(${(dx).toFixed(2)} ${(dy).toFixed(2)}) translate(${cx} ${cy}) scale(${sx.toFixed(3)} ${sy.toFixed(3)}) translate(${-cx} ${-cy})`);
  const refs = (svg, names) => { const R = { bot: $(svg, '.bot') }; names.split(' ').forEach(n => R[n] = $(svg, '.' + n)); return R; };
  // eye with squint arcs: the solid eye fades out and a happy ^ arc fades in
  function eyes(R, E, cl, cr, cy, k = {}) {
    const a = clamp((E.sq - .3) * 6, 0, 1), gs = k.gaze ?? 3;
    eyeT(R.eL, cl, cy, E.sx, E.open * (1 - E.sq * .2), E.gx * gs, E.gy * gs * .85); eyeT(R.eR, cr, cy, E.sx, E.open * (1 - E.sq * .2), E.gx * gs, E.gy * gs * .85);
    R.eL.setAttribute('opacity', 1 - a); R.eR.setAttribute('opacity', 1 - a); R.sqL.setAttribute('opacity', a); R.sqR.setAttribute('opacity', a);
    if (R.plL) { const r = (k.pr ?? 5) * E.pup; A(R.plL, { r }); A(R.plR, { r }); }
  }
  function brows(R, E, y, xl, xr, w = 16) {
    const f = (el, v, side, x) => { const by = y - v * 5, inner = E.tilt * 3; A(el, { x1: x, x2: x + w, y1: side ? by - inner : by + inner, y2: side ? by + inner : by - inner, opacity: E.open < .2 ? 0 : 1 }); };
    f(R.bL, E.browL, 1, xl); f(R.bR, E.browR, 0, xr);
  }
  function mouth(R, E, cx, cy, w) {
    const o = clamp((E.mouth - .06) * 8, 0, 1);
    R.openG.setAttribute('opacity', o);
    A(R.openE, { cx, cy: cy + E.mouth * 3, rx: w * .5 + E.mouth * w * .45, ry: 1.5 + E.mouth * w * 1.15 });
    if (R.tongue) A(R.tongue, { cx, cy: cy + 2 + E.mouth * w * 1.1, rx: w * .35, ry: Math.max(.5, E.mouth * w * .35) });
    R.smile.setAttribute('d', `M${cx - w} ${cy} q${w} ${E.smile * w * .9 + 1} ${2 * w} 0`); R.smile.setAttribute('opacity', 1 - o);
  }
  const dots = (G, E) => { G.setAttribute('opacity', E.dots); [...G.children].forEach((c, i) => c.setAttribute('transform', `translate(0 ${(Math.sin(E.t / 180 + i * .9) * -3).toFixed(1)})`)); };
  const cueFill = (el, E, def, attr = 'fill') => el.setAttribute(attr, (E.cueA > .05 && E.cue) ? E.cue : def);
  const cheeks = (R, E, base = .3) => { R.chL.setAttribute('opacity', base + E.blush); R.chR.setAttribute('opacity', base + E.blush); };

  /* 1. Mochi: a soft rice-cake blob, kawaii dot eyes, blush, a bow on top (the bow takes the news colour) */
  g.LOOKS.mochi = {
    name: 'mochi', title: 'Mochi', card: { bg: '#fdeef0', fg: '#5a3a40' },
    blurb: 'Soft white rice-cake blob with dot eyes, blush and a pink bow. Round, quiet, very kawaii.',
    svg: `<ellipse cx="100" cy="190" rx="48" ry="6" fill="#0000001a"/><g class="bot">
      <ellipse cx="76" cy="182" rx="14" ry="8" fill="#f6a6b0"/><ellipse cx="124" cy="182" rx="14" ry="8" fill="#f6a6b0"/>
      <path d="M44 150c-6-50 12-92 56-92s62 42 56 92c-2 18-22 28-56 28s-54-10-56-28z" fill="#fff8f2" stroke="#f1d6cc" stroke-width="3"/>
      <g class="cue" fill="#f6a6b0"><path d="M100 62c-8-14-26-12-26-2s14 10 26 2z"/><path d="M100 62c8-14 26-12 26-2s-14 10-26 2z"/><circle cx="100" cy="62" r="5"/></g>
      <ellipse class="chL" cx="62" cy="126" rx="10" ry="6" fill="#f6a6b0" opacity=".4"/><ellipse class="chR" cx="138" cy="126" rx="10" ry="6" fill="#f6a6b0" opacity=".4"/>
      <g class="eL"><ellipse cx="78" cy="108" rx="6" ry="8" fill="#3a2a2a"/><circle cx="80" cy="105" r="2.4" fill="#fff"/></g>
      <g class="eR"><ellipse cx="122" cy="108" rx="6" ry="8" fill="#3a2a2a"/><circle cx="124" cy="105" r="2.4" fill="#fff"/></g>
      <path class="sqL" d="M70 110q8-10 16 0" stroke="#3a2a2a" stroke-width="3.5" fill="none" stroke-linecap="round" opacity="0"/>
      <path class="sqR" d="M114 110q8-10 16 0" stroke="#3a2a2a" stroke-width="3.5" fill="none" stroke-linecap="round" opacity="0"/>
      <line class="bL" x1="70" y1="92" x2="86" y2="92" stroke="#8a6a5a" stroke-width="2.6" stroke-linecap="round"/><line class="bR" x1="114" y1="92" x2="130" y2="92" stroke="#8a6a5a" stroke-width="2.6" stroke-linecap="round"/>
      <path class="smile" d="M92 125q8 6 16 0" stroke="#c0505e" stroke-width="3" fill="none" stroke-linecap="round"/>
      <g class="openG" opacity="0"><ellipse class="openE" cx="100" cy="126" rx="5" ry="3" fill="#c0505e"/><ellipse class="tongue" cx="100" cy="129" rx="3" ry="1.5" fill="#f08a9a"/></g>
      <g class="dots" fill="#f1b4bd" opacity="0"><circle cx="140" cy="56" r="4"/><circle cx="152" cy="56" r="4"/><circle cx="164" cy="56" r="4"/></g></g>`,
    init: s => refs(s, 'eL eR sqL sqR bL bR smile openG openE tongue chL chR cue dots'),
    apply(R, E) { eyes(R, E, 78, 122, 108); brows(R, E, 92, 70, 114); mouth(R, E, 100, 125, 8); cheeks(R, E, .3); dots(R.dots, E); cueFill(R.cue, E, '#f6a6b0'); }
  };

  /* 2. Sprout: a terracotta pot with a seedling; the leaves are the ears (perk up, droop, sway) */
  g.LOOKS.sprout = {
    name: 'sprout', title: 'Sprout', card: { bg: '#eaf5e4', fg: '#2f4a2c' },
    blurb: 'A potted seedling. The leaves do the body language: perk when listening, sway while thinking, spread on a surprise.',
    svg: `<ellipse cx="100" cy="201" rx="44" ry="6" fill="#0000001a"/><g class="bot">
      <path d="M100 112V86" stroke="#4a9a47" stroke-width="5" stroke-linecap="round"/>
      <g class="lfL"><path d="M100 88c-6-24-30-34-50-26c4 22 28 34 50 26z" fill="#6bbf59"/><path d="M96 84c-12-8-26-14-38-14" stroke="#4a9a47" stroke-width="2" fill="none"/></g>
      <g class="lfR"><path d="M100 88c6-24 30-34 50-26c-4 22-28 34-50 26z" fill="#6bbf59"/><path d="M104 84c12-8 26-14 38-14" stroke="#4a9a47" stroke-width="2" fill="none"/></g>
      <circle class="cue" cx="100" cy="82" r="6.5" fill="#ffd166"/>
      <rect x="56" y="112" width="88" height="18" rx="9" fill="#c96f48"/>
      <path d="M64 130h72l-8 58c-1 6-6 10-12 10H84c-6 0-11-4-12-10z" fill="#e08a60"/>
      <ellipse class="chL" cx="72" cy="166" rx="8" ry="5" fill="#f4a08a" opacity=".4"/><ellipse class="chR" cx="128" cy="166" rx="8" ry="5" fill="#f4a08a" opacity=".4"/>
      <g class="eL"><circle cx="84" cy="152" r="9.5" fill="#fff"/><circle class="plL" cx="84" cy="152" r="5" fill="#2d1e19"/></g>
      <g class="eR"><circle cx="116" cy="152" r="9.5" fill="#fff"/><circle class="plR" cx="116" cy="152" r="5" fill="#2d1e19"/></g>
      <path class="sqL" d="M75 154q9-10 18 0" stroke="#2d1e19" stroke-width="3.5" fill="none" stroke-linecap="round" opacity="0"/>
      <path class="sqR" d="M107 154q9-10 18 0" stroke="#2d1e19" stroke-width="3.5" fill="none" stroke-linecap="round" opacity="0"/>
      <line class="bL" x1="75" y1="137" x2="93" y2="137" stroke="#8a4b2d" stroke-width="2.6" stroke-linecap="round"/><line class="bR" x1="107" y1="137" x2="125" y2="137" stroke="#8a4b2d" stroke-width="2.6" stroke-linecap="round"/>
      <path class="smile" d="M93 172q7 6 14 0" stroke="#6b2d1d" stroke-width="3" fill="none" stroke-linecap="round"/>
      <g class="openG" opacity="0"><ellipse class="openE" cx="100" cy="173" rx="5" ry="3" fill="#6b2d1d"/><ellipse class="tongue" cx="100" cy="176" rx="3" ry="1.5" fill="#f08a9a"/></g>
      <g class="dots" fill="#6bbf59" opacity="0"><circle cx="146" cy="70" r="4"/><circle cx="158" cy="70" r="4"/><circle cx="170" cy="70" r="4"/></g></g>`,
    init: s => refs(s, 'lfL lfR eL eR plL plR sqL sqR bL bR smile openG openE tongue chL chR cue dots'),
    apply(R, E) {
      const sway = (E.st === 'waiting' || E.st === 'transcribing') ? Math.sin(E.t / 650) * 5 : Math.sin(E.t / 1800) * 1.5;
      const lift = E.alert * 20, tw = E.st === 'hearing' ? Math.sin(E.t / 90) * 2 : 0;
      R.lfL.setAttribute('transform', `rotate(${(lift + sway + tw).toFixed(1)} 100 88)`); R.lfR.setAttribute('transform', `rotate(${(-lift + sway - tw).toFixed(1)} 100 88)`);
      eyes(R, E, 84, 116, 152, { gaze: 2.5, pr: 5 }); brows(R, E, 137, 75, 107, 18); mouth(R, E, 100, 172, 7); cheeks(R, E, .3); dots(R.dots, E);
      cueFill(R.cue, E, '#ffd166'); R.cue.setAttribute('r', 6.5 + E.cueA * 3 + (E.st === 'speaking' ? 0 : 0));
    }
  };

  /* 3. Nimbus: a little cloud with a sun peeking over it (the sun takes the news colour; it rains while thinking) */
  const CLOUD = '<circle cx="66" cy="136" r="28"/><circle cx="96" cy="114" r="38"/><circle cx="134" cy="128" r="32"/><circle cx="100" cy="140" r="34"/><ellipse cx="100" cy="152" rx="58" ry="24"/>';
  g.LOOKS.nimbus = {
    name: 'nimbus', title: 'Nimbus', card: { bg: 'linear-gradient(#cfe8ff,#eef7ff)', fg: '#274a6a' },
    blurb: 'A fluffy cloud with a small sun beside it. Light rain falls when it is thinking; the sun lights up with news.',
    svg: `<g class="sunG"><g class="rays" stroke="#ffd35c" stroke-width="3" stroke-linecap="round">${[0, 45, 90, 135, 180, 225, 270, 315].map(a => `<line x1="152" y1="62" x2="152" y2="57" transform="rotate(${a} 152 78)"/>`).join('')}</g><circle class="cue" cx="152" cy="78" r="11" fill="#ffd35c"/></g>
      <g class="bot"><g fill="#cfe2f3" stroke="#cfe2f3" stroke-width="7">${CLOUD}</g><g fill="#f7fbff">${CLOUD}</g>
      <ellipse cx="100" cy="162" rx="50" ry="11" fill="#e3eef9" opacity=".85"/>
      <ellipse class="chL" cx="66" cy="146" rx="9" ry="5.5" fill="#f7a8b8" opacity=".4"/><ellipse class="chR" cx="134" cy="146" rx="9" ry="5.5" fill="#f7a8b8" opacity=".4"/>
      <g class="eL"><ellipse cx="82" cy="130" rx="4.8" ry="8" fill="#26456b"/><circle cx="83.6" cy="127" r="2" fill="#fff"/></g>
      <g class="eR"><ellipse cx="118" cy="130" rx="4.8" ry="8" fill="#26456b"/><circle cx="119.6" cy="127" r="2" fill="#fff"/></g>
      <path class="sqL" d="M74 132q8-10 16 0" stroke="#26456b" stroke-width="3.5" fill="none" stroke-linecap="round" opacity="0"/>
      <path class="sqR" d="M110 132q8-10 16 0" stroke="#26456b" stroke-width="3.5" fill="none" stroke-linecap="round" opacity="0"/>
      <line class="bL" x1="74" y1="114" x2="90" y2="114" stroke="#5b7ea3" stroke-width="2.6" stroke-linecap="round"/><line class="bR" x1="110" y1="114" x2="126" y2="114" stroke="#5b7ea3" stroke-width="2.6" stroke-linecap="round"/>
      <path class="smile" d="M92 146q8 6 16 0" stroke="#3a5f8c" stroke-width="3" fill="none" stroke-linecap="round"/>
      <g class="openG" opacity="0"><ellipse class="openE" cx="100" cy="147" rx="5" ry="3" fill="#3a5f8c"/><ellipse class="tongue" cx="100" cy="150" rx="3" ry="1.5" fill="#f08a9a"/></g></g>
      <g class="rain" fill="#7fb6ea" opacity="0"><ellipse cx="80" cy="182" rx="2.6" ry="4"/><ellipse cx="100" cy="182" rx="2.6" ry="4"/><ellipse cx="120" cy="182" rx="2.6" ry="4"/></g>`,
    init: s => refs(s, 'sunG rays eL eR sqL sqR bL bR smile openG openE tongue chL chR cue rain'),
    apply(R, E) {
      eyes(R, E, 82, 118, 130); brows(R, E, 114, 74, 110); mouth(R, E, 100, 146, 8); cheeks(R, E, .3);
      cueFill(R.cue, E, '#ffd35c'); R.cue.setAttribute('r', 11 + E.cueA * 3); cueFill(R.rays, E, '#ffd35c', 'stroke');
      R.rays.setAttribute('transform', `rotate(${(E.t / 40 % 360).toFixed(1)} 152 78)`);
      R.sunG.setAttribute('opacity', E.st === 'off' ? .4 : 1);
      R.rain.setAttribute('opacity', E.dots); [...R.rain.children].forEach((c, i) => c.setAttribute('transform', `translate(0 ${((E.t / 14 + i * 9) % 20).toFixed(1)})`));
    }
  };

  /* 4. Kit: a fox head; ears forward when listening, flat when sleepy, a scarf that takes the news colour */
  g.LOOKS.kit = {
    name: 'kit', title: 'Kit', card: { bg: '#fff3e4', fg: '#5a3820' },
    blurb: 'A young fox with big ears and a teal scarf. Ears do the listening; the scarf lights up with news.',
    svg: `<ellipse cx="100" cy="203" rx="46" ry="5" fill="#0000001a"/><g class="bot">
      <g class="earL"><path d="M46 112L36 50 84 88z" fill="#ee8a3a"/><path d="M50 100L45 66 74 90z" fill="#fff1dc"/></g>
      <g class="earR"><path d="M154 112L164 50 116 88z" fill="#ee8a3a"/><path d="M150 100L155 66 126 90z" fill="#fff1dc"/></g>
      <path d="M40 132c0-36 26-52 60-52s60 16 60 52c0 34-26 54-60 54s-60-20-60-54z" fill="#ee8a3a"/>
      <path d="M50 150c10-18 28-20 50-8 22-12 40-10 50 8-6 24-26 36-50 36s-44-12-50-36z" fill="#fff1dc"/>
      <path class="cue" d="M58 181q42 16 84 0l-4 15q-38 14-76 0z" fill="#3fa7a0"/>
      <ellipse class="chL" cx="56" cy="146" rx="9" ry="5.5" fill="#f5a08a" opacity=".4"/><ellipse class="chR" cx="144" cy="146" rx="9" ry="5.5" fill="#f5a08a" opacity=".4"/>
      <ellipse cx="100" cy="144" rx="6" ry="4.2" fill="#3b2a24"/>
      <g class="eL"><ellipse cx="72" cy="124" rx="6.2" ry="8.5" fill="#3b2a24"/><circle cx="74" cy="121" r="2.4" fill="#fff"/></g>
      <g class="eR"><ellipse cx="128" cy="124" rx="6.2" ry="8.5" fill="#3b2a24"/><circle cx="130" cy="121" r="2.4" fill="#fff"/></g>
      <path class="sqL" d="M63 126q9-11 18 0" stroke="#3b2a24" stroke-width="3.6" fill="none" stroke-linecap="round" opacity="0"/>
      <path class="sqR" d="M119 126q9-11 18 0" stroke="#3b2a24" stroke-width="3.6" fill="none" stroke-linecap="round" opacity="0"/>
      <line class="bL" x1="62" y1="106" x2="80" y2="106" stroke="#fff1dc" stroke-width="3.6" stroke-linecap="round"/><line class="bR" x1="120" y1="106" x2="138" y2="106" stroke="#fff1dc" stroke-width="3.6" stroke-linecap="round"/>
      <path class="smile" d="M92 156q8 6 16 0" stroke="#3b2a24" stroke-width="3" fill="none" stroke-linecap="round"/>
      <g class="openG" opacity="0"><ellipse class="openE" cx="100" cy="157" rx="5" ry="3" fill="#3b2a24"/><ellipse class="tongue" cx="100" cy="161" rx="3" ry="1.5" fill="#f08a9a"/></g>
      <g class="dots" fill="#ee8a3a" opacity="0"><circle cx="150" cy="56" r="4"/><circle cx="162" cy="56" r="4"/><circle cx="174" cy="56" r="4"/></g></g>`,
    init: s => refs(s, 'earL earR eL eR sqL sqR bL bR smile openG openE tongue chL chR cue dots'),
    apply(R, E) {
      const think = (E.st === 'waiting' || E.st === 'transcribing'), tw = E.st === 'hearing' ? Math.sin(E.t / 70) * 2.5 : 0;
      const a = (E.alert - .4) * 9;
      R.earL.setAttribute('transform', `rotate(${(-a + (think ? 8 + Math.sin(E.t / 600) * 6 : 0) + tw).toFixed(1)} 62 110)`);
      R.earR.setAttribute('transform', `rotate(${(a - tw).toFixed(1)} 138 110)`);
      eyes(R, E, 72, 128, 124); brows(R, E, 106, 62, 120, 18); mouth(R, E, 100, 157, 8); cheeks(R, E, .3); dots(R.dots, E); cueFill(R.cue, E, '#3fa7a0');
    }
  };

  /* 5. Orbit: a glowing spirit orb on a dark panel; the mouth is a live waveform and little moons orbit it */
  g.LOOKS.orbit = {
    name: 'orbit', title: 'Orbit', card: { bg: '#10122a', fg: '#c9d4ff' },
    blurb: 'A glowing violet orb with neon eyes, a waveform mouth and orbiting moons. Best on a dark panel; the ring takes the news colour.',
    svg: `<defs><radialGradient id="§g" cx="38%" cy="32%" r="75%"><stop offset="0" stop-color="#d4c6ff"/><stop offset=".5" stop-color="#7a63ff"/><stop offset="1" stop-color="#2a2891"/></radialGradient>
      <filter id="§f" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="7"/></filter><filter id="§s" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="2"/></filter></defs>
      <g class="bot"><circle cx="100" cy="112" r="74" fill="#7a63ff" opacity=".4" filter="url(#§f)"/><circle cx="100" cy="112" r="60" fill="url(#§g)"/>
      <ellipse cx="80" cy="82" rx="18" ry="9" fill="#fff" opacity=".18" transform="rotate(-30 80 82)"/>
      <ellipse class="ring" cx="100" cy="112" rx="82" ry="22" fill="none" stroke="#7df9ff" stroke-width="1.6" opacity=".45" transform="rotate(-20 100 112)"/>
      <circle class="m0" r="4" fill="#7df9ff"/><circle class="m1" r="4" fill="#7df9ff"/><circle class="m2" r="4" fill="#7df9ff"/>
      <ellipse class="chL" cx="66" cy="124" rx="8" ry="4.5" fill="#ff8fd0" opacity=".25"/><ellipse class="chR" cx="134" cy="124" rx="8" ry="4.5" fill="#ff8fd0" opacity=".25"/>
      <g class="eL" filter="url(#§s)"><ellipse cx="80" cy="104" rx="7" ry="10" fill="#aaf6ff"/><circle class="plL" cx="80" cy="104" r="3.5" fill="#26256e"/></g>
      <g class="eR" filter="url(#§s)"><ellipse cx="120" cy="104" rx="7" ry="10" fill="#aaf6ff"/><circle class="plR" cx="120" cy="104" r="3.5" fill="#26256e"/></g>
      <path class="sqL" d="M71 106q9-12 18 0" stroke="#aaf6ff" stroke-width="4" fill="none" stroke-linecap="round" opacity="0" filter="url(#§s)"/>
      <path class="sqR" d="M111 106q9-12 18 0" stroke="#aaf6ff" stroke-width="4" fill="none" stroke-linecap="round" opacity="0" filter="url(#§s)"/>
      <line class="bL" x1="72" y1="86" x2="88" y2="86" stroke="#aaf6ff" stroke-width="3" stroke-linecap="round" opacity=".9"/><line class="bR" x1="112" y1="86" x2="128" y2="86" stroke="#aaf6ff" stroke-width="3" stroke-linecap="round" opacity=".9"/>
      <path class="wave" d="" stroke="#aaf6ff" stroke-width="4" fill="none" stroke-linecap="round" stroke-linejoin="round" filter="url(#§s)"/>
      <g class="dots" fill="#7df9ff" opacity="0"><circle cx="150" cy="50" r="4"/><circle cx="162" cy="50" r="4"/><circle cx="174" cy="50" r="4"/></g></g>`,
    init: s => { const R = refs(s, 'ring m0 m1 m2 eL eR plL plR sqL sqR bL bR chL chR wave dots'); R.ang = 0; R.lt = 0; return R; },
    apply(R, E) {
      eyes(R, E, 80, 120, 104, { gaze: 3, pr: 3.5 }); R.plL.setAttribute('cx', 80 + E.gx * 2.5); R.plR.setAttribute('cx', 120 + E.gx * 2.5); brows(R, E, 86, 72, 112); cheeks(R, E, .12); dots(R.dots, E);
      // mouth: a waveform whose height is the audio level; at rest it is a smile line
      const pts = []; for (let x = 78; x <= 122; x += 4) { const u = (x - 100) / 22, env = 1 - u * u * .5;
        pts.push(`${x} ${(131 + E.smile * 7 * (1 - u * u) + Math.sin(x * .55 + E.t / 55) * E.mouth * 10 * env).toFixed(1)}`); }
      R.wave.setAttribute('d', 'M' + pts.join(' L'));
      // moons: speed follows alertness
      const dt = R.lt ? Math.min(.1, (E.t - R.lt) / 1000) : 0; R.lt = E.t; R.ang += dt * (.4 + Math.max(0, E.alert) * 1.1);
      const rot = -20 * Math.PI / 180;
      for (let i = 0; i < 3; i++) { const a = R.ang + i * 2.094, x = 82 * Math.cos(a), y = 22 * Math.sin(a), m = R['m' + i];
        A(m, { cx: 100 + x * Math.cos(rot) - y * Math.sin(rot), cy: 112 + x * Math.sin(rot) + y * Math.cos(rot), r: 3 + (y > 0 ? 1.6 : 0), opacity: y > 0 ? 1 : .4 }); cueFill(m, E, '#7df9ff'); }
      cueFill(R.ring, E, '#7df9ff', 'stroke'); R.ring.setAttribute('opacity', .45 + E.cueA * .5); R.ring.setAttribute('stroke-width', 1.6 + E.cueA * 2.4);
    }
  };
})(window);
