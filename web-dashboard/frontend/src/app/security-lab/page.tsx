"use client";

import { useEffect, useMemo, useState } from "react";
import { Activity, Play, RefreshCw, ShieldCheck, Wrench } from "lucide-react";

import {
  securityLabApi,
  type SecurityLabAccess,
  type SecurityProfile,
  type SecurityScanRecord,
  type SecurityTargetRecord,
  type SecurityTool,
} from "@/lib/security-lab";

export default function SecurityLabPage() {
  const [access, setAccess] = useState<SecurityLabAccess | null>(null);
  const [targets, setTargets] = useState<SecurityTargetRecord[]>([]);
  const [scans, setScans] = useState<SecurityScanRecord[]>([]);
  const [tools, setTools] = useState<SecurityTool[]>([]);
  const [targetId, setTargetId] = useState("");
  const [profile, setProfile] = useState<SecurityProfile>("passive");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("Loading Security Lab access…");

  async function load(signal?: AbortSignal) {
    setLoading(true);
    try {
      const accessData = await securityLabApi.access(signal);
      setAccess(accessData);
      if (accessData.granted && accessData.enabled) {
        const [targetData, scanData, toolData] = await Promise.all([
          securityLabApi.targets(signal),
          securityLabApi.scans(signal),
          securityLabApi.tools(signal),
        ]);
        setTargets(targetData);
        setScans(scanData);
        setTools(toolData);
        if (!targetId && targetData.length) setTargetId(targetData[0].id);
        if (!accessData.profiles.includes(profile)) {
          setProfile(accessData.profiles[0] ?? "passive");
        }
        setMessage("Security Lab synchronized with durable backend state.");
      } else {
        setTargets([]);
        setScans([]);
        setTools([]);
        setMessage(
          "Security Lab is available only when the Super Owner grants this account access.",
        );
      }
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setMessage(
          error instanceof Error ? error.message : "Security Lab load failed.",
        );
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const availableTools = useMemo(
    () => tools.filter((item) => item.available).length,
    [tools],
  );
  const activeScans = useMemo(
    () =>
      scans.filter((item) => ["queued", "running"].includes(item.status))
        .length,
    [scans],
  );

  async function startScan() {
    if (!targetId) return;
    setBusy(true);
    try {
      const created = await securityLabApi.createScan(targetId, profile);
      setMessage(`Security scan ${created.id.slice(0, 8)} queued.`);
      await load();
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Security scan could not be queued.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (!access) {
    return (
      <div className="glass-card p-6 text-sm text-white/50">{message}</div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs text-electric-300">
            <ShieldCheck className="h-3.5 w-3.5" /> AIONEX Security Lab
          </div>
          <h1 className="text-3xl font-bold text-white">
            Project Security Validation
          </h1>
          <p className="mt-2 max-w-4xl text-sm leading-6 text-white/45">
            Evidence-gated SAST, dependency, secret, TLS, API, container,
            mobile, and authorized runtime validation for AIONEX projects.
            Advanced and Elite validation is isolated from production by the
            security-clone boundary.
          </p>
        </div>
        <button
          className="btn-secondary"
          disabled={loading || busy}
          onClick={() => void load()}
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />{" "}
          Refresh
        </button>
      </div>

      <div className="glass-card p-4 text-xs text-electric-300">{message}</div>

      {!access.granted || !access.enabled ? (
        <section className="glass-card p-6">
          <h2 className="font-semibold text-white">
            Owner-controlled capability
          </h2>
          <p className="mt-2 text-sm leading-6 text-white/45">
            The Super Owner is the only authority that can enable this
            capability for an account and select its validation level. No
            browser-side change can elevate the entitlement because every scan
            is re-authorized by the backend.
          </p>
        </section>
      ) : (
        <>
          <div className="grid gap-4 md:grid-cols-3">
            <div className="glass-card p-5">
              <ShieldCheck className="h-5 w-5 text-electric-300" />
              <div className="mt-3 text-2xl font-bold text-white">
                {access.level}
              </div>
              <div className="text-xs text-white/35">Owner-granted level</div>
            </div>
            <div className="glass-card p-5">
              <Wrench className="h-5 w-5 text-electric-300" />
              <div className="mt-3 text-2xl font-bold text-white">
                {availableTools}
              </div>
              <div className="text-xs text-white/35">Available engines</div>
            </div>
            <div className="glass-card p-5">
              <Activity className="h-5 w-5 text-electric-300" />
              <div className="mt-3 text-2xl font-bold text-white">
                {activeScans}
              </div>
              <div className="text-xs text-white/35">
                Queued or running scans
              </div>
            </div>
          </div>

          <section className="glass-card p-5">
            <h2 className="font-semibold text-white">Authorized targets</h2>
            <p className="mt-2 text-xs leading-5 text-white/40">
              The Super Owner or trusted deployment automation registers
              AIONEX-managed targets. External targets require ownership
              verification before scanning. Advanced and Elite validation can
              run only against an Owner-registered isolated security clone.
            </p>
            <div className="mt-3 text-sm text-white/60">
              {targets.length} authorized target
              {targets.length === 1 ? "" : "s"} available.
            </div>
          </section>

          <section className="glass-card space-y-4 p-5">
            <div className="flex items-center gap-2 text-white">
              <Play className="h-5 w-5 text-electric-300" />
              <h2 className="font-semibold">Start security validation</h2>
            </div>
            <div className="grid gap-3 lg:grid-cols-2">
              <label className="text-xs text-white/45">
                Verified target
                <select
                  className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 p-2 text-white"
                  value={targetId}
                  onChange={(event) => setTargetId(event.target.value)}
                >
                  <option value="">Select target</option>
                  {targets
                    .filter((item) => item.authorization_status === "verified")
                    .map((target) => (
                      <option key={target.id} value={target.id}>
                        {target.origin}
                      </option>
                    ))}
                </select>
              </label>
              <label className="text-xs text-white/45">
                Profile
                <select
                  className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 p-2 text-white"
                  value={profile}
                  onChange={(event) =>
                    setProfile(event.target.value as SecurityProfile)
                  }
                >
                  {access.profiles.map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <button
              className="btn-primary"
              disabled={busy || !targetId}
              onClick={() => void startScan()}
            >
              <Play className="h-4 w-4" /> Queue validation
            </button>
          </section>

          <section className="glass-card p-5">
            <h2 className="font-semibold text-white">Recent scans</h2>
            <div className="mt-4 overflow-x-auto">
              <table className="w-full min-w-[760px] text-left text-xs">
                <thead className="text-white/35">
                  <tr>
                    <th className="p-2">Target</th>
                    <th className="p-2">Profile</th>
                    <th className="p-2">Mode</th>
                    <th className="p-2">Status</th>
                    <th className="p-2">Findings</th>
                    <th className="p-2">Severity</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.05]">
                  {scans.slice(0, 50).map((scan) => {
                    const target = targets.find(
                      (item) => item.id === scan.target_id,
                    );
                    const severity = scan.summary.severity ?? {};
                    return (
                      <tr key={scan.id} className="text-white/60">
                        <td className="p-2">
                          {target?.origin ?? scan.target_id.slice(0, 8)}
                        </td>
                        <td className="p-2">{scan.profile}</td>
                        <td className="p-2">{scan.execution_mode}</td>
                        <td className="p-2">{scan.status}</td>
                        <td className="p-2">
                          {scan.summary.finding_count ?? "—"}
                        </td>
                        <td className="p-2">
                          C {severity.critical ?? 0} · H {severity.high ?? 0} ·
                          M {severity.medium ?? 0}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          <section className="glass-card p-5">
            <h2 className="font-semibold text-white">
              Security engine inventory
            </h2>
            <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
              {tools.map((tool) => (
                <div
                  key={tool.id}
                  className="rounded-xl border border-white/[0.06] bg-black/20 p-3"
                >
                  <div className="text-xs font-medium text-white">
                    {tool.id}
                  </div>
                  <div className="mt-1 text-[11px] text-white/35">
                    {tool.category} ·{" "}
                    {tool.available ? "available" : "optional/unavailable"}
                  </div>
                  <div className="mt-1 text-[10px] text-white/25">
                    {tool.requires_clone
                      ? "clone-only"
                      : tool.active
                        ? "authorized runtime"
                        : "source/passive"}
                  </div>
                </div>
              ))}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
