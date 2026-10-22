import type {
  ProjectAIProvider,
  ProjectAIProviderFinance,
} from "./owner-project-ai";

export type ProjectAIProviderFinanceCoverage = {
  connected: number;
  predictive: number;
  ownerAttestedOnly: number;
  disabled: number;
  noEarlyWarningThreshold: number;
  unverified: number;
};

/**
 * Finance coverage is not connectivity: a connected provider without a
 * confirmed numeric baseline and positive low threshold cannot be counted as
 * having a predictive pre-depletion alert.
 *
 * Missing responses (including transient fetch errors) are deliberately
 * classified as unverified, not as zero credit or as a configured policy.
 */
export function summarizeProjectAIProviderFinanceCoverage(
  providers: ReadonlyArray<Pick<ProjectAIProvider, "id" | "status" | "enabled">>,
  finance: Readonly<Record<string, ProjectAIProviderFinance | null | undefined>>,
): ProjectAIProviderFinanceCoverage {
  const result: ProjectAIProviderFinanceCoverage = {
    connected: 0,
    predictive: 0,
    ownerAttestedOnly: 0,
    disabled: 0,
    noEarlyWarningThreshold: 0,
    unverified: 0,
  };
  for (const provider of providers) {
    if (!provider.enabled || provider.status !== "connected") continue;
    result.connected++;
    const policy = finance[provider.id];
    if (!policy) {
      result.unverified++;
      continue;
    }
    if (!policy.enabled) {
      result.disabled++;
      continue;
    }
    if (policy.funding_mode === "owner_attested") {
      result.ownerAttestedOnly++;
      continue;
    }
    if (
      policy.funded_confirmed &&
      typeof policy.low_balance_threshold_usd === "number" &&
      Number.isFinite(policy.low_balance_threshold_usd) &&
      policy.low_balance_threshold_usd > 0
    ) {
      result.predictive++;
    } else {
      result.noEarlyWarningThreshold++;
    }
  }
  return result;
}

export function providerCreditMonitoringCopy(
  policy: ProjectAIProviderFinance | null | undefined,
): string {
  if (!policy) {
    return "Predictive credit monitoring is not verified. No numeric funded baseline or low/critical alert policy has been loaded. Enter real amounts below or check the Owner finance connection; do not assume alerts are active.";
  }
  if (!policy.enabled) {
    return "This provider's predictive credit monitoring is disabled. Enable a verified numeric funding policy to receive low-balance alerts.";
  }
  if (policy.funding_mode === "owner_attested") {
    return "Funding was confirmed without an amount. Billing/quota failures can be reported, but predictive low-balance alerts require real numeric funded credit and thresholds.";
  }
  if (
    !policy.funded_confirmed ||
    typeof policy.low_balance_threshold_usd !== "number" ||
    !Number.isFinite(policy.low_balance_threshold_usd) ||
    policy.low_balance_threshold_usd <= 0
  ) {
    return "A numeric policy exists, but no positive low-balance warning threshold is verified. Configure a real positive Low threshold to enable pre-depletion alerts.";
  }
  return policy.funding_mode === "numeric_private"
    ? "Numeric pre-depletion monitoring is configured. Funded balances and alert amounts remain private to the Super Owner."
    : "Numeric pre-depletion monitoring is configured from the recorded funded baseline and durable provider spend.";
}
