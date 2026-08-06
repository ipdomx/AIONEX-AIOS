"use client";

import { useCallback, useEffect, useState } from "react";
import {
  LifeBuoy,
  Loader2,
  MessageSquareText,
  RefreshCw,
  Send,
} from "lucide-react";

import { useLanguageVoice } from "@/components/providers/LanguageVoiceProvider";
import { translateInterfaceText } from "@/lib/interface-translations";
import {
  fetchSupportRequest,
  fetchSupportRequests,
  replyToSupportRequest,
  updateSupportRequest,
  type SupportRequest,
} from "@/lib/owner-communications";

export default function OwnerSupportPage() {
  const { locale } = useLanguageVoice();
  const t = useCallback(
    (text: string) => translateInterfaceText(text, locale),
    [locale],
  );
  const [tickets, setTickets] = useState<SupportRequest[]>([]);
  const [selected, setSelected] = useState<SupportRequest | null>(null);
  const [reply, setReply] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setMessage("");
    try {
      setTickets(await fetchSupportRequests());
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : t("Unable to load support requests."),
      );
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function openTicket(ticket: SupportRequest) {
    setLoading(true);
    setMessage("");
    try {
      setSelected(await fetchSupportRequest(ticket.id));
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : t("Unable to load support request."),
      );
    } finally {
      setLoading(false);
    }
  }

  async function sendReply() {
    if (!selected || !reply.trim()) return;
    setBusy(true);
    setMessage("");
    try {
      await replyToSupportRequest(selected.id, {
        message: reply.trim(),
        visibility: "requester",
      });
      setReply("");
      setSelected(await fetchSupportRequest(selected.id));
      setTickets(await fetchSupportRequests());
      setMessage(t("Reply delivered and recorded."));
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : t("Unable to send the reply."),
      );
    } finally {
      setBusy(false);
    }
  }

  async function setStatus(status: string) {
    if (!selected) return;
    setBusy(true);
    setMessage("");
    try {
      await updateSupportRequest(selected.id, { status });
      setSelected(await fetchSupportRequest(selected.id));
      setTickets(await fetchSupportRequests());
      setMessage(t("Support request status updated."));
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : t("Unable to update the support request."),
      );
    } finally {
      setBusy(false);
    }
  }

  const openCount = tickets.filter(
    (ticket) => !["resolved", "closed"].includes(ticket.status),
  ).length;

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs text-electric-300">
            <LifeBuoy className="h-3.5 w-3.5" />
            {t("Owner Support Command")}
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-white">
            {t("Durable Support Operations")}
          </h1>
          <p className="mt-1 max-w-3xl text-sm text-white/40">
            {t(
              "Review tenant requests, preserve every message, assign work, and close the loop with auditable status changes.",
            )}
          </p>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-xl border border-white/[0.08] bg-white/[0.04] px-4 py-2 text-xs text-white/70 hover:bg-white/[0.08] disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          {t("Refresh")}
        </button>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <div className="glass-card p-5">
          <div className="text-2xl font-bold text-white">{tickets.length}</div>
          <div className="mt-1 text-xs text-white/35">
            {t("Total requests")}
          </div>
        </div>
        <div className="glass-card p-5">
          <div className="text-2xl font-bold text-orange-300">{openCount}</div>
          <div className="mt-1 text-xs text-white/35">{t("Open requests")}</div>
        </div>
        <div className="glass-card p-5">
          <div className="text-2xl font-bold text-green-300">
            {tickets.filter((ticket) => ticket.status === "resolved").length}
          </div>
          <div className="mt-1 text-xs text-white/35">
            {t("Resolved requests")}
          </div>
        </div>
      </div>

      {message ? (
        <div className="rounded-xl border border-electric-500/20 bg-electric-500/10 px-4 py-3 text-xs text-electric-300">
          {message}
        </div>
      ) : null}

      {selected ? (
        <div className="glass-card p-6">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <button
                type="button"
                onClick={() => setSelected(null)}
                className="text-xs text-white/45 hover:text-white"
              >
                {t("Back to requests")}
              </button>
              <h2 className="mt-4 text-xl font-semibold text-white">
                {selected.subject}
              </h2>
              <p className="mt-2 text-xs text-white/35">
                {selected.id} · {selected.organization_id} · {selected.category}{" "}
                · {selected.priority} · {selected.status}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                disabled={busy}
                onClick={() => void setStatus("in_progress")}
                className="rounded-xl border border-orange-500/20 bg-orange-500/10 px-3 py-2 text-xs text-orange-300 disabled:opacity-50"
              >
                {t("Start work")}
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void setStatus("resolved")}
                className="rounded-xl border border-green-500/20 bg-green-500/10 px-3 py-2 text-xs text-green-300 disabled:opacity-50"
              >
                {t("Resolve")}
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void setStatus("closed")}
                className="rounded-xl border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-xs text-white/65 disabled:opacity-50"
              >
                {t("Close")}
              </button>
            </div>
          </div>

          <div className="mt-6 space-y-3">
            {(selected.messages || []).map((entry) => (
              <div
                key={entry.id}
                className="rounded-xl border border-white/[0.06] bg-black/15 p-4"
              >
                <div className="flex items-center justify-between gap-3 text-[10px] uppercase tracking-wider text-white/30">
                  <span>{entry.visibility}</span>
                  <span>{entry.created_at}</span>
                </div>
                <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-white/70">
                  {entry.message}
                </p>
              </div>
            ))}
          </div>

          {selected.status !== "closed" ? (
            <div className="mt-6 flex flex-col gap-3 lg:flex-row">
              <textarea
                value={reply}
                onChange={(event) => setReply(event.target.value)}
                placeholder={t("Write a durable reply")}
                className="min-h-28 flex-1 rounded-xl border border-white/[0.08] bg-black/20 p-4 text-sm text-white outline-none focus:border-electric-500/40"
              />
              <button
                type="button"
                disabled={busy || !reply.trim()}
                onClick={() => void sendReply()}
                className="inline-flex self-end items-center gap-2 rounded-xl border border-electric-500/20 bg-electric-500/10 px-4 py-3 text-xs text-electric-300 disabled:opacity-50"
              >
                {busy ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
                {t("Send reply")}
              </button>
            </div>
          ) : null}
        </div>
      ) : loading ? (
        <div className="glass-card flex min-h-48 items-center justify-center text-sm text-white/40">
          <Loader2 className="me-2 h-5 w-5 animate-spin" />
          {t("Loading support requests…")}
        </div>
      ) : tickets.length === 0 ? (
        <div className="glass-card p-10 text-center text-sm text-white/40">
          {t("No support requests are currently recorded.")}
        </div>
      ) : (
        <div className="space-y-3">
          {tickets.map((ticket) => (
            <button
              type="button"
              key={ticket.id}
              onClick={() => void openTicket(ticket)}
              className="glass-card flex w-full items-center justify-between gap-4 p-5 text-start transition hover:bg-white/[0.04]"
            >
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="truncate text-sm font-semibold text-white">
                    {ticket.subject}
                  </span>
                  <span className="rounded-full border border-white/[0.08] px-2 py-0.5 text-[10px] text-white/45">
                    {ticket.status}
                  </span>
                  <span className="rounded-full border border-orange-500/20 bg-orange-500/10 px-2 py-0.5 text-[10px] text-orange-300">
                    {ticket.priority}
                  </span>
                </div>
                <p className="mt-2 truncate text-xs text-white/35">
                  {ticket.id} · {ticket.organization_id} · {ticket.category} ·{" "}
                  {ticket.updated_at}
                </p>
              </div>
              <MessageSquareText className="h-5 w-5 shrink-0 text-electric-300" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
