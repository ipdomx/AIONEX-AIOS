"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { RefreshCw, ShieldCheck, Stethoscope } from "lucide-react";

import {
  professionalApi,
  type ProfessionalCase,
  type ProtectedDataProfiles,
} from "@/lib/professional-api";

const inputClass =
  "glass-input rounded-xl px-3 py-2.5 text-sm text-white outline-none disabled:opacity-50";
const buttonClass =
  "inline-flex items-center justify-center gap-2 rounded-xl border border-electric-500/20 bg-electric-500/10 px-3 py-2 text-xs font-semibold text-electric-200 transition hover:bg-electric-500/15 disabled:opacity-50";

export default function ProfessionalPage() {
  const [cases, setCases] = useState<ProfessionalCase[]>([]);
  const [profiles, setProfiles] = useState<ProtectedDataProfiles | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    try {
      const [caseRows, profileRows] = await Promise.all([
        professionalApi.listCases(),
        professionalApi.profiles(),
      ]);
      setCases(caseRows);
      setProfiles(profileRows);
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Professional evidence could not be loaded.",
      );
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function createCase(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setBusy("create");
    try {
      await professionalApi.createCase({
        case_mode: String(data.get("case_mode") || "clinical_high_stakes"),
        purpose: String(data.get("purpose") || "").trim(),
        subject_reference: String(data.get("subject_reference") || "").trim(),
        request_summary: String(data.get("request_summary") || "").trim(),
        direct_identifiers_removed:
          data.get("direct_identifiers_removed") === "on",
        residency_profile: String(
          data.get("residency_profile") || "tenant-default",
        ),
        citations: [1, 2].map((index) => ({
          citation_id: `source-${index}`,
          title: String(data.get(`source_${index}_title`) || "").trim(),
          uri: String(data.get(`source_${index}_uri`) || "").trim(),
          source_sha256: String(
            data.get(`source_${index}_sha256`) || "",
          ).trim(),
        })),
      });
      form.reset();
      setMessage(
        "Evidence case created. Raw subject reference was not persisted; human review is pending.",
      );
      await load();
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Case creation failed.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function decide(item: ProfessionalCase, decision: string) {
    setBusy(item.id);
    try {
      await professionalApi.reviewCase(
        item.id,
        decision,
        decision === "approved"
          ? "Evidence and provenance reviewed by an authorized human reviewer."
          : "Human reviewer rejected this evidence package.",
      );
      setMessage(`Human review recorded: ${decision}.`);
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Review failed.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.2em] text-electric-300">
            <Stethoscope className="h-4 w-4" /> Professional Evidence
          </div>
          <h1 className="text-2xl font-bold text-white">
            Healthcare & high-stakes review controls
          </h1>
          <p className="mt-2 max-w-3xl text-sm text-slate-400">
            Pseudonymous evidence cases, bounded retention, source provenance
            and mandatory human review. Compliance profiles are configuration
            templates, not certifications.
          </p>
        </div>
        <button className={buttonClass} onClick={() => void load()}>
          <RefreshCw className="h-3.5 w-3.5" /> Refresh
        </button>
      </div>

      {message ? (
        <div className="glass-card rounded-xl p-3 text-sm text-slate-200">
          {message}
        </div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[1.05fr_0.95fr]">
        <form
          className="glass-card space-y-3 rounded-2xl p-5"
          onSubmit={createCase}
        >
          <h2 className="font-semibold text-white">
            Create governed evidence case
          </h2>
          <select
            className={inputClass}
            name="case_mode"
            defaultValue="clinical_high_stakes"
          >
            <option value="clinical_high_stakes">
              Clinical high-stakes review
            </option>
            <option value="professional_assistance">
              Professional assistance
            </option>
            <option value="administrative">Healthcare administration</option>
            <option value="education">Professional education</option>
          </select>
          <input
            className={inputClass}
            name="purpose"
            placeholder="Purpose"
            required
          />
          <input
            className={inputClass}
            name="subject_reference"
            placeholder="Subject reference (hashed before persistence)"
            required
          />
          <textarea
            className={`${inputClass} min-h-24 w-full`}
            name="request_summary"
            placeholder="Redacted request summary"
            required
          />
          <select
            className={inputClass}
            name="residency_profile"
            defaultValue="tenant-default"
          >
            {Object.keys(profiles?.profiles || { "tenant-default": {} }).map(
              (key) => (
                <option key={key} value={key}>
                  {key}
                </option>
              ),
            )}
          </select>
          {[1, 2].map((index) => (
            <div
              className="grid gap-2 rounded-xl border border-white/10 p-3"
              key={index}
            >
              <span className="text-xs text-slate-400">
                Evidence source {index}
              </span>
              <input
                className={inputClass}
                name={`source_${index}_title`}
                placeholder="Source title"
                required
              />
              <input
                className={inputClass}
                name={`source_${index}_uri`}
                placeholder="https://… or internal://…"
                required
              />
              <input
                className={inputClass}
                name={`source_${index}_sha256`}
                placeholder="SHA-256 digest"
                minLength={64}
                maxLength={64}
                required
              />
            </div>
          ))}
          <label className="flex items-start gap-2 text-xs text-slate-300">
            <input
              className="mt-0.5"
              type="checkbox"
              name="direct_identifiers_removed"
              required
            />
            I confirm direct identifiers were removed from the durable request
            summary.
          </label>
          <button
            className={buttonClass}
            disabled={busy === "create"}
            type="submit"
          >
            <ShieldCheck className="h-3.5 w-3.5" /> Create pending-review case
          </button>
        </form>

        <div className="space-y-3">
          <div className="glass-card rounded-2xl p-4 text-xs text-slate-300">
            <strong className="text-white">Fail-closed:</strong> autonomous
            high-stakes decisions are disabled. Local legal validation remains
            required for every residency/compliance profile.
          </div>
          {cases.map((item) => (
            <div className="glass-card rounded-2xl p-4" key={item.id}>
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold text-white">
                    {item.purpose}
                  </div>
                  <div className="text-xs text-slate-400">
                    {item.case_mode} · {item.status} · review v
                    {item.review_version}
                  </div>
                </div>
                <span className="rounded-full border border-white/10 px-2 py-1 text-[11px] text-slate-300">
                  {item.residency_profile}
                </span>
              </div>
              <p className="mt-3 text-sm text-slate-300">
                {item.request_summary}
              </p>
              <div className="mt-3 break-all text-[11px] text-slate-500">
                Evidence: {item.evidence_digest}
              </div>
              {item.status === "pending_review" ? (
                <div className="mt-4 flex gap-2">
                  <button
                    className={buttonClass}
                    disabled={busy === item.id}
                    onClick={() => void decide(item, "approved")}
                  >
                    Approve
                  </button>
                  <button
                    className={buttonClass}
                    disabled={busy === item.id}
                    onClick={() => void decide(item, "rejected")}
                  >
                    Reject
                  </button>
                </div>
              ) : null}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
