"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Plus, RefreshCw, ShieldCheck, Trash2 } from "lucide-react";
import {
  identityApi,
  type OrganizationRecord,
  type PermissionRecord,
  type RoleRecord,
} from "@/lib/identity-api";

export default function RolesPage() {
  const [roles, setRoles] = useState<RoleRecord[]>([]);
  const [permissions, setPermissions] = useState<PermissionRecord[]>([]);
  const [organizations, setOrganizations] = useState<OrganizationRecord[]>([]);
  const [selectedPermissions, setSelectedPermissions] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("Loading role authority...");

  async function load() {
    try {
      const [nextRoles, nextPermissions, nextOrganizations] = await Promise.all(
        [
          identityApi.roles(),
          identityApi.permissions(),
          identityApi.organizations(),
        ],
      );
      setRoles(nextRoles);
      setPermissions(nextPermissions);
      setOrganizations(nextOrganizations);
      setMessage(
        `Synchronized ${nextRoles.length} roles and ${nextPermissions.length} permissions.`,
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Role load failed");
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const groupedPermissions = useMemo(() => {
    const groups = new Map<string, PermissionRecord[]>();
    for (const permission of permissions) {
      const group = permission.code.split(":", 1)[0] || "platform";
      groups.set(group, [...(groups.get(group) || []), permission]);
    }
    return [...groups.entries()];
  }, [permissions]);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    try {
      const role = await identityApi.createRole({
        name: String(form.get("name") || "").trim(),
        description: String(form.get("description") || "").trim(),
        organization_id: String(form.get("organization_id") || "") || undefined,
        permissions: selectedPermissions,
      });
      setRoles((current) => [...current, role]);
      setSelectedPermissions([]);
      event.currentTarget.reset();
      setMessage("Role and permission assignments created.");
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Role creation failed",
      );
    } finally {
      setBusy(false);
    }
  }

  async function remove(role: RoleRecord) {
    if (!window.confirm(`Delete role ${role.name}?`)) return;
    setBusy(true);
    try {
      await identityApi.deleteRole(role.id);
      setRoles((current) => current.filter((item) => item.id !== role.id));
      setMessage("Role deleted.");
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Role deletion failed",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <header className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Roles</h1>
          <p className="mt-1 text-sm text-white/40">{message}</p>
        </div>
        <button onClick={() => void load()} className="btn-primary">
          <RefreshCw className="h-4 w-4" />
          Refresh
        </button>
      </header>

      <form onSubmit={create} className="glass-card space-y-4 p-5">
        <div className="grid gap-3 md:grid-cols-3">
          <input
            name="name"
            required
            minLength={2}
            placeholder="Role name"
            className="glass-input rounded-xl px-3 py-2 text-sm text-white"
          />
          <input
            name="description"
            placeholder="Description"
            className="glass-input rounded-xl px-3 py-2 text-sm text-white"
          />
          <select
            name="organization_id"
            className="glass-input rounded-xl px-3 py-2 text-sm text-white"
          >
            <option value="">Current organization</option>
            {organizations.map((item) => (
              <option key={item.id} value={item.id} className="bg-space-800">
                {item.name}
              </option>
            ))}
          </select>
        </div>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {groupedPermissions.map(([group, items]) => (
            <fieldset
              key={group}
              className="rounded-xl border border-white/[0.06] p-3"
            >
              <legend className="px-1 text-xs font-semibold text-white/50">
                {group}
              </legend>
              <div className="space-y-2">
                {items.map((permission) => (
                  <label
                    key={permission.id}
                    className="flex items-start gap-2 text-xs text-white/55"
                  >
                    <input
                      type="checkbox"
                      checked={selectedPermissions.includes(permission.code)}
                      onChange={(event) =>
                        setSelectedPermissions((current) =>
                          event.target.checked
                            ? [...current, permission.code]
                            : current.filter(
                                (code) => code !== permission.code,
                              ),
                        )
                      }
                    />
                    <span>{permission.code}</span>
                  </label>
                ))}
              </div>
            </fieldset>
          ))}
        </div>
        <button
          disabled={busy || !selectedPermissions.length}
          className="btn-primary"
        >
          <Plus className="h-4 w-4" />
          Create role
        </button>
      </form>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {roles.map((role) => (
          <article key={role.id} className="glass-card p-5">
            <div className="flex items-start gap-3">
              <ShieldCheck className="h-5 w-5 text-electric-300" />
              <div className="min-w-0 flex-1">
                <h2 className="truncate text-sm font-semibold text-white">
                  {role.name}
                </h2>
                <p className="text-xs text-white/35">
                  {role.organization || "Global"} · {role.status}
                </p>
              </div>
              {!role.system && (
                <button
                  disabled={busy}
                  onClick={() => void remove(role)}
                  className="rounded-lg border border-red-500/20 bg-red-500/10 p-2 text-red-300"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              )}
            </div>
            <p className="mt-3 text-xs leading-6 text-white/45">
              {role.description || "No description"}
            </p>
            <div className="mt-4 flex flex-wrap gap-1.5">
              {role.permissions.map((permission) => (
                <span
                  key={permission}
                  className="rounded-md bg-white/[0.05] px-2 py-1 text-[10px] text-white/45"
                >
                  {permission}
                </span>
              ))}
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}
