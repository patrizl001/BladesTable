/* Blades Table — read-only live view of the table. Plain JS, no dependencies, no network except same-origin /api. */
(() => {
'use strict';

/* ------------------------------------------------------------------ utils */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const arr = x => (Array.isArray(x) ? x : []);
const obj = x => (x && typeof x === 'object' && !Array.isArray(x) ? x : {});
const isNum = x => typeof x === 'number' && Number.isFinite(x);
const num = (x, d = 0) => { const n = typeof x === 'string' && x.trim() !== '' ? Number(x) : x; return isNum(n) ? n : d; };
const clamp = (n, a, b) => Math.max(a, Math.min(b, n));
const title = id => String(id ?? '').replace(/[_-]+/g, ' ').trim().replace(/\b\w/g, c => c.toUpperCase());
const cap = s => { s = String(s ?? ''); return s.charAt(0).toUpperCase() + s.slice(1); };
const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;
const signed = n => (n > 0 ? '+' + n : n < 0 ? '−' + Math.abs(n) : '0');
const str = x => (x === null || x === undefined ? '' : typeof x === 'string' ? x : typeof x === 'number' ? String(x) : '');
const idFor = s => String(s).replace(/[^a-zA-Z0-9_-]/g, '_');

/* ------------------------------------------------------------- constants */
const IDEAS = {
  bravery: ['might', 'willpower', 'calculation'],
  truth: ['gut', 'experience', 'knowledge'],
  compassion: ['stamina', 'empathy', 'attunement'],
  justice: ['swiftness', 'improvisation', 'passion'],
};
const IDEA_ORDER = Object.keys(IDEAS);
const IDEA_SHAPE = { // faceted marker per idea (redundant cue besides colour)
  bravery: '<polygon points="6,1 11,10 1,10"/>',
  truth: '<polygon points="6,1 11,6 6,11 1,6"/>',
  compassion: '<polygon points="3.5,1.5 8.5,1.5 11,6 8.5,10.5 3.5,10.5 1,6"/>',
  justice: '<polygon points="6,0.8 7.6,4.4 11.2,4.4 8.3,6.8 9.4,10.8 6,8.5 2.6,10.8 3.7,6.8 0.8,4.4 4.4,4.4"/>',
};
const ELEMENTS = ['fire', 'water', 'wind', 'ice', 'earth', 'electricity', 'light', 'dark'];
const ELEMENT_IDEA = { fire: 'bravery', water: 'bravery', wind: 'truth', ice: 'truth', earth: 'compassion', electricity: 'compassion', light: 'justice', dark: 'justice' };
const ELEMENT_LABEL = { electricity: 'Electric' };
const ATTR_ORDER = [].concat(...IDEA_ORDER.map(i => IDEAS[i]));
const ATTR_IDEA = {}; IDEA_ORDER.forEach(i => IDEAS[i].forEach(a => { ATTR_IDEA[a] = i; }));
const ARC_ABILITIES = [
  ['feeling_it', 'I’m Really Feeling It', 'Add one attribute to your initiative roll and gain 6 special points.'],
  ['reyn_time', 'It’s Reyn Time', 'Guarantee a roll’s success.'],
  ['heronop', 'The Heronop Special', 'Turn a failed roll into a near miss.'],
];
const TIERS = {
  success: { label: 'SUCCESS', sub: 'clean win', cls: 'success' },
  near_hit: { label: 'NEAR HIT', sub: 'succeeds, with a complication', cls: 'near_hit' },
  near_miss: { label: 'NEAR MISS', sub: 'fails, with a small benefit', cls: 'near_miss' },
  failure: { label: 'FAILURE', sub: 'it goes wrong', cls: 'failure' },
};
const AUTO = {
  reyn_time: 'It’s Reyn Time — success guaranteed',
  heronop: 'The Heronop Special — failure turned into a near miss',
  topple: 'Toppled target — a failed attack becomes a near hit',
  undodgeable: 'Undodgeable attack',
};
const KIND_LABEL = { check: 'Check', attack: 'Attack', defense: 'Defense', initiative: 'Initiative', special: 'Special', raw: 'Raw roll' };
const CONDITION_CLASS = { fresh: 'c-fresh', scratched: 'c-scratched', hurt: 'c-hurt', 'badly hurt': 'c-bad', down: 'c-down' };

/* ---- art tags */
const TAGS = {
  potency: { cat: 'fund', l: n => `Potency +${n}`, d: 'Adds dice to the attack roll.' },
  healing_potion: { cat: 'fund', l: () => 'Healing Potion', d: 'One ally heals the net successes.' },
  cooldown: { cat: 'fund', l: n => `Cooldown −${n}`, d: 'Starts the cooldown die lower.' },
  circle: { cat: 'aoe', l: n => (n > 1 ? 'Circle 5×5' : 'Circle 3×3'), d: 'Hits every enemy in the area.' },
  line: { cat: 'aoe', l: () => 'Line', d: 'Hits everything in a straight line (5 + bonus range).' },
  break: { cat: 'react', l: () => 'Break', d: 'Target is Broken: vulnerable to Topple and Launch.' },
  topple: { cat: 'react', l: () => 'Topple', d: 'Requires Break. Target cannot move or attack.' },
  launch: { cat: 'react', l: () => 'Launch', d: 'Requires Break. Target is pushed back.' },
  stagger: { cat: 'react', l: () => 'Stagger', d: 'Target moves back one place in the turn order.' },
  rush: { cat: 'react', l: n => `Rush +${n}`, d: 'Movement bonus.' },
  side: { cat: 'pos', l: () => 'Side +1', d: 'Bearer: +1 dice when attacking from the side.' },
  rear: { cat: 'pos', l: () => 'Rear +2', d: 'Bearer: +2 dice when attacking from behind.' },
  pincer: { cat: 'pos', l: () => 'Pincer +2', d: 'Blade: +2 dice against a target in a lower radius.' },
  unique_effect: { cat: 'elem', l: () => 'Unique effect', d: 'Choose any unique elemental effect of an affinity you hold.' },
  invigorating_steam: { cat: 'elem', idea: 'bravery', l: () => 'Invigorating Steam', d: 'An ally uses an art one turn sooner.' },
  bitter_snowstorm: { cat: 'elem', idea: 'truth', l: () => 'Bitter Snowstorm', d: '−1 movement and attack range on the target.' },
  counter_spike: { cat: 'elem', idea: 'compassion', l: () => 'Counter Spike', d: 'Attackers take 1 damage back.' },
  blinding_eclipse: { cat: 'elem', idea: 'justice', l: () => 'Blinding Eclipse', d: '−1 to the target’s attack and defense rolls.' },
  range: { cat: 'other', l: n => `Range +${n}`, d: 'Extends attack range.' },
  precise: { cat: 'other', l: () => 'Precise', d: 'Detrimental effects do not hit allies.' },
};
const TAG_ORDER = ['potency', 'range', 'cooldown'];
const CAT_LABEL = { fund: 'Fundamental', aoe: 'Area of effect', react: 'Reaction', pos: 'Positional', elem: 'Elemental', other: 'Other' };

/* ---- statuses (unknown ids fall back to a generic badge) */
const STATUS = {
  burning: { n: 'Burning', el: 'fire', i: 'flame', d: 'Takes 1 damage at the start of each of its turns.' },
  arts_seal: { n: 'Arts Seal', el: 'water', i: 'seal', d: 'Cannot use arts; cooldowns do not tick on its next turn.' },
  blustering_gale: { n: 'Blustering Gale', el: 'wind', i: 'wind', d: '+1 defense.' },
  frozen: { n: 'Frozen', el: 'ice', i: 'flake', d: 'Cannot move (a frozen Blade cannot change radius).' },
  cradled: { n: 'Cradled', el: 'earth', i: 'shield', d: 'Detrimental effects removed and blocked.' },
  electrifying_burst: { n: 'Electrifying Burst', el: 'electricity', i: 'bolt', d: 'Turn order shifted.' },
  blade_of_light: { n: 'Blade of Light', el: 'light', i: 'sun', d: '+2 range (Bearer) or free radius movement (Blade).' },
  shadowed: { n: 'Shadowed', el: 'dark', i: 'moon', d: 'May only attack the redirected target.' },
  invigorating_steam: { n: 'Invigorating Steam', idea: 'bravery', i: 'steam', d: 'An art comes back one turn sooner.' },
  snowstorm: { n: 'Bitter Snowstorm', idea: 'truth', i: 'flake2', d: '−1 movement (min 0) and −1 attack range (min 1).' },
  counter_spike: { n: 'Counter Spike', idea: 'compassion', i: 'spike', d: 'Anyone who successfully attacks it takes 1 damage.' },
  blinded: { n: 'Blinded', idea: 'justice', i: 'eclipse', d: '−1 to attack and defense rolls.' },
  broken: { n: 'Broken', i: 'crack', d: 'Vulnerable to Topple and Launch.' },
  toppled: { n: 'Toppled', i: 'topple', d: 'Cannot move or attack; failed attacks against it become near hits.' },
};
const STATUS_ALIAS = { burning_blade: 'burning', freezing_force: 'frozen', cradling_earth: 'cradled', shadow_manipulation: 'shadowed', bitter_snowstorm: 'snowstorm', blinding_eclipse: 'blinded' };
const ICONS = {
  flame: '<path d="M5 .8c.5 2 3.2 2.9 3.2 5.4a3.2 3.2 0 0 1-6.4 0c0-1.3.7-2 1.3-2.8.2.8.7 1 1.1.7.4-.9.4-2 .8-3.3z"/>',
  seal: '<circle cx="5" cy="5" r="3.6"/><path d="M2.4 7.6l5.2-5.2"/>',
  wind: '<path d="M1 3.5h5.2a1.6 1.6 0 1 0-1.6-1.6M1 6h7a1.6 1.6 0 1 1-1.6 1.6M1 8.4h3"/>',
  flake: '<path d="M5 1v8M1.5 3l7 4M1.5 7l7-4"/>',
  flake2: '<path d="M5 1v8M1 5h8M2.2 2.2l5.6 5.6M7.8 2.2 2.2 7.8"/>',
  shield: '<path d="M5 1l3.4 1.2v2.9C8.4 7.2 6.8 8.4 5 9 3.2 8.4 1.6 7.2 1.6 5.1V2.2z"/>',
  bolt: '<path d="M5.8.8 2.2 5.6h2.6L4.2 9.2 7.8 4.4H5.2z"/>',
  sun: '<circle cx="5" cy="5" r="1.9"/><path d="M5 .8v1.2M5 8v1.2M.8 5H2M8 5h1.2M2 2l.9.9M7.1 7.1l.9.9M8 2l-.9.9M2.9 7.1 2 8"/>',
  moon: '<path d="M7.6 6.6A3.6 3.6 0 1 1 4.4 1.4a2.9 2.9 0 0 0 3.2 5.2z"/>',
  steam: '<path d="M2.5 8.5c-1-1.5 1-2.2 0-3.8s1-2.2 0-3.4M5.3 8.5c-1-1.5 1-2.2 0-3.8s1-2.2 0-3.4M8 8.5c-1-1.5 1-2.2 0-3.8"/>',
  spike: '<path d="M5 .8l1.2 2.9 3 .3-2.3 2 .7 3L5 7.4 2.4 9l.7-3-2.3-2 3-.3z"/>',
  eclipse: '<circle cx="5" cy="5" r="3.6"/><circle cx="6" cy="4.4" r="2.3" fill="currentColor"/>',
  crack: '<path d="M6.6.8 3.6 4.4l2.6.9-2.2 3.9"/>',
  topple: '<path d="M1.5 7.6h7M3 7.6V3.4l5-1.4"/>',
  unknown: '<path d="M3.6 3.8a1.5 1.5 0 1 1 2.2 1.3c-.5.3-.8.6-.8 1.2M5 8.3v.1"/>',
};
function statusInfo(st) {
  const raw = str(obj(st).id);
  const id = STATUS_ALIAS[raw] || raw;
  const base = STATUS[id];
  const kind = str(st.kind) || 'neutral';
  let color = kind === 'beneficial' ? 'var(--good)' : kind === 'detrimental' ? 'var(--bad)' : 'var(--muted)';
  if (base && base.el) color = `var(--el-${base.el})`;
  else if (base && base.idea) color = `var(--idea-${base.idea})`;
  return {
    id: raw, name: str(st.label) || (base && base.n) || title(raw) || 'Status', icon: (base && base.i) || 'unknown',
    desc: (base && base.d) || '', kind, color,
  };
}
function statusSVG(st, size = 14) {
  const i = statusInfo(st);
  return `<svg class="sico k-${esc(i.kind)}" style="color:${i.color};width:${size}px;height:${size}px" viewBox="0 0 10 10" fill="none" stroke="currentColor" stroke-width="1.15" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[i.icon] || ICONS.unknown}</svg>`;
}

/* ------------------------------------------------------------- UI state */
const ui = {
  tab: 'journal', open: {}, spoilers: false, pinned: null, showRadii: true, zoom: 1,
  rollSel: null, sceneOpen: null, seenRollId: null, tumbleId: null, hover: null,
};
let S = null;            // last state
let lastText = '';       // last response body, for cheap change detection
let loadErr = null;
const conn = { state: 'connecting', fails: 0 };

/* ------------------------------------------------------------ data helpers */
const chars = () => obj(S && S.characters);
const charName = id => str(obj(chars()[id]).name) || title(id);
const combat = () => { const c = S && S.combat; return c && typeof c === 'object' ? c : null; };
const cmbs = () => obj(combat() && combat().combatants);
const isGM = () => !!(S && (S.view === 'gm')) || ui.spoilers;
const sideOf = c => (['party', 'enemy', 'neutral'].includes(c.side) ? c.side : 'neutral');
const posOf = c => { const p = arr(c.pos); return p.length >= 2 && isNum(p[0]) && isNum(p[1]) ? [p[0], p[1]] : null; };
const cheb = (a, b) => Math.max(Math.abs(a[0] - b[0]), Math.abs(a[1] - b[1]));
const combatantFor = charId => Object.values(cmbs()).find(c => c && c.char_id === charId) || null;

function derive(c) {
  const a = obj(c.attributes), d = obj(c.derived), g = k => num(a[k], 1);
  const ideas = {};
  IDEA_ORDER.forEach(i => { ideas[i] = isNum(obj(d.ideas)[i]) ? d.ideas[i] : IDEAS[i].reduce((s, k) => s + (isNum(a[k]) ? a[k] : (k === 'attunement' ? 0 : 1)), 0); });
  return {
    max_hp: isNum(d.max_hp) ? d.max_hp : g('willpower') + g('stamina') + 4,
    initiative_pool: isNum(d.initiative_pool) ? d.initiative_pool : Math.max(g('improvisation') + g('gut'), g('calculation') + g('experience')),
    movement: isNum(d.movement) ? d.movement : (c.role === 'blade' ? 1 : 3),
    basic_range: isNum(d.basic_range) ? d.basic_range : 1 + num(c.basic_range_bonus, 0),
    max_radius: isNum(d.max_radius) ? d.max_radius : 3,
    ideas,
  };
}
function hpOf(c) {
  const dv = derive(c), cb = combatantFor(c.id);
  if (cb && isNum(cb.hp)) return { hp: cb.hp, max: isNum(cb.max_hp) ? cb.max_hp : dv.max_hp, live: true };
  return { hp: isNum(c.hp) ? c.hp : null, max: dv.max_hp, live: false };
}
function pairKey(a, b) { return [a, b].sort().join('|'); }

/* ------------------------------------------------------------ small widgets */
function hpBar(hp, max, cls = '') {
  if (!isNum(hp)) return `<div class="hp ${cls}"><div class="hptrack"><i style="width:0"></i></div><span class="hpnum">– / ${isNum(max) ? max : '–'}</span></div>`;
  const pct = isNum(max) && max > 0 ? clamp(hp / max, 0, 1) : 0;
  const lvl = pct <= 0.25 ? 'low' : pct <= 0.5 ? 'mid' : 'hi';
  return `<div class="hp ${lvl} ${cls}" role="img" aria-label="HP ${hp} of ${max}"><div class="hptrack"><i style="width:${(pct * 100).toFixed(1)}%"></i></div><span class="hpnum"><b>${hp}</b> / ${isNum(max) ? max : '–'}</span></div>`;
}
const PIPS = {
  1: [[50, 50]], 2: [[28, 28], [72, 72]], 3: [[26, 26], [50, 50], [74, 74]],
  4: [[28, 28], [72, 28], [28, 72], [72, 72]], 5: [[26, 26], [74, 26], [50, 50], [26, 74], [74, 74]],
  6: [[30, 24], [70, 24], [30, 50], [70, 50], [30, 76], [70, 76]],
};
function dieSVG(v, o = {}) {
  const hit = o.hit === undefined ? v >= 5 : o.hit;
  const pips = PIPS[v];
  const body = '<polygon class="dbody" points="22,3 78,3 97,22 97,78 78,97 22,97 3,78 3,22"/><polygon class="dfacet" points="22,3 78,3 70,13 30,13"/><polygon class="dfacet2" points="3,22 13,30 13,70 3,78"/>';
  const inner = pips ? pips.map(p => `<circle class="pip" cx="${p[0]}" cy="${p[1]}" r="8.2"/>`).join('')
    : (o.empty ? '' : `<text class="dnum" x="50" y="64" text-anchor="middle">${esc(v)}</text>`);
  return `<svg class="die ${hit ? 'hit' : ''} ${o.empty ? 'empty' : ''} ${o.cls || ''}" viewBox="0 0 100 100" aria-hidden="true">${body}${inner}</svg>`;
}
function chip(text, o = {}) {
  return `<span class="chip ${o.cls || ''}"${o.style ? ` style="${o.style}"` : ''}${o.title ? ` title="${esc(o.title)}"` : ''}>${o.html || esc(text)}</span>`;
}
function elChip(el, on = true) {
  const lab = ELEMENT_LABEL[el] || cap(el);
  return `<span class="chip el ${on ? 'on' : 'off'}" style="--c:var(--el-${esc(el)})" title="${esc(lab)}${on ? '' : ' (not held)'}"><i class="elgem" aria-hidden="true"></i>${esc(lab)}${on ? '<span class="vh"> (held)</span>' : ''}</span>`;
}
function ideaMark(i, size = 12) {
  return `<svg class="imark" style="color:var(--idea-${i});width:${size}px;height:${size}px" viewBox="0 0 12 12" fill="currentColor" aria-hidden="true">${IDEA_SHAPE[i] || ''}</svg>`;
}
function sectionTitle(t, extra = '') { return `<h4 class="stitle"><span>${t}</span>${extra}</h4>`; }
function fmtTime(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  if (isNaN(d)) return esc(str(ts));
  return d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}
function emblem(c) {
  const el = arr(c.affinities)[0];
  const color = el && ELEMENTS.includes(el) ? `var(--el-${el})` : 'var(--core)';
  const ini = (str(c.name).trim().match(/\b\w/g) || ['?']).slice(0, 2).join('').toUpperCase();
  const shape = c.role === 'blade' ? '<polygon points="30,3 55,30 30,57 5,30"/>' : '<polygon points="18,3 42,3 57,30 42,57 18,57 3,30"/>';
  return `<svg class="emblem" viewBox="0 0 60 60" style="--c:${color}" aria-hidden="true">${shape}<text x="30" y="36" text-anchor="middle">${esc(ini)}</text></svg>`;
}

/* ------------------------------------------------------------------ HEADER */
function renderHeader() {
  const meta = obj(S && S.meta), clock = obj(S && S.clock);
  const has = S && S.has_campaign !== false && S.ok !== false;
  $('#campName').textContent = has ? (str(meta.name) || 'Untitled campaign') : 'Blades Table';
  let line = '';
  if (!S) line = loadErr ? 'Cannot reach the table' : 'Connecting to the table…';
  else if (S.ok === false) line = 'The table reported a problem';
  else if (!has) line = 'No campaign yet';
  else {
    const bits = [];
    if (isNum(clock.session)) bits.push(clock.session > 0 ? `Session ${clock.session}${clock.session_open ? ' (open)' : ''}` : 'Before session 1');
    if (isNum(clock.arc)) bits.push(`Arc ${clock.arc}${str(clock.arc_title) ? ': ' + clock.arc_title : ''}`);
    line = bits.join(' · ') || 'Campaign loaded';
  }
  $('#sessionLine').textContent = line;
  document.title = (has && str(meta.name) ? meta.name + ' — ' : '') + 'Blades Table' + (isGM() ? ' [GM VIEW]' : '');
  $('#gmBadge').hidden = !isGM();
  document.body.classList.toggle('gmview', isGM());
  const sb = $('#spoilerBtn');
  sb.setAttribute('aria-checked', String(ui.spoilers));
  sb.classList.toggle('on', ui.spoilers);
}
function setConn(state) {
  conn.state = state;
  const el = $('#conn');
  el.dataset.state = state;
  $('#connText').textContent = { live: 'live', connecting: 'connecting', retry: 'reconnecting', offline: 'offline' }[state] || state;
  el.title = { live: 'Live updates connected', connecting: 'Connecting…', retry: 'Connection lost — retrying', offline: 'Table server unreachable — retrying' }[state] || '';
}

/* ------------------------------------------------------------- PARTY COLUMN */
function orderedChars() {
  const cs = chars(), seen = new Set(), out = [];
  const add = id => { if (cs[id] && !seen.has(id)) { seen.add(id); out.push(cs[id]); } };
  Object.values(obj(S.teams)).forEach(t => { add(obj(t).bearer); arr(obj(t).blades).forEach(add); });
  Object.keys(cs).forEach(add);
  return out;
}
function partyHTML() {
  if (!S || S.has_campaign === false || S.ok === false) {
    return `<section class="panel"><h2 class="ptitle">Party</h2><p class="empty">No characters yet.</p></section>`;
  }
  const list = orderedChars();
  let h = `<h2 class="ptitle sr-only">Party</h2>`;
  if (!list.length) {
    h += `<section class="panel"><h2 class="ptitle">Party</h2><div class="emptybox"><p><b>No characters yet.</b></p><p class="muted">Ask Claude to create your Bearer and their Blade partner and they will appear here.</p></div></section>`;
    return h;
  }
  h += list.map(charCard).join('');
  const teams = Object.values(obj(S.teams));
  if (teams.length) h += teams.map(teamBox).join('');
  return h;
}
function teamBox(t) {
  t = obj(t);
  const names = [t.bearer, ...arr(t.blades)].filter(Boolean).map(charName);
  const cb = combat();
  const pts = cb ? num(obj(obj(cb.special).points)[t.id], 0) : 0;
  return `<section class="panel team"><h3 class="stitle"><span>Team special dice</span></h3>
    <p class="muted sm">${esc(names.join(' & ') || 'Team')}</p>
    ${specialDice(pts)}
    ${cb ? '' : '<p class="muted sm">Dice fill during combat: 18 points, 6 per die.</p>'}</section>`;
}
function specialDice(points) {
  points = clamp(num(points, 0), 0, 18);
  const dice = [0, 1, 2].map(i => {
    const v = clamp(points - 6 * i, 0, 6);
    const full = v >= 6;
    return `<div class="sdie ${full ? 'full' : ''}">${dieSVG(v, { hit: full, empty: v === 0, cls: 'big' })}<span class="sdlab">${v === 6 ? 'full' : v + '/6'}</span></div>`;
  }).join('');
  return `<div class="sdice" role="img" aria-label="Team special dice: ${points} of 18 points">${dice}<div class="spoints"><b>${points}</b><span>/ 18</span></div></div>`;
}

function charCard(c) {
  c = obj(c);
  const id = str(c.id), open = !!ui.open['sheet:' + id];
  const cb = combatantFor(id);
  const hp = hpOf(c);
  const you = c.controller === 'player';
  const role = c.role === 'blade' ? 'Blade' : c.role === 'bearer' ? 'Bearer' : title(c.role) || 'Character';
  const isCur = cb && arr(combat().order)[0] === cb.cid;
  let h = `<article class="card char role-${esc(c.role || 'x')} ${you ? 'mine' : ''} ${c.dead ? 'dead' : ''} ${isCur ? 'cur' : ''}" data-char="${esc(id)}">
    <button class="cardhead" type="button" data-act="tog" data-key="sheet:${esc(id)}" data-k="sheet:${esc(id)}" aria-expanded="${open}">
      ${emblem(c)}
      <span class="who"><span class="nm">${esc(str(c.name) || 'Unnamed')}</span>
        <span class="meta">${esc(str(c.pronouns))}${str(c.pronouns) ? ' · ' : ''}${esc(role)}</span></span>
      <span class="badges">${chip(you ? 'You' : cap(str(c.controller) === 'architect' ? 'Architect' : str(c.controller) || '?'), { cls: you ? 'ctl you' : 'ctl arch', title: you ? 'Controlled by you' : 'Controlled by the Architect (Claude)' })}</span>
      <svg class="chev" viewBox="0 0 12 12" aria-hidden="true"><path d="M3 4.5 6 8l3-3.5" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>
    </button>
    <div class="cardbody">
      ${hpBar(hp.hp, hp.max)}
      <div class="chips">${arr(c.affinities).map(e => elChip(e)).join('')}</div>`;
  if (cb) h += combatStrip(c, cb);
  if (c.dead) h += `<p class="deadflag">☠ Dead</p>`;
  h += `</div>`;
  if (open) h += sheetHTML(c, cb);
  h += `</article>`;
  return h;
}
function combatStrip(c, cb) {
  const arts = arr(c.arts);
  const cds = arr(cb.cooldowns);
  const pos = posOf(cb);
  let rad = '';
  if (c.role === 'blade' && cb.bearer_cid && cmbs()[cb.bearer_cid]) {
    const bp = posOf(cmbs()[cb.bearer_cid]);
    if (bp && pos) { const r = cheb(pos, bp); rad = r >= 1 && r <= 3 ? `Radius ${r}` : 'Outside radii'; }
  }
  const sts = arr(cb.statuses);
  return `<div class="cstrip">
    <div class="cmeta">${pos ? `<span class="coordtag" title="Position">${pos[0]},${pos[1]}</span>` : ''}${cb.facing ? `<span class="tagsm">facing ${esc(cb.facing)}</span>` : ''}${rad ? `<span class="tagsm rad">${esc(rad)}</span>` : ''}${cb.down ? '<span class="tagsm bad">DOWN</span>' : ''}</div>
    ${arts.length ? `<ul class="miniarts">${arts.map((a, i) => `<li><span class="an">${esc(str(obj(a).name) || 'Art ' + (i + 1))}</span>${cdPill(cds[i], i in cds)}</li>`).join('')}</ul>` : ''}
    ${sts.length ? `<div class="stline">${sts.map(statusChip).join('')}</div>` : ''}
  </div>`;
}
function cdPill(n, known) {
  if (!known || !isNum(n)) return `<span class="cd unk" title="Cooldown unknown">–</span>`;
  if (n <= 0) return `<span class="cd ready" title="Ready to use">READY</span>`;
  return `<span class="cd wait" title="${plural(n, 'turn')} until ready">${dieSVG(clamp(n, 1, 6), { hit: false, cls: 'mini' })}<span>${n}</span></span>`;
}
function remainingText(st) {
  const r = st.remaining, src = st.source && cmbs()[st.source] ? str(cmbs()[st.source].name) : '';
  if (!isNum(r)) return '';
  if (st.unit === 'until_source_turn_start') return src ? `until ${src}’s next turn starts` : 'until the source’s next turn starts';
  if (st.unit === 'until_source_turn_end') return src ? `until ${src}’s next turn ends` : 'until the source’s next turn ends';
  return plural(r, 'turn');
}
function statusChip(st) {
  const i = statusInfo(st);
  const rem = remainingText(st);
  return `<span class="schip k-${esc(i.kind)}" title="${esc(i.name + (rem ? ' — ' + rem : '') + (i.desc ? '. ' + i.desc : ''))}">${statusSVG(st, 13)}<span>${esc(i.name)}</span>${isNum(st.remaining) ? `<b>${st.remaining}</b>` : ''}</span>`;
}

/* ---- full character sheet */
function tagChip(id, n) {
  const t = TAGS[id];
  const nn = isNum(n) ? n : 1;
  const label = t ? t.l(nn) : (title(id) + (nn > 1 ? ` ×${nn}` : ''));
  const cat = t ? t.cat : 'other';
  const style = t && t.idea ? `--c:var(--idea-${t.idea})` : '';
  return `<span class="tag cat-${cat}" ${style ? `style="${style}"` : ''} title="${esc((t ? CAT_LABEL[cat] + ': ' + t.d : 'Unrecognised tag: ' + id))}">${esc(label)}</span>`;
}
function artHTML(a, i, cb) {
  a = obj(a);
  const tags = obj(a.tags);
  const keys = Object.keys(tags).sort((x, y) => {
    const ix = TAG_ORDER.indexOf(x), iy = TAG_ORDER.indexOf(y);
    return (ix < 0 ? 99 : ix) - (iy < 0 ? 99 : iy);
  });
  let cd = '';
  if (cb) {
    const cds = arr(cb.cooldowns), n = cds[i];
    cd = isNum(n) && n > 0
      ? `<div class="cdbox wait" title="${plural(n, 'turn')} until ready">${dieSVG(clamp(n, 1, 6), { hit: false, cls: 'big' })}<span><b>${n}</b> turn${n === 1 ? '' : 's'}</span></div>`
      : isNum(n) ? `<div class="cdbox ready"><span class="gem" aria-hidden="true"></span><b>READY</b></div>` : '';
  }
  return `<li class="art"><div class="arthead"><span class="artno">${i + 1}</span><span class="artname">${esc(str(a.name) || 'Unnamed art')}</span>${cd}</div>
    ${str(a.description) ? `<p class="artdesc">${esc(a.description)}</p>` : ''}
    <div class="tags">${keys.length ? keys.map(k => tagChip(k, tags[k])).join('') : '<span class="muted sm">no tags</span>'}</div></li>`;
}
function usageBox(t, cb) {
  const per = t.per ? str(t.per) : '';
  if (!per) return '<span class="use none" title="Always active">passive</span>';
  const usedCombat = cb && arr(cb.combat_talents_used).includes(t.id);
  const used = !!t.used || (per === 'combat' && usedCombat);
  const perLab = per === 'once' ? 'once' : `per ${per}`;
  return `<span class="use ${used ? 'used' : 'ready'}" title="${used ? 'Used' : 'Available'} (${perLab})"><i class="box" aria-hidden="true">${used ? '✕' : ''}</i>${esc(perLab)}<span class="vh">${used ? ', used' : ', available'}</span></span>`;
}
function bondHTML(c, otherId, bond) {
  bond = obj(bond);
  const aff = clamp(num(obj(S.affinity)[pairKey(str(c.id), otherId)], 0), -2, 2);
  const notches = [-2, -1, 0, 1, 2].map(v => `<i class="notch ${v === aff ? 'on' : ''} ${v < 0 ? 'neg' : v > 0 ? 'pos' : ''}" title="${signed(v)}"><span>${v === 0 ? '0' : signed(v)}</span></i>`).join('');
  return `<li class="bond"><div class="bondhead"><b>${esc(charName(otherId))}</b>${str(bond.name) ? `<span class="bname">${esc(bond.name)}</span>` : ''}</div>
    <div class="track" role="img" aria-label="Affinity ${signed(aff)}">${notches}<span class="tracklab">Affinity ${signed(aff)}</span></div>
    ${aff < 0 ? `<p class="hint">${aff <= -2 ? 'A free level 3 reconciliation burst is available.' : 'A free level 1 reconciliation burst is available.'}</p>` : ''}
    ${str(bond.benefit) ? `<p class="bn"><span class="lbl ben">Benefit</span> ${esc(bond.benefit)}</p>` : ''}
    ${str(bond.drawback) ? `<p class="bn"><span class="lbl dra">Drawback</span> ${esc(bond.drawback)}</p>` : ''}</li>`;
}
function sheetHTML(c, cb) {
  const dv = derive(c), a = obj(c.attributes), id = str(c.id);
  const blade = c.role === 'blade';
  const hp = hpOf(c);
  let h = `<div class="sheet" data-sheet="${esc(id)}">`;
  // identity
  const idrows = [['Weapon', c.weapon], ['Home Titan', c.home_titan],
    ['Partner', arr(c.partner_ids).map(charName).join(', ')], ['Player', c.controller === 'player' ? str(obj(S.meta).player_name) || 'You' : 'Architect (Claude)']]
    .filter(r => str(r[1]));
  h += `<div class="sblock ident"><dl class="kv">${idrows.map(r => `<div><dt>${r[0]}</dt><dd>${esc(r[1])}</dd></div>`).join('')}</dl>
    ${str(c.appearance) ? `<p class="appear">${esc(c.appearance)}</p>` : ''}
    ${str(c.personality) ? `<p class="sm"><span class="lbl">Personality</span> ${esc(c.personality)}</p>` : ''}
    ${str(c.background) ? `<p class="sm"><span class="lbl">Background</span> ${esc(c.background)}</p>` : ''}</div>`;
  // traits
  h += `<div class="sblock">${sectionTitle('Traits')}<div class="traits">
    <div class="trait hpt"><span class="tl">HP</span><span class="tv">${isNum(hp.hp) ? `<b>${hp.hp}</b>` : '–'}<small>/ ${hp.max}</small></span>${hpBar(hp.hp, hp.max, 'slim')}</div>
    <div class="trait"><span class="tl">Basic attack range</span><span class="tv"><b>${dv.basic_range}</b></span></div>
    <div class="trait"><span class="tl">Initiative pool</span><span class="tv"><b>${dv.initiative_pool}</b><small>dice</small></span></div>
    <div class="trait"><span class="tl">${blade ? 'Movement (radius moves)' : 'Movement'}</span><span class="tv"><b>${dv.movement}</b></span></div>
    ${blade ? `<div class="trait"><span class="tl">Max radius</span><span class="tv"><b>${dv.max_radius}</b></span></div>` : ''}
  </div></div>`;
  // attributes
  h += `<div class="sblock">${sectionTitle('Attributes')}<div class="ideas">${IDEA_ORDER.map(i => `<div class="idea" style="--c:var(--idea-${i})">
      <div class="ihead">${ideaMark(i)}<span>${cap(i)}</span><b title="${cap(i)} total">${dv.ideas[i]}</b></div>
      ${IDEAS[i].map(k => { const v = a[k]; const n = isNum(v) ? v : 0; return `<div class="attr"><span class="an">${cap(k)}</span><b>${isNum(v) ? v : '–'}</b><span class="meter" aria-hidden="true">${Array.from({ length: 12 }, (_, j) => `<i class="${j < n ? 'f' : ''}"></i>`).join('')}</span></div>`; }).join('')}
    </div>`).join('')}</div></div>`;
  // affinities
  const held = arr(c.affinities);
  h += `<div class="sblock">${sectionTitle('Elemental affinities')}<div class="chips grid8">${ELEMENTS.map(e => elChip(e, held.includes(e))).join('')}</div></div>`;
  // field skills
  const fs = arr(c.field_skills);
  h += `<div class="sblock">${sectionTitle('Field skills')}${fs.length ? `<ul class="skills">${fs.map(s => `<li><b>${esc(str(obj(s).name) || 'Skill')}</b>${str(obj(s).description) ? `<span>${esc(s.description)}</span>` : ''}</li>`).join('')}</ul>` : '<p class="muted sm">None.</p>'}</div>`;
  // arts
  const arts = arr(c.arts);
  h += `<div class="sblock">${sectionTitle('Arts', cb ? '<span class="muted sm">cooldown dice live</span>' : '')}${arts.length ? `<ol class="arts">${arts.map((x, i) => artHTML(x, i, cb)).join('')}</ol>` : '<p class="muted sm">No arts yet.</p>'}</div>`;
  // talents
  const ts = arr(c.talents);
  h += `<div class="sblock">${sectionTitle('Talents')}${ts.length ? `<ul class="talents">${ts.map(t => { t = obj(t); return `<li><span class="tn">${esc(str(t.name) || title(t.id) || 'Talent')}${str(t.choice) ? `<em>${esc(t.choice)}</em>` : ''}</span><span class="rank" title="Rank ${num(t.rank, 1)}">${Array.from({ length: Math.max(1, Math.min(5, num(t.rank, 1))) }, () => '<i></i>').join('')}<span class="vh">rank ${num(t.rank, 1)}</span></span>${usageBox(t, cb)}</li>`; }).join('')}</ul>` : '<p class="muted sm">None.</p>'}</div>`;
  // once-per-arc
  const aa = obj(c.arc_abilities);
  h += `<div class="sblock">${sectionTitle('Once per arc')}<ul class="abil">${ARC_ABILITIES.map(([k, name, tip]) => {
    const avail = aa[k] !== false && (k in aa ? !!aa[k] : true);
    return `<li class="${avail ? 'avail' : 'spent'}" title="${esc(tip)}"><span class="cbx" role="checkbox" aria-checked="${avail}" aria-label="${esc(name)}: ${avail ? 'available' : 'spent'}">${avail ? '✓' : ''}</span><span class="aname">${esc(name)}</span><span class="astate">${avail ? 'available' : 'spent'}</span></li>`;
  }).join('')}</ul></div>`;
  // bonds
  const bonds = obj(c.bonds), bk = Object.keys(bonds);
  h += `<div class="sblock">${sectionTitle('Bonds')}${bk.length ? `<ul class="bonds">${bk.map(k => bondHTML(c, k, bonds[k])).join('')}</ul>` : '<p class="muted sm">No bonds yet.</p>'}</div>`;
  // bp + inventory
  const bp = obj(c.bp);
  h += `<div class="sblock">${sectionTitle('Bond points')}<div class="bp"><span class="bpv"><b>${isNum(bp.current) ? bp.current : '–'}</b><small>current</small></span><span class="bpv"><b>${isNum(bp.total) ? bp.total : '–'}</b><small>total earned</small></span>${c.tag_refund_available ? chip('Tag refund available', { cls: 'good', title: 'One art tag may be refunded at the end of the arc' }) : ''}</div></div>`;
  const inv = arr(c.inventory);
  h += `<div class="sblock">${sectionTitle('Inventory & notes')}${inv.length ? `<ul class="inv">${inv.map(i => `<li>${esc(str(i) || JSON.stringify(i))}</li>`).join('')}</ul>` : '<p class="muted sm">Empty.</p>'}${str(c.notes) ? `<p class="notes">${esc(c.notes)}</p>` : ''}</div>`;
  return h + '</div>';
}

/* ------------------------------------------------------------- CENTER COLUMN */
function sceneHTML() {
  const sc = obj(S.scene);
  const cb = combat();
  const hasAny = str(sc.title) || str(sc.location) || str(sc.description) || str(sc.mood) || arr(sc.present).length;
  if (!hasAny) return `<section class="panel scene"><h2 class="ptitle">Scene</h2><p class="muted">No scene has been set yet.</p></section>`;
  const open = ui.sceneOpen === null ? !cb : ui.sceneOpen;
  const present = arr(sc.present).map(p => {
    const t = str(p) || str(obj(p).name);
    const nm = chars()[t] ? charName(t) : (obj(S.entities)[t] ? str(obj(S.entities)[t].name) : t);
    return chip(nm, { cls: 'pres' });
  }).join('');
  const desc = str(sc.description);
  return `<section class="panel scene ${open ? 'open' : 'collapsed'}">
    <div class="scenehead"><div>
      <h2 class="ptitle">${esc(str(sc.title) || 'Scene')}</h2>
      <p class="loc">${str(sc.location) ? `<span class="pin" aria-hidden="true"></span>${esc(sc.location)}` : ''}${str(sc.mood) ? `<span class="mood">${esc(sc.mood)}</span>` : ''}</p></div>
      ${desc ? `<button type="button" class="linkbtn" data-act="scene" data-k="scene" aria-expanded="${open}">${open ? 'Collapse' : 'Read scene'}</button>` : ''}</div>
    ${desc ? `<p class="desc">${esc(desc)}</p>` : ''}
    ${present ? `<div class="present"><span class="lbl">Present</span>${present}</div>` : ''}
  </section>`;
}

function emptyCenter() {
  if (!S && loadErr) {
    return `<section class="panel hero"><div class="heroart">${heroSVG()}</div><h2>Cannot reach the table</h2><p class="muted">The table server is not answering (${esc(loadErr)}). This page will reconnect on its own once <code>boe serve</code> is running.</p></section>`;
  }
  if (!S) return `<section class="panel hero"><div class="heroart">${heroSVG()}</div><h2>Connecting…</h2></section>`;
  if (S.ok === false) return `<section class="panel hero"><div class="heroart">${heroSVG()}</div><h2>Something went wrong</h2><p class="muted">${esc(str(S.error) || 'The table reported an error.')}</p></section>`;
  return `<section class="panel hero"><div class="heroart">${heroSVG()}</div>
    <h2>No campaign yet</h2>
    <p>The table is set and the Cloud Sea is waiting. Ask Claude to start a campaign.</p>
    <p class="muted">For example: <q>Start a new Blades of Ether campaign. I want to play a Bearer.</q> Characters, maps, dice and your journal will show up here live as the story unfolds.</p></section>`;
}
function heroSVG() {
  return `<svg viewBox="0 0 320 130" role="img" aria-label="A crystal above a sea of clouds"><defs><linearGradient id="hg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7ff5e4"/><stop offset="1" stop-color="#3a6bd8"/></linearGradient></defs>
    <g opacity=".55" fill="#9db6ff"><ellipse cx="70" cy="112" rx="56" ry="16"/><ellipse cx="160" cy="120" rx="76" ry="14"/><ellipse cx="250" cy="110" rx="56" ry="17"/></g>
    <g opacity=".3" fill="#fff"><ellipse cx="100" cy="100" rx="50" ry="10"/><ellipse cx="220" cy="98" rx="55" ry="10"/></g>
    <polygon points="160,8 190,48 160,98 130,48" fill="url(#hg)" stroke="#e8fffb" stroke-width="1.5"/><polygon points="160,8 175,48 160,98" fill="#fff" opacity=".28"/>
    <circle cx="160" cy="52" r="46" fill="none" stroke="#7ff5e4" stroke-opacity=".25"/><circle cx="160" cy="52" r="62" fill="none" stroke="#7ff5e4" stroke-opacity=".12"/></svg>`;
}

/* ---- battle map */
const CELL = 64, PAD = 30;
function terrainSVG(type, x, y, info) {
  const X = PAD + x * CELL, Y = PAD + y * CELL, c = CELL;
  const cx = X + c / 2, cy = Y + c / 2;
  switch (type) {
    case 'wall': return `<rect class="t-wall" x="${X}" y="${Y}" width="${c}" height="${c}"/><rect x="${X}" y="${Y}" width="${c}" height="${c}" fill="url(#pWall)"/>`;
    case 'obstacle': return `<polygon class="t-obst" points="${X + 8},${Y + 44} ${X + 14},${Y + 18} ${X + 32},${Y + 8} ${X + 52},${Y + 16} ${X + 57},${Y + 42} ${X + 40},${Y + 56} ${X + 20},${Y + 55}"/><polyline class="t-obst-hi" points="${X + 14},${Y + 18} ${X + 32},${Y + 8} ${X + 52},${Y + 16}"/>`;
    case 'hazard': return `<rect class="t-haz" x="${X + 2}" y="${Y + 2}" width="${c - 4}" height="${c - 4}"/><rect x="${X + 2}" y="${Y + 2}" width="${c - 4}" height="${c - 4}" fill="url(#pHaz)"/>`;
    case 'difficult': return `<rect class="t-diff" x="${X}" y="${Y}" width="${c}" height="${c}"/><rect x="${X}" y="${Y}" width="${c}" height="${c}" fill="url(#pDiff)"/>`;
    case 'feature': return `<polygon class="t-feat" points="${cx},${Y + 9} ${cx + 15},${cy} ${cx},${Y + c - 9} ${cx - 15},${cy}"/><polygon class="t-feat-hi" points="${cx},${Y + 9} ${cx + 15},${cy} ${cx},${cy}"/>`;
    case 'cover': return `<rect class="t-cover" x="${X + 6}" y="${Y + 28}" width="${c - 12}" height="22" rx="4"/><path class="t-cover-l" d="M${X + 6} ${Y + 39}H${X + c - 6}M${cx} ${Y + 28}V${Y + 50}"/>`;
    default: return `<rect class="t-unk" x="${X + 3}" y="${Y + 3}" width="${c - 6}" height="${c - 6}" rx="6"/><text class="t-q" x="${cx}" y="${cy + 6}" text-anchor="middle">?</text>`;
  }
}
const FACE_ANGLE = { N: 0, E: 90, S: 180, W: 270 };
function tokenSVG(cb, cur) {
  const p = posOf(cb);
  if (!p) return '';
  const cx = PAD + p[0] * CELL + CELL / 2, cy = PAD + p[1] * CELL + CELL / 2;
  const side = sideOf(cb), down = !!cb.down || cb.condition === 'down';
  const blade = cb.role === 'blade';
  const R = 18, ty = -6;
  const shape = blade
    ? `<polygon class="tshape" points="0,${ty - 21} 21,${ty} 0,${ty + 21} -21,${ty}"/>`
    : `<polygon class="tshape" points="${[0, 1, 2, 3, 4, 5, 6, 7].map(i => { const a = (i * 45 + 22.5) * Math.PI / 180; return (Math.sin(a) * R).toFixed(1) + ',' + (ty - Math.cos(a) * R).toFixed(1); }).join(' ')}"/>`;
  const ang = FACE_ANGLE[cb.facing];
  const wedge = ang === undefined ? '' : `<g transform="translate(0 ${ty}) rotate(${ang})"><polygon class="twedge" points="-7,${-(blade ? 19 : R) + 1} 7,${-(blade ? 19 : R) + 1} 0,${-(blade ? 19 : R) - 8}"/></g>`;
  // hp or condition
  let low = '';
  if (isNum(cb.hp) && isNum(cb.max_hp) && cb.max_hp > 0) {
    const pct = clamp(cb.hp / cb.max_hp, 0, 1);
    low = `<g class="thp ${pct <= .25 ? 'low' : pct <= .5 ? 'mid' : 'hi'}"><rect class="trk" x="-21" y="19" width="42" height="6" rx="3"/><rect class="fil" x="-21" y="19" width="${(42 * pct).toFixed(1)}" height="6" rx="3"/></g>`;
  } else if (cb.condition) {
    const cc = CONDITION_CLASS[cb.condition] || 'c-fresh';
    low = `<g class="tcond ${cc}"><rect x="-22" y="17" width="44" height="12" rx="6"/><text x="0" y="26" text-anchor="middle">${esc(cb.condition)}</text></g>`;
  }
  // statuses: left column then right column
  const sts = arr(cb.statuses);
  const stIcons = sts.slice(0, 6).map((st, i) => {
    const col = i < 3 ? 0 : 1, row = i % 3;
    const sx = col === 0 ? -31 : 19, sy = -30 + row * 15;
    const inf = statusInfo(st);
    return `<g class="tst k-${esc(inf.kind)}" transform="translate(${sx} ${sy})"><circle cx="6" cy="6" r="6.6"/><svg x="1.4" y="1.4" width="9.2" height="9.2" viewBox="0 0 10 10" style="color:${inf.color}" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round">${ICONS[inf.icon] || ICONS.unknown}</svg>${isNum(st.remaining) ? `<g class="tcount"><circle cx="${col === 0 ? 12 : 0}" cy="12" r="4.6"/><text x="${col === 0 ? 12 : 0}" y="14.6" text-anchor="middle">${st.remaining > 9 ? '9+' : st.remaining}</text></g>` : ''}</g>`;
  }).join('') + (sts.length > 6 ? `<text class="tmore" x="${27}" y="${-30 + 45 + 7}" text-anchor="middle">+${sts.length - 6}</text>` : '');
  const nm = str(cb.name) || str(cb.cid);
  const label = `${nm}, ${side}${cb.condition ? ', ' + cb.condition : isNum(cb.hp) ? `, ${cb.hp} of ${cb.max_hp} HP` : ''}, at ${p[0]},${p[1]}${down ? ', down' : ''}. Press Enter to pin details.`;
  const pinned = ui.pinned === cb.cid;
  return `<g class="tok side-${side} role-${esc(cb.role || 'other')} ${down ? 'down' : ''} ${cur ? 'cur' : ''} ${pinned ? 'pinned' : ''}" transform="translate(${cx} ${cy})" data-cid="${esc(cb.cid)}" tabindex="0" role="button" aria-label="${esc(label)}">
    ${cur ? `<g class="pulse" transform="translate(0 ${ty})"><circle r="${blade ? 27 : 25}"/></g>` : ''}
    ${pinned ? `<circle class="pinring" r="${CELL / 2 - 1}" cy="0" />` : ''}
    ${wedge}${shape}<text class="tshort" x="0" y="${ty + 5}" text-anchor="middle">${esc(str(cb.short).slice(0, 2) || nm.slice(0, 2).toUpperCase())}</text>
    ${down ? `<path class="tx" d="M-10 ${ty - 10}L10 ${ty + 10}M10 ${ty - 10}L-10 ${ty + 10}"/>` : ''}
    ${low}${stIcons}</g>`;
}
function radiiSVG(W, H) {
  const out = [];
  const colors = ['var(--core)', 'var(--gold)', 'var(--idea-justice)'];
  let n = 0;
  Object.values(cmbs()).forEach(b => {
    if (!b || b.role !== 'blade' || sideOf(b) !== 'party' || !b.bearer_cid) return;
    const br = cmbs()[b.bearer_cid]; if (!br) return;
    const bp = posOf(br), kp = posOf(b); if (!bp) return;
    const cur = kp ? cheb(kp, bp) : -1;
    const col = colors[n++ % colors.length];
    for (let r = 3; r >= 1; r--) {
      const x = PAD + (bp[0] - r) * CELL, y = PAD + (bp[1] - r) * CELL, s = (2 * r + 1) * CELL;
      const on = cur === r;
      out.push(`<g class="ring ${on ? 'on' : ''}" style="--rc:${col}"><rect x="${x + 2}" y="${y + 2}" width="${s - 4}" height="${s - 4}" rx="6"/><text x="${x + 8}" y="${y + 16}">R${r}</text></g>`);
    }
  });
  return out.length ? `<g class="rings" clip-path="url(#mapclip)" pointer-events="none">${out.join('')}</g>` : '';
}
function mapSVG(cb) {
  const m = obj(cb.map);
  const W = clamp(Math.round(num(m.width, 0)) || 12, 1, 60);
  const Hh = clamp(Math.round(num(m.height, 0)) || 9, 1, 60);
  let cells = m.cells;
  if (Array.isArray(cells)) { const o = {}; cells.forEach(c => { if (c && isNum(c.x) && isNum(c.y)) o[c.x + ',' + c.y] = c; }); cells = o; }
  cells = obj(cells);
  const vw = PAD + W * CELL + 6, vh = PAD + Hh * CELL + 6;
  let grid = '', terr = '', labels = '', axes = '';
  for (let y = 0; y < Hh; y++) for (let x = 0; x < W; x++) {
    grid += `<rect class="cell ${(x + y) % 2 ? 'c1' : 'c0'}" x="${PAD + x * CELL}" y="${PAD + y * CELL}" width="${CELL}" height="${CELL}"/>`;
  }
  Object.keys(cells).forEach(k => {
    const m2 = /^\s*(-?\d+)\s*,\s*(-?\d+)\s*$/.exec(k); if (!m2) return;
    const x = +m2[1], y = +m2[2]; if (x < 0 || y < 0 || x >= W || y >= Hh) return;
    const info = obj(cells[k]), type = str(info.type);
    terr += `<g class="terr type-${esc(type || 'unknown')}" data-cell="${x},${y}">${terrainSVG(type, x, y, info)}</g>`;
    const lab = str(info.label);
    if (lab) labels += `<text class="tlabel" x="${PAD + x * CELL + CELL / 2}" y="${PAD + y * CELL + CELL - 5}" text-anchor="middle">${esc(lab.length > 9 ? lab.slice(0, 8) + '…' : lab)}</text>`;
  });
  for (let x = 0; x < W; x++) axes += `<text class="axis" x="${PAD + x * CELL + CELL / 2}" y="${PAD - 10}" text-anchor="middle">${x}</text>`;
  for (let y = 0; y < Hh; y++) axes += `<text class="axis" x="${PAD - 10}" y="${PAD + y * CELL + CELL / 2 + 4}" text-anchor="middle">${y}</text>`;
  const order = arr(cb.order), curCid = order[0];
  const toks = Object.values(cmbs()).filter(c => c && c.cid).sort((a, b) => (a.cid === curCid) - (b.cid === curCid) || (a.cid === ui.pinned) - (b.cid === ui.pinned));
  const frame = `<rect class="frame" x="${PAD}" y="${PAD}" width="${W * CELL}" height="${Hh * CELL}" rx="4"/>`;
  const defs = `<defs>
    <pattern id="pWall" width="16" height="16" patternUnits="userSpaceOnUse"><path d="M0 8h16M8 0v8M0 8v8M0 0h0" stroke="#000" stroke-opacity=".28" stroke-width="1" fill="none"/></pattern>
    <pattern id="pHaz" width="12" height="12" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="12" fill="#ff4d6a" fill-opacity=".34"/></pattern>
    <pattern id="pDiff" width="14" height="14" patternUnits="userSpaceOnUse"><circle cx="3" cy="3" r="1.3" fill="#a8e8ff" fill-opacity=".5"/><circle cx="10" cy="10" r="1.3" fill="#a8e8ff" fill-opacity=".5"/><path d="M0 7q3.5-3 7 0t7 0" stroke="#a8e8ff" stroke-opacity=".22" fill="none"/></pattern>
    <clipPath id="mapclip"><rect x="${PAD}" y="${PAD}" width="${W * CELL}" height="${Hh * CELL}"/></clipPath></defs>`;
  const fit = ui.zoom === 1;
  return `<svg class="mapsvg ${fit ? 'fit' : ''}" id="mapsvg" viewBox="0 0 ${vw} ${vh}" style="${fit ? `aspect-ratio:${vw}/${vh}` : `width:${ui.zoom * 100}%`}" data-w="${W}" data-h="${Hh}" role="group" aria-label="Battle map, ${W} by ${Hh} squares">
    ${defs}${axes}${grid}${terr}${labels}${radiiSVG(W, Hh)}${frame}<rect id="hovercell" class="hovercell" width="${CELL}" height="${CELL}" visibility="hidden" pointer-events="none"/>${toks.map(t => tokenSVG(t, t.cid === curCid)).join('')}</svg>`;
}
function orderStrip(cb) {
  const order = arr(cb.order);
  if (!order.length) return `<p class="muted sm">No turn order yet.</p>`;
  return `<ol class="orderstrip" aria-label="Turn order">${order.map((cid, i) => {
    const c = obj(cmbs()[cid]);
    const side = sideOf(c);
    const sub = isNum(c.hp) ? `${c.hp}/${c.max_hp}` : str(c.condition);
    return `<li class="oc side-${side} ${i === 0 ? 'now' : ''} ${c.down ? 'down' : ''}" data-cid="${esc(cid)}">${i === 0 ? '<span class="nowtag">NOW</span>' : `<span class="pos">${i + 1}</span>`}
      <span class="osh">${esc(str(c.short).slice(0, 2) || '??')}</span><span class="on">${esc(str(c.name) || cid)}</span><span class="osub">${esc(sub)}</span></li>`;
  }).join('')}</ol>`;
}
function pinnedHTML(cb) {
  const c = ui.pinned && cmbs()[ui.pinned];
  if (!c) return `<section class="box pinbox"><h3 class="stitle"><span>Token details</span></h3><p class="muted sm">Click a token on the map to pin its details here.</p></section>`;
  const p = posOf(c), side = sideOf(c);
  let rad = '';
  if (c.role === 'blade' && c.bearer_cid && cmbs()[c.bearer_cid]) {
    const bp = posOf(cmbs()[c.bearer_cid]);
    if (bp && p) { const r = cheb(p, bp); rad = r >= 1 && r <= 3 ? `Radius ${r} of ${charName(obj(cmbs()[c.bearer_cid]).char_id) || cmbs()[c.bearer_cid].name}` : 'Outside all radii'; }
  }
  const ch = c.char_id ? chars()[c.char_id] : null;
  const sts = arr(c.statuses);
  const cds = arr(c.cooldowns);
  return `<section class="box pinbox side-${side}"><h3 class="stitle"><span>Token details</span><button type="button" class="linkbtn" data-act="unpin" data-k="unpin">Unpin</button></h3>
    <div class="pinhead"><span class="osh side-${side}">${esc(str(c.short).slice(0, 2))}</span><div><b>${esc(str(c.name) || c.cid)}</b>
      <div class="muted sm">${esc(cap(side))} · ${esc(cap(str(c.role) || 'other'))}${c.kind === 'pc' ? ' · PC' : ''}${c.down ? ' · DOWN' : ''}</div></div></div>
    <dl class="kv compact"><div><dt>Position</dt><dd>${p ? `<span class="coordtag">${p[0]},${p[1]}</span>` : 'unknown'}</dd></div>
      <div><dt>Facing</dt><dd>${esc(str(c.facing) || '?')}</dd></div>
      <div><dt>${isNum(c.hp) ? 'HP' : 'Condition'}</dt><dd>${isNum(c.hp) ? hpBar(c.hp, c.max_hp, 'slim') : `<span class="cond ${CONDITION_CLASS[c.condition] || ''}">${esc(str(c.condition) || 'unknown')}</span>`}</dd></div>
      ${rad ? `<div><dt>Radius</dt><dd>${esc(rad)}</dd></div>` : ''}
      ${c.kind === 'pc' && c.turn ? `<div><dt>This turn</dt><dd>${[c.turn.moved ? 'moved ' + c.turn.moved : '', c.turn.acted ? 'acted' : '', c.turn.attacked ? 'attacked' : ''].filter(Boolean).join(', ') || 'nothing yet'}</dd></div>` : ''}</dl>
    ${ch && cds.length ? `<ul class="miniarts">${arr(ch.arts).map((a, i) => `<li><span class="an">${esc(str(obj(a).name) || 'Art ' + (i + 1))}</span>${cdPill(cds[i], i in cds)}</li>`).join('')}</ul>` : ''}
    ${sts.length ? `<ul class="stlist">${sts.map(st => { const i = statusInfo(st); const rem = remainingText(st); return `<li class="k-${esc(i.kind)}">${statusSVG(st, 18)}<div><b>${esc(i.name)}</b>${rem ? `<span class="muted"> · ${esc(rem)}</span>` : ''}${i.desc ? `<div class="sm muted">${esc(i.desc)}</div>` : ''}</div></li>`; }).join('')}</ul>` : '<p class="muted sm">No active statuses.</p>'}
    ${isGM() && c.card ? `<p class="gmnote sm">GM card: ${esc(JSON.stringify(c.card).slice(0, 220))}</p>` : ''}
  </section>`;
}
function specialHTML(cb) {
  const sp = obj(cb.special), chain = clamp(num(sp.chain_level, 0), 0, 3);
  const next = chain >= 3 ? 1 : chain + 1;
  const teams = Object.values(obj(S.teams));
  const pts = obj(sp.points);
  const keys = Object.keys(pts);
  return `<section class="box special"><h3 class="stitle"><span>Special gauge</span></h3>
    <div class="chain" role="img" aria-label="Last special level ${chain}. Next special: level ${next}">
      ${[1, 2, 3].map(l => `<span class="clv ${l <= chain ? 'done' : ''} ${l === next ? 'next' : ''}"><i>${l}</i><small>Lv ${l} · ${l * 6}</small></span>`).join('<span class="clink"></span>')}
    </div>
    <p class="sm muted">Chain level <b>${chain}</b> — next special: <b class="nextlv">level ${next}</b> (${next * 6} points).</p>
    ${(keys.length ? keys : []).map(k => {
      const t = obj(obj(S.teams)[k]);
      const nm = t.bearer ? charName(t.bearer) : title(k);
      return `<div class="teamdice"><span class="tdn">${esc(nm)}’s team</span>${specialDice(pts[k])}</div>`;
    }).join('') || (teams.length ? '<p class="muted sm">No special points yet.</p>' : '')}
  </section>`;
}
function logHTML(cb) {
  const lg = arr(cb.log).slice(-14);
  return `<section class="box clog"><h3 class="stitle"><span>Combat log</span><span class="muted sm">latest ${lg.length}</span></h3>
    <ol class="log" data-scroll="clog" data-stick="1">${lg.length ? lg.map(l => `<li><span class="lt">T${esc(str(obj(l).turn))}</span><span>${esc(str(obj(l).text) || str(l))}</span></li>`).join('') : '<li class="muted">Nothing yet.</li>'}</ol></section>`;
}
function pendingHTML(cb) {
  const p = cb.pending; if (!p || typeof p !== 'object') return '';
  const labels = { special_split: 'A special attack’s damage must be split among targets', life_force: 'A Blade may share life force to keep their Bearer standing' };
  return `<div class="pending" role="status"><b>Waiting on the Architect:</b> ${esc(labels[p.type] || title(p.type) || 'a decision')}</div>`;
}
function terrainLegend(cb) {
  const cells = obj(obj(cb.map).cells);
  const types = [...new Set(Object.values(cells).map(c => str(obj(c).type)).filter(Boolean))];
  if (!types.length) return '';
  const names = { wall: 'Wall', obstacle: 'Obstacle', hazard: 'Hazard', difficult: 'Difficult', feature: 'Feature', cover: 'Cover' };
  return `<div class="legend" aria-label="Terrain legend">${types.map(t => `<span class="lg"><i class="sw t-${esc(t)}"></i>${esc(names[t] || title(t))}</span>`).join('')}</div>`;
}
function combatHTML(cb) {
  const m = obj(cb.map);
  const hasRad = Object.values(cmbs()).some(b => b && b.role === 'blade' && b.bearer_cid);
  return `<section class="panel combat">
    <div class="combathead"><div><h2 class="ptitle">${esc(str(cb.name) || 'Combat')}</h2>
      <p class="muted sm">${esc(str(m.name))}${str(m.name) ? ' · ' : ''}Turn ${num(cb.turns_taken, 0) + 1}</p></div>
      <div class="mapctl" role="group" aria-label="Map controls">
        ${hasRad ? `<label class="tgl"><input type="checkbox" data-act="radii" data-k="radii" ${ui.showRadii ? 'checked' : ''}><span>Blade radii</span></label>` : ''}
        <span class="zoomctl"><button type="button" class="ibtn" data-act="zoom" data-d="-1" data-k="zoomout" aria-label="Zoom out" ${ui.zoom <= 1 ? 'disabled' : ''}>−</button><button type="button" class="ibtn" data-act="zoom" data-d="0" data-k="zoomfit" aria-label="Fit map" title="Fit">${ui.zoom === 1 ? 'Fit' : Math.round(ui.zoom * 100) + '%'}</button><button type="button" class="ibtn" data-act="zoom" data-d="1" data-k="zoomin" aria-label="Zoom in" ${ui.zoom >= 2.5 ? 'disabled' : ''}>+</button></span>
        <output id="coord" class="coordout" aria-live="off"><span class="muted">hover a square</span></output></div></div>
    ${orderStrip(cb)}
    ${pendingHTML(cb)}
    <div class="mapwrap ${ui.showRadii ? '' : 'noradii'}" id="mapwrap" data-scroll="map">${mapSVG(cb)}</div>
    ${terrainLegend(cb)}
    <div class="hudgrid">${pinnedHTML(cb)}${specialHTML(cb)}</div>
    ${logHTML(cb)}
  </section>`;
}
function centerHTML() {
  if (!S || S.has_campaign === false || S.ok === false) return emptyCenter();
  const cb = combat();
  return sceneHTML() + (cb ? combatHTML(cb) : `<section class="panel noCombat"><h2 class="ptitle">Battle map</h2><p class="muted">No battle in progress. The map appears here when a fight begins.</p></section>`);
}

/* ------------------------------------------------------------- SIDE COLUMN */
function rollList() { return arr(S && S.rolls).filter(r => r && typeof r === 'object'); }
function rollHTML(r, isLatest) {
  const tier = TIERS[r.tier];
  const dice = arr(r.dice).filter(isNum);
  const attrs = (Array.isArray(r.attribute) ? r.attribute : r.attribute ? [r.attribute] : []).map(str).filter(Boolean);
  const succ = isNum(r.successes) ? r.successes : dice.filter(d => d >= 5).length;
  const mods = arr(r.mods).filter(m => m && typeof m === 'object');
  const ch = chars()[r.char_id];
  const attrChip = k => `<span class="chip attrchip" style="--c:var(--idea-${ATTR_IDEA[k] || 'truth'})">${ideaMark(ATTR_IDEA[k] || 'truth', 10)}${esc(cap(k))}${ch && isNum(obj(ch.attributes)[k]) ? ` <b>${ch.attributes[k]}</b>` : ''}</span>`;
  const hasNet = isNum(r.net) || isNum(r.check);
  return `<div class="roll ${isLatest ? 'latest' : 'picked'}" data-roll="${esc(str(r.id))}">
    <div class="rollhead"><span class="rwho">${esc(str(r.who) || 'Unknown')}</span><span class="rkind k-${esc(str(r.kind) || 'raw')}">${esc(KIND_LABEL[r.kind] || title(r.kind) || 'Roll')}</span></div>
    ${str(r.label) ? `<p class="rlabel">${esc(r.label)}</p>` : ''}
    <div class="dicerow" role="img" aria-label="Dice: ${dice.join(', ') || 'none'}; ${succ} success${succ === 1 ? '' : 'es'}">${dice.length ? dice.map((d, i) => `<span class="dwrap" style="--i:${i}">${dieSVG(d)}</span>`).join('') : '<span class="muted sm">no dice recorded</span>'}</div>
    <div class="rmath">${isNum(r.pool) ? `<span class="pool">Pool <b>${r.pool}</b>${r.pool_floor ? '<em title="Pool below 1 rolls a single die; failure also affects another character"> floor</em>' : ''}</span>` : ''}${attrs.map(attrChip).join('')}${mods.map(m => `<span class="chip mod ${num(m.value) < 0 ? 'neg' : 'pos'}">${esc(str(m.label) || 'mod')} <b>${isNum(m.value) ? signed(m.value) : ''}</b></span>`).join('')}</div>
    <div class="rres"><span class="succ"><b>${succ}</b> success${succ === 1 ? '' : 'es'}</span>${hasNet ? `<span class="net">${isNum(r.check) ? `vs check <b>${r.check}</b>` : ''}${isNum(r.net) ? ` → net <b>${signed(r.net)}</b>` : ''}</span>` : ''}${isNum(r.damage) ? `<span class="dmg ${r.damage > 0 ? 'hurt' : ''}"><b>${r.damage}</b> damage</span>` : ''}</div>
    ${tier ? `<div class="stamp ${tier.cls}" role="status"><span class="sl">${tier.label}</span><span class="ss">${tier.sub}</span></div>` : (str(r.tier) ? `<div class="stamp unk"><span class="sl">${esc(title(r.tier).toUpperCase())}</span></div>` : '')}
    ${r.auto ? `<p class="auto">✦ ${esc(AUTO[r.auto] || title(r.auto))}</p>` : ''}
    ${str(r.note) ? `<p class="rnote">${esc(r.note)}</p>` : ''}
  </div>`;
}
function diceTray() {
  const rolls = rollList();
  if (!rolls.length) {
    return `<section class="panel tray"><h2 class="ptitle">Dice tray</h2><div class="ghostdice">${[3, 5, 6, 2].map(v => dieSVG(v, { hit: false, cls: 'ghost' })).join('')}</div><p class="muted">No rolls yet. When Claude rolls for the table, the dice land here.</p></section>`;
  }
  const latest = rolls[rolls.length - 1];
  const sel = ui.rollSel && rolls.find(r => r.id === ui.rollSel);
  const shown = sel || latest;
  const hist = rolls.slice(0, -1).reverse();
  return `<section class="panel tray"><h2 class="ptitle">Dice tray${sel ? ' <button type="button" class="linkbtn" data-act="roll" data-id="" data-k="rollback">Back to latest</button>' : ''}</h2>
    ${rollHTML(shown, !sel)}
    ${hist.length ? `<h3 class="stitle"><span>Earlier rolls</span><span class="muted sm">${hist.length}</span></h3><ol class="hist" data-scroll="hist">${hist.map(r => {
      const dice = arr(r.dice).filter(isNum), t = TIERS[r.tier];
      return `<li><button type="button" class="hrow ${r === shown ? 'sel' : ''}" data-act="roll" data-id="${esc(str(r.id))}" data-k="roll:${esc(str(r.id))}">
        <span class="tdot ${t ? t.cls : ''}" title="${esc(t ? t.label : '')}"></span>
        <span class="hw"><b>${esc(str(r.who) || '?')}</b> <span class="muted">${esc(str(r.label))}</span></span>
        <span class="hd">${dice.slice(0, 12).map(d => dieSVG(d, { cls: 'tiny' })).join('')}</span>
        <span class="hs">${isNum(r.successes) ? r.successes : dice.filter(d => d >= 5).length}★</span><span class="ht">${esc(t ? t.label : '')}</span></button></li>`;
    }).join('')}</ol>` : ''}
  </section>`;
}

/* tabs */
const TABS = [['journal', 'Journal'], ['codex', 'Codex'], ['sessions', 'Sessions']];
function tabsHTML() {
  return `<section class="panel tabs"><div class="tablist" role="tablist" aria-label="Records">${TABS.map(([k, l]) => `<button type="button" role="tab" id="tab-${k}" aria-selected="${ui.tab === k}" aria-controls="tabpanel" tabindex="${ui.tab === k ? 0 : -1}" data-act="tab" data-tab="${k}" data-k="tab:${k}">${l}</button>`).join('')}</div>
    <div class="tabpanel" id="tabpanel" role="tabpanel" aria-labelledby="tab-${ui.tab}" data-scroll="tab:${ui.tab}">${ui.tab === 'codex' ? codexHTML() : ui.tab === 'sessions' ? sessionsHTML() : journalHTML()}</div></section>`;
}
const KIND_ICON = { event: '◆', note: '✎', recap: '↺', system: '⚙', bp: '★' };
function sessionLabel(n) {
  if (!isNum(n) || n <= 0) return 'Prologue / unsorted';
  const s = arr(S.sessions).find(x => x && x.n === n);
  const arc = s && isNum(s.arc) ? arr(S.arcs).find(a => a && a.n === s.arc) : null;
  return `Session ${n}${arc ? ` · Arc ${arc.n}${str(arc.title) ? ': ' + arc.title : ''}` : ''}`;
}
function journalHTML() {
  const j = arr(S.journal).filter(e => e && typeof e === 'object');
  if (!j.length) return '<p class="muted">The journal is empty. Events and recaps will be written here as you play.</p>';
  const groups = new Map();
  j.forEach((e, idx) => { const n = isNum(e.session) ? e.session : 0; if (!groups.has(n)) groups.set(n, []); groups.get(n).push({ e, idx }); });
  return [...groups.keys()].sort((a, b) => b - a).map(n => `<div class="jgroup"><h3 class="jsess">${esc(sessionLabel(n))}</h3><ol class="jlist">${groups.get(n).slice().reverse().map(({ e }) => {
    const kind = str(e.kind) || 'event';
    return `<li class="je k-${esc(kind)}"><span class="jk" title="${esc(title(kind))}" aria-hidden="true">${KIND_ICON[kind] || '◆'}</span><div><div class="jmeta"><span class="jkind">${esc(title(kind))}</span>${e.ts ? `<time>${fmtTime(e.ts)}</time>` : ''}${e.gm_only ? chip('GM only', { cls: 'gm' }) : ''}</div>
      <p>${esc(str(e.text))}</p>${arr(e.tags).length ? `<div class="tags jt">${arr(e.tags).map(t => `<span class="tag cat-other">${esc(str(t))}</span>`).join('')}</div>` : ''}</div></li>`;
  }).join('')}</ol></div>`).join('');
}
const KIND_ORDER = ['npc', 'location', 'titan', 'faction', 'thread', 'item', 'secret', 'other'];
const KIND_TITLE = { npc: 'NPCs', location: 'Locations', titan: 'Titans', faction: 'Factions', thread: 'Threads', item: 'Items', secret: 'Secrets (GM)', other: 'Other' };
function statusClass(s) {
  s = str(s).toLowerCase();
  if (/resolv|done|complete|closed|ally|friend|safe|carried/.test(s)) return 'ok';
  if (/hostile|enemy|danger|dying|dead|lost|hidden/.test(s)) return 'bad';
  if (/open|active|progress|dim|current|unreached|neutral/.test(s)) return 'live';
  return '';
}
function codexHTML() {
  const ents = Object.values(obj(S.entities)).filter(e => e && typeof e === 'object');
  if (!ents.length) return '<p class="muted">The codex is empty. NPCs, places, Titans, factions and story threads will be catalogued here.</p>';
  const groups = {};
  ents.forEach(e => { const k = KIND_ORDER.includes(e.kind) ? e.kind : 'other'; (groups[k] = groups[k] || []).push(e); });
  return KIND_ORDER.filter(k => groups[k]).map(k => `<div class="cgroup"><h3 class="jsess">${KIND_TITLE[k]} <span class="count">${groups[k].length}</span></h3><ul class="clist">${groups[k].map(e => {
    const key = 'ent:' + str(e.id || e.name), open = !!ui.open[key];
    const body = str(e.details) || (isGM() && str(e.gm_notes)) || arr(e.tags).length;
    return `<li class="ent ${open ? 'open' : ''}"><button type="button" class="enthead" data-act="tog" data-key="${esc(key)}" data-k="${esc(key)}" aria-expanded="${open}" ${body ? '' : 'aria-disabled="true"'}>
      <span class="entn">${esc(str(e.name) || 'Unnamed')}</span>${str(e.status) ? `<span class="status ${statusClass(e.status)}">${esc(e.status)}</span>` : ''}${e.gm_only ? chip('GM only', { cls: 'gm' }) : ''}</button>
      ${str(e.summary) ? `<p class="entsum">${esc(e.summary)}</p>` : ''}
      ${open ? `<div class="entdet">${str(e.details) ? `<p>${esc(e.details)}</p>` : ''}${isGM() && str(e.gm_notes) ? `<p class="gmnote"><span class="lbl">GM notes</span> ${esc(e.gm_notes)}</p>` : ''}${arr(e.tags).length ? `<div class="tags">${arr(e.tags).map(t => `<span class="tag cat-other">${esc(str(t))}</span>`).join('')}</div>` : ''}${isNum(e.updated_session) ? `<p class="muted sm">Updated session ${e.updated_session}</p>` : ''}</div>` : ''}</li>`;
  }).join('')}</ul></div>`).join('');
}
function awardText(a) {
  if (typeof a === 'string') return esc(a);
  a = obj(a);
  const who = charName(str(a.char_id) || str(a.char) || str(a.who)) ;
  const amt = isNum(a.amount) ? a.amount : isNum(a.bp) ? a.bp : isNum(a.points) ? a.points : null;
  const has = str(a.char_id) || str(a.char) || str(a.who);
  return `${has ? `<b>${esc(who)}</b> ` : ''}${amt !== null ? `+${amt} BP` : ''}${str(a.reason) ? ` <span class="muted">— ${esc(a.reason)}</span>` : ''}` || esc(JSON.stringify(a));
}
function sessionsHTML() {
  const ss = arr(S.sessions).filter(s => s && typeof s === 'object'), arcs = arr(S.arcs).filter(a => a && typeof a === 'object');
  if (!ss.length && !arcs.length) return '<p class="muted">No sessions recorded yet.</p>';
  let h = '';
  if (arcs.length) h += `<div class="sgroup"><h3 class="jsess">Arcs</h3><ul class="arclist">${arcs.slice().reverse().map(a => `<li><b>Arc ${esc(str(a.n))}${str(a.title) ? ': ' + esc(a.title) : ''}</b><span class="muted sm">${isNum(a.first_session) ? `Sessions ${a.first_session}–${isNum(a.last_session) ? a.last_session : 'now'}` : ''}</span>${str(a.summary) ? `<p>${esc(a.summary)}</p>` : ''}</li>`).join('')}</ul></div>`;
  h += `<div class="sgroup"><h3 class="jsess">Sessions</h3><ul class="seslist">${ss.slice().sort((a, b) => num(b.n) - num(a.n)).map(s => `<li class="ses"><div class="seshead"><b>Session ${esc(str(s.n))}</b>${isNum(s.arc) ? `<span class="chip">Arc ${s.arc}</span>` : ''}${!s.ended && s.started ? '<span class="chip live">in progress</span>' : ''}</div>
    <div class="muted sm">${s.started ? fmtTime(s.started) : ''}${s.ended ? ' → ' + fmtTime(s.ended) : ''}</div>
    ${str(s.summary) ? `<p>${esc(s.summary)}</p>` : '<p class="muted sm">No recap yet.</p>'}
    ${arr(s.bp_awards).length ? `<div class="awards"><span class="lbl">Bond point awards</span><ul>${arr(s.bp_awards).map(a => `<li>${awardText(a)}</li>`).join('')}</ul></div>` : ''}</li>`).join('')}</ul></div>`;
  return h;
}
function sideHTML() {
  if (!S || S.has_campaign === false || S.ok === false) {
    return `<section class="panel tray"><h2 class="ptitle">Dice tray</h2><div class="ghostdice">${[3, 5, 6, 2].map(v => dieSVG(v, { hit: false, cls: 'ghost' })).join('')}</div><p class="muted">Nothing rolled yet.</p></section>`;
  }
  return diceTray() + tabsHTML();
}

/* ------------------------------------------------------------- render engine */
const regions = { party: partyHTML, center: centerHTML, side: sideHTML };
function captureScroll() {
  const m = {};
  $$('[data-scroll]').forEach(el => {
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 6;
    m[el.dataset.scroll] = { top: el.scrollTop, left: el.scrollLeft, atBottom };
  });
  m.__win = window.scrollY;
  return m;
}
function restoreScroll(m) {
  $$('[data-scroll]').forEach(el => {
    const s = m[el.dataset.scroll]; if (!s) return;
    if (el.dataset.stick && s.atBottom) el.scrollTop = el.scrollHeight; else { el.scrollTop = s.top; el.scrollLeft = s.left; }
  });
  if (Math.abs(window.scrollY - m.__win) > 1) window.scrollTo(0, m.__win);
}
function renderAll() {
  const sc = captureScroll();
  const ak = document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.k : null;
  const akCid = document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.cid : null;
  try { renderHeader(); } catch (e) { console.error('header', e); }
  document.body.classList.toggle('in-combat', !!(S && S.has_campaign !== false && combat()));
  const changed = new Set();
  // roll tumble bookkeeping
  const rolls = S ? rollList() : [];
  const loaded = !!S;
  const latestId = rolls.length ? str(rolls[rolls.length - 1].id) : null;
  if (loaded && ui.seenRollId !== null && latestId && latestId !== ui.seenRollId) { ui.tumbleId = latestId; ui.rollSel = null; }
  if (loaded) ui.seenRollId = latestId || '';
  // pinned token that vanished
  if (S && ui.pinned && !cmbs()[ui.pinned]) ui.pinned = null;
  for (const [id, fn] of Object.entries(regions)) {
    let html;
    try { html = fn(); } catch (e) { console.error('render ' + id, e); html = `<section class="panel err"><h2 class="ptitle">Display problem</h2><p class="muted">This section could not be drawn from the current data (${esc(e && e.message)}).</p></section>`; }
    const el = document.getElementById(id);
    if (el._html !== html) { el.innerHTML = html; el._html = html; changed.add(id); }
  }
  restoreScroll(sc);
  if (ak) { const t = $$('[data-k]').find(n => n.dataset.k === ak); if (t && t !== document.activeElement) t.focus({ preventScroll: true }); }
  else if (akCid) { const t = $$('.tok').find(n => n.dataset.cid === akCid); if (t && t !== document.activeElement) t.focus({ preventScroll: true }); }
  if (changed.has('side') && ui.tumbleId) {
    const wrap = $('.roll.latest');
    if (wrap && wrap.dataset.roll === ui.tumbleId && !matchMedia('(prefers-reduced-motion: reduce)').matches) wrap.classList.add('tumble');
    ui.tumbleId = null;
  }
  applyHover();
}

/* ----------------------------------------------------------- fetch + SSE */
let fetching = false, again = false;
async function fetchState(force) {
  if (fetching) { again = true; return; }
  fetching = true;
  try {
    const p = new URLSearchParams();
    if (ui.spoilers) p.set('view', 'gm');
    const here = new URLSearchParams(location.search);
    for (const k of ['combat', 'empty', 'partial']) if (here.has(k)) p.set(k, here.get(k)); // dev-only passthrough for the mock server
    const r = await fetch('/api/state' + (p.toString() ? '?' + p : ''), { cache: 'no-store' });
    const text = await r.text();
    let data;
    try { data = JSON.parse(text); } catch (e) { throw new Error('bad response (HTTP ' + r.status + ')'); }
    if (!r.ok && !(data && data.error)) throw new Error('HTTP ' + r.status);
    loadErr = null;
    if (force || text !== lastText) { lastText = text; S = data; renderAll(); }
    if (conn.state === 'offline' || conn.state === 'retry') { /* SSE decides */ }
  } catch (e) {
    loadErr = String(e && e.message || e);
    if (!S) { lastText = ''; renderAll(); }
    if (conn.state === 'live') setConn('retry');
  } finally {
    fetching = false;
    if (again) { again = false; fetchState(); }
  }
}
let es = null, backoff = 1000, retryTimer = null;
function connect() {
  clearTimeout(retryTimer);
  if (typeof EventSource === 'undefined' || new URLSearchParams(location.search).has('nosse')) { setConn('retry'); return; } // ?nosse: dev/screenshot aid, poll only
  setConn(conn.fails > 1 ? 'offline' : conn.fails ? 'retry' : 'connecting');
  try { es = new EventSource('/api/events'); } catch (e) { fail(); return; }
  es.addEventListener('open', () => { conn.fails = 0; backoff = 1000; setConn('live'); fetchState(); });
  es.addEventListener('state', () => fetchState());
  es.addEventListener('error', () => { if (es) { es.close(); es = null; } fail(); });
}
function fail() {
  conn.fails++;
  setConn(conn.fails > 2 ? 'offline' : 'retry');
  retryTimer = setTimeout(connect, backoff);
  backoff = Math.min(backoff * 2, 15000);
}
setInterval(() => { if (conn.state !== 'live') fetchState(); }, 5000); // polling fallback while SSE is down
document.addEventListener('visibilitychange', () => { if (!document.hidden) fetchState(); });

/* ---------------------------------------------------------------- events */
function rerender() { renderAll(); }
document.addEventListener('click', ev => {
  const t = ev.target.closest('[data-act], .tok, .oc');
  if (!t) return;
  const act = t.dataset.act;
  if (!act) { // token or order chip
    const cid = t.dataset.cid; if (!cid) return;
    ui.pinned = ui.pinned === cid && t.classList.contains('tok') ? null : cid; rerender(); return;
  }
  if (act === 'tog') { const k = t.dataset.key; ui.open[k] = !ui.open[k]; rerender(); }
  else if (act === 'tab') { ui.tab = t.dataset.tab; rerender(); }
  else if (act === 'roll') { ui.rollSel = t.dataset.id || null; rerender(); }
  else if (act === 'scene') { const cur = ui.sceneOpen === null ? !combat() : ui.sceneOpen; ui.sceneOpen = !cur; rerender(); }
  else if (act === 'unpin') { ui.pinned = null; rerender(); }
  else if (act === 'zoom') {
    const d = +t.dataset.d;
    ui.zoom = d === 0 ? 1 : clamp(Math.round((ui.zoom + d * 0.5) * 100) / 100, 1, 2.5);
    rerender();
  }
});
document.addEventListener('change', ev => {
  const t = ev.target;
  if (t && t.dataset && t.dataset.act === 'radii') { ui.showRadii = !!t.checked; rerender(); }
});
document.addEventListener('keydown', ev => {
  const t = ev.target;
  if ((ev.key === 'Enter' || ev.key === ' ') && t.classList && t.classList.contains('tok')) {
    ev.preventDefault(); ui.pinned = ui.pinned === t.dataset.cid ? null : t.dataset.cid; rerender();
  } else if (t.getAttribute && t.getAttribute('role') === 'tab' && (ev.key === 'ArrowRight' || ev.key === 'ArrowLeft')) {
    const i = TABS.findIndex(x => x[0] === ui.tab), n = (i + (ev.key === 'ArrowRight' ? 1 : TABS.length - 1)) % TABS.length;
    ui.tab = TABS[n][0]; rerender();
  } else if (ev.key === 'Escape' && ui.pinned) { ui.pinned = null; rerender(); }
});
$('#spoilerBtn').addEventListener('click', () => {
  ui.spoilers = !ui.spoilers; renderHeader(); lastText = ''; fetchState(true);
});

/* hover: coordinates + token tooltips */
const tip = $('#tip');
function svgCell(ev) {
  const svg = $('#mapsvg'); if (!svg) return null;
  const ctm = svg.getScreenCTM(); if (!ctm) return null;
  const pt = svg.createSVGPoint(); pt.x = ev.clientX; pt.y = ev.clientY;
  const p = pt.matrixTransform(ctm.inverse());
  const W = +svg.dataset.w, H = +svg.dataset.h;
  const x = Math.floor((p.x - PAD) / CELL), y = Math.floor((p.y - PAD) / CELL);
  return x >= 0 && y >= 0 && x < W && y < H ? [x, y] : null;
}
function applyHover() {
  const out = $('#coord'), rect = $('#hovercell');
  if (!out) return;
  if (!ui.hover) { out.innerHTML = '<span class="muted">hover a square</span>'; if (rect) rect.setAttribute('visibility', 'hidden'); return; }
  const [x, y] = ui.hover;
  const info = obj(obj(obj(combat() && combat().map).cells)[x + ',' + y]);
  const occ = Object.values(cmbs()).find(c => { const p = posOf(c); return p && p[0] === x && p[1] === y; });
  out.innerHTML = `<b class="xy">${x},${y}</b>${occ ? `<span> ${esc(str(occ.name))}</span>` : ''}${str(info.type) ? `<span class="muted"> ${esc(str(info.label) || title(info.type))} (${esc(info.type)})</span>` : ''}`;
  if (rect) { rect.setAttribute('x', PAD + x * CELL); rect.setAttribute('y', PAD + y * CELL); rect.setAttribute('visibility', 'visible'); }
}
function tipHTML(c) {
  const p = posOf(c), sts = arr(c.statuses);
  return `<b class="tn side-${sideOf(c)}">${esc(str(c.name) || c.cid)}</b> <span class="muted">${esc(cap(sideOf(c)))}${c.role && c.role !== 'other' ? ' ' + esc(c.role) : ''}</span>
    <div>${p ? `at <b>${p[0]},${p[1]}</b>` : ''}${c.facing ? ` · facing <b>${esc(c.facing)}</b>` : ''}</div>
    <div>${isNum(c.hp) ? `HP <b>${c.hp}/${c.max_hp}</b>` : str(c.condition) ? `Condition: <b>${esc(c.condition)}</b>` : ''}${c.down ? ' · <b>DOWN</b>' : ''}</div>
    ${sts.length ? `<ul>${sts.map(st => { const i = statusInfo(st), r = remainingText(st); return `<li>${statusSVG(st, 13)} ${esc(i.name)}${r ? ` <span class="muted">(${esc(r)})</span>` : ''}</li>`; }).join('')}</ul>` : '<div class="muted">no statuses</div>'}`;
}
document.addEventListener('mousemove', ev => {
  const svg = ev.target.closest && ev.target.closest('#mapsvg');
  const tok = ev.target.closest && ev.target.closest('.tok, .oc');
  if (svg) { const c = svgCell(ev), same = (c && ui.hover && c[0] === ui.hover[0] && c[1] === ui.hover[1]) || (!c && !ui.hover); if (!same) { ui.hover = c; applyHover(); } }
  else if (ui.hover) { ui.hover = null; applyHover(); }
  const c = tok && cmbs()[tok.dataset.cid];
  if (c) {
    tip.innerHTML = tipHTML(c); tip.hidden = false;
    const w = tip.offsetWidth, h = tip.offsetHeight;
    let x = ev.clientX + 16, y = ev.clientY + 14;
    if (x + w > innerWidth - 8) x = ev.clientX - w - 16;
    if (y + h > innerHeight - 8) y = innerHeight - h - 8;
    tip.style.left = Math.max(4, x) + 'px'; tip.style.top = Math.max(4, y) + 'px';
  } else tip.hidden = true;
});
document.addEventListener('focusin', ev => {
  const t = ev.target; const c = t.classList && t.classList.contains('tok') && cmbs()[t.dataset.cid];
  if (c) {
    tip.innerHTML = tipHTML(c); tip.hidden = false;
    const r = t.getBoundingClientRect();
    tip.style.left = Math.min(innerWidth - tip.offsetWidth - 8, r.right + 6) + 'px'; tip.style.top = Math.max(4, r.top) + 'px';
  }
});
document.addEventListener('focusout', () => { tip.hidden = true; });
document.addEventListener('mouseleave', () => { tip.hidden = true; if (ui.hover) { ui.hover = null; applyHover(); } });

/* ------------------------------------------------------------------ start */
(() => { // dev/screenshot aids: ?open=sera,tamsin &tab=codex &pin=c_g1 &zoom=1.5 &radii=0
  const q = new URLSearchParams(location.search);
  (q.get('open') || '').split(',').filter(Boolean).forEach(k => { ui.open['sheet:' + k] = true; });
  if (q.get('tab')) ui.tab = q.get('tab');
  if (q.get('pin')) ui.pinned = q.get('pin');
  if (q.get('zoom')) ui.zoom = clamp(+q.get('zoom') || 1, 1, 2.5);
  if (q.get('radii') === '0') ui.showRadii = false;
  if (q.get('scene') === '1') ui.sceneOpen = true;
})();
renderAll();
connect();
fetchState();
})();
