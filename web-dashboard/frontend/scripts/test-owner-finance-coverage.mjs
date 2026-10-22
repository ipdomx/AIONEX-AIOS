import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

import {
  providerCreditMonitoringCopy,
  summarizeProjectAIProviderFinanceCoverage,
} from "../src/lib/provider-credit-coverage.ts";

const provider = (id, overrides = {}) => ({
  id,
  status: "connected",
  enabled: true,
  ...overrides,
});

const finance = (mode, overrides = {}) => ({
  provider_id: "p",
  provider_type: "openai",
  enabled: true,
  funding_mode: mode,
  funded_confirmed: true,
  balance_amount_private: mode !== "numeric",
  funded_usd: mode === "numeric" ? 10 : null,
  remaining_usd: mode === "numeric" ? 10 : null,
  consumed_since_topup_usd: 0,
  low_balance_threshold_usd: mode === "owner_attested" ? null : 2,
  critical_balance_threshold_usd: mode === "owner_attested" ? null : 1,
  billing_failure_alerts_enabled: true,
  state: "healthy",
  policy_version: 1,
  ...overrides,
});

test("missing policies never claim predictive monitoring or a zero balance", () => {
  const result = summarizeProjectAIProviderFinanceCoverage(
    [provider("a"), provider("b"), provider("c")], {},
  );
  assert.deepEqual(result, {
    connected: 3,
    predictive: 0,
    ownerAttestedOnly: 0,
    disabled: 0,
    noEarlyWarningThreshold: 0,
    unverified: 3,
  });
  const message = providerCreditMonitoringCopy(null);
  assert.match(message, /not verified/);
  assert.match(message, /do not assume alerts are active/);
  assert.doesNotMatch(message, /monitoring is configured/);
});

test("owner attestation is not mistaken for a numeric early-warning policy", () => {
  const result = summarizeProjectAIProviderFinanceCoverage(
    [provider("a")], { a: finance("owner_attested") },
  );
  assert.equal(result.ownerAttestedOnly, 1);
  assert.equal(result.predictive, 0);
  assert.match(providerCreditMonitoringCopy(finance("owner_attested")), /require real numeric/);
});

test("positive low threshold is required for pre-depletion coverage", () => {
  const result = summarizeProjectAIProviderFinanceCoverage(
    [provider("a"), provider("b"), provider("c")],
    {
      a: finance("numeric_private", { low_balance_threshold_usd: 3 }),
      b: finance("numeric", { low_balance_threshold_usd: 0 }),
      c: finance("numeric", { enabled: false }),
    },
  );
  assert.equal(result.predictive, 1);
  assert.equal(result.noEarlyWarningThreshold, 1);
  assert.equal(result.disabled, 1);
  assert.match(providerCreditMonitoringCopy(finance("numeric", { low_balance_threshold_usd: 0 })), /no positive/);
  assert.match(providerCreditMonitoringCopy(finance("numeric", { enabled: false })), /disabled/);
});

test("disconnected and disabled source providers do not inflate coverage", () => {
  const result = summarizeProjectAIProviderFinanceCoverage(
    [
      provider("connected"),
      provider("configured", { status: "configured" }),
      provider("disabled", { enabled: false }),
    ],
    { connected: finance("numeric") },
  );
  assert.equal(result.connected, 1);
  assert.equal(result.predictive, 1);
});

test("private policy never discloses numeric amounts in status copy", () => {
  const p = finance("numeric_private", {
    funded_usd: null,
    remaining_usd: null,
    low_balance_threshold_usd: 4,
  });
  assert.match(providerCreditMonitoringCopy(p), /private/);
  assert.doesNotMatch(providerCreditMonitoringCopy(p), /\$\d/);
});

test("coverage reports a 14-provider fleet with 3 attestations and 11 unknown policies", () => {
  const providers = Array.from({ length: 14 }, (_, i) => provider("provider-" + i));
  const policies = Object.fromEntries(
    providers.slice(0, 3).map((p) => [p.id, finance("owner_attested")]),
  );
  const result = summarizeProjectAIProviderFinanceCoverage(providers, policies);
  assert.equal(result.connected, 14);
  assert.equal(result.ownerAttestedOnly, 3);
  assert.equal(result.unverified, 11);
  assert.equal(result.predictive, 0);
});

test("Owner page does not report active predictive finance for a missing response", () => {
  const source = readFileSync(new URL("../src/app/owner/project-ai/page.tsx", import.meta.url), "utf8");
  assert.match(source, /providerCreditMonitoringCopy\(row\)/);
  assert.match(source, /financeCoverage\.predictive/);
  assert.match(source, /financeCoverage\.unverified/);
  assert.match(source, /row\?\.state \?\? "finance unverified"/);
  assert.doesNotMatch(source, /: "Predictive low\/critical monitoring is active from the recorded funded baseline/);
  assert.doesNotMatch(source, /low_balance_threshold_usd: row\?\.low_balance_threshold_usd \?\? 5/);
  assert.match(source, /draft\.funded_credit_usd <= 0/);
  assert.match(source, /draft\.low_balance_threshold_usd <= 0/);
  assert.match(source, /draft\.critical_balance_threshold_usd > draft\.low_balance_threshold_usd/);
});
