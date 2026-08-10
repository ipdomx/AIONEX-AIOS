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
  const [message, setMessage] = useState("جارٍ تحميل مركز تحكم مختبر الأمان…");

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
      setMessage("تمت مزامنة مركز تحكم مختبر الأمان.");
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setMessage(
          error instanceof Error ? error.message : "فشلت مزامنة مختبر الأمان.",
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
      setMessage("تم حفظ سياسة مختبر الأمان وتسجيلها في سجل التدقيق.");
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "فشل تحديث السياسة.");
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
        "تم تسجيل هدف المشروع المُدار وربطه بالمشروع من جهة المالك الأعلى.",
      );
      await load();
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "فشل تسجيل هدف المشروع المُدار.",
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
        "تم تسجيل هدف النسخة الأمنية المعزولة وربطه بالمشروع المُدار.",
      );
      await load();
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "فشل تسجيل النسخة الأمنية المعزولة.",
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
      setMessage("تم حفظ صلاحية مختبر الأمان للمستخدم المحدد.");
      await load();
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "فشل تحديث الصلاحية.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function revokeAccess(userId: string) {
    if (!window.confirm("هل تريد إلغاء صلاحية مختبر الأمان لهذا المستخدم؟"))
      return;
    setBusy(true);
    try {
      await ownerSecurityLabApi.revoke(userId);
      setMessage("تم إلغاء صلاحية مختبر الأمان.");
      await load();
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "فشل إلغاء الصلاحية.",
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
        "هل تؤكد هذه النتيجة كدليل أمني موثّق؟ قد يتم إنشاء قاعدة مرشحة في الجينوم الأمني.",
      )
    )
      return;
    setBusy(true);
    try {
      await ownerSecurityLabApi.decideFinding(item.id, state);
      setMessage(`تم تسجيل حالة النتيجة: ${state}.`);
      await load();
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "فشل تسجيل قرار النتيجة الأمنية.",
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
        "تم التحقق من قاعدة الجينوم الأمني المرشحة مقابل حالات اختبار إيجابية وسلبية.",
      );
      await load();
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "فشل التحقق من القاعدة.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function promoteRule(ruleId: string) {
    if (
      !window.confirm(
        "هل تريد ترقية هذه القاعدة الموثّقة إلى المعرفة الأمنية المعتمدة في المنصة؟",
      )
    )
      return;
    setBusy(true);
    try {
      await ownerSecurityLabApi.promoteRule(ruleId);
      setMessage(
        "تمت ترقية قاعدة الجينوم الأمني الموثّقة إلى معرفة المنصة المعتمدة.",
      );
      await load();
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "فشلت ترقية القاعدة.",
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
      setMessage(`قرار بوابة الإصدار الأمني: ${gate.decision}.`);
      await load();
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "فشل تقييم بوابة الإصدار.",
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
            <ShieldCheck className="h-3.5 w-3.5" /> سلطة الأمان للمالك الأعلى
          </div>
          <h1 className="text-3xl font-bold text-white">
            منظومة الأمان والتعلّم الذاتي
          </h1>
          <p className="mt-2 max-w-5xl text-sm leading-6 text-white/45">
            تحكّم كامل في الصلاحيات وقبول الأهداف وعمق الفحص والأدلة المؤكدة
            وترقية الجينوم الأمني وسياسة الإصلاح الذاتي وبوابات الإصدار المبنية
            على الأدلة. لا تستطيع طلبات العميل تجاوز هذه الضوابط.
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
          <div className="text-xs text-white/35">الصلاحيات النشطة</div>
        </div>
        <div className="glass-card p-5">
          <ShieldCheck className="h-5 w-5 text-electric-300" />
          <div className="mt-3 text-2xl font-bold text-white">
            {snapshot.targets.length}
          </div>
          <div className="text-xs text-white/35">الأهداف المسجلة</div>
        </div>
        <div className="glass-card p-5">
          <XCircle className="h-5 w-5 text-electric-300" />
          <div className="mt-3 text-2xl font-bold text-white">
            {unresolved.length}
          </div>
          <div className="text-xs text-white/35">الملاحظات غير المحسومة</div>
        </div>
        <div className="glass-card p-5">
          <BrainCircuit className="h-5 w-5 text-electric-300" />
          <div className="mt-3 text-2xl font-bold text-white">
            {promotedRules}
          </div>
          <div className="text-xs text-white/35">القواعد الأمنية المرقّاة</div>
        </div>
      </div>

      <section className="glass-card space-y-4 p-5">
        <h2 className="font-semibold text-white">سياسة مختبر الأمان العامة</h2>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {(
            [
              ["enabled", "مختبر الأمان مفعّل"],
              ["active_on_verified_targets", "فحص آمن نشط للأهداف الموثقة"],
              [
                "deep_validation_requires_clone",
                "الفحص المتقدم والنخبوي يتطلب نسخة أمنية معزولة",
              ],
              ["learning_enabled", "التعلّم الأمني التكيفي"],
              ["auto_rule_candidates", "إنشاء قواعد مرشحة من النتائج المؤكدة"],
              ["auto_remediation_enabled", "السماح بإدارة الإصلاح الذاتي"],
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
            نطاقات المشاريع المُدارة
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
            أقصى فحوص متزامنة لكل مستخدم
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
            أقصى مدة للفحص بالثواني
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
                "حظر الإصدار عند وجود ثغرات حرجة مؤكدة",
              ],
              [
                "block_confirmed_high",
                "حظر الإصدار عند وجود ثغرات عالية مؤكدة",
              ],
              ["require_tls", "اشتراط دليل فحص TLS"],
              ["require_security_headers", "اشتراط دليل فحص ترويسات الأمان"],
              [
                "require_backup_restore_evidence",
                "اشتراط دليل نسخ احتياطي واستعادة حديث",
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
            الحد المسموح للثغرات المتوسطة المؤكدة
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
          أهداف مشاريع المنصة المُدارة
        </h2>
        <p className="text-xs leading-5 text-white/40">
          يسجل المالك الأعلى فقط عنوان النشر المرتبط بالمشروع. بهذه الطريقة لا
          يستطيع مستخدم ربط مشروعه بعنوان مشروع آخر حتى لو كان على نفس النطاق
          العام.
        </p>
        <div className="grid gap-3 lg:grid-cols-[1fr_1fr_180px_auto]">
          <select
            className="rounded-lg border border-white/10 bg-black/20 p-2 text-sm text-white"
            value={managedProjectId}
            onChange={(event) => setManagedProjectId(event.target.value)}
          >
            <option value="">اختر المشروع</option>
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
            <option value="production">إنتاج</option>
            <option value="staging">تجريبي</option>
          </select>
          <button
            className="btn-primary"
            disabled={busy || !managedProjectId || !managedOrigin.trim()}
            onClick={() => void registerManagedTarget()}
          >
            تسجيل الهدف
          </button>
        </div>
      </section>

      <section className="glass-card space-y-4 p-5">
        <h2 className="font-semibold text-white">نسخ الفحص الأمنية المعزولة</h2>
        <p className="text-xs leading-5 text-white/40">
          لا يستطيع المستخدم تحويل هدف إنتاج إلى نسخة أمنية بمجرد تغيير قيمة في
          الطلب. يسجل المالك الأعلى فقط عنوان نسخة منفصلة منشورة للمشروع، وبعد
          ذلك يسمح النظام بالفحوص المتقدمة والنخبوية على هذه النسخة دون اعتبار
          هدف الإنتاج نسخة اختبار.
        </p>
        <div className="grid gap-3 md:grid-cols-[1fr_1fr_auto]">
          <select
            className="rounded-lg border border-white/10 bg-black/20 p-2 text-sm text-white"
            value={cloneSourceId}
            onChange={(event) => setCloneSourceId(event.target.value)}
          >
            <option value="">اختر الهدف المُدار</option>
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
            تسجيل النسخة
          </button>
        </div>
      </section>

      <section className="glass-card space-y-4 p-5">
        <h2 className="font-semibold text-white">
          صلاحيات المستخدمين — للمالك الأعلى فقط
        </h2>
        <div className="grid gap-3 md:grid-cols-[1fr_220px_auto]">
          <select
            className="rounded-lg border border-white/10 bg-black/20 p-2 text-sm text-white"
            value={selectedUser}
            onChange={(event) => setSelectedUser(event.target.value)}
          >
            <option value="">اختر المستخدم</option>
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
            <option value="standard">قياسي</option>
            <option value="advanced">متقدم</option>
            <option value="elite">نخبوي</option>
            <option value="autonomous">ذاتي</option>
          </select>
          <button
            className="btn-primary"
            disabled={busy || !selectedUser}
            onClick={() => void grantAccess()}
          >
            منح / تحديث
          </button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-xs">
            <thead className="text-white/35">
              <tr>
                <th className="p-2">المستخدم</th>
                <th className="p-2">المستوى</th>
                <th className="p-2">أنماط الفحص</th>
                <th className="p-2">الحالة</th>
                <th className="p-2">الإجراء</th>
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
                          إلغاء
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
        <h2 className="font-semibold text-white">فرز الأدلة الأمنية</h2>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[980px] text-left text-xs">
            <thead className="text-white/35">
              <tr>
                <th className="p-2">الخطورة</th>
                <th className="p-2">النتيجة</th>
                <th className="p-2">المصدر</th>
                <th className="p-2">الثقة</th>
                <th className="p-2">الحالة</th>
                <th className="p-2">قرار المالك</th>
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
                        تأكيد
                      </button>
                      <button
                        className="rounded border border-white/10 px-2 py-1 text-white/50"
                        disabled={busy || item.state === "false_positive"}
                        onClick={() =>
                          void decideFinding(item, "false_positive")
                        }
                      >
                        إنذار كاذب
                      </button>
                      <button
                        className="rounded border border-electric-500/20 px-2 py-1 text-electric-300"
                        disabled={busy || item.state === "resolved"}
                        onClick={() => void decideFinding(item, "resolved")}
                      >
                        تم الحل
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
          <h2 className="font-semibold">الجينوم الأمني ومصنع القواعد</h2>
        </div>
        <p className="mt-2 text-xs leading-5 text-white/40">
          تبقى القواعد المرشحة في الحجر حتى تنجح اختبارات التحقق الإيجابية
          والسلبية. لا تُرقّى أي ملاحظة تلقائيًا، وتُحفظ المعرفة المرقّاة مع
          مصدرها ودليل التحقق.
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
                  {rule.rule_type} · {rule.status} · ثقة{" "}
                  {Math.round(rule.trust_score * 100)}% ·{" "}
                  {rule.validation_passes} نجاح / {rule.validation_failures} فشل
                </div>
              </div>
              <div className="flex gap-2">
                <button
                  className="btn-secondary"
                  disabled={busy || rule.status === "promoted"}
                  onClick={() => void validateRule(rule.id)}
                >
                  تحقق
                </button>
                <button
                  className="btn-primary"
                  disabled={busy || rule.status !== "validated"}
                  onClick={() => void promoteRule(rule.id)}
                >
                  ترقية
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="glass-card space-y-4 p-5">
        <div className="flex items-center gap-2 text-white">
          <CheckCircle2 className="h-5 w-5 text-electric-300" />
          <h2 className="font-semibold">بوابة الإصدار الأمني</h2>
        </div>
        <p className="text-xs leading-5 text-white/40">
          يتطلب النجاح اكتمال الأدلة الأمنية، وعدم وجود نتائج مؤكدة تمنعها
          السياسة، وعدم وجود ملاحظة خطيرة غير محسومة، وتوفر دليل النسخ الاحتياطي
          والاستعادة المطلوب.
        </p>
        <div className="flex flex-col gap-2 md:flex-row">
          <select
            className="min-w-0 flex-1 rounded-lg border border-white/10 bg-black/20 p-2 text-sm text-white"
            value={selectedScan}
            onChange={(event) => setSelectedScan(event.target.value)}
          >
            <option value="">اختر فحصًا مكتملًا</option>
            {scans
              .filter((item) => item.status === "completed")
              .map((scan) => (
                <option key={scan.id} value={scan.id}>
                  {scan.id.slice(0, 8)} · {scan.profile} · نتائج{" "}
                  {scan.summary.finding_count ?? 0}
                </option>
              ))}
          </select>
          <button
            className="btn-primary"
            disabled={busy || !selectedScan}
            onClick={() => void evaluateGate()}
          >
            تقييم البوابة
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
                scan {gate.scan_id.slice(0, 8)} · موانع {gate.blockers.length}
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
