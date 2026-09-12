"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  BadgeCheck,
  CircleAlert,
  RefreshCw,
  Search,
  ShieldCheck,
  UserCog,
  UserX,
} from "lucide-react";

import {
  clearOwnerIdentityMediaAccess,
  getOwnerIdentityMedia,
  reviewOwnerIdentityMediaRequest,
  searchOwnerIdentityMediaUsers,
  setOwnerIdentityMediaAccess,
  type IdentityMediaOperation,
  type OwnerIdentityMediaAccess,
  type OwnerIdentityMediaRequest,
  type OwnerIdentityMediaSnapshot,
  type OwnerIdentityMediaUser,
  type RealIdentityBasis,
} from "@/lib/owner-identity-media";

const operationLabels: Record<IdentityMediaOperation, string> = {
  voice_clone: "Voice clone",
  voice_transform: "Voice transformation",
  face_reenactment: "Face reenactment",
  face_swap: "Face swap",
  talking_head: "Talking head / avatar video",
  lip_sync: "Lip sync",
  avatar_generation: "Avatar generation",
};

const basisLabels: Record<RealIdentityBasis, string> = {
  self: "User's own identity",
  consented_person: "Consented person",
  licensed_public_figure: "Licensed public figure / artist",
};

const inputClass =
  "w-full rounded-xl border border-white/10 bg-black/20 px-3 py-2.5 text-sm text-white outline-hidden focus:border-electric-400/50";

export default function OwnerIdentityMediaPage() {
  const [snapshot, setSnapshot] = useState<OwnerIdentityMediaSnapshot | null>(
    null,
  );
  const [users, setUsers] = useState<OwnerIdentityMediaUser[]>([]);
  const [selectedUser, setSelectedUser] = useState("");
  const [operation, setOperation] =
    useState<IdentityMediaOperation>("voice_clone");
  const [allowed, setAllowed] = useState(true);
  const [bases, setBases] = useState<RealIdentityBasis[]>([
    "self",
    "consented_person",
  ]);
  const [scope, setScope] = useState<"any" | "exact">("any");
  const [subject, setSubject] = useState("");
  const [note, setNote] = useState("");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("Loading Identity Media authority…");

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      try {
        const [next, found] = await Promise.all([
          getOwnerIdentityMedia("", signal),
          searchOwnerIdentityMediaUsers(query, signal),
        ]);
        setSnapshot(next);
        setUsers(found.users);
        setSelectedUser((current) => current || found.users[0]?.id || "");
        setMessage("Identity Media Owner authority synchronized.");
      } catch (error) {
        if (!(error instanceof DOMException && error.name === "AbortError"))
          setMessage(
            error instanceof Error
              ? error.message
              : "Identity Media authority could not be loaded.",
          );
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [query],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const grants = useMemo(
    () => snapshot?.access.filter((item) => item.allowed).length ?? 0,
    [snapshot],
  );
  const denies = useMemo(
    () => snapshot?.access.filter((item) => !item.allowed).length ?? 0,
    [snapshot],
  );

  function toggleBasis(basis: RealIdentityBasis) {
    setBases((current) =>
      current.includes(basis)
        ? current.length === 1
          ? current
          : current.filter((item) => item !== basis)
        : [...current, basis],
    );
  }

  async function saveAccess() {
    if (!selectedUser) {
      setMessage("Select a user first.");
      return;
    }
    if (scope === "exact" && !subject.trim()) {
      setMessage("Enter the exact identity/subject this rule applies to.");
      return;
    }
    setBusy("save");
    try {
      await setOwnerIdentityMediaAccess({
        user_id: selectedUser,
        operation,
        allowed,
        identity_bases: bases,
        subject_scope: scope,
        subject_reference: scope === "exact" ? subject.trim() : null,
        note,
      });
      setMessage(
        allowed
          ? "User Identity Media permission granted and audit-logged. Identity rights remain separately required."
          : "User Identity Media permission denied immediately and audit-logged.",
      );
      await load();
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Owner access update failed.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function clearAccess(item: OwnerIdentityMediaAccess) {
    if (
      !window.confirm(
        `Remove the Owner override for ${item.user_email || item.user_id} · ${operationLabels[item.operation]}?`,
      )
    )
      return;
    setBusy(`clear:${item.user_id}:${item.operation}`);
    try {
      await clearOwnerIdentityMediaAccess(item.user_id, item.operation);
      setMessage(
        "Owner override removed. Real-person identity use now falls back to default deny.",
      );
      await load();
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Owner override removal failed.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function review(
    request: OwnerIdentityMediaRequest,
    decision: "approved" | "denied" | "revoked",
  ) {
    const label =
      decision === "approved"
        ? "approve"
        : decision === "denied"
          ? "deny"
          : "revoke";
    if (
      !window.confirm(
        `${label} this Identity Media request for ${request.user_email || request.user_id}?`,
      )
    )
      return;
    setBusy(`request:${request.request_id}`);
    try {
      await reviewOwnerIdentityMediaRequest(request.request_id, decision);
      setMessage(`Identity Media request ${decision} and audit-logged.`);
      await load();
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Request review failed.",
      );
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-6 pb-20">
      <header className="glass-card p-6">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="flex gap-3">
            <UserCog className="mt-1 h-7 w-7 shrink-0 text-electric-300" />
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-electric-300">
                Super Owner Identity Authority
              </p>
              <h1 className="mt-2 text-3xl font-bold text-white">
                Identity Media Access
              </h1>
              <p className="mt-2 max-w-4xl text-sm leading-6 text-white/45">
                Grant, deny, revoke, or scope real-person voice and face
                identity tools per user. Fictional/non-identical media remains
                directly available when its runtime is live.
              </p>
            </div>
          </div>
          <button
            className="btn-secondary"
            disabled={loading || busy !== null}
            onClick={() => void load()}
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />{" "}
            Refresh
          </button>
        </div>
      </header>

      <div className="rounded-2xl border border-amber-500/20 bg-amber-500/5 p-4 text-sm leading-6 text-amber-100/80">
        <div className="flex gap-3">
          <CircleAlert className="mt-0.5 h-5 w-5 shrink-0" />
          <p>
            Owner approval is an <strong>AIOS application permission</strong>;
            it is not consent or a legal likeness/voice license from an artist
            or other person. Real-person execution still requires valid rights
            evidence, and public-figure use additionally requires an accepted
            licensed-catalog authority.
          </p>
        </div>
      </div>

      <section className="grid gap-4 sm:grid-cols-3">
        <div className="glass-card p-5">
          <BadgeCheck className="h-5 w-5 text-green-300" />
          <div className="mt-3 text-3xl font-bold text-white">{grants}</div>
          <div className="text-xs text-white/40">Owner grants</div>
        </div>
        <div className="glass-card p-5">
          <UserX className="h-5 w-5 text-rose-300" />
          <div className="mt-3 text-3xl font-bold text-white">{denies}</div>
          <div className="text-xs text-white/40">Owner denies</div>
        </div>
        <div className="glass-card p-5">
          <ShieldCheck className="h-5 w-5 text-electric-300" />
          <div className="mt-3 text-3xl font-bold text-white">
            {snapshot?.pending_requests.length ?? 0}
          </div>
          <div className="text-xs text-white/40">Pending user requests</div>
        </div>
      </section>

      <div className="glass-card p-4 text-xs text-electric-300">{message}</div>

      <section className="glass-card space-y-5 p-6">
        <div>
          <h2 className="text-lg font-semibold text-white">
            Grant / deny a user
          </h2>
          <p className="mt-1 text-xs text-white/40">
            A deny overrides all default access for that operation. Clearing an
            override restores the default policy.
          </p>
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <label className="text-xs text-white/50">
            Search users
            <div className="mt-1 flex gap-2">
              <Search className="mt-3 h-4 w-4 text-white/30" />
              <input
                className={inputClass}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Name, email, or user ID"
              />
            </div>
          </label>
          <label className="text-xs text-white/50">
            User
            <select
              className={`mt-1 ${inputClass}`}
              value={selectedUser}
              onChange={(event) => setSelectedUser(event.target.value)}
            >
              <option value="">Select user</option>
              {users.map((user) => (
                <option key={user.id} value={user.id}>
                  {user.name} · {user.email}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-white/50">
            Identity operation
            <select
              className={`mt-1 ${inputClass}`}
              value={operation}
              onChange={(event) =>
                setOperation(event.target.value as IdentityMediaOperation)
              }
            >
              {(snapshot?.operations || Object.keys(operationLabels)).map(
                (item) => (
                  <option key={item} value={item}>
                    {operationLabels[item as IdentityMediaOperation]}
                  </option>
                ),
              )}
            </select>
          </label>
          <label className="text-xs text-white/50">
            Owner decision
            <select
              className={`mt-1 ${inputClass}`}
              value={allowed ? "grant" : "deny"}
              onChange={(event) => setAllowed(event.target.value === "grant")}
            >
              <option value="grant">Grant</option>
              <option value="deny">Deny / block</option>
            </select>
          </label>
        </div>
        <div>
          <div className="text-xs text-white/50">
            Permitted real-person bases
          </div>
          <div className="mt-2 flex flex-wrap gap-4">
            {(Object.keys(basisLabels) as RealIdentityBasis[]).map((basis) => (
              <label
                key={basis}
                className="flex items-center gap-2 text-xs text-white/55"
              >
                <input
                  type="checkbox"
                  checked={bases.includes(basis)}
                  onChange={() => toggleBasis(basis)}
                />{" "}
                {basisLabels[basis]}
              </label>
            ))}
          </div>
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <label className="text-xs text-white/50">
            Subject scope
            <select
              className={`mt-1 ${inputClass}`}
              value={scope}
              onChange={(event) =>
                setScope(event.target.value as "any" | "exact")
              }
            >
              <option value="any">
                Any rights-verified subject under this operation
              </option>
              <option value="exact">One exact subject only</option>
            </select>
          </label>
          <label className="text-xs text-white/50">
            Exact subject reference
            <input
              className={`mt-1 ${inputClass}`}
              disabled={scope !== "exact"}
              value={subject}
              onChange={(event) => setSubject(event.target.value)}
              placeholder="Internal subject/rights reference"
            />
          </label>
        </div>
        <label className="block text-xs text-white/50">
          Owner audit note
          <textarea
            className={`mt-1 min-h-24 ${inputClass}`}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Why this user is being granted or denied access"
          />
        </label>
        <button
          className="btn-primary"
          disabled={busy !== null || !selectedUser}
          onClick={() => void saveAccess()}
        >
          <ShieldCheck className="h-4 w-4" />{" "}
          {allowed
            ? "Grant Identity Media access"
            : "Deny Identity Media access"}
        </button>
      </section>

      <section className="glass-card p-6">
        <h2 className="text-lg font-semibold text-white">
          Pending approval requests
        </h2>
        <div className="mt-4 space-y-3">
          {(snapshot?.pending_requests || []).map((request) => (
            <div
              key={request.request_id}
              className="rounded-2xl border border-white/[0.07] bg-black/10 p-4"
            >
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div className="text-sm text-white/70">
                  <div className="font-semibold text-white">
                    {request.user_name || request.user_id} ·{" "}
                    {operationLabels[request.operation]}
                  </div>
                  <div className="mt-1 text-xs text-white/40">
                    {request.user_email} · {basisLabels[request.identity_basis]}{" "}
                    · subject: {request.subject_reference}
                  </div>
                  {request.reason && (
                    <div className="mt-2 text-xs text-white/50">
                      {request.reason}
                    </div>
                  )}
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    className="btn-primary"
                    disabled={busy !== null}
                    onClick={() => void review(request, "approved")}
                  >
                    Approve
                  </button>
                  <button
                    className="btn-secondary"
                    disabled={busy !== null}
                    onClick={() => void review(request, "denied")}
                  >
                    Deny
                  </button>
                </div>
              </div>
            </div>
          ))}
          {!snapshot?.pending_requests.length && (
            <p className="py-4 text-sm text-white/35">
              No pending Identity Media requests.
            </p>
          )}
        </div>
      </section>

      <section className="glass-card p-6">
        <h2 className="text-lg font-semibold text-white">
          Current per-user overrides
        </h2>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[760px] text-left text-xs text-white/55">
            <thead className="text-white/30">
              <tr>
                <th className="py-2">User</th>
                <th>Operation</th>
                <th>Decision</th>
                <th>Basis</th>
                <th>Scope</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {(snapshot?.access || []).map((item) => (
                <tr
                  key={`${item.user_id}:${item.operation}`}
                  className="border-t border-white/6"
                >
                  <td className="py-3">
                    <div className="font-medium text-white/75">
                      {item.user_name || item.user_id}
                    </div>
                    <div>{item.user_email}</div>
                  </td>
                  <td>{operationLabels[item.operation]}</td>
                  <td
                    className={
                      item.allowed ? "text-green-300" : "text-rose-300"
                    }
                  >
                    {item.allowed ? "Granted" : "Denied"}
                  </td>
                  <td>
                    {item.identity_bases
                      .map((basis) => basisLabels[basis])
                      .join(" · ")}
                  </td>
                  <td>
                    {item.subject_scope === "exact"
                      ? item.subject_reference || "exact"
                      : "any verified subject"}
                  </td>
                  <td>
                    <button
                      className="text-amber-300 hover:text-amber-200"
                      disabled={busy !== null}
                      onClick={() => void clearAccess(item)}
                    >
                      Remove override
                    </button>
                  </td>
                </tr>
              ))}
              {!snapshot?.access.length && (
                <tr>
                  <td colSpan={6} className="py-8 text-center text-white/30">
                    No Owner overrides yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
