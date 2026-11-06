"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import { LoaderCircle, Search, ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import { StatusMessage } from "@/components/ui/status-message";
import { ApiError, getMetaDataDeletionStatus } from "@/lib/api";
import type { MetaDataDeletionStatus } from "@/types";

const CODE_PATTERN = /^[A-Za-z0-9]{8,32}$/;

/** Public data-deletion instructions and the confirmation-code status check. */
export function DataDeletionClient() {
  const t = useTranslations("dataDeletion");
  const format = useFormatter();
  const locale = useLocale();
  const [code, setCode] = useState("");
  const [result, setResult] = useState<MetaDataDeletionStatus | null>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");

  const check = useCallback(
    async (value: string) => {
      const normalized = value.trim();
      if (!CODE_PATTERN.test(normalized)) {
        setResult(null);
        setError(t("status.invalid"));
        return;
      }
      setChecking(true);
      try {
        setResult(await getMetaDataDeletionStatus(normalized));
        setError("");
      } catch (cause) {
        setResult(null);
        setError(cause instanceof ApiError && cause.status === 404 ? t("status.notFound") : t("status.error"));
      } finally {
        setChecking(false);
      }
    },
    [t],
  );

  // Meta's confirmation URL carries ?code=...; read it once on the client.
  useEffect(() => {
    const value = new URLSearchParams(window.location.search).get("code") || "";
    if (CODE_PATTERN.test(value)) {
      setCode(value);
      void check(value);
    }
  }, [check]);

  const steps = [1, 2, 3, 4];

  return (
    <section className="section-pad">
      <article className="page-shell max-w-4xl">
        <span className="eyebrow">
          <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" /> {t("eyebrow")}
        </span>
        <h1 className="section-title mt-7">{t("title")}</h1>
        <p className="section-copy mt-6">{t("intro")}</p>

        <section className="mt-10 border-t border-white/[0.07] pt-8">
          <h2 className="text-xl font-semibold">{t("stepsTitle")}</h2>
          <ol className="mt-4 grid list-decimal gap-3 ps-6 text-sm leading-7 text-white/60">
            {steps.map((index) => (
              <li key={index}>{t(`step${index}`)}</li>
            ))}
          </ol>
        </section>

        <section className="mt-10 border-t border-white/[0.07] pt-8">
          <h2 className="text-xl font-semibold">{t("whatTitle")}</h2>
          <p className="mt-4 whitespace-pre-line text-sm leading-8 text-white/55">{t("whatCopy")}</p>
        </section>

        <section className="mt-10 border-t border-white/[0.07] pt-8" aria-labelledby="deletion-status-title">
          <h2 id="deletion-status-title" className="text-xl font-semibold">
            {t("status.title")}
          </h2>
          <p className="mt-4 text-sm leading-7 text-white/55">{t("status.intro")}</p>
          <form
            className="mt-4 flex flex-wrap items-end gap-3"
            onSubmit={(event) => {
              event.preventDefault();
              void check(code);
            }}
          >
            <label className="grid gap-2 text-xs font-semibold text-white/70">
              {t("status.codeLabel")}
              <input
                value={code}
                onChange={(event) => setCode(event.target.value)}
                maxLength={32}
                autoComplete="off"
                spellCheck={false}
                className="h-11 w-72 max-w-full rounded-xl border border-white/[0.1] bg-black/40 px-4 font-mono text-sm text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crimson-500"
              />
            </label>
            <Button type="submit" disabled={checking}>
              {checking ? (
                <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <Search className="h-4 w-4" aria-hidden="true" />
              )}
              {t("status.check")}
            </Button>
          </form>
          {error && (
            <StatusMessage tone="error" className="mt-4">
              {error}
            </StatusMessage>
          )}
          {result && (
            <StatusMessage tone={result.status === "completed" ? "success" : "info"} className="mt-4">
              <span className="block font-semibold">
                {result.kind === "deletion" ? t("status.kindDeletion") : t("status.kindDeauthorize")} ·{" "}
                {result.status === "completed" ? t("status.completed") : t("status.received")}
              </span>
              <span className="mt-1 block">
                {t("status.requestedAt", {
                  date: format.dateTime(new Date(result.requested_at), { dateStyle: "medium", timeStyle: "short" }),
                })}
              </span>
              {result.completed_at && (
                <span className="block">
                  {t("status.completedAt", {
                    date: format.dateTime(new Date(result.completed_at), { dateStyle: "medium", timeStyle: "short" }),
                  })}
                </span>
              )}
              <span className="mt-1 block">
                {t("status.counts", {
                  connections: result.connections_revoked,
                  accounts: result.accounts_cleared,
                  conversations: result.conversations_deleted,
                })}
              </span>
            </StatusMessage>
          )}
        </section>

        <section className="mt-10 border-t border-white/[0.07] pt-8 text-sm">
          <h2 className="text-xl font-semibold">{t("contactTitle")}</h2>
          <p className="mt-4 leading-7 text-white/55">{t("contactCopy")}</p>
          <div className="mt-4 flex flex-wrap gap-4">
            <Link href={`/${locale}/contact`} className="text-crimson-200 underline underline-offset-4">
              {t("contactLink")}
            </Link>
            <Link href={`/${locale}/legal/privacy`} className="text-crimson-200 underline underline-offset-4">
              {t("privacyLink")}
            </Link>
          </div>
        </section>
      </article>
    </section>
  );
}
