"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import {
  Activity,
  Building2,
  FolderKanban,
  Play,
  ShieldCheck,
  UserCog,
} from "lucide-react";
import { useOwnerResource } from "@/hooks/use-owner-resource";
import {
  executeOwnerOperation,
  type OwnerEntityKind,
  type OwnerOperation,
} from "@/lib/owner-operations";

type OwnerOrganizationOption = {
  id: string;
  name: string;
  status: string;
};

type OwnerRoleOption = {
  id: string;
  name: string;
  scope: string;
  status: "active" | "suspended" | "protected";
};

const entities: { value: OwnerEntityKind; label: string }[] = [
  { value: "project", label: "Project" },
  { value: "organization", label: "Organization" },
  { value: "user", label: "User" },
];

const operations: OwnerOperation[] = [
  "create",
  "update",
  "suspend",
  "restore",
  "delete",
];

export default function OwnerOperationsPage() {
  const [entity, setEntity] = useState<OwnerEntityKind>("project");
  const [operation, setOperation] = useState<OwnerOperation>("create");
  const [recordId, setRecordId] = useState("");
  const [name, setName] = useState("");
  const [organizationId, setOrganizationId] = useState("");
  const [roleId, setRoleId] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [description, setDescription] = useState("");
  const [plan, setPlan] = useState("enterprise");
  const [priority, setPriority] = useState("medium");
  const [message, setMessage] = useState(
    "Ready to execute an audited Owner operation.",
  );
  const [running, setRunning] = useState(false);
  const runningRef = useRef(false);

  const {
    items: organizations,
    loading: organizationsLoading,
    message: organizationsMessage,
  } = useOwnerResource<OwnerOrganizationOption>("organizations");
  const {
    items: roles,
    loading: rolesLoading,
    message: rolesMessage,
  } = useOwnerResource<OwnerRoleOption>("access");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const requestedEntity = params.get("entity");
    const requestedOperation = params.get("operation");
    const requestedId = params.get("id");
    const validEntity = entities.some((item) => item.value === requestedEntity);
    const validOperation = operations.includes(
      requestedOperation as OwnerOperation,
    );

    if (validEntity) setEntity(requestedEntity as OwnerEntityKind);
    if (validOperation) {
      const nextOperation = requestedOperation as OwnerOperation;
      setOperation(nextOperation);
      setPlan(nextOperation === "create" ? "enterprise" : "");
      setPriority(nextOperation === "create" ? "medium" : "");
    }
    if (requestedId) setRecordId(requestedId);
  }, []);

  useEffect(() => {
    if (!organizationId && organizations.length === 1) {
      setOrganizationId(organizations[0].id);
    }
  }, [organizationId, organizations]);

  useEffect(() => {
    const availableRoles = roles.filter((role) => role.status !== "suspended");
    if (!roleId && availableRoles.length === 1) {
      setRoleId(availableRoles[0].id);
    }
  }, [roleId, roles]);

  const Icon = useMemo(
    () =>
      entity === "project"
        ? FolderKanban
        : entity === "organization"
          ? Building2
          : UserCog,
    [entity],
  );

  const activeRoles = useMemo(
    () => roles.filter((role) => role.status !== "suspended"),
    [roles],
  );

  const referencesLoading = organizationsLoading || rolesLoading;
  const createUserReady =
    entity !== "user" ||
    operation !== "create" ||
    (Boolean(organizationId) &&
      Boolean(roleId) &&
      Boolean(email.trim()) &&
      password.length >= 12);

  async function submit() {
    const payload: Record<string, unknown> = {};
    if (name.trim()) payload.name = name.trim();

    if (entity === "organization" && ["create", "update"].includes(operation)) {
      if (operation === "create") payload.plan = plan || "enterprise";
      if (operation === "update" && plan) payload.plan = plan;
    }

    if (entity === "project" && ["create", "update"].includes(operation)) {
      if (description.trim()) payload.description = description.trim();
      if (operation === "create") payload.priority = priority || "medium";
      if (operation === "update" && priority) payload.priority = priority;
      if (operation === "create" && organizationId) {
        payload.organization_id = organizationId;
      }
    }

    if (entity === "user" && ["create", "update"].includes(operation)) {
      if (roleId) payload.role_id = roleId;
      if (operation === "create") {
        payload.organization_id = organizationId;
        payload.email = email.trim();
        payload.password = password;
      }
    }

    if (operation !== "create" && !recordId.trim()) {
      setMessage("Record ID is required for this operation.");
      return;
    }
    if (operation === "create" && name.trim().length < 2) {
      setMessage("A name with at least two characters is required.");
      return;
    }
    if (entity === "user" && operation === "create" && !createUserReady) {
      setMessage(
        "Select a live organization and role, enter a valid email, and use a 12+ character password.",
      );
      return;
    }
    if (operation === "update" && Object.keys(payload).length === 0) {
      setMessage("Provide at least one field to update.");
      return;
    }
    if (
      ["suspend", "delete"].includes(operation) &&
      !window.confirm(
        `${operation === "delete" ? "Delete" : "Suspend"} this ${entity}? This audited operation changes its live platform state.`,
      )
    ) {
      return;
    }
    if (runningRef.current) return;

    runningRef.current = true;
    setRunning(true);
    setMessage("Executing protected owner operation...");
    try {
      const result = await executeOwnerOperation({
        entity,
        operation,
        id: recordId.trim() || undefined,
        payload,
      });
      setMessage(`${result.message} Operation ID: ${result.operationId}`);
      setPassword("");
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Owner operation failed.",
      );
    } finally {
      runningRef.current = false;
      setRunning(false);
    }
  }

  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs font-medium text-electric-300">
          <ShieldCheck className="h-3.5 w-3.5" /> Owner CRUD Gateway
        </div>
        <h1 className="text-3xl font-bold tracking-tight text-white">
          Protected Entity Operations
        </h1>
        <p className="mt-2 text-sm text-white/45">
          Authenticated create, update, suspend, restore and delete requests for
          owner-managed records. No local-only success is reported when the
          backend contract is unavailable.
        </p>
      </motion.div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1fr_320px]">
        <fieldset
          disabled={running}
          className="glass-card space-y-4 p-5 disabled:opacity-80"
        >
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <label className="space-y-2 text-xs text-white/50">
              Entity
              <select
                value={entity}
                onChange={(event) => {
                  setEntity(event.target.value as OwnerEntityKind);
                  setPlan(operation === "create" ? "enterprise" : "");
                  setPriority(operation === "create" ? "medium" : "");
                }}
                className="glass-input w-full rounded-xl px-4 py-3 text-sm text-white outline-none"
              >
                {entities.map((item) => (
                  <option
                    key={item.value}
                    value={item.value}
                    className="bg-space-800"
                  >
                    {item.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="space-y-2 text-xs text-white/50">
              Operation
              <select
                value={operation}
                onChange={(event) => {
                  const nextOperation = event.target.value as OwnerOperation;
                  setOperation(nextOperation);
                  setPlan(nextOperation === "create" ? "enterprise" : "");
                  setPriority(nextOperation === "create" ? "medium" : "");
                }}
                className="glass-input w-full rounded-xl px-4 py-3 text-sm text-white outline-none"
              >
                {operations.map((item) => (
                  <option key={item} value={item} className="bg-space-800">
                    {item}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <label className="block space-y-2 text-xs text-white/50">
            Record ID
            <input
              value={recordId}
              onChange={(event) => setRecordId(event.target.value)}
              placeholder={
                operation === "create" ? "Generated by the backend" : "Required"
              }
              disabled={operation === "create"}
              className="glass-input w-full rounded-xl px-4 py-3 text-sm text-white outline-none"
            />
          </label>

          {["create", "update"].includes(operation) && (
            <>
              <label className="block space-y-2 text-xs text-white/50">
                Name
                <input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder={
                    operation === "create"
                      ? `${entity} name`
                      : "Leave blank to keep the current name"
                  }
                  className="glass-input w-full rounded-xl px-4 py-3 text-sm text-white outline-none"
                />
              </label>

              {entity === "organization" && (
                <label className="block space-y-2 text-xs text-white/50">
                  Plan
                  <select
                    value={plan}
                    onChange={(event) => setPlan(event.target.value)}
                    className="glass-input w-full rounded-xl px-4 py-3 text-sm text-white outline-none"
                  >
                    {operation === "update" && (
                      <option value="" className="bg-space-800">
                        Keep current plan
                      </option>
                    )}
                    {["enterprise", "professional", "starter"].map((item) => (
                      <option key={item} value={item} className="bg-space-800">
                        {item}
                      </option>
                    ))}
                  </select>
                </label>
              )}

              {entity === "project" && (
                <>
                  {operation === "create" && (
                    <label className="block space-y-2 text-xs text-white/50">
                      Organization
                      <select
                        value={organizationId}
                        onChange={(event) =>
                          setOrganizationId(event.target.value)
                        }
                        disabled={organizationsLoading}
                        className="glass-input w-full rounded-xl px-4 py-3 text-sm text-white outline-none"
                      >
                        <option value="" className="bg-space-800">
                          Owner default organization
                        </option>
                        {organizations.map((organization) => (
                          <option
                            key={organization.id}
                            value={organization.id}
                            className="bg-space-800"
                          >
                            {organization.name} · {organization.status}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}

                  <label className="block space-y-2 text-xs text-white/50">
                    Description
                    <textarea
                      value={description}
                      onChange={(event) => setDescription(event.target.value)}
                      rows={3}
                      className="glass-input w-full rounded-xl px-4 py-3 text-sm text-white outline-none"
                    />
                  </label>

                  <label className="block space-y-2 text-xs text-white/50">
                    Priority
                    <select
                      value={priority}
                      onChange={(event) => setPriority(event.target.value)}
                      className="glass-input w-full rounded-xl px-4 py-3 text-sm text-white outline-none"
                    >
                      {operation === "update" && (
                        <option value="" className="bg-space-800">
                          Keep current priority
                        </option>
                      )}
                      {["low", "medium", "high", "critical"].map((item) => (
                        <option key={item} value={item} className="bg-space-800">
                          {item}
                        </option>
                      ))}
                    </select>
                  </label>
                </>
              )}

              {entity === "user" && (
                <>
                  <label className="block space-y-2 text-xs text-white/50">
                    Role
                    <select
                      value={roleId}
                      onChange={(event) => setRoleId(event.target.value)}
                      disabled={rolesLoading}
                      className="glass-input w-full rounded-xl px-4 py-3 text-sm text-white outline-none"
                    >
                      <option value="" className="bg-space-800">
                        Select a live role
                      </option>
                      {activeRoles.map((role) => (
                        <option
                          key={role.id}
                          value={role.id}
                          className="bg-space-800"
                        >
                          {role.name} · {role.scope} · {role.status}
                        </option>
                      ))}
                    </select>
                  </label>

                  {operation === "create" && (
                    <>
                      <label className="block space-y-2 text-xs text-white/50">
                        Organization
                        <select
                          value={organizationId}
                          onChange={(event) =>
                            setOrganizationId(event.target.value)
                          }
                          disabled={organizationsLoading}
                          className="glass-input w-full rounded-xl px-4 py-3 text-sm text-white outline-none"
                        >
                          <option value="" className="bg-space-800">
                            Select a live organization
                          </option>
                          {organizations.map((organization) => (
                            <option
                              key={organization.id}
                              value={organization.id}
                              className="bg-space-800"
                            >
                              {organization.name} · {organization.status}
                            </option>
                          ))}
                        </select>
                      </label>

                      <label className="block space-y-2 text-xs text-white/50">
                        Email
                        <input
                          type="email"
                          value={email}
                          onChange={(event) => setEmail(event.target.value)}
                          placeholder="owner-managed@example.com"
                          className="glass-input w-full rounded-xl px-4 py-3 text-sm text-white outline-none"
                        />
                      </label>

                      <label className="block space-y-2 text-xs text-white/50">
                        Initial password
                        <input
                          type="password"
                          value={password}
                          onChange={(event) => setPassword(event.target.value)}
                          placeholder="12+ characters"
                          autoComplete="new-password"
                          className="glass-input w-full rounded-xl px-4 py-3 text-sm text-white outline-none"
                        />
                      </label>
                    </>
                  )}
                </>
              )}
            </>
          )}

          <button
            type="button"
            disabled={running || referencesLoading || !createUserReady}
            onClick={() => void submit()}
            className="btn-primary disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Play className="h-4 w-4" />
            {running
              ? "Executing..."
              : referencesLoading
                ? "Loading live references..."
                : "Execute operation"}
          </button>

          <div className="flex items-start gap-2 rounded-xl border border-electric-500/15 bg-electric-500/5 p-4 text-xs text-electric-300">
            <Activity className="mt-0.5 h-4 w-4 flex-shrink-0" />
            <div className="space-y-1">
              <div>{message}</div>
              {(organizationsLoading || rolesLoading) && (
                <div className="text-electric-200/70">
                  {organizationsLoading
                    ? organizationsMessage
                    : rolesLoading
                      ? rolesMessage
                      : null}
                </div>
              )}
            </div>
          </div>
        </fieldset>

        <div className="glass-card p-5">
          <div className="rounded-xl border border-white/[0.06] bg-white/[0.03] p-3">
            <Icon className="h-6 w-6 text-electric-300" />
          </div>
          <h2 className="mt-4 text-sm font-semibold text-white">
            Current request
          </h2>
          <dl className="mt-4 space-y-3 text-xs">
            <div className="flex justify-between gap-3">
              <dt className="text-white/35">Entity</dt>
              <dd className="text-white/75">{entity}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-white/35">Operation</dt>
              <dd className="text-white/75">{operation}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-white/35">Record</dt>
              <dd className="max-w-[180px] truncate text-white/75">
                {recordId || "new record"}
              </dd>
            </div>
          </dl>
        </div>
      </div>
    </div>
  );
}
