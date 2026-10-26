"use client";

import { useCallback, useEffect, useState } from "react";
import { ClipboardList, RefreshCw, ShieldAlert } from "lucide-react";

import {
  getOwnerIdentityMediaRecoveryReview,
  type OwnerIdentityMediaRecoveryReview,
} from "@/lib/owner-identity-media";

/** Read-only Owner inventory; no controls that retry, cancel or charge a provider. */
export default function IdentityMediaRecoveryReview() {
  const [review, setReview] = useState<OwnerIdentityMediaRecoveryReview | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [unverified, setUnverified] = useState(false);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    try {
      const value = await getOwnerIdentityMediaRecoveryReview(signal);
      if (!signal?.aborted) {
        setReview(value);
        setUnverified(false);
      }
    } catch {
      if (!signal?.aborted) {
        setReview(null);
        setUnverified(true);
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

  return (
    <section
      data-identity-media-recovery-review
      className="glass-card space-y-4 p-5 sm:p-6"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <ClipboardList className="h-5 w-5 text-electric-300" />
            <h2 className="text-lg font-semibold text-white">
              Execution recovery review
            </h2>
          </div>
          <p className="mt-2 max-w-3xl text-xs leading-5 text-white/55">
            Read-only provider provenance checks. Automatic replay is disabled.
          </p>
        </div>
        <button
          type="button"
          className="btn-secondary"
          disabled={loading}
          onClick={() => void load()}
        >
          <RefreshCw className="mr-2 inline h-4 w-4" />
          Refresh review
        </button>
      </div>

      {loading && (
        <p className="text-sm text-white/50">
          Reading execution review queue...
        </p>
      )}
      {!loading && (unverified || !review) && (
        <p role="status" className="text-sm text-amber-200">
          Review queue not verified; retry read-only refresh.
        </p>
      )}

      {!loading && review && (
        <>
          <div
            className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5"
            data-review-counts
          >
            <div className="rounded-lg border border-white/10 p-3 text-sm">
              Manual review required: {review.total_review_required}
            </div>
            <div className="rounded-lg border border-white/10 p-3 text-sm">
              Without provider reference: {review.no_provider_reference}
            </div>
            <div className="rounded-lg border border-white/10 p-3 text-sm">
              Provider reference recorded: {review.provider_reference_recorded}
            </div>
            <div className="rounded-lg border border-white/10 p-3 text-sm">
              Failed with unverified provider state:{" "}
              {review.failed_provider_state_unverified}
            </div>
            <div className="rounded-lg border border-white/10 p-3 text-sm">
              Failed without provider reference:{" "}
              {review.failed_no_provider_reference}
            </div>
          </div>
          {review.total_review_required === 0 &&
          review.failed_provider_state_unverified === 0 ? (
            <p className="text-sm text-white/55">
              No outstanding execution reviews.
            </p>
          ) : (
            <>
              <div className="flex items-start gap-2 rounded-lg border border-amber-500/20 bg-amber-500/5 p-3 text-xs text-amber-100/85">
                <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
                <div>
                  <p className="font-semibold">Automatic replay disabled</p>
                  <p className="mt-1">
                    Provider ledger and billing evidence must be reconciled
                    before any retry.
                  </p>
                </div>
              </div>
              <ul className="space-y-2" data-review-executions>
                {review.executions.map((execution) => (
                  <li
                    key={execution.execution_id}
                    className="rounded-lg border border-white/10 px-3 py-2 text-xs text-white/65"
                  >
                    <div className="break-all font-mono text-white/75">
                      {execution.execution_id}
                    </div>
                    <p className="mt-1">
                      {execution.operation} / {execution.provider}
                    </p>
                    <p className="mt-1 text-amber-200/90">
                      {execution.provider_reference_recorded
                        ? "Provider reference recorded; verify before retry."
                        : "No provider reference; manual reconciliation required."}
                    </p>
                  </li>
                ))}
              </ul>
              {review.truncated && (
                <p className="text-xs text-amber-200">
                  Additional review records remain beyond this page.
                </p>
              )}
              {review.failed_provider_state_unverified > 0 && (
                <div className="space-y-2" data-failed-provider-state>
                  <p className="text-sm text-amber-200/90">
                    Locally failed, remote provider outcome not confirmed:{" "}
                    {review.failed_provider_state_unverified}
                  </p>
                  <ul className="space-y-2">
                    {review.failed_provider_state_executions.map(
                      (execution) => (
                        <li
                          key={execution.execution_id}
                          className="rounded-lg border border-amber-500/20 px-3 py-2 text-xs text-white/65"
                        >
                          <div className="break-all font-mono text-white/75">
                            {execution.execution_id}
                          </div>
                          <p className="mt-1">
                            {execution.operation} / {execution.provider} /{" "}
                            {execution.provider_state}
                          </p>
                          <p className="mt-1 text-amber-200/90">
                            {execution.provider_reference_recorded
                              ? "Provider reference exists; check remote terminal status before settlement."
                              : "No provider reference; check remote history and billing before any retry."}
                          </p>
                        </li>
                      ),
                    )}
                  </ul>
                  {review.failed_provider_state_truncated && (
                    <p className="text-xs text-amber-200">
                      Additional unverified failed provider records remain.
                    </p>
                  )}
                </div>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
