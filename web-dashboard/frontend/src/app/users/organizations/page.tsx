"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Building2, Plus, RefreshCw } from "lucide-react";
import { identityApi, type OrganizationRecord } from "@/lib/identity-api";

export default function OrganizationsPage() {
  const [items, setItems] = useState<OrganizationRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("Loading organizations...");

  async function load() {
    setLoading(true);
    try {
      const result = await identityApi.organizations();
      setItems(result);
      setMessage(`Synchronized ${result.length} organizations.`);
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Organization load failed",
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    try {
      const created = await identityApi.createOrganization({
        name: String(form.get("name") || "").trim(),
        slug: String(form.get("slug") || "").trim() || undefined,
        plan: String(form.get("plan") || "enterprise"),
      });
      setItems((current) => [created, ...current]);
      event.currentTarget.reset();
      setMessage("Organization created.");
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Organization creation failed",
      );
    } finally {
      setBusy(false);
    }
  }

  async function toggle(item: OrganizationRecord) {
    setBusy(true);
    try {
      const updated = await identityApi.updateOrganization(item.id, {
        status: item.status === "active" ? "inactive" : "active",
      });
      setItems((current) =>
        current.map((row) => (row.id === item.id ? updated : row)),
      );
      setMessage("Organization status and member sessions synchronized.");
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Organization update failed",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Organizations</h1>
          <p className="mt-1 text-sm text-white/40">{message}</p>
        </div>
        <button
          disabled={loading}
          onClick={() => void load()}
          className="btn-primary"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />{" "}
          Refresh
        </button>
      </header>

      <form
        onSubmit={create}
        className="glass-card grid gap-3 p-5 md:grid-cols-4"
      >
        <input
          name="name"
          required
          minLength={2}
          placeholder="Organization name"
          className="glass-input rounded-xl px-3 py-2 text-sm text-white"
        />
        <input
          name="slug"
          placeholder="Optional slug"
          className="glass-input rounded-xl px-3 py-2 text-sm text-white"
        />
        <select
          name="plan"
          className="glass-input rounded-xl px-3 py-2 text-sm text-white"
        >
          <option value="enterprise" className="bg-space-800">
            Enterprise
          </option>
          <option value="professional" className="bg-space-800">
            Professional
          </option>
          <option value="free" className="bg-space-800">
            Free
          </option>
        </select>
        <button disabled={busy} className="btn-primary">
          <Plus className="h-4 w-4" />
          Create
        </button>
      </form>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {items.map((item) => (
          <article key={item.id} className="glass-card p-5">
            <div className="flex items-start gap-3">
              <span className="rounded-xl bg-electric-500/10 p-2.5 text-electric-300">
                <Building2 className="h-5 w-5" />
              </span>
              <div className="min-w-0 flex-1">
                <h2 className="truncate text-sm font-semibold text-white">
                  {item.name}
                </h2>
                <p className="text-xs text-white/35">
                  {item.slug} · {item.plan}
                </p>
              </div>
              <span
                className={`rounded-full px-2.5 py-1 text-xs ${item.status === "active" ? "bg-green-500/10 text-green-300" : "bg-orange-500/10 text-orange-300"}`}
              >
                {item.status}
              </span>
            </div>
            <div className="mt-5 grid grid-cols-2 gap-3 text-center text-xs text-white/45">
              <div className="rounded-xl bg-white/[0.03] p-3">
                <div className="text-lg font-bold text-white">
                  {item.member_count}
                </div>
                Members
              </div>
              <div className="rounded-xl bg-white/[0.03] p-3">
                <div className="text-lg font-bold text-white">
                  {item.role_count}
                </div>
                Roles
              </div>
            </div>
            <button
              disabled={busy || item.id === "aionex-org"}
              onClick={() => void toggle(item)}
              className="mt-4 w-full rounded-xl border border-orange-500/20 bg-orange-500/10 px-3 py-2 text-xs text-orange-300 disabled:opacity-40"
            >
              {item.status === "active"
                ? "Suspend organization"
                : "Restore organization"}
            </button>
          </article>
        ))}
      </div>
    </div>
  );
}
