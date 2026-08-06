"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import {
  Loader2,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  UserRound,
} from "lucide-react";
import {
  identityApi,
  type IdentityUser,
  type OrganizationRecord,
  type RoleRecord,
  type WorkspaceRecord,
} from "@/lib/identity-api";

export default function UsersPage() {
  const [users, setUsers] = useState<IdentityUser[]>([]);
  const [organizations, setOrganizations] = useState<OrganizationRecord[]>([]);
  const [roles, setRoles] = useState<RoleRecord[]>([]);
  const [workspaces, setWorkspaces] = useState<WorkspaceRecord[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("Loading live identity records...");

  async function load() {
    setLoading(true);
    try {
      const [nextUsers, nextOrganizations, nextRoles, nextWorkspaces] =
        await Promise.all([
          identityApi.users(),
          identityApi.organizations(),
          identityApi.roles(),
          identityApi.workspaces(),
        ]);
      setUsers(nextUsers);
      setOrganizations(nextOrganizations);
      setRoles(nextRoles);
      setWorkspaces(nextWorkspaces);
      setMessage(`Synchronized ${nextUsers.length} user records.`);
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Identity load failed",
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    return users.filter((user) =>
      `${user.name} ${user.email} ${user.role} ${user.organization} ${user.workspace || ""}`
        .toLowerCase()
        .includes(query),
    );
  }, [search, users]);

  async function createUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    try {
      const result = await identityApi.createUser({
        name: String(form.get("name") || "").trim(),
        email: String(form.get("email") || "").trim(),
        password: String(form.get("password") || ""),
        organization_id: String(form.get("organization_id") || ""),
        role_id: String(form.get("role_id") || ""),
        workspace_id: String(form.get("workspace_id") || "") || null,
      });
      setUsers((current) => [result.user, ...current]);
      event.currentTarget.reset();
      setMessage("User created with a stored workspace and role assignment.");
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "User creation failed",
      );
    } finally {
      setBusy(false);
    }
  }

  async function changeUser(
    user: IdentityUser,
    payload: Record<string, unknown>,
  ) {
    setBusy(true);
    try {
      const updated = await identityApi.updateUser(user.id, payload);
      setUsers((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setMessage("User identity and sessions were synchronized.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "User update failed");
    } finally {
      setBusy(false);
    }
  }

  async function removeUser(user: IdentityUser) {
    if (!window.confirm(`Delete ${user.email}?`)) return;
    setBusy(true);
    try {
      await identityApi.deleteUser(user.id);
      setUsers((current) => current.filter((item) => item.id !== user.id));
      setMessage("User deleted and active refresh sessions revoked.");
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "User deletion failed",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Users</h1>
          <p className="mt-1 text-sm text-white/40">{message}</p>
        </div>
        <button
          className="btn-primary"
          disabled={loading}
          onClick={() => void load()}
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </header>

      <form
        onSubmit={createUser}
        className="glass-card grid gap-3 p-5 md:grid-cols-2 xl:grid-cols-6"
      >
        <input
          name="name"
          required
          minLength={2}
          placeholder="Full name"
          className="glass-input rounded-xl px-3 py-2 text-sm text-white"
        />
        <input
          name="email"
          required
          type="email"
          placeholder="Email"
          className="glass-input rounded-xl px-3 py-2 text-sm text-white"
        />
        <input
          name="password"
          required
          type="password"
          minLength={12}
          placeholder="Initial password"
          className="glass-input rounded-xl px-3 py-2 text-sm text-white"
        />
        <select
          name="organization_id"
          required
          className="glass-input rounded-xl px-3 py-2 text-sm text-white"
        >
          <option value="">Organization</option>
          {organizations.map((item) => (
            <option key={item.id} value={item.id} className="bg-space-800">
              {item.name}
            </option>
          ))}
        </select>
        <select
          name="role_id"
          required
          className="glass-input rounded-xl px-3 py-2 text-sm text-white"
        >
          <option value="">Role</option>
          {roles
            .filter((item) => item.name !== "Super Owner")
            .map((item) => (
              <option key={item.id} value={item.id} className="bg-space-800">
                {item.name}
              </option>
            ))}
        </select>
        <div className="flex gap-2">
          <select
            name="workspace_id"
            className="glass-input min-w-0 flex-1 rounded-xl px-3 py-2 text-sm text-white"
          >
            <option value="">No workspace</option>
            {workspaces.map((item) => (
              <option key={item.id} value={item.id} className="bg-space-800">
                {item.name}
              </option>
            ))}
          </select>
          <button disabled={busy} className="btn-primary px-3">
            <Plus className="h-4 w-4" />
          </button>
        </div>
      </form>

      <label className="relative block max-w-xl">
        <Search className="absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/30" />
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search users, roles, organizations or workspaces..."
          className="glass-input w-full rounded-xl py-3 ps-10 pe-4 text-sm text-white"
        />
      </label>

      <div className="grid gap-4 xl:grid-cols-2">
        {filtered.map((user) => (
          <article key={user.id} className="glass-card p-5">
            <div className="flex items-start gap-3">
              <span className="rounded-xl bg-electric-500/10 p-2.5 text-electric-300">
                <UserRound className="h-5 w-5" />
              </span>
              <div className="min-w-0 flex-1">
                <h2 className="truncate text-sm font-semibold text-white">
                  {user.name}
                </h2>
                <p className="truncate text-xs text-white/40">{user.email}</p>
                <p className="mt-2 text-xs text-white/45">
                  {user.organization} · {user.role} ·{" "}
                  {user.workspace || "No workspace"}
                </p>
                <p className="mt-1 text-[11px] text-white/30">
                  Last active:{" "}
                  {user.last_active
                    ? new Date(user.last_active).toLocaleString()
                    : "Never"}
                </p>
              </div>
              <span
                className={`rounded-full px-2.5 py-1 text-xs ${user.status === "active" || user.status === "online" ? "bg-green-500/10 text-green-300" : "bg-orange-500/10 text-orange-300"}`}
              >
                {user.status}
              </span>
            </div>
            <div className="mt-4 grid gap-2 sm:grid-cols-[1fr_auto_auto]">
              <select
                value={user.workspace_id || ""}
                disabled={busy}
                onChange={(event) =>
                  void changeUser(user, {
                    workspace_id: event.target.value || null,
                  })
                }
                className="glass-input rounded-lg px-3 py-2 text-xs text-white"
              >
                <option value="">No workspace</option>
                {workspaces
                  .filter(
                    (item) => item.organization_id === user.organization_id,
                  )
                  .map((item) => (
                    <option
                      key={item.id}
                      value={item.id}
                      className="bg-space-800"
                    >
                      {item.name}
                    </option>
                  ))}
              </select>
              <button
                disabled={busy}
                onClick={() =>
                  void changeUser(user, {
                    status:
                      user.status === "active" || user.status === "online"
                        ? "inactive"
                        : "active",
                  })
                }
                className="rounded-lg border border-orange-500/20 bg-orange-500/10 px-3 py-2 text-xs text-orange-300"
              >
                {user.status === "active" || user.status === "online"
                  ? "Suspend"
                  : "Restore"}
              </button>
              <button
                disabled={busy}
                onClick={() => void removeUser(user)}
                className="rounded-lg border border-red-500/20 bg-red-500/10 p-2 text-red-300"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          </article>
        ))}
      </div>
      {loading && (
        <div className="flex items-center gap-2 text-sm text-white/40">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading users…
        </div>
      )}
    </div>
  );
}
