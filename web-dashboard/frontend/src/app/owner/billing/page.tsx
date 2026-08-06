"use client";

import {
  BadgeCheck,
  Building2,
  CircleDollarSign,
  Coins,
  CreditCard,
  FileText,
  KeyRound,
  LoaderCircle,
  Percent,
  ReceiptText,
  RefreshCw,
  RotateCcw,
  Search,
  ShieldAlert,
  ShieldCheck,
  Tags,
  WalletCards,
  Webhook,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type FormEvent,
} from "react";

import {
  createBillingCoupon,
  creditBillingWallet,
  fetchBillingOverview,
  issueBillingLicense,
  reconcileBillingProvider,
  recordBillingUsage,
  refundBillingTransaction,
  revokeBillingLicense,
  saveBillingTax,
  settleBillingTransaction,
  updateBillingAccount,
  type BillingAccount,
  type BillingOverview,
  type BillingTransaction,
} from "@/lib/billing-api";

type Tab = "accounts" | "payments" | "commerce" | "licenses" | "operations";

const inputClass =
  "glass-input rounded-xl px-3 py-2 text-sm text-white outline-none disabled:cursor-not-allowed disabled:opacity-50";
const buttonClass =
  "inline-flex items-center justify-center gap-2 rounded-xl border border-electric-500/20 bg-electric-500/10 px-3 py-2 text-xs font-semibold text-electric-200 transition hover:bg-electric-500/15 disabled:cursor-not-allowed disabled:opacity-50";

function idempotencyKey(prefix: string): string {
  const value =
    globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  return `${prefix}-${value}`;
}

function money(amountMinor: number, currency = "USD"): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(amountMinor / 100);
}

function dateValue(value: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function accountStatusClass(status: string): string {
  if (status === "active" || status === "trial") {
    return "border-green-500/20 bg-green-500/10 text-green-300";
  }
  if (status === "past_due") {
    return "border-amber-500/20 bg-amber-500/10 text-amber-200";
  }
  return "border-red-500/20 bg-red-500/10 text-red-300";
}

export default function OwnerBillingPage() {
  const [overview, setOverview] = useState<BillingOverview | null>(null);
  const [tab, setTab] = useState<Tab>("accounts");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("Loading durable billing control...");

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    try {
      const data = await fetchBillingOverview(signal);
      setOverview(data);
      setMessage(
        `Billing synchronized from portal catalogue version ${data.catalog.source_version}.`,
      );
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setMessage(
          error instanceof Error ? error.message : "Billing load failed.",
        );
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  async function perform(label: string, action: () => Promise<unknown>) {
    if (busy) return;
    setBusy(true);
    setMessage(`${label}...`);
    try {
      await action();
      await load();
      setMessage(`${label} completed and persisted.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : `${label} failed.`);
    } finally {
      setBusy(false);
    }
  }

  const visibleAccounts = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!overview || !normalized) return overview?.accounts || [];
    return overview.accounts.filter((account) =>
      `${account.organization} ${account.plan || ""} ${account.status}`
        .toLowerCase()
        .includes(normalized),
    );
  }, [overview, query]);

  function saveAccount(
    event: FormEvent<HTMLFormElement>,
    account: BillingAccount,
  ) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const plan = String(form.get("plan") || "");
    const seats = Number(form.get("seats"));
    void perform("Updating billing account", () =>
      updateBillingAccount(account.organization_id, {
        plan_code: plan || undefined,
        seats: Number.isFinite(seats) ? seats : undefined,
      }),
    );
  }

  function toggleAccount(account: BillingAccount) {
    const action = account.status === "suspended" ? "restore" : "suspend";
    if (
      action === "suspend" &&
      !window.confirm(`Suspend billing access for ${account.organization}?`)
    ) {
      return;
    }
    void perform(
      `${action === "restore" ? "Restoring" : "Suspending"} account`,
      () => updateBillingAccount(account.organization_id, { action }),
    );
  }

  function creditWallet(account: BillingAccount) {
    const raw = window.prompt(
      `Credit ${account.organization} wallet. Enter amount in cents/minor units:`,
      "1000",
    );
    if (raw === null) return;
    const amount = Number(raw);
    if (!Number.isInteger(amount) || amount <= 0) {
      setMessage("Wallet credit must be a positive integer in minor units.");
      return;
    }
    const description =
      window.prompt("Credit description:", "Owner-approved wallet credit") ||
      "Owner-approved wallet credit";
    void perform("Crediting wallet", () =>
      creditBillingWallet(
        account.organization_id,
        amount,
        description,
        idempotencyKey("owner-credit"),
      ),
    );
  }

  function meterUsage(account: BillingAccount) {
    const metric = window.prompt("Usage metric key:", "tokens")?.trim();
    if (!metric) return;
    const raw = window.prompt("Usage quantity:", "1");
    if (raw === null) return;
    const quantity = Number(raw);
    if (!Number.isInteger(quantity) || quantity <= 0) {
      setMessage("Usage quantity must be a positive integer.");
      return;
    }
    void perform("Recording metered usage", () =>
      recordBillingUsage(
        account.organization_id,
        metric,
        quantity,
        idempotencyKey("owner-usage"),
      ),
    );
  }

  function createCoupon(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const type = String(form.get("type")) as "percent" | "fixed";
    const value = Number(form.get("value"));
    const max = Number(form.get("max"));
    void perform("Creating coupon", () =>
      createBillingCoupon({
        code: String(form.get("code") || "")
          .trim()
          .toUpperCase(),
        discount_type: type,
        ...(type === "percent"
          ? { percent_off: value }
          : {
              amount_off_minor: value,
              currency: String(form.get("currency") || "USD").toUpperCase(),
            }),
        ...(Number.isFinite(max) && max > 0 ? { max_redemptions: max } : {}),
      }),
    );
    event.currentTarget.reset();
  }

  function saveTax(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    void perform("Saving tax rate", () =>
      saveBillingTax({
        code: String(form.get("code") || "")
          .trim()
          .toUpperCase(),
        country_code: String(form.get("country") || "")
          .trim()
          .toUpperCase(),
        percentage: Number(form.get("percentage")),
        inclusive: form.get("inclusive") === "on",
      }),
    );
  }

  function settle(transaction: BillingTransaction, succeeded: boolean) {
    const note = window.prompt(
      succeeded ? "Settlement note:" : "Failure note:",
      succeeded ? "Offline payment verified" : "Offline payment rejected",
    );
    if (note === null) return;
    const reference = succeeded
      ? window.prompt("External payment reference (optional):", "") || undefined
      : undefined;
    void perform("Settling offline transaction", () =>
      settleBillingTransaction(transaction.id, {
        succeeded,
        external_reference: reference,
        note,
      }),
    );
  }

  function refund(transaction: BillingTransaction) {
    const raw = window.prompt(
      `Refund amount in minor units. Maximum ${transaction.amount_minor}:`,
      String(transaction.amount_minor),
    );
    if (raw === null) return;
    const amount = Number(raw);
    if (
      !Number.isInteger(amount) ||
      amount <= 0 ||
      amount > transaction.amount_minor
    ) {
      setMessage("Refund amount is outside the refundable balance.");
      return;
    }
    const reason = window.prompt("Refund reason:", "Owner-approved refund");
    if (!reason) return;
    void perform("Refunding transaction", () =>
      refundBillingTransaction(
        transaction.id,
        amount,
        reason,
        idempotencyKey("owner-refund"),
      ),
    );
  }

  function issueLicense(account: BillingAccount) {
    const raw = window.prompt("License seats:", String(account.licensed_seats));
    if (raw === null) return;
    const seats = Number(raw);
    if (!Number.isInteger(seats) || seats < 1) {
      setMessage("License seats must be a positive integer.");
      return;
    }
    void perform("Issuing license", async () => {
      const result = await issueBillingLicense(account.organization_id, seats);
      await navigator.clipboard?.writeText(result.license_key);
      window.alert(
        `License issued. The complete key is shown once and was copied when browser permissions allowed:\n\n${result.license_key}`,
      );
    });
  }

  if (loading && !overview) {
    return (
      <div className="flex min-h-[55vh] items-center justify-center gap-3 text-white/45">
        <LoaderCircle className="h-6 w-6 animate-spin text-electric-300" />
        Loading billing control plane...
      </div>
    );
  }

  if (!overview) {
    return <div className="glass-card p-8 text-red-300">{message}</div>;
  }

  const tabs: Array<[Tab, string]> = [
    ["accounts", "Accounts & entitlements"],
    ["payments", "Invoices & transactions"],
    ["commerce", "Coupons, tax & wallets"],
    ["licenses", "Licenses & usage"],
    ["operations", "Providers & webhooks"],
  ];

  return (
    <div className="space-y-6 pb-20">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs text-electric-300">
            <WalletCards className="h-3.5 w-3.5" /> Durable Billing Authority
          </div>
          <h1 className="text-3xl font-bold text-white">
            Billing, Licensing, Payments & Entitlements
          </h1>
          <p className="mt-2 max-w-4xl text-sm leading-6 text-white/45">
            One control plane for public pricing, enforced limits, seats,
            wallets, usage, subscriptions, invoices, refunds, licenses, verified
            webhooks, and provider reconciliation.
          </p>
        </div>
        <button
          type="button"
          disabled={busy || loading}
          onClick={() => void load()}
          className={buttonClass}
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
        {[
          ["Active accounts", overview.summary.active_accounts, Building2],
          ["Gross", money(overview.summary.gross_minor), CircleDollarSign],
          ["Refunded", money(overview.summary.refunded_minor), RotateCcw],
          ["Open invoices", overview.summary.open_invoices, ReceiptText],
          [
            "Wallet balance",
            money(overview.summary.wallet_balance_minor),
            Coins,
          ],
          [
            "Usage charges",
            money(overview.summary.usage_charge_minor),
            CreditCard,
          ],
        ].map(([label, value, Icon]) => {
          const MetricIcon = Icon as typeof Building2;
          return (
            <div key={String(label)} className="glass-card p-4">
              <MetricIcon className="h-5 w-5 text-electric-300" />
              <div className="mt-3 break-words text-xl font-bold text-white">
                {String(value)}
              </div>
              <div className="mt-1 text-xs text-white/35">{String(label)}</div>
            </div>
          );
        })}
      </div>

      <div className="rounded-xl border border-electric-500/20 bg-electric-500/10 px-4 py-3 text-xs text-electric-200">
        {message}
      </div>

      <div className="flex flex-wrap gap-2 rounded-2xl border border-white/[0.07] bg-white/[0.02] p-2">
        {tabs.map(([id, label]) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={`rounded-xl px-4 py-2.5 text-sm font-semibold transition ${
              tab === id
                ? "bg-white text-ink-950"
                : "text-white/50 hover:bg-white/[0.05]"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "accounts" && (
        <div className="space-y-4">
          <div className="glass-card p-4">
            <div className="relative max-w-xl">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/30" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search organizations, plans, or status..."
                className={`${inputClass} w-full pl-10`}
              />
            </div>
          </div>
          {visibleAccounts.map((account) => (
            <form
              key={account.id}
              onSubmit={(event) => saveAccount(event, account)}
              className="glass-card p-5"
            >
              <div className="flex flex-col gap-5 2xl:flex-row 2xl:items-center 2xl:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="font-semibold text-white">
                      {account.organization}
                    </h2>
                    <span
                      className={`rounded-full border px-2.5 py-1 text-[11px] ${accountStatusClass(account.status)}`}
                    >
                      {account.status}
                    </span>
                    {account.protected && (
                      <span className="rounded-full border border-blue-500/20 bg-blue-500/10 px-2.5 py-1 text-[11px] text-blue-200">
                        Protected
                      </span>
                    )}
                  </div>
                  <p className="mt-2 text-xs text-white/35">
                    {account.active_seats} active of {account.licensed_seats}{" "}
                    licensed seats · period ends{" "}
                    {dateValue(account.current_period_end)}
                  </p>
                  <p className="mt-2 max-w-3xl break-words text-[11px] text-white/30">
                    Limits: {JSON.stringify(account.limits)} · Entitlements:{" "}
                    {account.entitlements.join(", ") || "none"}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <select
                    name="plan"
                    defaultValue={account.plan || ""}
                    disabled={busy}
                    className={inputClass}
                  >
                    {overview.catalog.plans.map((plan) => (
                      <option
                        key={plan.code}
                        value={plan.code}
                        className="bg-space-800"
                      >
                        {plan.name.en || plan.code}
                      </option>
                    ))}
                  </select>
                  <input
                    name="seats"
                    type="number"
                    min={Math.max(1, account.active_seats)}
                    defaultValue={account.licensed_seats}
                    disabled={busy}
                    aria-label={`Licensed seats for ${account.organization}`}
                    className={`${inputClass} w-28`}
                  />
                  <button type="submit" disabled={busy} className={buttonClass}>
                    <BadgeCheck className="h-4 w-4" /> Save
                  </button>
                  <button
                    type="button"
                    disabled={busy || account.protected}
                    onClick={() => toggleAccount(account)}
                    className={buttonClass}
                  >
                    {account.status === "suspended" ? (
                      <ShieldCheck className="h-4 w-4" />
                    ) : (
                      <ShieldAlert className="h-4 w-4" />
                    )}
                    {account.status === "suspended" ? "Restore" : "Suspend"}
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => creditWallet(account)}
                    className={buttonClass}
                  >
                    <Coins className="h-4 w-4" /> Credit
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => meterUsage(account)}
                    className={buttonClass}
                  >
                    <CreditCard className="h-4 w-4" /> Meter
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => issueLicense(account)}
                    className={buttonClass}
                  >
                    <KeyRound className="h-4 w-4" /> License
                  </button>
                </div>
              </div>
            </form>
          ))}
        </div>
      )}

      {tab === "payments" && (
        <div className="grid gap-5 xl:grid-cols-2">
          <section className="glass-card p-5">
            <h2 className="flex items-center gap-2 text-lg font-semibold text-white">
              <ReceiptText className="h-5 w-5 text-electric-300" /> Transactions
            </h2>
            <div className="mt-4 space-y-3">
              {overview.transactions.slice(0, 100).map((item) => (
                <div
                  key={item.id}
                  className="rounded-xl border border-white/[0.07] bg-black/15 p-4"
                >
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <p className="font-semibold text-white">
                        {money(item.amount_minor, item.currency)}
                      </p>
                      <p className="mt-1 text-xs text-white/35">
                        {item.provider} · {item.status} ·{" "}
                        {dateValue(item.created_at)}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {item.status === "pending" &&
                        ["manual", "bank_transfer", "internal"].includes(
                          item.provider,
                        ) && (
                          <>
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => settle(item, true)}
                              className={buttonClass}
                            >
                              Settle
                            </button>
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => settle(item, false)}
                              className={buttonClass}
                            >
                              Fail
                            </button>
                          </>
                        )}
                      {["succeeded", "partially_refunded"].includes(
                        item.status,
                      ) && (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => refund(item)}
                          className={buttonClass}
                        >
                          <RotateCcw className="h-4 w-4" /> Refund
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              ))}
              {!overview.transactions.length && (
                <p className="text-sm text-white/35">
                  No transactions recorded.
                </p>
              )}
            </div>
          </section>

          <section className="glass-card p-5">
            <h2 className="flex items-center gap-2 text-lg font-semibold text-white">
              <FileText className="h-5 w-5 text-electric-300" /> Invoices
            </h2>
            <div className="mt-4 space-y-3">
              {overview.invoices.slice(0, 100).map((item) => (
                <div
                  key={item.id}
                  className="rounded-xl border border-white/[0.07] bg-black/15 p-4"
                >
                  <div className="flex items-center justify-between gap-4">
                    <div>
                      <p className="font-semibold text-white">{item.number}</p>
                      <p className="mt-1 text-xs text-white/35">
                        {item.provider} · {item.status} ·{" "}
                        {dateValue(item.created_at)}
                      </p>
                    </div>
                    <p className="font-semibold text-white">
                      {money(item.total_minor, item.currency)}
                    </p>
                  </div>
                  <p className="mt-2 text-[11px] text-white/30">
                    Discount {money(item.discount_minor, item.currency)} · Tax{" "}
                    {money(item.tax_minor, item.currency)} · Paid{" "}
                    {money(item.amount_paid_minor, item.currency)} · Refunded{" "}
                    {money(item.amount_refunded_minor, item.currency)}
                  </p>
                </div>
              ))}
              {!overview.invoices.length && (
                <p className="text-sm text-white/35">No invoices recorded.</p>
              )}
            </div>
          </section>
        </div>
      )}

      {tab === "commerce" && (
        <div className="grid gap-5 xl:grid-cols-2">
          <section className="glass-card p-5">
            <h2 className="flex items-center gap-2 text-lg font-semibold text-white">
              <Tags className="h-5 w-5 text-electric-300" /> Coupons
            </h2>
            <form
              onSubmit={createCoupon}
              className="mt-4 grid gap-3 sm:grid-cols-2"
            >
              <input
                name="code"
                required
                placeholder="Code"
                className={inputClass}
              />
              <select name="type" className={inputClass}>
                <option value="percent">Percent</option>
                <option value="fixed">Fixed amount</option>
              </select>
              <input
                name="value"
                required
                type="number"
                min="0.01"
                step="0.01"
                placeholder="Percent or minor amount"
                className={inputClass}
              />
              <input
                name="currency"
                defaultValue="USD"
                maxLength={3}
                placeholder="Currency"
                className={inputClass}
              />
              <input
                name="max"
                type="number"
                min="1"
                placeholder="Max redemptions"
                className={inputClass}
              />
              <button type="submit" disabled={busy} className={buttonClass}>
                <Percent className="h-4 w-4" /> Create coupon
              </button>
            </form>
            <div className="mt-5 space-y-2">
              {overview.coupons.map((item) => (
                <div
                  key={item.id}
                  className="rounded-xl border border-white/[0.07] p-3 text-sm text-white/65"
                >
                  <span className="font-semibold text-white">{item.code}</span>{" "}
                  ·{" "}
                  {item.type === "percent"
                    ? `${item.percent_off}%`
                    : money(
                        item.amount_off_minor || 0,
                        item.currency || "USD",
                      )}{" "}
                  · {item.redeemed_count}/{item.max_redemptions ?? "∞"} used
                </div>
              ))}
            </div>
          </section>

          <section className="glass-card p-5">
            <h2 className="flex items-center gap-2 text-lg font-semibold text-white">
              <Percent className="h-5 w-5 text-electric-300" /> Tax rates
            </h2>
            <form onSubmit={saveTax} className="mt-4 grid gap-3 sm:grid-cols-2">
              <input
                name="code"
                required
                placeholder="Tax code"
                className={inputClass}
              />
              <input
                name="country"
                required
                minLength={2}
                maxLength={2}
                placeholder="Country code"
                className={inputClass}
              />
              <input
                name="percentage"
                required
                type="number"
                min="0"
                max="100"
                step="0.01"
                placeholder="Percentage"
                className={inputClass}
              />
              <label className="flex items-center gap-2 text-sm text-white/55">
                <input name="inclusive" type="checkbox" /> Inclusive
              </label>
              <button type="submit" disabled={busy} className={buttonClass}>
                <BadgeCheck className="h-4 w-4" /> Save tax
              </button>
            </form>
            <div className="mt-5 space-y-2">
              {overview.tax_rates.map((item) => (
                <div
                  key={item.id}
                  className="rounded-xl border border-white/[0.07] p-3 text-sm text-white/65"
                >
                  <span className="font-semibold text-white">
                    {item.country_code} · {item.code}
                  </span>{" "}
                  · {item.percentage}% ·{" "}
                  {item.inclusive ? "inclusive" : "exclusive"}
                </div>
              ))}
            </div>
          </section>

          <section className="glass-card p-5 xl:col-span-2">
            <h2 className="flex items-center gap-2 text-lg font-semibold text-white">
              <Coins className="h-5 w-5 text-electric-300" /> Organization
              wallets
            </h2>
            <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {overview.wallets.map((item) => (
                <div
                  key={item.id}
                  className="rounded-xl border border-white/[0.07] bg-black/15 p-4"
                >
                  <p className="font-semibold text-white">
                    {item.organization}
                  </p>
                  <p className="mt-2 text-2xl font-bold text-electric-200">
                    {money(item.balance_minor, item.currency)}
                  </p>
                  <p className="mt-1 text-xs text-white/35">{item.status}</p>
                </div>
              ))}
              {!overview.wallets.length && (
                <p className="text-sm text-white/35">
                  Wallets are created on first credit or usage event.
                </p>
              )}
            </div>
          </section>
        </div>
      )}

      {tab === "licenses" && (
        <div className="grid gap-5 xl:grid-cols-2">
          <section className="glass-card p-5">
            <h2 className="flex items-center gap-2 text-lg font-semibold text-white">
              <KeyRound className="h-5 w-5 text-electric-300" /> Licenses
            </h2>
            <div className="mt-4 space-y-3">
              {overview.licenses.map((item) => {
                const account = overview.accounts.find(
                  (candidate) =>
                    candidate.organization_id === item.organization_id,
                );
                return (
                  <div
                    key={item.id}
                    className="rounded-xl border border-white/[0.07] bg-black/15 p-4"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <p className="font-semibold text-white">
                          {account?.organization || item.organization_id}
                        </p>
                        <p className="mt-1 text-xs text-white/35">
                          {item.key_prefix}… · {item.seats} seats ·{" "}
                          {item.status}
                        </p>
                      </div>
                      {item.status !== "revoked" && (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() =>
                            void perform("Revoking license", () =>
                              revokeBillingLicense(item.id),
                            )
                          }
                          className={buttonClass}
                        >
                          Revoke
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
              {!overview.licenses.length && (
                <p className="text-sm text-white/35">
                  No durable licenses issued.
                </p>
              )}
            </div>
          </section>

          <section className="glass-card p-5">
            <h2 className="flex items-center gap-2 text-lg font-semibold text-white">
              <CreditCard className="h-5 w-5 text-electric-300" /> Metered usage
            </h2>
            <div className="mt-4 space-y-3">
              {overview.usage.map((item) => {
                const account = overview.accounts.find(
                  (candidate) =>
                    candidate.organization_id === item.organization_id,
                );
                return (
                  <div
                    key={item.id}
                    className="rounded-xl border border-white/[0.07] bg-black/15 p-4"
                  >
                    <div className="flex items-center justify-between gap-4">
                      <div>
                        <p className="font-semibold text-white">
                          {account?.organization || item.organization_id}
                        </p>
                        <p className="mt-1 text-xs text-white/35">
                          {item.metric} · {item.quantity} used ·{" "}
                          {item.billable_quantity} billable
                        </p>
                      </div>
                      <p className="font-semibold text-electric-200">
                        {money(item.charge_minor, item.currency)}
                      </p>
                    </div>
                  </div>
                );
              })}
              {!overview.usage.length && (
                <p className="text-sm text-white/35">
                  No metered usage recorded.
                </p>
              )}
            </div>
          </section>
        </div>
      )}

      {tab === "operations" && (
        <div className="grid gap-5 xl:grid-cols-2">
          <section className="glass-card p-5">
            <h2 className="flex items-center gap-2 text-lg font-semibold text-white">
              <ShieldCheck className="h-5 w-5 text-electric-300" /> Payment
              providers
            </h2>
            <div className="mt-4 space-y-3">
              {overview.providers.map((provider) => (
                <div
                  key={provider.id}
                  className="rounded-xl border border-white/[0.07] bg-black/15 p-4"
                >
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <p className="font-semibold text-white">{provider.id}</p>
                      <p className="mt-1 text-xs text-white/35">
                        {provider.status} · {provider.mode} ·{" "}
                        {provider.capabilities.join(", ")}
                      </p>
                    </div>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() =>
                        void perform(`Reconciling ${provider.id}`, () =>
                          reconcileBillingProvider(provider.id),
                        )
                      }
                      className={buttonClass}
                    >
                      <RefreshCw className="h-4 w-4" /> Reconcile
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className="glass-card p-5">
            <h2 className="flex items-center gap-2 text-lg font-semibold text-white">
              <Webhook className="h-5 w-5 text-electric-300" /> Verified webhook
              ledger
            </h2>
            <div className="mt-4 space-y-3">
              {overview.webhooks.map((item) => (
                <div
                  key={item.id}
                  className="rounded-xl border border-white/[0.07] bg-black/15 p-4"
                >
                  <p className="font-semibold text-white">
                    {item.provider} · {item.event_type}
                  </p>
                  <p className="mt-1 text-xs text-white/35">
                    {item.status} · {dateValue(item.created_at)}
                  </p>
                </div>
              ))}
              {!overview.webhooks.length && (
                <p className="text-sm text-white/35">
                  No verified webhook events received.
                </p>
              )}
            </div>
          </section>

          <section className="glass-card p-5 xl:col-span-2">
            <h2 className="flex items-center gap-2 text-lg font-semibold text-white">
              <RefreshCw className="h-5 w-5 text-electric-300" /> Reconciliation
              history
            </h2>
            <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {overview.reconciliation_runs.map((item) => (
                <div
                  key={item.id}
                  className="rounded-xl border border-white/[0.07] bg-black/15 p-4"
                >
                  <p className="font-semibold text-white">
                    {item.provider} · {item.status}
                  </p>
                  <p className="mt-2 break-words text-xs text-white/35">
                    {JSON.stringify(item.summary)}
                  </p>
                  <p className="mt-2 text-[11px] text-white/25">
                    {dateValue(item.completed_at || item.created_at)}
                  </p>
                </div>
              ))}
              {!overview.reconciliation_runs.length && (
                <p className="text-sm text-white/35">
                  No reconciliation runs yet.
                </p>
              )}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
