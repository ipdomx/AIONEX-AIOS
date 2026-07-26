"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { Settings, User, Shield, Bell, Globe, Palette, Database, CreditCard, Key } from "lucide-react";

const settingsSections = [
  { id: "profile", label: "Profile", icon: User, description: "Manage your personal information" },
  { id: "security", label: "Security", icon: Shield, description: "Password, MFA, and sessions" },
  { id: "notifications", label: "Notifications", icon: Bell, description: "Email, push, and webhook settings" },
  { id: "language", label: "Language & Region", icon: Globe, description: "Language, timezone, and format" },
  { id: "appearance", label: "Appearance", icon: Palette, description: "Theme, colors, and layout" },
  { id: "database", label: "Database", icon: Database, description: "Connection and migration settings" },
  { id: "billing", label: "Billing", icon: CreditCard, description: "Subscription and payment methods" },
  { id: "api", label: "API Keys", icon: Key, description: "Manage API keys and webhooks" },
];

export default function SettingsPage() {
  const [activeSection, setActiveSection] = useState("profile");

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }}>
        <h1 className="text-2xl font-bold text-white tracking-tight">Settings</h1>
        <p className="text-sm text-white/40 mt-1">Manage your account and system preferences</p>
      </motion.div>
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        <motion.div initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} className="space-y-1">
          {settingsSections.map((section) => {
            const Icon = section.icon;
            const isActive = activeSection === section.id;
            return (
              <button key={section.id} onClick={() => setActiveSection(section.id)} className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl text-left transition-all duration-200 ${isActive ? "bg-white/[0.08] text-white" : "text-white/50 hover:text-white/80 hover:bg-white/[0.04]"}`}>
                <Icon className={`w-[18px] h-[18px] ${isActive ? "text-electric-400" : "text-white/40"}`} />
                <div className="flex-1">
                  <div className="text-sm font-medium">{section.label}</div>
                  <div className="text-[10px] text-white/30">{section.description}</div>
                </div>
              </button>
            );
          })}
        </motion.div>
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="lg:col-span-3 glass-card p-6">
          {activeSection === "profile" && (
            <div className="space-y-6">
              <h2 className="text-lg font-semibold text-white">Profile Settings</h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-2"><label className="text-xs text-white/40 uppercase tracking-wider">Full Name</label><input type="text" defaultValue="Alex Chen" className="w-full px-4 py-2.5 rounded-xl glass-input text-sm text-white outline-none" /></div>
                <div className="space-y-2"><label className="text-xs text-white/40 uppercase tracking-wider">Email</label><input type="email" defaultValue="alex@aionex.io" className="w-full px-4 py-2.5 rounded-xl glass-input text-sm text-white outline-none" /></div>
                <div className="space-y-2"><label className="text-xs text-white/40 uppercase tracking-wider">Job Title</label><input type="text" defaultValue="Super Owner" className="w-full px-4 py-2.5 rounded-xl glass-input text-sm text-white outline-none" /></div>
                <div className="space-y-2"><label className="text-xs text-white/40 uppercase tracking-wider">Department</label><input type="text" defaultValue="Engineering" className="w-full px-4 py-2.5 rounded-xl glass-input text-sm text-white outline-none" /></div>
              </div>
              <div className="flex justify-end"><button className="btn-primary">Save Changes</button></div>
            </div>
          )}
          {activeSection === "security" && (
            <div className="space-y-6">
              <h2 className="text-lg font-semibold text-white">Security Settings</h2>
              <div className="space-y-4">
                <div className="p-4 rounded-xl bg-white/[0.02] border border-white/[0.04]">
                  <div className="flex items-center justify-between"><div><h3 className="text-sm font-medium text-white">Two-Factor Authentication</h3><p className="text-xs text-white/40">Add an extra layer of security</p></div><button className="px-4 py-2 rounded-lg bg-green-500/10 text-green-400 text-xs font-medium border border-green-500/20">Enabled</button></div>
                </div>
                <div className="p-4 rounded-xl bg-white/[0.02] border border-white/[0.04]">
                  <div className="flex items-center justify-between"><div><h3 className="text-sm font-medium text-white">Password</h3><p className="text-xs text-white/40">Last changed 30 days ago</p></div><button className="px-4 py-2 rounded-lg bg-white/[0.04] text-white/60 text-xs font-medium border border-white/[0.08] hover:bg-white/[0.08]">Change</button></div>
                </div>
                <div className="p-4 rounded-xl bg-white/[0.02] border border-white/[0.04]">
                  <div className="flex items-center justify-between"><div><h3 className="text-sm font-medium text-white">Active Sessions</h3><p className="text-xs text-white/40">3 active sessions</p></div><button className="px-4 py-2 rounded-lg bg-white/[0.04] text-white/60 text-xs font-medium border border-white/[0.08] hover:bg-white/[0.08]">Manage</button></div>
                </div>
              </div>
            </div>
          )}
          {activeSection === "appearance" && (
            <div className="space-y-6">
              <h2 className="text-lg font-semibold text-white">Appearance</h2>
              <div className="space-y-4">
                <div className="space-y-2"><label className="text-xs text-white/40 uppercase tracking-wider">Theme</label><div className="flex gap-3"><button className="flex-1 p-4 rounded-xl bg-white/[0.08] border border-electric-500/50 text-center"><div className="text-sm font-medium text-white">Dark</div></button><button className="flex-1 p-4 rounded-xl bg-white/[0.02] border border-white/[0.06] text-center"><div className="text-sm font-medium text-white/60">Light</div></button><button className="flex-1 p-4 rounded-xl bg-white/[0.02] border border-white/[0.06] text-center"><div className="text-sm font-medium text-white/60">System</div></button></div></div>
              </div>
            </div>
          )}
          {activeSection !== "profile" && activeSection !== "security" && activeSection !== "appearance" && (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Settings className="w-12 h-12 text-white/10 mb-4" />
              <p className="text-sm text-white/30">{settingsSections.find((s) => s.id === activeSection)?.label} settings coming soon</p>
            </div>
          )}
        </motion.div>
      </div>
    </div>
  );
}
