"use client";

import {
  BadgeDollarSign,
  CalendarClock,
  Check,
  CreditCard,
  ExternalLink,
  LoaderCircle,
  ReceiptText,
  RefreshCw,
  ShieldCheck,
  WalletCards,
  XCircle,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { StatusMessage } from "@/components/ui/status-message";
import { useAuth } from "@/hooks/use-auth";
import {
  cancelBillingSubscription,
  createBillingCheckout,
  createBillingPortalSession,
  getBillingSummary,
  getPublicBillingCatalog,
  listBillingPaymentMethods,
  removeBillingPaymentMethod,
  setDefaultBillingPaymentMethod,
  validateBillingCoupon,
} from "@/lib/api";
import type {
  BillingCatalog,
  BillingCatalogPeriod,
  BillingCatalogPlan,
  BillingCheckout,
  BillingPaymentMethod,
  BillingSummary,
} from "@/types";

function localized(
  value: Record<string, string> | undefined,
  locale: string,
  fallback = "",
): string {
  return value?.[locale] || value?.en || value?.ar || fallback;
}

function idempotencyKey(): string {
  const cryptoApi = globalThis.crypto;
  if (cryptoApi && typeof cryptoApi.randomUUID === "function") {
    return `billing-${cryptoApi.randomUUID()}`;
  }
  return `billing-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function money(
  amountMinor: number | null | undefined,
  currency: string,
  locale: string,
) {
  if (amountMinor == null) return "—";
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(amountMinor / 100);
}

function dateValue(value: string | null | undefined, locale: string): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function BillingClient() {
  const t = useTranslations("billing");
  const locale = useLocale();
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, isAuthenticated, isLoading } = useAuth();
  const [summary, setSummary] = useState<BillingSummary | null>(null);
  const [catalog, setCatalog] = useState<BillingCatalog | null>(null);
  const [methods, setMethods] = useState<BillingPaymentMethod[]>([]);
  const [selectedPlanCode, setSelectedPlanCode] = useState("");
  const [selectedPeriodCode, setSelectedPeriodCode] = useState("");
  const [coupon, setCoupon] = useState("");
  const [country, setCountry] = useState("");
  const [couponResult, setCouponResult] = useState<{
    discount_minor: number;
    total_minor: number;
  } | null>(null);
  const [checkoutResult, setCheckoutResult] = useState<BillingCheckout | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.replace(`/${locale}/login`);
    }
  }, [isAuthenticated, isLoading, locale, router]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [billingSummary, billingCatalog, paymentMethods] =
        await Promise.all([
          getBillingSummary(),
          getPublicBillingCatalog(),
          listBillingPaymentMethods(),
        ]);
      setSummary(billingSummary);
      setCatalog(billingCatalog);
      setMethods(paymentMethods);
      const requestedPlan = searchParams.get("plan") || "";
      const requestedPeriod = searchParams.get("period") || "";
      const defaultPlan =
        billingCatalog.plans.find((item) => item.code === requestedPlan) ||
        billingCatalog.plans.find(
          (item) => item.enabled && item.code !== billingSummary.account.plan,
        ) ||
        billingCatalog.plans.find((item) => item.enabled);
      if (defaultPlan) {
        setSelectedPlanCode(defaultPlan.code);
        const period =
          defaultPlan.periods.find((item) => item.id === requestedPeriod) ||
          defaultPlan.periods.find(
            (item) => item.id === billingCatalog.default_period && item.enabled,
          ) ||
          defaultPlan.periods.find((item) => item.enabled);
        setSelectedPeriodCode(period?.id || "");
      }
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : t("loadError"));
    } finally {
      setLoading(false);
    }
  }, [searchParams, t]);

  useEffect(() => {
    if (isAuthenticated) void load();
  }, [isAuthenticated, load]);

  const selectedPlan = useMemo(
    () => catalog?.plans.find((item) => item.code === selectedPlanCode) || null,
    [catalog, selectedPlanCode],
  );
  const selectedPeriod = useMemo(
    () =>
      selectedPlan?.periods.find((item) => item.id === selectedPeriodCode) ||
      selectedPlan?.periods.find((item) => item.enabled) ||
      null,
    [selectedPeriodCode, selectedPlan],
  );
  const canManage = Boolean(
    user?.permissions.includes("*") ||
    user?.permissions.includes("billing:write"),
  );

  function selectPlan(plan: BillingCatalogPlan, period?: BillingCatalogPeriod) {
    setSelectedPlanCode(plan.code);
    setSelectedPeriodCode(
      period?.id || plan.periods.find((item) => item.enabled)?.id || "",
    );
    setCouponResult(null);
    setCheckoutResult(null);
    setError("");
    setSuccess("");
  }

  async function checkCoupon() {
    if (!selectedPeriod?.amount_minor || !coupon.trim()) return;
    setBusy(true);
    setError("");
    try {
      const result = await validateBillingCoupon(
        coupon.trim(),
        selectedPeriod.amount_minor,
        selectedPeriod.currency,
      );
      setCouponResult(result);
      setSuccess(t("couponApplied"));
    } catch (couponError) {
      setCouponResult(null);
      setError(
        couponError instanceof Error ? couponError.message : t("couponError"),
      );
    } finally {
      setBusy(false);
    }
  }

  async function checkout() {
    if (!selectedPlan || !selectedPeriod || !canManage) return;
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      const result = await createBillingCheckout(
        {
          plan_code: selectedPlan.code,
          period_code: selectedPeriod.id,
          coupon_code: coupon.trim() || null,
          billing_country: country.trim().toUpperCase() || null,
        },
        idempotencyKey(),
      );
      setCheckoutResult(result);
      if (result.checkout_url) {
        const target = new URL(result.checkout_url);
        if (target.protocol !== "https:") throw new Error(t("unsafeCheckout"));
        window.location.assign(target.toString());
        return;
      }
      setSuccess(t("offlinePaymentCreated"));
      await load();
    } catch (checkoutError) {
      setError(
        checkoutError instanceof Error
          ? checkoutError.message
          : t("checkoutError"),
      );
    } finally {
      setBusy(false);
    }
  }

  async function openBillingPortal() {
    setBusy(true);
    setError("");
    try {
      const nativeManagement = summary?.subscription?.management_url;
      if (nativeManagement) {
        const target = new URL(nativeManagement);
        if (target.protocol !== "https:") throw new Error(t("unsafeCheckout"));
        window.location.assign(target.toString());
        return;
      }
      const result = await createBillingPortalSession();
      const target = new URL(result.url);
      if (target.protocol !== "https:") throw new Error(t("unsafeCheckout"));
      window.location.assign(target.toString());
    } catch (portalError) {
      setError(
        portalError instanceof Error ? portalError.message : t("portalError"),
      );
      setBusy(false);
    }
  }

  async function cancelSubscription() {
    if (!window.confirm(t("cancelConfirm"))) return;
    setBusy(true);
    setError("");
    try {
      await cancelBillingSubscription(false);
      setSuccess(t("cancelScheduled"));
      await load();
    } catch (cancelError) {
      setError(
        cancelError instanceof Error ? cancelError.message : t("cancelError"),
      );
    } finally {
      setBusy(false);
    }
  }

  async function makeDefault(methodId: string) {
    setBusy(true);
    setError("");
    try {
      await setDefaultBillingPaymentMethod(methodId);
      setMethods(await listBillingPaymentMethods());
      setSuccess(t("paymentMethodUpdated"));
    } catch (methodError) {
      setError(
        methodError instanceof Error ? methodError.message : t("methodError"),
      );
    } finally {
      setBusy(false);
    }
  }

  async function removeMethod(methodId: string) {
    if (!window.confirm(t("removeMethodConfirm"))) return;
    setBusy(true);
    setError("");
    try {
      await removeBillingPaymentMethod(methodId);
      setMethods(await listBillingPaymentMethods());
      setSuccess(t("paymentMethodRemoved"));
    } catch (methodError) {
      setError(
        methodError instanceof Error ? methodError.message : t("methodError"),
      );
    } finally {
      setBusy(false);
    }
  }

  if (isLoading || loading || !summary || !catalog) {
    return (
      <section className="section-pad">
        <div className="page-shell flex min-h-[45vh] items-center justify-center">
          <LoaderCircle className="h-8 w-8 animate-spin text-electric-200" />
        </div>
      </section>
    );
  }

  const checkoutState = searchParams.get("checkout");
  const limits = Object.entries(summary.account.limits);
  const usage = summary.account.usage;

  return (
    <section className="section-pad">
      <div className="page-shell space-y-8">
        <div className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <span className="eyebrow">
              <BadgeDollarSign className="h-3.5 w-3.5" /> {t("eyebrow")}
            </span>
            <h1 className="section-title mt-6">{t("title")}</h1>
            <p className="section-copy mt-4">{t("description")}</p>
          </div>
          <Button
            variant="secondary"
            disabled={busy}
            onClick={() => void load()}
          >
            <RefreshCw className={`h-4 w-4 ${busy ? "animate-spin" : ""}`} />
            {t("refresh")}
          </Button>
        </div>

        {checkoutState === "success" && (
          <StatusMessage tone="success">
            {t("checkoutReturnedSuccess")}
          </StatusMessage>
        )}
        {checkoutState === "cancelled" && (
          <StatusMessage tone="info">
            {t("checkoutReturnedCancelled")}
          </StatusMessage>
        )}
        {error && <StatusMessage tone="error">{error}</StatusMessage>}
        {success && <StatusMessage tone="success">{success}</StatusMessage>}

        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {[
            [
              t("currentPlan"),
              summary.account.plan_name || summary.account.plan || "—",
              ShieldCheck,
            ],
            [t("accountStatus"), summary.account.status, CalendarClock],
            [
              t("licensedSeats"),
              String(summary.account.licensed_seats),
              CreditCard,
            ],
            [
              t("walletBalance"),
              money(
                summary.wallet.balance_minor,
                summary.wallet.currency,
                locale,
              ),
              WalletCards,
            ],
          ].map(([label, value, Icon]) => {
            const MetricIcon = Icon as typeof ShieldCheck;
            return (
              <Card key={String(label)}>
                <CardContent>
                  <MetricIcon className="h-5 w-5 text-electric-200" />
                  <p className="mt-5 text-xs uppercase tracking-[0.14em] text-white/35">
                    {String(label)}
                  </p>
                  <p className="mt-2 break-words text-2xl font-semibold text-white">
                    {String(value)}
                  </p>
                </CardContent>
              </Card>
            );
          })}
        </div>

        <Card>
          <CardContent>
            <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <h2 className="text-xl font-semibold">{t("subscription")}</h2>
                {summary.subscription ? (
                  <p className="mt-2 text-sm text-white/45">
                    {summary.subscription.provider_label || summary.subscription.provider} ·{" "}
                    {t(summary.subscription.source === "mobile_store" ? "sourceMobileStore" : "sourceWeb")} ·{" "}
                    {summary.subscription.status} ·{" "}
                    {t("renews", {
                      date: dateValue(
                        summary.subscription.current_period_end,
                        locale,
                      ),
                    })}
                  </p>
                ) : (
                  <p className="mt-2 text-sm text-white/45">
                    {t("noSubscription")}
                  </p>
                )}
              </div>
              <div className="flex flex-wrap gap-3">
                {summary.subscription &&
                  summary.subscription.source !== "mobile_store" &&
                  !summary.subscription.cancel_at_period_end && (
                    <Button
                      variant="secondary"
                      disabled={busy}
                      onClick={() => void cancelSubscription()}
                    >
                      <XCircle className="h-4 w-4" /> {t("cancelAtPeriodEnd")}
                    </Button>
                  )}
                {summary.subscription?.cancel_at_period_end && (
                  <span className="rounded-xl border border-amber-400/20 bg-amber-400/10 px-4 py-3 text-sm text-amber-100">
                    {t("cancellationScheduled")}
                  </span>
                )}
                <Button
                  disabled={busy}
                  onClick={() => void openBillingPortal()}
                >
                  <ExternalLink className="h-4 w-4" /> {t(summary.subscription?.source === "mobile_store" ? "manageStoreSubscription" : "manageWithProvider")}
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>

        <div>
          <h2 className="text-2xl font-semibold">{t("plans")}</h2>
          <p className="mt-2 text-sm text-white/45">{t("plansCopy")}</p>
          <div className="mt-5 grid gap-5 lg:grid-cols-3">
            {catalog.plans
              .filter((plan) => plan.enabled)
              .sort((left, right) => left.order - right.order)
              .map((plan) => {
                const period =
                  plan.periods.find(
                    (item) =>
                      item.id === catalog.default_period && item.enabled,
                  ) || plan.periods.find((item) => item.enabled);
                return (
                  <article
                    key={plan.code}
                    className={`rounded-3xl border p-6 ${
                      selectedPlanCode === plan.code
                        ? "border-electric-300/40 bg-electric-400/[0.08]"
                        : "border-white/[0.08] bg-white/[0.025]"
                    }`}
                  >
                    <h3 className="text-xl font-semibold">
                      {localized(plan.name, locale, plan.code)}
                    </h3>
                    <p className="mt-3 min-h-14 text-sm leading-7 text-white/45">
                      {localized(plan.description, locale)}
                    </p>
                    <p className="mt-5 text-3xl font-bold">
                      {period?.amount_minor == null
                        ? t("contactSales")
                        : money(period.amount_minor, period.currency, locale)}
                    </p>
                    <ul className="mt-5 space-y-2">
                      {plan.features.slice(0, 6).map((feature, index) => (
                        <li
                          key={index}
                          className="flex items-start gap-2 text-sm text-white/60"
                        >
                          <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-300" />
                          {localized(feature, locale)}
                        </li>
                      ))}
                    </ul>
                    <Button
                      className="mt-6 w-full"
                      variant={
                        selectedPlanCode === plan.code ? "primary" : "secondary"
                      }
                      onClick={() => selectPlan(plan, period)}
                    >
                      {summary.account.plan === plan.code
                        ? t("currentPlan")
                        : t("selectPlan")}
                    </Button>
                  </article>
                );
              })}
          </div>
        </div>

        {selectedPlan && selectedPeriod && (
          <Card>
            <CardContent>
              <h2 className="text-xl font-semibold">{t("checkout")}</h2>
              <p className="mt-2 text-sm text-white/45">
                {localized(selectedPlan.name, locale, selectedPlan.code)} ·{" "}
                {money(
                  selectedPeriod.amount_minor,
                  selectedPeriod.currency,
                  locale,
                )}
              </p>
              <div className="mt-5 flex flex-wrap gap-2">
                {selectedPlan.periods
                  .filter((item) => item.enabled)
                  .map((period) => (
                    <button
                      key={period.id}
                      type="button"
                      onClick={() => {
                        setSelectedPeriodCode(period.id);
                        setCouponResult(null);
                      }}
                      className={`rounded-xl border px-4 py-2 text-sm ${
                        selectedPeriod.id === period.id
                          ? "border-electric-300/40 bg-electric-400/10 text-electric-100"
                          : "border-white/10 text-white/55"
                      }`}
                    >
                      {localized(period.label, locale, period.id)} ·{" "}
                      {money(period.amount_minor, period.currency, locale)}
                    </button>
                  ))}
              </div>
              <div className="mt-6 grid gap-4 lg:grid-cols-[1fr_140px_auto]">
                <input
                  value={coupon}
                  onChange={(event) =>
                    setCoupon(event.target.value.toUpperCase())
                  }
                  placeholder={t("couponPlaceholder")}
                  className="field-control"
                />
                <input
                  value={country}
                  onChange={(event) =>
                    setCountry(event.target.value.toUpperCase().slice(0, 2))
                  }
                  placeholder={t("countryPlaceholder")}
                  className="field-control"
                />
                <Button
                  variant="secondary"
                  disabled={
                    busy || !coupon.trim() || !selectedPeriod.amount_minor
                  }
                  onClick={() => void checkCoupon()}
                >
                  {t("applyCoupon")}
                </Button>
              </div>
              {couponResult && (
                <p className="mt-3 text-sm text-emerald-200">
                  {t("discountSummary", {
                    discount: money(
                      couponResult.discount_minor,
                      selectedPeriod.currency,
                      locale,
                    ),
                    total: money(
                      couponResult.total_minor,
                      selectedPeriod.currency,
                      locale,
                    ),
                  })}
                </p>
              )}
              <Button
                size="lg"
                className="mt-6 w-full"
                disabled={
                  busy || !canManage || !selectedPeriod.checkout_available
                }
                onClick={() => void checkout()}
              >
                {busy ? (
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                ) : (
                  <CreditCard className="h-4 w-4" />
                )}
                {selectedPeriod.checkout_available
                  ? t("continueToPayment")
                  : t("checkoutUnavailable")}
              </Button>
              {!canManage && (
                <p className="mt-3 text-xs text-amber-200">
                  {t("writePermissionRequired")}
                </p>
              )}
              {checkoutResult?.summary.instructions && (
                <div className="mt-6 rounded-2xl border border-electric-300/20 bg-electric-400/[0.06] p-5">
                  <h3 className="font-semibold">{t("paymentInstructions")}</h3>
                  <dl className="mt-4 grid gap-3 sm:grid-cols-2">
                    {Object.entries(checkoutResult.summary.instructions).map(
                      ([key, value]) => (
                        <div key={key}>
                          <dt className="text-xs uppercase tracking-wide text-white/35">
                            {key.replaceAll("_", " ")}
                          </dt>
                          <dd className="mt-1 break-words text-sm text-white/75">
                            {String(value ?? "—")}
                          </dd>
                        </div>
                      ),
                    )}
                  </dl>
                </div>
              )}
            </CardContent>
          </Card>
        )}

        <div className="grid gap-6 xl:grid-cols-2">
          <Card>
            <CardContent>
              <h2 className="text-xl font-semibold">{t("limitsAndUsage")}</h2>
              <div className="mt-5 space-y-3">
                {limits.length ? (
                  limits.map(([key, allowed]) => (
                    <div
                      key={key}
                      className="flex items-center justify-between rounded-xl border border-white/[0.07] px-4 py-3 text-sm"
                    >
                      <span className="text-white/55">
                        {key.replaceAll("_", " ")}
                      </span>
                      <span className="font-semibold">
                        {usage[key] ?? 0} / {String(allowed)}
                      </span>
                    </div>
                  ))
                ) : (
                  <p className="text-sm text-white/40">{t("noLimits")}</p>
                )}
              </div>
              <h3 className="mt-7 font-semibold">{t("entitlements")}</h3>
              <div className="mt-3 flex flex-wrap gap-2">
                {summary.account.entitlements.map((item) => (
                  <span
                    key={item}
                    className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs text-white/55"
                  >
                    {item}
                  </span>
                ))}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent>
              <h2 className="text-xl font-semibold">{t("paymentMethods")}</h2>
              <div className="mt-5 space-y-3">
                {methods.length ? (
                  methods.map((method) => (
                    <div
                      key={method.id}
                      className="rounded-xl border border-white/[0.07] p-4"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div>
                          <p className="font-semibold">
                            {method.brand || method.type}{" "}
                            {method.last4 ? `•••• ${method.last4}` : ""}
                          </p>
                          <p className="mt-1 text-xs text-white/35">
                            {method.provider}
                            {method.expiry_month
                              ? ` · ${method.expiry_month}/${method.expiry_year}`
                              : ""}
                          </p>
                        </div>
                        <div className="flex gap-2">
                          {!method.is_default && (
                            <Button
                              variant="secondary"
                              disabled={busy}
                              onClick={() => void makeDefault(method.id)}
                            >
                              {t("makeDefault")}
                            </Button>
                          )}
                          {method.is_default && (
                            <span className="rounded-lg bg-emerald-400/10 px-3 py-2 text-xs text-emerald-200">
                              {t("defaultMethod")}
                            </span>
                          )}
                          <Button
                            variant="secondary"
                            disabled={busy}
                            onClick={() => void removeMethod(method.id)}
                          >
                            {t("remove")}
                          </Button>
                        </div>
                      </div>
                    </div>
                  ))
                ) : (
                  <p className="text-sm text-white/40">
                    {t("noPaymentMethods")}
                  </p>
                )}
              </div>
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardContent>
            <h2 className="flex items-center gap-2 text-xl font-semibold">
              <ReceiptText className="h-5 w-5 text-electric-200" />{" "}
              {t("invoices")}
            </h2>
            <div className="mt-5 overflow-x-auto">
              <table className="w-full min-w-[760px] text-sm">
                <thead className="text-left text-xs uppercase tracking-wide text-white/35">
                  <tr>
                    <th className="pb-3">{t("invoiceNumber")}</th>
                    <th className="pb-3">{t("date")}</th>
                    <th className="pb-3">{t("provider")}</th>
                    <th className="pb-3">{t("status")}</th>
                    <th className="pb-3 text-right">{t("total")}</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.invoices.map((invoice) => (
                    <tr
                      key={invoice.id}
                      className="border-t border-white/[0.06]"
                    >
                      <td className="py-4 font-semibold">{invoice.number}</td>
                      <td className="py-4 text-white/50">
                        {dateValue(invoice.created_at, locale)}
                      </td>
                      <td className="py-4 text-white/50">{invoice.provider}</td>
                      <td className="py-4 text-white/50">{invoice.status}</td>
                      <td className="py-4 text-right font-semibold">
                        {money(invoice.total_minor, invoice.currency, locale)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!summary.invoices.length && (
                <p className="py-8 text-center text-sm text-white/40">
                  {t("noInvoices")}
                </p>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </section>
  );
}
