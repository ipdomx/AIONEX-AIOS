"use client";

import {
  Archive,
  BookOpen,
  Brain,
  CheckCircle2,
  Database,
  Loader2,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import {
  phase29fApi,
  type KnowledgeItem,
  type LearningEvent,
  type Lesson,
  type ScopedMemory,
} from "@/lib/phase29f-api";

type Tab = "knowledge" | "memory" | "learning" | "lessons";

const inputClass =
  "glass-input rounded-xl px-3 py-2.5 text-sm text-white outline-none disabled:cursor-not-allowed disabled:opacity-50";
const buttonClass =
  "inline-flex items-center justify-center gap-2 rounded-xl border border-electric-500/20 bg-electric-500/10 px-3 py-2 text-xs font-semibold text-electric-200 transition hover:bg-electric-500/15 disabled:cursor-not-allowed disabled:opacity-50";

export default function KnowledgePage() {
  const [tab, setTab] = useState<Tab>("knowledge");
  const [items, setItems] = useState<KnowledgeItem[]>([]);
  const [memories, setMemories] = useState<ScopedMemory[]>([]);
  const [learning, setLearning] = useState<LearningEvent[]>([]);
  const [lessons, setLessons] = useState<Lesson[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setMessage("");
    try {
      const [knowledgeRows, memoryRows, learningRows, lessonRows] =
        await Promise.all([
          phase29fApi.listKnowledge({ limit: 100 }),
          phase29fApi.listMemories(),
          phase29fApi.listLearningEvents(),
          phase29fApi.listLessons(),
        ]);
      setItems(knowledgeRows);
      setMemories(memoryRows);
      setLearning(learningRows);
      setLessons(lessonRows);
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Knowledge records could not be loaded.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const visibleItems = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return items;
    return items.filter((item) =>
      `${item.subject} ${item.namespace} ${item.content_text} ${item.tags.join(" ")}`
        .toLowerCase()
        .includes(normalized),
    );
  }, [items, query]);

  async function createKnowledge(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    setBusy("knowledge-create");
    try {
      await phase29fApi.createKnowledge({
        scope_type: "organization",
        namespace: String(values.get("namespace") || "default").trim(),
        subject: String(values.get("subject") || "").trim(),
        content_text: String(values.get("content_text") || "").trim(),
        content: { retained_by: "phase29f-dashboard" },
        confidence: Number(values.get("confidence") || 0.7),
        tags: String(values.get("tags") || "")
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
        provenance: [
          {
            source: String(
              values.get("source") || "AIOS internal record",
            ).trim(),
            source_type: "internal",
            source_quality: 0.8,
            direct_evidence: true,
          },
        ],
      });
      form.reset();
      setMessage(
        "Knowledge item ingested with provenance and checksum evidence.",
      );
      await load();
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Knowledge ingestion failed.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function verifyKnowledge(item: KnowledgeItem, accepted: boolean) {
    setBusy(item.id);
    try {
      const updated = await phase29fApi.verifyKnowledge(
        item.id,
        accepted,
        accepted ? Math.max(item.confidence, 0.8) : item.confidence,
      );
      setItems((current) =>
        current.map((row) => (row.id === updated.id ? updated : row)),
      );
      setMessage(
        `Knowledge item ${accepted ? "verified" : "rejected"} and audited.`,
      );
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Knowledge verification failed.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function searchKnowledge() {
    if (!query.trim()) return;
    setBusy("search");
    try {
      setItems(await phase29fApi.searchKnowledge(query.trim()));
      setMessage("Tenant-scoped knowledge search completed.");
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Knowledge search failed.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function createMemory(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    setBusy("memory-create");
    try {
      await phase29fApi.upsertMemory({
        scope_type: "organization",
        key: String(values.get("key") || "").trim(),
        value: { value: String(values.get("value") || "").trim() },
        summary: String(values.get("summary") || "").trim() || null,
        confidence: Number(values.get("confidence") || 0.7),
      });
      form.reset();
      setMessage("Scoped memory saved with version history.");
      await load();
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Memory could not be saved.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function createLearning(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    setBusy("learning-create");
    try {
      await phase29fApi.createLearningEvent({
        action: String(values.get("action") || "").trim(),
        context: { source: "dashboard", phase: "29F" },
        outcome: String(values.get("outcome") || "success"),
        evidence: String(values.get("evidence") || "")
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
        lesson: String(values.get("lesson") || "").trim() || null,
      });
      form.reset();
      setMessage(
        "Learning event retained for verification and lesson promotion.",
      );
      await load();
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Learning event creation failed.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function verifyLearning(item: LearningEvent) {
    setBusy(item.id);
    try {
      const updated = await phase29fApi.verifyLearningEvent(item.id, true);
      setLearning((current) =>
        current.map((row) => (row.id === updated.id ? updated : row)),
      );
      setMessage("Learning evidence verified.");
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Learning verification failed.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function promote(item: LearningEvent) {
    const title = item.lesson || `${item.action} lesson`;
    setBusy(item.id);
    try {
      await phase29fApi.promoteLesson(item.id, title, item.lesson || undefined);
      setMessage("Verified learning promoted to an organizational lesson.");
      await load();
      setTab("lessons");
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Lesson promotion failed.",
      );
    } finally {
      setBusy(null);
    }
  }

  const tabs: Array<[Tab, string, React.ElementType]> = [
    ["knowledge", "Knowledge", BookOpen],
    ["memory", "Scoped Memory", Database],
    ["learning", "Learning Events", Brain],
    ["lessons", "Lessons", Sparkles],
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs text-electric-300">
            <ShieldCheck className="h-3.5 w-3.5" /> Verified Knowledge Plane
          </div>
          <h1 className="mt-3 text-3xl font-bold text-white">
            Knowledge, Memory & Learning
          </h1>
          <p className="mt-2 text-sm text-white/45">
            Retain provenance, verify claims, scope memory, record outcomes, and
            promote reusable lessons.
          </p>
        </div>
        <button
          className={buttonClass}
          onClick={() => void load()}
          disabled={loading}
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />{" "}
          Refresh
        </button>
      </div>

      {message && (
        <div className="rounded-xl border border-electric-500/20 bg-electric-500/10 px-4 py-3 text-sm text-electric-200">
          {message}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {tabs.map(([id, label, Icon]) => (
          <button
            key={id}
            className={`inline-flex items-center gap-2 rounded-xl border px-4 py-2 text-sm ${tab === id ? "border-electric-500/30 bg-electric-500/10 text-electric-200" : "border-white/[0.07] bg-white/[0.03] text-white/50"}`}
            onClick={() => setTab(id)}
          >
            <Icon className="h-4 w-4" /> {label}
          </button>
        ))}
      </div>

      {tab === "knowledge" && (
        <>
          <form
            onSubmit={createKnowledge}
            className="glass-card grid gap-3 p-5 lg:grid-cols-6"
          >
            <input
              name="subject"
              minLength={2}
              required
              placeholder="Knowledge subject"
              className={`${inputClass} lg:col-span-2`}
            />
            <input
              name="namespace"
              defaultValue="default"
              placeholder="Namespace"
              className={inputClass}
            />
            <input
              name="source"
              defaultValue="AIOS internal record"
              placeholder="Provenance source"
              className={inputClass}
            />
            <input
              name="tags"
              placeholder="tags,comma,separated"
              className={inputClass}
            />
            <input
              name="confidence"
              type="number"
              min="0"
              max="1"
              step="0.05"
              defaultValue="0.7"
              className={inputClass}
            />
            <textarea
              name="content_text"
              minLength={1}
              required
              placeholder="Retained knowledge content"
              className={`${inputClass} min-h-28 lg:col-span-5`}
            />
            <button
              className={buttonClass}
              disabled={busy === "knowledge-create"}
            >
              {busy === "knowledge-create" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Plus className="h-4 w-4" />
              )}{" "}
              Ingest
            </button>
          </form>

          <div className="flex gap-2">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/30" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search subject, content, namespace, or tags"
                className={`${inputClass} w-full pl-10`}
              />
            </div>
            <button
              className={buttonClass}
              disabled={!query.trim() || busy === "search"}
              onClick={() => void searchKnowledge()}
            >
              <Search className="h-4 w-4" /> Search
            </button>
          </div>

          {loading ? (
            <Loading />
          ) : visibleItems.length === 0 ? (
            <Empty text="No knowledge items are currently visible." />
          ) : (
            <div className="grid gap-4 xl:grid-cols-2">
              {visibleItems.map((item) => (
                <section key={item.id} className="glass-card p-5">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <h2 className="font-semibold text-white">
                          {item.subject}
                        </h2>
                        <span
                          className={`rounded-full px-2 py-0.5 text-[10px] ${item.status === "verified" ? "bg-green-500/10 text-green-300" : item.status === "rejected" ? "bg-red-500/10 text-red-300" : "bg-amber-500/10 text-amber-200"}`}
                        >
                          {item.status}
                        </span>
                      </div>
                      <p className="mt-1 text-xs text-white/35">
                        {item.namespace} · {item.scope_type} · confidence{" "}
                        {Math.round(item.confidence * 100)}%
                      </p>
                    </div>
                    <BookOpen className="h-5 w-5 text-electric-300" />
                  </div>
                  <p className="mt-4 whitespace-pre-wrap text-sm leading-6 text-white/60">
                    {item.content_text}
                  </p>
                  <div className="mt-4 rounded-xl border border-white/[0.06] bg-black/15 p-3 text-xs text-white/40">
                    <p>
                      Provenance:{" "}
                      {item.provenance
                        .map((source) => source.source)
                        .join(", ") || "None"}
                    </p>
                    <p className="mt-1 break-all font-mono text-[10px] text-white/25">
                      {item.checksum}
                    </p>
                  </div>
                  {item.status === "pending" && (
                    <div className="mt-4 flex gap-2">
                      <button
                        className={buttonClass}
                        disabled={busy === item.id}
                        onClick={() => void verifyKnowledge(item, true)}
                      >
                        <CheckCircle2 className="h-3.5 w-3.5" /> Verify
                      </button>
                      <button
                        className={buttonClass}
                        disabled={busy === item.id}
                        onClick={() => void verifyKnowledge(item, false)}
                      >
                        <Archive className="h-3.5 w-3.5" /> Reject
                      </button>
                    </div>
                  )}
                </section>
              ))}
            </div>
          )}
        </>
      )}

      {tab === "memory" && (
        <>
          <form
            onSubmit={createMemory}
            className="glass-card grid gap-3 p-5 lg:grid-cols-5"
          >
            <input
              name="key"
              minLength={1}
              required
              placeholder="Memory key"
              className={inputClass}
            />
            <input
              name="value"
              required
              placeholder="Memory value"
              className={`${inputClass} lg:col-span-2`}
            />
            <input
              name="confidence"
              type="number"
              min="0"
              max="1"
              step="0.05"
              defaultValue="0.7"
              className={inputClass}
            />
            <button className={buttonClass} disabled={busy === "memory-create"}>
              <Plus className="h-4 w-4" /> Save memory
            </button>
            <input
              name="summary"
              placeholder="Summary and usage boundary"
              className={`${inputClass} lg:col-span-5`}
            />
          </form>
          {loading ? (
            <Loading />
          ) : memories.length === 0 ? (
            <Empty text="No scoped memories are retained." />
          ) : (
            <div className="grid gap-4 xl:grid-cols-2">
              {memories.map((memory) => (
                <section key={memory.id} className="glass-card p-5">
                  <div className="flex items-center justify-between">
                    <h2 className="font-semibold text-white">{memory.key}</h2>
                    <span className="text-xs text-white/35">
                      v{memory.version}
                    </span>
                  </div>
                  <p className="mt-2 text-xs text-white/35">
                    {memory.scope_type} · {memory.status} · confidence{" "}
                    {Math.round(memory.confidence * 100)}%
                  </p>
                  <p className="mt-4 text-sm text-white/55">
                    {memory.summary || JSON.stringify(memory.value)}
                  </p>
                </section>
              ))}
            </div>
          )}
        </>
      )}

      {tab === "learning" && (
        <>
          <form
            onSubmit={createLearning}
            className="glass-card grid gap-3 p-5 lg:grid-cols-5"
          >
            <input
              name="action"
              minLength={2}
              required
              placeholder="Action or experiment"
              className={`${inputClass} lg:col-span-2`}
            />
            <select
              name="outcome"
              defaultValue="success"
              className={inputClass}
            >
              <option value="success">Success</option>
              <option value="partial">Partial</option>
              <option value="failure">Failure</option>
              <option value="unknown">Unknown</option>
            </select>
            <input
              name="evidence"
              placeholder="evidence ids, comma separated"
              className={inputClass}
            />
            <button
              className={buttonClass}
              disabled={busy === "learning-create"}
            >
              <Plus className="h-4 w-4" /> Record
            </button>
            <textarea
              name="lesson"
              placeholder="Candidate lesson"
              className={`${inputClass} min-h-24 lg:col-span-5`}
            />
          </form>
          {loading ? (
            <Loading />
          ) : learning.length === 0 ? (
            <Empty text="No learning events are currently retained." />
          ) : (
            <div className="space-y-3">
              {learning.map((item) => (
                <section key={item.id} className="glass-card p-5">
                  <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <h2 className="font-semibold text-white">
                          {item.action}
                        </h2>
                        <span className="rounded-full border border-white/[0.08] px-2 py-0.5 text-[10px] text-white/45">
                          {item.outcome}
                        </span>
                        <span className="rounded-full bg-purple-500/10 px-2 py-0.5 text-[10px] text-purple-300">
                          {item.status}
                        </span>
                      </div>
                      <p className="mt-2 text-sm text-white/50">
                        {item.lesson || "No lesson proposed."}
                      </p>
                      <p className="mt-2 text-xs text-white/30">
                        Evidence: {item.evidence.join(", ") || "none"}
                      </p>
                    </div>
                    <div className="flex gap-2">
                      {item.status === "pending" && (
                        <button
                          className={buttonClass}
                          disabled={busy === item.id}
                          onClick={() => void verifyLearning(item)}
                        >
                          <CheckCircle2 className="h-3.5 w-3.5" /> Verify
                        </button>
                      )}
                      {item.status === "verified" && (
                        <button
                          className={buttonClass}
                          disabled={busy === item.id || !item.lesson}
                          onClick={() => void promote(item)}
                        >
                          <Sparkles className="h-3.5 w-3.5" /> Promote lesson
                        </button>
                      )}
                    </div>
                  </div>
                </section>
              ))}
            </div>
          )}
        </>
      )}

      {tab === "lessons" &&
        (loading ? (
          <Loading />
        ) : lessons.length === 0 ? (
          <Empty text="No lessons have been promoted." />
        ) : (
          <div className="grid gap-4 xl:grid-cols-2">
            {lessons.map((lesson) => (
              <section key={lesson.id} className="glass-card p-5">
                <div className="flex items-center justify-between">
                  <h2 className="font-semibold text-white">{lesson.title}</h2>
                  <Sparkles className="h-5 w-5 text-purple-300" />
                </div>
                <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-white/60">
                  {lesson.lesson}
                </p>
                <p className="mt-3 text-xs text-white/35">
                  confidence {Math.round(lesson.confidence * 100)}% ·{" "}
                  {lesson.status} · version {lesson.version}
                </p>
              </section>
            ))}
          </div>
        ))}
    </div>
  );
}

function Loading() {
  return (
    <div className="glass-card flex min-h-44 items-center justify-center text-white/45">
      <Loader2 className="me-2 h-5 w-5 animate-spin" />
      Loading retained evidence…
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="glass-card p-10 text-center text-sm text-white/40">
      {text}
    </div>
  );
}
