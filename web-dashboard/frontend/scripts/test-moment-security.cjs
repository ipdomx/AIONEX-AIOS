'use strict';

// Run against the installed package, or an explicit isolated baseline package.
// Module traversal probes are intercepted before resolution: no outside file is read.
const assert = require('node:assert/strict');
const Module = require('node:module');
const path = require('node:path');
const entry = process.argv[2] ? path.resolve(process.argv[2]) : require.resolve('moment');
const packageRoot = path.dirname(entry);
const results = [];

function freshMoment() {
  for (const key of Object.keys(require.cache)) {
    if (key.startsWith(packageRoot + path.sep)) delete require.cache[key];
  }
  return require(entry);
}
function check(name, action) {
  try { action(); results.push({ name, passed: true }); }
  catch (error) { results.push({ name, passed: false, error: String(error.message) }); }
}
function traversalAttempt(call, asObject) {
  const moment = freshMoment();
  const fakeName = '../aionex_fixture_never_loaded';
  const crafted = asObject ? {
    match() { return true; },
    toString() { return fakeName; },
    toLowerCase() { return fakeName; },
  } : fakeName;
  const original = Module._load;
  const attempts = [];
  Module._load = function(request, parent, isMain) {
    if (parent && parent.filename === entry && typeof request === 'string' && request.startsWith('./locale/')) {
      const suffix = request.slice('./locale/'.length);
      if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(suffix)) {
        attempts.push(request);
        throw new Error('Synthetic module resolution intercepted before file access');
      }
    }
    return original.apply(this, arguments);
  };
  try { call(moment, crafted); }
  finally { Module._load = original; }
  assert.equal(attempts.length, 0, 'Unexpected unsafe locale-module resolution attempt');
  assert.equal(moment.locale(), 'en');
}

for (const [name, call] of [
  ['locale setter', (m, v) => m.locale(v)],
  ['locale getter', (m, v) => m.localeData(v)],
  ['locale fallback array', (m, v) => m.locale([v, 'en'])],
]) {
  check(name + ' rejects crafted non-string module path', () => traversalAttempt(call, true));
  check(name + ' rejects plain string module path', () => traversalAttempt(call, false));
}
for (const locale of ['en', 'ar', 'fr', 'de', 'es', 'id']) {
  check('locale loads and date round-trips: ' + locale, () => {
    const m = freshMoment();
    assert.equal(m.locale(locale), locale);
    const date = m.utc([2026, 8, 30]);
    const text = date.format('YYYY-MM-DD');
    const restored = m.utc(text, 'YYYY-MM-DD', locale, true);
    assert.equal(restored.isValid(), true);
    assert.equal(restored.valueOf(), date.valueOf());
  });
}
check('UTC leap-day date arithmetic', () => {
  const m = freshMoment();
  assert.equal(m.utc('2024-02-28').add(1, 'day').format('YYYY-MM-DD'), '2024-02-29');
  assert.equal(m.utc('2026-02-29', 'YYYY-MM-DD', true).isValid(), false);
});
check('offset is preserved when parsing zoned timestamps', () => {
  const m = freshMoment();
  const d = m.parseZone('2026-09-30T10:45:00+04:00');
  assert.equal(d.utcOffset(), 240);
  assert.equal(d.clone().utc().format('HH:mm'), '06:45');
});
check('valid lazy locale name normalization', () => {
  const m = freshMoment();
  assert.equal(m.locale('EN_gb'), 'en-gb');
  assert.equal(m.localeData().firstDayOfWeek(), 1);
});
check('unknown locale preserves current selection', () => {
  const m = freshMoment();
  m.locale('en');
  assert.equal(m.locale('aionex-not-a-locale'), 'en');
});
check('prototype names do not replace global locale', () => {
  const m = freshMoment();
  m.locale('en');
  m.locale('__proto__');
  assert.equal(m.locale(), 'en');
  assert.equal(m.utc([2026, 8, 30]).format('YYYY-MM-DD'), '2026-09-30');
});
const version = freshMoment().version;
const failures = results.filter(r => !r.passed);
console.log(JSON.stringify({ version, tests: results.length, passed: results.length - failures.length,
  failed: failures.length, results, external_file_resolution_blocked_by_harness: true,
  network_used: false, production_changed: false }, null, 2));
if (failures.length) process.exitCode = 1;
