"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw, Save, Shield } from "lucide-react";
import {
  identityApi,
  type PermissionRecord,
  type RoleRecord,
} from "@/lib/identity-api";

export default function PermissionsPage() {
  const [roles, setRoles] = useState<RoleRecord[]>([]);
  const [permissions, setPermissions] = useState<PermissionRecord[]>([]);
  const [selectedRoleId, setSelectedRoleId] = useState("");
  const [selectedPermissions, setSelectedPermissions] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("Loading permission catalogue...");

  const load = useCallback(async () => {
    try {
      const [nextRoles, nextPermissions] = await Promise.all([
        identityApi.roles(),
        identityApi.permissions(),
      ]);
      setRoles(nextRoles);
      setPermissions(nextPermissions);
      const selected =
        nextRoles.find((item) => item.id === selectedRoleId) || nextRoles[0];
      if (selected) {
        setSelectedRoleId(selected.id);
        setSelectedPermissions(selected.permissions);
      }
      setMessage(`Synchronized ${nextPermissions.length} permissions.`);
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Permission load failed",
      );
    }
  }, [selectedRoleId]);

  useEffect(() => {
    void load();
  }, [load]);

  const selectedRole = roles.find((item) => item.id === selectedRoleId) || null;
  const grouped = useMemo(() => {
    const result = new Map<string, PermissionRecord[]>();
    for (const item of permissions) {
      const group = item.code.split(":", 1)[0] || "platform";
      result.set(group, [...(result.get(group) || []), item]);
    }
    return [...result.entries()];
  }, [permissions]);

  function chooseRole(roleId: string) {
    setSelectedRoleId(roleId);
    setSelectedPermissions(
      roles.find((item) => item.id === roleId)?.permissions || [],
    );
  }

  async function save() {
    if (!selectedRole) return;
    setBusy(true);
    try {
      const updated = await identityApi.updateRole(selectedRole.id, {
        permissions: selectedPermissions,
      });
      setRoles((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setSelectedPermissions(updated.permissions);
      setMessage("Role permission authority updated.");
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Permission update failed",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Permissions</h1>
          <p className="mt-1 text-sm text-white/40">{message}</p>
        </div>
        <button onClick={() => void load()} className="btn-primary">
          <RefreshCw className="h-4 w-4" />
          Refresh
        </button>
      </header>

      <div className="grid gap-5 lg:grid-cols-[280px_1fr]">
        <aside className="glass-card space-y-2 p-4">
          {roles.map((role) => (
            <button
              key={role.id}
              onClick={() => chooseRole(role.id)}
              className={`w-full rounded-xl px-3 py-3 text-left text-sm ${selectedRoleId === role.id ? "bg-electric-500/15 text-electric-200" : "bg-white/[0.02] text-white/55 hover:bg-white/[0.05]"}`}
            >
              <span className="block font-semibold">{role.name}</span>
              <span className="mt-1 block text-[11px] opacity-60">
                {role.organization || "Global"} · {role.permissions.length}{" "}
                permissions
              </span>
            </button>
          ))}
        </aside>

        <section className="glass-card p-5">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Shield className="h-5 w-5 text-electric-300" />
              <h2 className="text-sm font-semibold text-white">
                {selectedRole?.name || "Select a role"}
              </h2>
            </div>
            <button
              disabled={
                busy || !selectedRole || selectedRole.name === "Super Owner"
              }
              onClick={() => void save()}
              className="btn-primary disabled:opacity-40"
            >
              <Save className="h-4 w-4" />
              Save
            </button>
          </div>
          <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {grouped.map(([group, items]) => (
              <fieldset
                key={group}
                className="rounded-xl border border-white/[0.06] p-4"
              >
                <legend className="px-1 text-xs font-semibold text-white/50">
                  {group}
                </legend>
                <div className="space-y-3">
                  {items.map((permission) => (
                    <label
                      key={permission.id}
                      className="flex items-start gap-2 text-xs text-white/55"
                    >
                      <input
                        type="checkbox"
                        disabled={
                          !selectedRole || selectedRole.name === "Super Owner"
                        }
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
                      <span>
                        <span className="block text-white/70">
                          {permission.code}
                        </span>
                        <span className="mt-0.5 block text-[10px] text-white/30">
                          {permission.description || "No description"}
                        </span>
                      </span>
                    </label>
                  ))}
                </div>
              </fieldset>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
