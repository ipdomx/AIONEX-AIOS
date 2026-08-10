"use client";

import { useEffect, useMemo, useState } from "react";
import {
  BrainCircuit,
  CheckCircle2,
  RefreshCw,
  Save,
  ShieldCheck,
  UserRoundCog,
  XCircle,
} from "lucide-react";

import {
  ownerSecurityLabApi,
  type SecurityEligibleProject,
  type SecurityEligibleUser,
  type SecurityGrantRecord,
  type SecurityLabOwnerSnapshot,
  type SecurityLabPolicy,
  type SecurityReleaseGateRecord,
  type SecurityRuleRecord,
} from "@/lib/owner-security-lab";
import type {
  SecurityFindingRecord,
  SecurityScanRecord,
} from "@/lib/security-lab";

const emptyPolicy: SecurityLabPolicy = {
  enabled: true,
  managed_domain_suffixes: ["vip-e.net"],
  max_concurrent_scans_per_user: 2,
  max_scan_runtime_seconds: 1800,
  active_on_verified_targets: true,
  deep_validation_requires_clone: true,
  learning_enabled: true,
  auto_rule_candidates: true,
  auto_remediation_enabled: false,
  release_gate: {
    block_confirmed_critical: true,
    block_confirmed_high: true,
    max_confirmed_medium: 0,
    require_tls: true,
    require_security_headers: true,
    require_backup_restore_evidence: true,
  },
};

export default function OwnerSecurityLabPage() {
  const [snapshot, setSnapshot] = useState<SecurityLabOwnerSnapshot | null>(
    null,
  );
  const [policy, setPolicy] = useState<SecurityLabPolicy>(emptyPolicy);
  const [users, setUsers] = useState<SecurityEligibleUser[]>([]);
  const [projects, setProjects] = useState<SecurityEligibleProject[]>([]);
  const [findings, setFindings] = useState<SecurityFindingRecord[]>([]);
  const [rules, setRules] = useState<SecurityRuleRecord[]>([]);
  const [gates, setGates] = useState<SecurityReleaseGateRecord[]>([]);
  const [scans, setScans] = useState<SecurityScanRecord[]>([]);
  const [selectedUser, setSelectedUser] = useState("");
  const [grantLevel, setGrantLevel] =
    useState<SecurityGrantRecord["level"]>("standard");
  const [managedProjectId, setManagedProjectId] = useState("");
  const [managedOrigin, setManagedOrigin] = useState("");
  const [managedEnvironment, setManagedEnvironment] = useState<
    "production" | "staging"
  >("production");
  const [cloneSourceId, setCloneSourceId] = useState("");
  const [cloneOrigin, setCloneOrigin] = useState("");
  const [selectedScan, setSelectedScan] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(
    "Loading Security Lab control center…",
  );

  async function load(signal?: AbortSignal) {
    setLoading(true);
    try {
      const [
        base,
        eligible,
        projectRows,
        findingRows,
        ruleRows,
        gateRows,
        scanRows,
      ] = await Promise.all([
        ownerSecurityLabApi.snapshot(signal),
        ownerSecurityLabApi.users(signal),
        ownerSecurityLabApi.projects(signal),
        ownerSecurityLabApi.findings(signal),
        ownerSecurityLabApi.rules(signal),
        ownerSecurityLabApi.releaseGates(signal),
        ownerSecurityLabApi.scans(signal),
      ]);
      setSnapshot(base);
      setPolicy(base.policy);
      setUsers(eligible);
      setProjects(projectRows);
      if (!managedProjectId && projectRows.length)
        setManagedProjectId(projectRows[0].id);
      setFindings(findingRows);
      setRules(ruleRows);
      setGates(gateRows);
      setScans(scanRows);
      if (!selectedUser && eligible.length) setSelectedUser(eligible[0].id);
      const firstManagedTarget = base.targets.find(
        (item) => item.kind === "managed_project",
      );
      if (!cloneSourceId && firstManagedTarget)
        setCloneSourceId(firstManagedTarget.id);
      const completed = scanRows.find((item) => item.status === "completed");
      if (!selectedScan && completed) setSelectedScan(completed.id);
      setMessage("Security Lab control center synchronized.");
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setMessage(
          error instanceof Error
            ? error.message
            : "Security Lab synchronization failed.",
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

  const activeGrants = useMemo(
    () => snapshot?.grants.filter((item) => item.status === "active") ?? [],
    [snapshot],
  );
  const unresolved = useMemo(
    () =>
      findings.filter(
        (item) => !["resolved", "false_positive"].includes(item.state),
      ),
    [findings],
  );
  const promotedRules = useMemo(
    () => rules.filter((item) => item.status === "promoted").length,
    [rules],
  );
  const managedTargets = useMemo(
    () =>
      snapshot?.targets.filter((item) => item.kind === "managed_project") ?? [],
    [snapshot],
  );

  function setPolicyField<K extends keyof SecurityLabPolicy>(
    key: K,
    value: SecurityLabPolicy[K],
  ) {
    setPolicy((current) => ({ ...current, [key]: value }));
  }

  async function savePolicy() {
    setBusy(true);
    try {
      const saved = await ownerSecurityLabApi.updatePolicy(policy);
      setPolicy(saved);
      setMessage("Security Lab policy saved and audit-logged.");
      await load();
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Security Lab policy update failed.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function registerManagedTarget() {
    if (!managedProjectId || !managedOrigin.trim()) return;
    setBusy(true);
    try {
      const created = await ownerSecurityLabApi.registerManagedTarget({
        project_id: managedProjectId,
        origin: managedOrigin.trim(),
        environment: managedEnvironment,
      });
      setManagedOrigin("");
      setCloneSourceId(created.id);
      setMessage(
        "Managed project target registered and bound by the Super Owner.",
      );
      await load();
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Managed project target registration failed.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function registerCloneTarget() {
    if (!cloneSourceId || !cloneOrigin.trim()) return;
    setBusy(true);
    try {
      await ownerSecurityLabApi.registerCloneTarget(
        cloneSourceId,
        cloneOrigin.trim(),
      );
      setCloneOrigin("");
      setMessage(
        "Isolated security clone target registered and linked to the managed project.",
      );
      await load();
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Security clone target registration failed.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function grantAccess() {
    if (!selectedUser) return;
    setBusy(true);
    try {
      await ownerSecurityLabApi.grant({
        user_id: selectedUser,
        level: grantLevel,
      });
      setMessage("Security Lab access saved for the selected user.");
      await load();
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Security Lab access update failed.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function revokeAccess(userId: string) {
    if (!window.confirm("Revoke Security Lab access for this user?")) return;
    setBusy(true);
    try {
      await ownerSecurityLabApi.revoke(userId);
      setMessage("Security Lab access revoked.");
      await load();
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Security Lab access revocation failed.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function decideFinding(
    item: SecurityFindingRecord,
    state: "confirmed" | "false_positive" | "resolved",
  ) {
    if (
      state === "confirmed" &&
      !window.confirm(
        "Confirm this finding as verified security evidence? A candidate Security Genome rule may be created.",
      )
    )
      return;
    setBusy(true);
    try {
      await ownerSecurityLabApi.decideFinding(item.id, state);
      setMessage(`Security finding state recorded: ${state}.`);
      await load();
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Security finding decision failed.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function validateRule(ruleId: string) {
    setBusy(true);
    try {
      await ownerSecurityLabApi.validateRule(ruleId);
      setMessage(
        "Security Genome candidate validated against positive and negative test cases.",
      );
      await load();
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Security rule validation failed.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function promoteRule(ruleId: string) {
    if (
      !window.confirm(
        "Promote this validated rule to approved platform security knowledge?",
      )
    )
      return;
    setBusy(true);
    try {
      await ownerSecurityLabApi.promoteRule(ruleId);
      setMessage(
        "Validated Security Genome rule promoted to approved platform knowledge.",
      );
      await load();
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Security rule promotion failed.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function evaluateGate() {
    if (!selectedScan) return;
    setBusy(true);
    try {
      const gate = await ownerSecurityLabApi.evaluateReleaseGate(selectedScan);
      setMessage(`Security release gate decision: ${gate.decision}.`);
      await load();
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Security release gate evaluation failed.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (!snapshot) {
    return (
      <div className="glass-card p-6 text-sm text-white/50">{message}</div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs text-electric-300">
            <ShieldCheck className="h-3.5 w-3.5" /> Super Owner Security
            Authority
          </div>
          <h1 className="text-3xl font-bold text-white">
            Security & Adaptive Learning Fabric
          </h1>
          <p className="mt-2 max-w-5xl text-sm leading-6 text-white/45">
            Full authority over entitlements, target admission, scan depth,
            confirmed evidence, Security Genome promotion, autonomous
            remediation policy, and evidence-based release gates. Client
            requests cannot bypass these controls.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            className="btn-secondary"
            disabled={loading || busy}
            onClick={() => void load()}
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />{" "}
            Refresh
          </button>
          <button
            className="btn-primary"
            disabled={busy}
            onClick={() => void savePolicy()}
          >
            <Save className="h-4 w-4" /> Save policy
          </button>
        </div>
      </div>

      <div className="glass-card p-4 text-xs text-electric-300">{message}</div>

      <div className="grid gap-4 md:grid-cols-4">
        <div className="glass-card p-5">
          <UserRoundCog className="h-5 w-5 text-electric-300" />
          <div className="mt-3 text-2xl font-bold text-white">
            {activeGrants.length}
          </div>
          <div className="text-xs text-white/35">Active grants</div>
        </div>
        <div className="glass-card p-5">
          <ShieldCheck className="h-5 w-5 text-electric-300" />
          <div className="mt-3 text-2xl font-bold text-white">
            {snapshot.targets.length}
          </div>
          <div className="text-xs text-white/35">Registered targets</div>
        </div>
        <div className="glass-card p-5">
          <XCircle className="h-5 w-5 text-electric-300" />
          <div className="mt-3 text-2xl font-bold text-white">
            {unresolved.length}
          </div>
          <div className="text-xs text-white/35">Unresolved findings</div>
        </div>
        <div className="glass-card p-5">
          <BrainCircuit className="h-5 w-5 text-electric-300" />
          <div className="mt-3 text-2xl font-bold text-white">
            {promotedRules}
          </div>
          <div className="text-xs text-white/35">Promoted security rules</div>
        </div>
      </div>

      <section className="glass-card space-y-4 p-5">
        <h2 className="font-semibold text-white">Global Security Lab policy</h2>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {(
            [
              ["enabled", "Security Lab enabled"],
              [
                "active_on_verified_targets",
                "Safe active scanning for verified targets",
              ],
              [
                "deep_validation_requires_clone",
                "Advanced and Elite validation requires an isolated security clone",
              ],
              ["learning_enabled", "Adaptive security learning"],
              [
                "auto_rule_candidates",
                "Create rule candidates from confirmed findings",
              ],
              [
                "auto_remediation_enabled",
                "Allow autonomous remediation management",
              ],
            ] as const
          ).map(([key, label]) => (
            <label
              key={key}
              className="flex items-center justify-between rounded-xl border border-white/[0.06] bg-black/20 p-3 text-xs text-white/60"
            >
              <span>{label}</span>
              <input
                type="checkbox"
                checked={Boolean(policy[key])}
                onChange={(event) => setPolicyField(key, event.target.checked)}
              />
            </label>
          ))}
        </div>
        <div className="grid gap-3 md:grid-cols-3">
          <label className="text-xs text-white/45">
            Managed project domains
            <input
              className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 p-2 text-white"
              value={policy.managed_domain_suffixes.join(", ")}
              onChange={(event) =>
                setPolicyField(
                  "managed_domain_suffixes",
                  event.target.value
                    .split(",")
                    .map((value) => value.trim())
                    .filter(Boolean),
                )
              }
            />
          </label>
          <label className="text-xs text-white/45">
            Maximum concurrent scans per user
            <input
              type="number"
              min={1}
              max={10}
              className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 p-2 text-white"
              value={policy.max_concurrent_scans_per_user}
              onChange={(event) =>
                setPolicyField(
                  "max_concurrent_scans_per_user",
                  Number(event.target.value),
                )
              }
            />
          </label>
          <label className="text-xs text-white/45">
            Maximum scan duration in seconds
            <input
              type="number"
              min={60}
              max={7200}
              className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 p-2 text-white"
              value={policy.max_scan_runtime_seconds}
              onChange={(event) =>
                setPolicyField(
                  "max_scan_runtime_seconds",
                  Number(event.target.value),
                )
              }
            />
          </label>
        </div>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {(
            [
              [
                "block_confirmed_critical",
                "Block release on confirmed critical findings",
              ],
              [
                "block_confirmed_high",
                "Block release on confirmed high findings",
              ],
              ["require_tls", "Require TLS validation evidence"],
              ["require_security_headers", "Require security header evidence"],
              [
                "require_backup_restore_evidence",
                "Require recent backup and restore evidence",
              ],
            ] as const
          ).map(([key, label]) => (
            <label
              key={key}
              className="flex items-center justify-between rounded-xl border border-white/[0.06] bg-black/20 p-3 text-xs text-white/60"
            >
              <span>{label}</span>
              <input
                type="checkbox"
                checked={Boolean(policy.release_gate[key])}
                onChange={(event) =>
                  setPolicy((current) => ({
                    ...current,
                    release_gate: {
                      ...current.release_gate,
                      [key]: event.target.checked,
                    },
                  }))
                }
              />
            </label>
          ))}
          <label className="rounded-xl border border-white/[0.06] bg-black/20 p-3 text-xs text-white/60">
            Allowed confirmed medium findings
            <input
              type="number"
              min={0}
              max={1000}
              className="mt-2 w-full rounded-lg border border-white/10 bg-black/20 p-2 text-white"
              value={policy.release_gate.max_confirmed_medium}
              onChange={(event) =>
                setPolicy((current) => ({
                  ...current,
                  release_gate: {
                    ...current.release_gate,
                    max_confirmed_medium: Number(event.target.value),
                  },
                }))
              }
            />
          </label>
        </div>
      </section>

      <section className="glass-card space-y-4 p-5">
        <h2 className="font-semibold text-white">
          Managed platform project targets
        </h2>
        <p className="text-xs leading-5 text-white/40">
          {
            "Only the Super Owner registers the deployment origin bound to a project. A user cannot bind a project to another project's origin even when both share the same parent domain."
          }
        </p>
        <div className="grid gap-3 lg:grid-cols-[1fr_1fr_180px_auto]">
          <select
            className="rounded-lg border border-white/10 bg-black/20 p-2 text-sm text-white"
            value={managedProjectId}
            onChange={(event) => setManagedProjectId(event.target.value)}
          >
            <option value="">Select project</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name} · {project.status}
              </option>
            ))}
          </select>
          <input
            className="rounded-lg border border-white/10 bg-black/20 p-2 text-sm text-white"
            value={managedOrigin}
            onChange={(event) => setManagedOrigin(event.target.value)}
            placeholder="https://project.vip-e.net"
          />
          <select
            className="rounded-lg border border-white/10 bg-black/20 p-2 text-sm text-white"
            value={managedEnvironment}
            onChange={(event) =>
              setManagedEnvironment(
                event.target.value as "production" | "staging",
              )
            }
          >
            <option value="production">Production</option>
            <option value="staging">Staging</option>
          </select>
          <button
            className="btn-primary"
            disabled={busy || !managedProjectId || !managedOrigin.trim()}
            onClick={() => void registerManagedTarget()}
          >
            Register target
          </button>
        </div>
      </section>

      <section className="glass-card space-y-4 p-5">
        <h2 className="font-semibold text-white">
          Isolated security scan clones
        </h2>
        <p className="text-xs leading-5 text-white/40">
          A user cannot turn a production target into a security clone by
          changing a request value. Only the Super Owner registers a separate
          deployed clone origin for the project; advanced validation then runs
          there without treating production as a test target.
        </p>
        <div className="grid gap-3 md:grid-cols-[1fr_1fr_auto]">
          <select
            className="rounded-lg border border-white/10 bg-black/20 p-2 text-sm text-white"
            value={cloneSourceId}
            onChange={(event) => setCloneSourceId(event.target.value)}
          >
            <option value="">Select managed target</option>
            {managedTargets.map((target) => (
              <option key={target.id} value={target.id}>
                {target.origin}
              </option>
            ))}
          </select>
          <input
            className="rounded-lg border border-white/10 bg-black/20 p-2 text-sm text-white"
            value={cloneOrigin}
            onChange={(event) => setCloneOrigin(event.target.value)}
            placeholder="https://security-clone.example.com"
          />
          <button
            className="btn-primary"
            disabled={busy || !cloneSourceId || !cloneOrigin.trim()}
            onClick={() => void registerCloneTarget()}
          >
            Register clone
          </button>
        </div>
      </section>

      <section className="glass-card space-y-4 p-5">
        <h2 className="font-semibold text-white">
          User entitlements — Super Owner only
        </h2>
        <div className="grid gap-3 md:grid-cols-[1fr_220px_auto]">
          <select
            className="rounded-lg border border-white/10 bg-black/20 p-2 text-sm text-white"
            value={selectedUser}
            onChange={(event) => setSelectedUser(event.target.value)}
          >
            <option value="">Select user</option>
            {users.map((user) => (
              <option key={user.id} value={user.id}>
                {user.name} · {user.email} · {user.role}
              </option>
            ))}
          </select>
          <select
            className="rounded-lg border border-white/10 bg-black/20 p-2 text-sm text-white"
            value={grantLevel}
            onChange={(event) =>
              setGrantLevel(event.target.value as SecurityGrantRecord["level"])
            }
          >
            <option value="standard">Standard</option>
            <option value="advanced">Advanced</option>
            <option value="elite">Elite</option>
            <option value="autonomous">Autonomous</option>
          </select>
          <button
            className="btn-primary"
            disabled={busy || !selectedUser}
            onClick={() => void grantAccess()}
          >
            Grant / update
          </button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-xs">
            <thead className="text-white/35">
              <tr>
                <th className="p-2">User</th>
                <th className="p-2">Level</th>
                <th className="p-2">Scan profiles</th>
                <th className="p-2">Status</th>
                <th className="p-2">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.05]">
              {snapshot.grants.map((grant) => {
                const user = users.find((item) => item.id === grant.user_id);
                return (
                  <tr key={grant.id} className="text-white/60">
                    <td className="p-2">
                      {user ? `${user.name} · ${user.email}` : grant.user_id}
                    </td>
                    <td className="p-2">{grant.level}</td>
                    <td className="p-2">{grant.profiles.join(", ")}</td>
                    <td className="p-2">{grant.status}</td>
                    <td className="p-2">
                      {grant.status === "active" && (
                        <button
                          className="rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-1 text-red-300"
                          disabled={busy}
                          onClick={() => void revokeAccess(grant.user_id)}
                        >
                          Revoke
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section className="glass-card p-5">
        <h2 className="font-semibold text-white">Security evidence triage</h2>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[980px] text-left text-xs">
            <thead className="text-white/35">
              <tr>
                <th className="p-2">Severity</th>
                <th className="p-2">Finding</th>
                <th className="p-2">Source</th>
                <th className="p-2">Confidence</th>
                <th className="p-2">Status</th>
                <th className="p-2">Owner decision</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.05]">
              {findings.slice(0, 200).map((item) => (
                <tr key={item.id} className="text-white/60">
                  <td className="p-2 uppercase">{item.severity}</td>
                  <td className="max-w-md p-2">
                    <div className="text-white/75">{item.title}</div>
                    <div className="mt-1 text-[10px] text-white/30">
                      {item.location ?? item.category}
                    </div>
                  </td>
                  <td className="p-2">{item.source}</td>
                  <td className="p-2">{Math.round(item.confidence * 100)}%</td>
                  <td className="p-2">{item.state}</td>
                  <td className="p-2">
                    <div className="flex gap-1">
                      <button
                        className="rounded border border-green-500/20 px-2 py-1 text-green-300"
                        disabled={busy || item.state === "confirmed"}
                        onClick={() => void decideFinding(item, "confirmed")}
                      >
                        Confirm
                      </button>
                      <button
                        className="rounded border border-white/10 px-2 py-1 text-white/50"
                        disabled={busy || item.state === "false_positive"}
                        onClick={() =>
                          void decideFinding(item, "false_positive")
                        }
                      >
                        False positive
                      </button>
                      <button
                        className="rounded border border-electric-500/20 px-2 py-1 text-electric-300"
                        disabled={busy || item.state === "resolved"}
                        onClick={() => void decideFinding(item, "resolved")}
                      >
                        Resolved
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="glass-card p-5">
        <div className="flex items-center gap-2 text-white">
          <BrainCircuit className="h-5 w-5 text-electric-300" />
          <h2 className="font-semibold">Security Genome & Rule Forge</h2>
        </div>
        <p className="mt-2 text-xs leading-5 text-white/40">
          Candidate rules remain quarantined until positive and negative
          validation passes. No finding is promoted automatically; promoted
          knowledge retains its provenance and validation evidence.
        </p>
        <div className="mt-4 space-y-2">
          {rules.slice(0, 100).map((rule) => (
            <div
              key={rule.id}
              className="flex flex-col gap-3 rounded-xl border border-white/[0.06] bg-black/20 p-3 lg:flex-row lg:items-center lg:justify-between"
            >
              <div>
                <div className="text-sm text-white">{rule.name}</div>
                <div className="mt-1 text-xs text-white/35">
                  {rule.rule_type} · {rule.status} · confidence{" "}
                  {Math.round(rule.trust_score * 100)}% ·{" "}
                  {rule.validation_passes} passed / {rule.validation_failures}{" "}
                  failed
                </div>
              </div>
              <div className="flex gap-2">
                <button
                  className="btn-secondary"
                  disabled={busy || rule.status === "promoted"}
                  onClick={() => void validateRule(rule.id)}
                >
                  Validate
                </button>
                <button
                  className="btn-primary"
                  disabled={busy || rule.status !== "validated"}
                  onClick={() => void promoteRule(rule.id)}
                >
                  Promote
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="glass-card space-y-4 p-5">
        <div className="flex items-center gap-2 text-white">
          <CheckCircle2 className="h-5 w-5 text-electric-300" />
          <h2 className="font-semibold">Security release gate</h2>
        </div>
        <p className="text-xs leading-5 text-white/40">
          A passing decision requires complete security evidence, no
          policy-blocking confirmed findings, no unresolved severe observations,
          and the required backup and restore evidence.
        </p>
        <div className="flex flex-col gap-2 md:flex-row">
          <select
            className="min-w-0 flex-1 rounded-lg border border-white/10 bg-black/20 p-2 text-sm text-white"
            value={selectedScan}
            onChange={(event) => setSelectedScan(event.target.value)}
          >
            <option value="">Select completed scan</option>
            {scans
              .filter((item) => item.status === "completed")
              .map((scan) => (
                <option key={scan.id} value={scan.id}>
                  {scan.id.slice(0, 8)} · {scan.profile} · findings{" "}
                  {scan.summary.finding_count ?? 0}
                </option>
              ))}
          </select>
          <button
            className="btn-primary"
            disabled={busy || !selectedScan}
            onClick={() => void evaluateGate()}
          >
            Evaluate gate
          </button>
        </div>
        <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
          {gates.slice(0, 30).map((gate) => (
            <div
              key={gate.id}
              className="rounded-xl border border-white/[0.06] bg-black/20 p-3"
            >
              <div className="text-sm font-medium text-white">
                {gate.decision}
              </div>
              <div className="mt-1 text-xs text-white/35">
                scan {gate.scan_id.slice(0, 8)} · blockers{" "}
                {gate.blockers.length}
              </div>
              <div className="mt-1 text-[10px] text-white/25">
                {gate.created_at ?? ""}
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
