"use client";

import {
  ArrowLeft,
  LoaderCircle,
  MessageSquareText,
  Plus,
  RefreshCw,
  Send,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { StatusMessage } from "@/components/ui/status-message";
import { useAuth } from "@/hooks/use-auth";
import {
  createSupportRequest,
  getSupportRequest,
  listSupportRequests,
  replyToSupportRequest,
} from "@/lib/api";
import type { SupportTicket } from "@/types";

function formatDate(value: string, locale: string): string {
  try {
    return new Intl.DateTimeFormat(locale, {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(value));
  } catch {
    return value;
  }
}

export function SupportClient() {
  const t = useTranslations("support");
  const locale = useLocale();
  const router = useRouter();
  const { isAuthenticated, isLoading } = useAuth();
  const [tickets, setTickets] = useState<SupportTicket[]>([]);
  const [selected, setSelected] = useState<SupportTicket | null>(null);
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [reply, setReply] = useState("");
  const [category, setCategory] = useState("general");
  const [priority, setPriority] = useState("normal");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    if (!isLoading && !isAuthenticated) router.replace(`/${locale}/login`);
  }, [isAuthenticated, isLoading, locale, router]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setTickets(await listSupportRequests());
    } catch {
      setError(t("loadError"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    if (isAuthenticated) void load();
  }, [isAuthenticated, load]);

  async function openTicket(ticket: SupportTicket) {
    setLoading(true);
    setError("");
    try {
      setSelected(await getSupportRequest(ticket.id));
    } catch {
      setError(t("loadError"));
    } finally {
      setLoading(false);
    }
  }

  async function submitTicket() {
    if (!subject.trim() || message.trim().length < 10) return;
    setSaving(true);
    setError("");
    try {
      const ticket = await createSupportRequest(subject.trim(), message.trim(), {
        category,
        priority,
      });
      setTickets((current) => [ticket, ...current]);
      setSubject("");
      setMessage("");
      setNotice(t("created"));
      await openTicket(ticket);
    } catch {
      setError(t("saveError"));
    } finally {
      setSaving(false);
    }
  }

  async function submitReply() {
    if (!selected || !reply.trim()) return;
    setSaving(true);
    setError("");
    try {
      await replyToSupportRequest(selected.id, reply.trim());
      setReply("");
      setSelected(await getSupportRequest(selected.id));
      setNotice(t("replySent"));
    } catch {
      setError(t("saveError"));
    } finally {
      setSaving(false);
    }
  }

  if (isLoading || (!isAuthenticated && !error)) {
    return (
      <section className="section-pad">
        <div className="page-shell flex min-h-[45vh] items-center justify-center">
          <LoaderCircle className="h-8 w-8 animate-spin text-electric-200" />
        </div>
      </section>
    );
  }

  return (
    <section className="section-pad">
      <div className="page-shell">
        <div className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <span className="eyebrow">{t("eyebrow")}</span>
            <h1 className="section-title mt-6">{t("title")}</h1>
            <p className="section-copy mt-4">{t("description")}</p>
          </div>
          <Button
            variant="secondary"
            onClick={() => void load()}
            disabled={loading}
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            {t("refresh")}
          </Button>
        </div>

        {error && (
          <StatusMessage tone="error" className="mt-6">
            {error}
          </StatusMessage>
        )}
        {notice && !error && (
          <StatusMessage tone="success" className="mt-6">
            {notice}
          </StatusMessage>
        )}

        {selected ? (
          <Card className="mt-8">
            <CardContent>
              <button
                type="button"
                onClick={() => setSelected(null)}
                className="inline-flex items-center gap-2 text-sm text-white/55 hover:text-white"
              >
                <ArrowLeft className="h-4 w-4 rtl:rotate-180" />
                {t("back")}
              </button>
              <div className="mt-6 flex flex-wrap items-start justify-between gap-4">
                <div>
                  <h2 className="text-2xl font-semibold">{selected.subject}</h2>
                  <p className="mt-2 text-sm text-white/40">
                    {selected.category} · {selected.priority} · {selected.status}
                  </p>
                </div>
                <span className="rounded-full border border-white/10 px-3 py-1.5 text-xs text-white/50">
                  {selected.id}
                </span>
              </div>
              <div className="mt-8 space-y-4">
                {(selected.messages || []).map((item) => (
                  <div
                    key={item.id}
                    className="rounded-2xl border border-white/[0.07] bg-black/15 p-5"
                  >
                    <p className="whitespace-pre-wrap text-sm leading-7 text-white/70">
                      {item.message}
                    </p>
                    <p className="mt-3 text-xs text-white/30">
                      {formatDate(item.created_at, locale)}
                    </p>
                  </div>
                ))}
              </div>
              {selected.status !== "closed" && (
                <div className="mt-8 flex flex-col gap-3 sm:flex-row">
                  <textarea
                    value={reply}
                    onChange={(event) => setReply(event.target.value)}
                    placeholder={t("replyPlaceholder")}
                    className="min-h-24 flex-1 rounded-2xl border border-white/10 bg-black/20 p-4 text-white placeholder:text-white/25"
                  />
                  <Button
                    className="self-end"
                    onClick={() => void submitReply()}
                    disabled={saving || !reply.trim()}
                  >
                    <Send className="h-4 w-4" />
                    {t("sendReply")}
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>
        ) : (
          <div className="mt-8 grid gap-6 xl:grid-cols-[.75fr_1.25fr]">
            <Card>
              <CardContent>
                <h2 className="text-xl font-semibold">{t("newTicket")}</h2>
                <div className="mt-5 grid gap-3">
                  <input
                    value={subject}
                    onChange={(event) => setSubject(event.target.value)}
                    placeholder={t("subject")}
                    className="h-11 rounded-xl border border-white/10 bg-black/20 px-3 text-white placeholder:text-white/25"
                  />
                  <div className="grid grid-cols-2 gap-3">
                    <select
                      value={category}
                      onChange={(event) => setCategory(event.target.value)}
                      className="h-11 rounded-xl border border-white/10 bg-ink-950 px-3 text-white"
                    >
                      {[
                        "general",
                        "technical",
                        "billing",
                        "security",
                        "account",
                        "project",
                      ].map((value) => (
                        <option key={value} value={value}>
                          {t(`category.${value}`)}
                        </option>
                      ))}
                    </select>
                    <select
                      value={priority}
                      onChange={(event) => setPriority(event.target.value)}
                      className="h-11 rounded-xl border border-white/10 bg-ink-950 px-3 text-white"
                    >
                      {['low', 'normal', 'high', 'urgent'].map((value) => (
                        <option key={value} value={value}>
                          {t(`priority.${value}`)}
                        </option>
                      ))}
                    </select>
                  </div>
                  <textarea
                    value={message}
                    onChange={(event) => setMessage(event.target.value)}
                    placeholder={t("message")}
                    className="min-h-36 rounded-2xl border border-white/10 bg-black/20 p-4 text-white placeholder:text-white/25"
                  />
                  <Button
                    onClick={() => void submitTicket()}
                    disabled={saving || !subject.trim() || message.trim().length < 10}
                  >
                    <Plus className="h-4 w-4" />
                    {t("create")}
                  </Button>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent>
                <h2 className="text-xl font-semibold">{t("history")}</h2>
                <div className="mt-5 space-y-3">
                  {tickets.length ? (
                    tickets.map((ticket) => (
                      <button
                        key={ticket.id}
                        type="button"
                        onClick={() => void openTicket(ticket)}
                        className="flex w-full items-center justify-between gap-4 rounded-2xl border border-white/[0.07] bg-black/15 p-5 text-start transition hover:bg-white/[0.04]"
                      >
                        <div className="min-w-0">
                          <p className="truncate font-semibold text-white">
                            {ticket.subject}
                          </p>
                          <p className="mt-2 text-xs text-white/35">
                            {formatDate(ticket.updated_at, locale)} · {ticket.status}
                          </p>
                        </div>
                        <MessageSquareText className="h-5 w-5 shrink-0 text-electric-200" />
                      </button>
                    ))
                  ) : (
                    <div className="rounded-2xl border border-dashed border-white/10 px-6 py-12 text-center text-sm text-white/40">
                      {t("empty")}
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          </div>
        )}
      </div>
    </section>
  );
}
