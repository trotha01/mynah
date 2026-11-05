// Run: node tests/test_workers_sort.js   (pulls sortWorkers/stampMs out of companion/index.html)
process.env.TZ = 'Asia/Shanghai';
const fs = require('fs'), assert = require('assert');
const html = fs.readFileSync(__dirname + '/../companion/index.html', 'utf8');
const src = html.slice(html.indexOf('/*SORT-START*/'), html.indexOf('/*SORT-END*/'));
const { stampMs, sortWorkers } = new Function(src + '; return {stampMs, sortWorkers}')();

// stamps
assert.strictEqual(stampMs('[2026-11-05 Thu 21:12]'), Date.parse('2026-11-05T21:12:00+08:00'));
assert.strictEqual(stampMs('2026-11-05T13:12:00Z'), Date.parse('2026-11-05T21:12:00+08:00'));
assert.strictEqual(stampMs('2026-11-05T21:12:00+0800'), stampMs('[2026-11-05 Thu 21:12]'));
assert.ok(isNaN(stampMs('')) && isNaN(stampMs(undefined)) && isNaN(stampMs('garbage')));

const W = (n, t, l, u) => ({ n, t, l, u });
const items = [
  W('blocked-dead-new', 'blocked', 0, '[2026-11-05 Thu 20:00]'),
  W('running-old', 'running', 1, '[2026-11-05 Thu 09:00]'),
  W('blocked-live-mid', 'blocked', 1, '[2026-11-05 Thu 15:00]'),
  W('blocked-dead-nostamp', 'blocked', 0, ''),
  W('waiting-iso-newest', 'waiting', 1, '2026-11-05T14:30:00Z'),   // = 22:30 local, newest of all
  W('blocked-live-nostamp', 'blocked', 1, undefined),
  W('needs-you-mid2', 'needs_you', 1, '[2026-11-05 Thu 16:45]'),
  W('blocked-dead-old', 'blocked', 0, '[2026-11-04 Wed 23:59]'),
  W('blocked-live-newer', 'blocked', 1, '[2026-11-05 Thu 21:12]'),
];
const got = sortWorkers(items).map(x => x.n);
const want = ['waiting-iso-newest', 'blocked-live-newer', 'needs-you-mid2', 'blocked-live-mid', 'running-old', 'blocked-live-nostamp',
  'blocked-dead-new', 'blocked-dead-old', 'blocked-dead-nostamp'];
assert.deepStrictEqual(got, want);
// text comparison of the same data would put every "[..." stamp before the ISO one and mix days: prove the old order differs
const old = items.slice().sort((a, b) => (a.l === 0) - (b.l === 0) || ((b.u || '') > (a.u || '') ? 1 : (b.u || '') < (a.u || '') ? -1 : 0)).map(x => x.n);
assert.notDeepStrictEqual(old, want);
console.log('ok  workers sort\nnew:', got.join(' > '), '\nold:', old.join(' > '));
