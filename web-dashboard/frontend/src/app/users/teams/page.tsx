"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type FormEvent,
} from "react";
import { Plus, RefreshCw, Trash2, UsersRound } from "lucide-react";
import {
  identityApi,
  type IdentityUser,
  type OrganizationRecord,
  type TeamRecord,
  type WorkspaceRecord,
} from "@/lib/identity-api";

export default function TeamsPage() {
  const [teams, setTeams] = useState<TeamRecord[]>([]);
  const [organizations, setOrganizations] = useState<OrganizationRecord[]>([]);
  const [createOrganizationId, setCreateOrganizationId] = useState("");
  const [users, setUsers] = useState<IdentityUser[]>([]);
  const [workspaces, setWorkspaces] = useState<WorkspaceRecord[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [members, setMembers] = useState<
    Array<IdentityUser & { membership_role: "lead" | "member" }>
  >([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("Loading teams...");

  const load = useCallback(async () => {
    try {
      const [nextTeams, nextOrganizations, nextUsers, nextWorkspaces] =
        await Promise.all([
          identityApi.teams(),
          identityApi.organizations(),
          identityApi.users(),
          identityApi.workspaces(),
        ]);
      setTeams(nextTeams);
      setOrganizations(nextOrganizations);
      setCreateOrganizationId(
        (current) => current || nextOrganizations[0]?.id || "",
      );
      setUsers(nextUsers);
      setWorkspaces(nextWorkspaces);
      setMessage(`Synchronized ${nextTeams.length} teams.`);
      if (selected && !nextTeams.some((item) => item.id === selected))
        setSelected("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Team load failed");
    }
  }, [selected]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!selected) {
      setMembers([]);
      return;
    }
    identityApi
      .teamMembers(selected)
      .then(setMembers)
      .catch((error) => {
        setMessage(
          error instanceof Error ? error.message : "Team members failed",
        );
      });
  }, [selected]);

  const selectedTeam = useMemo(
    () => teams.find((item) => item.id === selected) || null,
    [selected, teams],
  );

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    try {
      const team = await identityApi.createTeam({
        name: String(form.get("name") || "").trim(),
        organization_id: String(form.get("organization_id") || "") || undefined,
        description: String(form.get("description") || "").trim() || undefined,
        workspace_id: String(form.get("workspace_id") || "") || null,
      });
      setTeams((current) => [...current, team]);
      setSelected(team.id);
      event.currentTarget.reset();
      setMessage("Team created.");
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Team creation failed",
      );
    } finally {
      setBusy(false);
    }
  }

  async function addMember(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) return;
    const form = new FormData(event.currentTarget);
    const userId = String(form.get("user_id") || "");
    const role = String(form.get("membership_role") || "member") as
      "lead" | "member";
    setBusy(true);
    try {
      await identityApi.upsertTeamMember(selected, userId, role);
      setMembers(await identityApi.teamMembers(selected));
      setTeams(await identityApi.teams());
      setMessage("Team membership synchronized.");
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Membership update failed",
      );
    } finally {
      setBusy(false);
    }
  }

  async function removeMember(userId: string) {
    if (!selected) return;
    setBusy(true);
    try {
      await identityApi.removeTeamMember(selected, userId);
      setMembers((current) => current.filter((item) => item.id !== userId));
      setTeams(await identityApi.teams());
      setMessage("Team member removed.");
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Member removal failed",
      );
    } finally {
      setBusy(false);
    }
  }

  async function deleteTeam(team: TeamRecord) {
    if (!window.confirm(`Delete team ${team.name}?`)) return;
    setBusy(true);
    try {
      await identityApi.deleteTeam(team.id);
      setTeams((current) => current.filter((item) => item.id !== team.id));
      if (selected === team.id) setSelected("");
      setMessage("Team deleted.");
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Team deletion failed",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <header className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Teams</h1>
          <p className="mt-1 text-sm text-white/40">{message}</p>
        </div>
        <button onClick={() => void load()} className="btn-primary">
          <RefreshCw className="h-4 w-4" />
          Refresh
        </button>
      </header>

      <form
        onSubmit={create}
        className="glass-card grid gap-3 p-5 md:grid-cols-5"
      >
        <input
          name="name"
          required
          minLength={2}
          placeholder="Team name"
          className="glass-input rounded-xl px-3 py-2 text-sm text-white"
        />
        <input
          name="description"
          placeholder="Description"
          className="glass-input rounded-xl px-3 py-2 text-sm text-white"
        />
        <select
          name="organization_id"
          required
          value={createOrganizationId}
          onChange={(event) => setCreateOrganizationId(event.target.value)}
          className="glass-input rounded-xl px-3 py-2 text-sm text-white"
        >
          <option value="">Organization</option>
          {organizations
            .filter((item) => item.status === "active")
            .map((item) => (
              <option key={item.id} value={item.id} className="bg-space-800">
                {item.name}
              </option>
            ))}
        </select>
        <select
          name="workspace_id"
          className="glass-input rounded-xl px-3 py-2 text-sm text-white"
        >
          <option value="">Organization-wide</option>
          {workspaces
            .filter((item) => item.organization_id === createOrganizationId)
            .map((item) => (
              <option key={item.id} value={item.id} className="bg-space-800">
                {item.name}
              </option>
            ))}
        </select>
        <button disabled={busy} className="btn-primary">
          <Plus className="h-4 w-4" />
          Create team
        </button>
      </form>

      <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
        <div className="space-y-3">
          {teams.map((team) => (
            <button
              key={team.id}
              onClick={() => setSelected(team.id)}
              className={`glass-card flex w-full items-center gap-3 p-4 text-left ${selected === team.id ? "border border-electric-400/30 bg-electric-500/10" : ""}`}
            >
              <UsersRound className="h-5 w-5 text-electric-300" />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-semibold text-white">
                  {team.name}
                </span>
                <span className="block text-xs text-white/35">
                  {team.workspace || "Organization-wide"} · {team.member_count}{" "}
                  members
                </span>
              </span>
              <span
                onClick={(event) => {
                  event.stopPropagation();
                  void deleteTeam(team);
                }}
                className="rounded-lg border border-red-500/20 bg-red-500/10 p-2 text-red-300"
              >
                <Trash2 className="h-4 w-4" />
              </span>
            </button>
          ))}
        </div>

        <section className="glass-card p-5">
          <h2 className="text-sm font-semibold text-white">
            {selectedTeam ? `${selectedTeam.name} members` : "Select a team"}
          </h2>
          {selectedTeam && (
            <>
              <form
                onSubmit={addMember}
                className="mt-4 grid gap-2 sm:grid-cols-[1fr_auto_auto]"
              >
                <select
                  name="user_id"
                  required
                  className="glass-input rounded-lg px-3 py-2 text-xs text-white"
                >
                  <option value="">User</option>
                  {users
                    .filter(
                      (user) =>
                        user.organization_id === selectedTeam.organization_id,
                    )
                    .map((user) => (
                      <option
                        key={user.id}
                        value={user.id}
                        className="bg-space-800"
                      >
                        {user.name} — {user.email}
                      </option>
                    ))}
                </select>
                <select
                  name="membership_role"
                  className="glass-input rounded-lg px-3 py-2 text-xs text-white"
                >
                  <option value="member" className="bg-space-800">
                    Member
                  </option>
                  <option value="lead" className="bg-space-800">
                    Lead
                  </option>
                </select>
                <button disabled={busy} className="btn-primary px-3 text-xs">
                  Add
                </button>
              </form>
              <div className="mt-5 space-y-2">
                {members.map((member) => (
                  <div
                    key={member.id}
                    className="flex items-center gap-3 rounded-xl bg-white/[0.03] p-3"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm text-white">
                        {member.name}
                      </div>
                      <div className="truncate text-xs text-white/35">
                        {member.email} · {member.membership_role}
                      </div>
                    </div>
                    <button
                      disabled={busy}
                      onClick={() => void removeMember(member.id)}
                      className="text-xs text-red-300"
                    >
                      Remove
                    </button>
                  </div>
                ))}
                {!members.length && (
                  <p className="text-xs text-white/35">No members assigned.</p>
                )}
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
