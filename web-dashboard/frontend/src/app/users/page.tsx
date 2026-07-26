"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { Users, Plus, Search, Shield, Mail, Clock } from "lucide-react";

const users = [
  { id: "1", name: "Alex Chen", email: "alex@aionex.io", role: "Super Owner", status: "online", department: "Engineering", lastActive: "2m ago", avatar: null },
  { id: "2", name: "Sarah Johnson", email: "sarah@aionex.io", role: "CTO", status: "online", department: "Engineering", lastActive: "5m ago", avatar: null },
  { id: "3", name: "Mike Davis", email: "mike@aionex.io", role: "Engineering Manager", status: "away", department: "Engineering", lastActive: "1h ago", avatar: null },
  { id: "4", name: "Emma Wilson", email: "emma@aionex.io", role: "Security Officer", status: "online", department: "Security", lastActive: "3m ago", avatar: null },
  { id: "5", name: "Chris Lee", email: "chris@aionex.io", role: "DevOps", status: "offline", department: "Infrastructure", lastActive: "3h ago", avatar: null },
  { id: "6", name: "Lisa Park", email: "lisa@aionex.io", role: "AI Researcher", status: "online", department: "Research", lastActive: "1m ago", avatar: null },
];

export default function UsersPage() {
  const [searchQuery, setSearchQuery] = useState("");
  const filteredUsers = users.filter((u) => u.name.toLowerCase().includes(searchQuery.toLowerCase()) || u.email.toLowerCase().includes(searchQuery.toLowerCase()));

  const getStatusColor = (status: string) => {
    switch (status) {
      case "online": return "bg-green-500";
      case "away": return "bg-orange-500";
      case "busy": return "bg-red-500";
      default: return "bg-white/30";
    }
  };

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight">Users</h1>
          <p className="text-sm text-white/40 mt-1">Manage team members and permissions</p>
        </div>
        <button className="btn-primary"><Plus className="w-4 h-4" />Invite User</button>
      </motion.div>
      <div className="relative max-w-md">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/30" />
        <input type="text" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} placeholder="Search users..." className="w-full pl-10 pr-4 py-2.5 rounded-xl glass-input text-sm text-white placeholder-white/30 outline-none" />
      </div>
      <div className="glass-card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-white/[0.06]">
                <th className="text-left px-4 py-3 text-xs font-semibold text-white/40 uppercase tracking-wider">User</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-white/40 uppercase tracking-wider">Role</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-white/40 uppercase tracking-wider">Department</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-white/40 uppercase tracking-wider">Status</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-white/40 uppercase tracking-wider">Last Active</th>
              </tr>
            </thead>
            <tbody>
              {filteredUsers.map((user, i) => (
                <motion.tr key={user.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * 0.05 }} className="border-b border-white/[0.04] hover:bg-white/[0.02] transition-colors">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500/20 to-purple-500/20 flex items-center justify-center border border-white/[0.08]">
                        <span className="text-xs font-bold text-white">{user.name.charAt(0)}</span>
                      </div>
                      <div>
                        <div className="text-sm font-medium text-white">{user.name}</div>
                        <div className="text-xs text-white/40">{user.email}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3"><span className="px-2 py-0.5 rounded-full text-xs bg-white/[0.06] text-white/60 border border-white/[0.08]">{user.role}</span></td>
                  <td className="px-4 py-3 text-sm text-white/60">{user.department}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <span className={`w-2 h-2 rounded-full ${getStatusColor(user.status)}`} />
                      <span className="text-sm text-white/60 capitalize">{user.status}</span>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-sm text-white/40">{user.lastActive}</td>
                </motion.tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
