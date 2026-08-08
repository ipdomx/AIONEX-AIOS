import { apiClient } from "@/lib/api-client";

export type BillingProvider = {
  id: string;
  configured: boolean;
  mode: string;
  capabilities: string[];
  status: string;
};

export type BillingAccount = {
  id: string;
  organization_id: string;
  organization: string;
  organization_status: string;
  plan: string | null;
  plan_name: string | null;
  status: string;
  licensed_seats: number;
  active_seats: number;
  limits: Record<string, number | string | boolean | null>;
  entitlements: string[];
  current_period_end: string | null;
  protected: boolean;
};

export type BillingInvoice = {
  id: string;
  organization_id: string;
  number: string;
  provider: string;
  status: string;
  currency: string;
  subtotal_minor: number;
  discount_minor: number;
  tax_minor: number;
  total_minor: number;
  amount_paid_minor: number;
  amount_refunded_minor: number;
  created_at: string;
  paid_at: string | null;
};

export type BillingTransaction = {
  id: string;
  organization_id: string;
  provider: string;
  type: string;
  status: string;
  amount_minor: number;
  currency: string;
  created_at: string;
  completed_at: string | null;
};

export type BillingRefund = {
  id: string;
  organization_id: string;
  transaction_id: string;
  provider: string;
  amount_minor: number;
  currency: string;
  reason: string;
  status: string;
  created_at: string;
};

export type BillingLicense = {
  id: string;
  organization_id: string;
  key_prefix: string;
  status: string;
  seats: number;
  issued_at: string;
  expires_at: string | null;
  revoked_at: string | null;
};

export type BillingCoupon = {
  id: string;
  code: string;
  type: "percent" | "fixed";
  percent_off: number | null;
  amount_off_minor: number | null;
  currency: string | null;
  max_redemptions: number | null;
  redeemed_count: number;
  expires_at: string | null;
  active: boolean;
};

export type BillingCatalogPlan = {
  code: string;
  name: Record<string, string>;
  status?: string;
  enabled: boolean;
  periods: Array<{
    id: string;
    amount_minor: number | null;
    currency: string;
    enabled: boolean;
    provider: string;
    checkout_available: boolean;
  }>;
};

export type BillingTaxRate = {
  id: string;
  code: string;
  country_code: string;
  region_code: string | null;
  percentage: number;
  inclusive: boolean;
  active: boolean;
};

export type BillingWallet = {
  id: string;
  organization_id: string;
  organization: string;
  currency: string;
  balance_minor: number;
  status: string;
};

export type BillingUsage = {
  id: string;
  organization_id: string;
  metric: string;
  quantity: number;
  included_quantity: number | null;
  billable_quantity: number;
  charge_minor: number;
  currency: string;
  period_start: string;
  period_end: string;
};

export type BillingReconciliationRun = {
  id: string;
  provider: string;
  status: string;
  summary: Record<string, number | boolean>;
  created_at: string;
  completed_at: string | null;
};


export type MobileStoreMapping = {
  id: string;
  store: "app_store" | "google_play";
  product_id: string;
  base_plan_id: string | null;
  offer_id: string | null;
  status: string;
  plan_id: string;
  plan_code: string | null;
  price_id: string;
  period_code: string | null;
  updated_at: string | null;
};

export type MobileStoreControl = {
  readiness: Record<string, { configured: boolean; [key: string]: unknown }>;
  mappings: MobileStoreMapping[];
  diagnostics: Array<{ severity: string; store: string; code: string; message: string; plan_code?: string; period_code?: string }>;
  catalog_options: Array<{ plan_id: string; plan_code: string; price_id: string; period_code: string; currency: string; amount_minor: number | null }>;
};

export type BillingOverview = {
  catalog: {
    source_version: number;
    default_currency: string;
    plans: BillingCatalogPlan[];
  };
  accounts: BillingAccount[];
  invoices: BillingInvoice[];
  transactions: BillingTransaction[];
  refunds: BillingRefund[];
  webhooks: Array<{
    id: string;
    provider: string;
    event_type: string;
    status: string;
    created_at: string;
    processed_at: string | null;
  }>;
  licenses: BillingLicense[];
  coupons: BillingCoupon[];
  tax_rates: BillingTaxRate[];
  wallets: BillingWallet[];
  usage: BillingUsage[];
  reconciliation_runs: BillingReconciliationRun[];
  summary: {
    gross_minor: number;
    refunded_minor: number;
    successful_transactions: number;
    failed_transactions: number;
    open_invoices: number;
    active_accounts: number;
    wallet_balance_minor: number;
    usage_charge_minor: number;
  };
  providers: BillingProvider[];
  mobile_stores: MobileStoreControl;
};

export function fetchBillingOverview(
  signal?: AbortSignal,
): Promise<BillingOverview> {
  return apiClient.get<BillingOverview>("/billing/owner/overview", { signal });
}

export function updateBillingAccount(
  organizationId: string,
  payload: {
    plan_code?: string;
    seats?: number;
    action?: "suspend" | "restore";
  },
): Promise<BillingAccount> {
  return apiClient.patch<BillingAccount>(
    `/billing/owner/accounts/${encodeURIComponent(organizationId)}`,
    payload,
  );
}

export function createBillingCoupon(payload: {
  code: string;
  discount_type: "percent" | "fixed";
  percent_off?: number;
  amount_off_minor?: number;
  currency?: string;
  max_redemptions?: number;
  expires_at?: string;
}): Promise<BillingCoupon> {
  return apiClient.post<BillingCoupon>("/billing/owner/coupons", payload);
}

export function saveBillingTax(payload: {
  code: string;
  country_code: string;
  percentage: number;
  inclusive: boolean;
}): Promise<Record<string, unknown>> {
  return apiClient.post<Record<string, unknown>>(
    "/billing/owner/taxes",
    payload,
  );
}

export function creditBillingWallet(
  organizationId: string,
  amountMinor: number,
  description: string,
  idempotencyKey: string,
): Promise<{
  entry_id: string;
  amount_minor: number;
  balance_after_minor: number;
}> {
  return apiClient.post(
    "/billing/owner/wallet/credit",
    {
      organization_id: organizationId,
      amount_minor: amountMinor,
      description,
    },
    { headers: { "Idempotency-Key": idempotencyKey } },
  );
}

export function recordBillingUsage(
  organizationId: string,
  metric: string,
  quantity: number,
  idempotencyKey: string,
): Promise<Record<string, unknown>> {
  return apiClient.post(
    "/billing/owner/usage",
    { organization_id: organizationId, metric, quantity },
    { headers: { "Idempotency-Key": idempotencyKey } },
  );
}

export function settleBillingTransaction(
  transactionId: string,
  payload: { succeeded: boolean; external_reference?: string; note?: string },
): Promise<BillingTransaction> {
  return apiClient.post<BillingTransaction>(
    `/billing/owner/transactions/${encodeURIComponent(transactionId)}/settle`,
    payload,
  );
}

export function refundBillingTransaction(
  transactionId: string,
  amountMinor: number,
  reason: string,
  idempotencyKey: string,
): Promise<{
  id: string;
  status: string;
  amount_minor: number;
  currency: string;
}> {
  return apiClient.post(
    "/billing/owner/refunds",
    { transaction_id: transactionId, amount_minor: amountMinor, reason },
    { headers: { "Idempotency-Key": idempotencyKey } },
  );
}

export function issueBillingLicense(
  organizationId: string,
  seats: number,
  expiresAt?: string,
): Promise<BillingLicense & { license_key: string }> {
  return apiClient.post("/billing/owner/licenses", {
    organization_id: organizationId,
    seats,
    expires_at: expiresAt || null,
  });
}

export function revokeBillingLicense(
  licenseId: string,
): Promise<BillingLicense> {
  return apiClient.post(
    `/billing/owner/licenses/${encodeURIComponent(licenseId)}/revoke`,
  );
}

export function reconcileBillingProvider(provider: string): Promise<{
  id: string;
  provider: string;
  status: string;
  summary: Record<string, number | boolean>;
}> {
  return apiClient.post("/billing/owner/reconcile", { provider });
}


export function saveMobileStoreMapping(payload: {
  store: "app_store" | "google_play"; plan_code: string; period_code: string;
  product_id: string; base_plan_id?: string | null; offer_id?: string | null;
  mapping_id?: string | null; active?: boolean;
}): Promise<MobileStoreMapping> {
  return apiClient.post<MobileStoreMapping>("/billing/mobile-store/owner/mappings", payload);
}

export function setMobileStoreMappingStatus(mappingId: string, active: boolean): Promise<{ id: string; store: string; status: string }> {
  return apiClient.patch(`/billing/mobile-store/owner/mappings/${encodeURIComponent(mappingId)}`, { active });
}
