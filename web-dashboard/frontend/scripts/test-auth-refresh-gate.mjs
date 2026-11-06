import assert from "node:assert/strict";
import test from "node:test";

import {
  createRefreshGate,
  isTerminalRefreshStatus,
  parseRetryAfterMs,
  refreshBackoffMs,
  RefreshFailure,
} from "../src/lib/auth-refresh-gate.ts";

function harness({ hint = true } = {}) {
  const state = { hint, clears: 0, now: 1_000_000, calls: 0 };
  const gate = createRefreshGate({
    hasSessionHint: () => state.hint,
    clearSession: () => {
      state.clears += 1;
      state.hint = false;
    },
    now: () => state.now,
    random: () => 0.5,
    baseBackoffMs: 1_000,
    maxBackoffMs: 60_000,
  });
  return { gate, state };
}

test("anonymous visitors never trigger a refresh request", async () => {
  const { gate, state } = harness({ hint: false });
  const result = await gate.run(async () => {
    state.calls += 1;
    return "session";
  });
  assert.equal(result, null);
  assert.equal(state.calls, 0);
  assert.equal(state.clears, 0);
});

test("concurrent 401s share a single in-flight refresh", async () => {
  const { gate, state } = harness();
  let release;
  const perform = () => {
    state.calls += 1;
    return new Promise((resolve) => {
      release = resolve;
    });
  };
  const pending = [gate.run(perform), gate.run(perform), gate.run(perform)];
  assert.equal(state.calls, 1);
  release("session");
  assert.deepEqual(await Promise.all(pending), ["session", "session", "session"]);
  assert.equal(await gate.run(async () => "again"), "again");
});

for (const status of [401, 429]) {
  test(`refresh ${status} clears the session once and is never retried`, async () => {
    const { gate, state } = harness();
    const perform = async () => {
      state.calls += 1;
      throw new RefreshFailure(status);
    };
    const results = await Promise.all([gate.run(perform), gate.run(perform)]);
    assert.deepEqual(results, [null, null]);
    assert.equal(state.calls, 1);
    assert.equal(state.clears, 1);
    // Subsequent 401s (e.g. polling) must not hit /auth/refresh again.
    for (let index = 0; index < 5; index += 1) {
      state.now += 10;
      assert.equal(await gate.run(perform), null);
    }
    assert.equal(state.calls, 1);
    assert.equal(state.clears, 1);
    assert.ok(gate.blockedUntil() > state.now);
  });
}

test("network/CORS failures resolve quietly and back off without clearing", async () => {
  const { gate, state } = harness();
  const perform = async () => {
    state.calls += 1;
    throw new TypeError("Load failed");
  };
  assert.equal(await gate.run(perform), null);
  assert.equal(state.clears, 0);
  assert.equal(await gate.run(perform), null);
  assert.equal(state.calls, 1, "second attempt must wait for the backoff");
  state.now = gate.blockedUntil();
  assert.equal(await gate.run(perform), null);
  assert.equal(state.calls, 2);
  const firstWindow = 750; // base 1000, jitter 0.5 -> 500 + 250
  assert.equal(gate.blockedUntil() - state.now, firstWindow * 2);
});

test("synchronous throws from perform never escape the gate", async () => {
  const { gate } = harness();
  const result = await gate.run(() => {
    throw new Error("boom");
  });
  assert.equal(result, null);
});

test("reset lifts the backoff after a fresh sign-in", async () => {
  const { gate, state } = harness();
  await gate.run(async () => {
    throw new RefreshFailure(503);
  });
  assert.equal(await gate.run(async () => "blocked"), null);
  gate.reset();
  assert.equal(await gate.run(async () => "ok"), "ok");
  assert.equal(state.clears, 0);
});

test("backoff is exponential, capped, jittered and honours Retry-After", () => {
  assert.equal(refreshBackoffMs(1, 0, 1_000, 60_000), 500);
  assert.equal(refreshBackoffMs(1, 1, 1_000, 60_000), 1_000);
  assert.equal(refreshBackoffMs(3, 1, 1_000, 60_000), 4_000);
  assert.equal(refreshBackoffMs(30, 1, 1_000, 60_000), 60_000);
  assert.equal(refreshBackoffMs(1, 0, 1_000, 60_000, 90_000), 90_000);
  assert.equal(parseRetryAfterMs("12"), 12_000);
  assert.equal(parseRetryAfterMs(null), null);
  assert.equal(parseRetryAfterMs("not-a-date"), null);
  assert.equal(
    parseRetryAfterMs("Thu, 01 Jan 1970 00:00:10 GMT", 4_000),
    6_000,
  );
  assert.ok(isTerminalRefreshStatus(401));
  assert.ok(isTerminalRefreshStatus(429));
  assert.ok(!isTerminalRefreshStatus(503));
  assert.ok(!isTerminalRefreshStatus(null));
});
