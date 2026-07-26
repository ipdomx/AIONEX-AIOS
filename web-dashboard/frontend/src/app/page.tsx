"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  BarChart3,
  Bot,
  Calendar,
  CheckCircle2,
  CheckSquare,
  Clock,
  Cpu,
  Database,
  FileText,
  Globe,
  HardDrive,
  Layers,
  MessageSquare,
  Minus,
  Network,
  Plus,
  Server,
  Shield,
  Sparkles,
  TrendingDown,
  TrendingUp,
  Users,
  Workflow,
  Zap,
} from "lucide-react";
import CountUp from "react-countup";

function AnimatedCounter({ end, duration = 2, suffix = "" }: { end: number; duration?: number; suffix?: string }) {
  return <CountUp end={end} duration={duration} separator="," suffix={suffix} className="tabular-nums" />;
}

function MetricCard({
  title,
  value,
  change,
  changeType,
  icon: Icon,
  color,
  delay = 0,
}: {
  title: string;
  value: number;
  change: number;
  changeType: "up" | "down" | "neutral";
  icon: React.ElementType;
  color: string;
  delay?: number;
}) {
  const ChangeIcon = changeType === "up" ? TrendingUp : changeType === "down" ? TrendingDown : Minus;
  const changeColor = changeType === "up" ? "text-green-400" : changeType === "down" ? "text-red-400" : "text-white/40";

  return (
    <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, delay, ease: [0.16, 1, 0.3, 1] }} className="glass-card p-5 group">
      <div className="flex items-start justify-between mb-4">
        <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${color}`}>
          <Icon className="w-5 h-5 text-white" />
        </div>
        <div className={`flex items-center gap-1 text-xs font-medium ${changeColor}`}>
          <ChangeIcon className="w-3.5 h-3.5" />
          <span>{Math.abs(change)}%</span>
        </div>
      </div>
      <div className="space-y-1">
        <div className="text-2xl font-bold text-white tracking-tight"><AnimatedCounter end={value} /></div>
        <div className="text-xs text-white/40 font-medium">{title}</div>
      </div>
    </motion.div>
  );
}

function StatusBadge({ status, text }: { status: "online" | "warning" | "error" | "offline"; text: string }) {
  const colors = {
    online: "bg-green-500/10 text-green-400 border-green-500/20",
    warning: "bg-orange-500/10 text-orange-400 border-orange-500/20",
    error: "bg-red-500/10 text-red-400 border-red-500/20",
    offline: "bg-white/10 text-white/40 border-white/20",
  };

  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${colors[status]}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${status === "online" ? "bg-green-400 animate-pulse" : status === "warning" ? "bg-orange-400" : status === "error" ? "bg-red-400" : "bg-white/40"}`} />
      {text}
    </span>
  );
}

function ActivityItem({ icon: Icon, title, description, time, color }: { icon: React.ElementType; title: string; description: string; time: string; color: string }) {
  return (
    <div className="flex items-start gap-3 py-3 border-b border-white/[0.04] last:border-0">
      <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${color}`}><Icon className="w-4 h-4 text-white" /></div>
      <div className="flex-1 min-w-0"><p className="text-sm font-medium text-white truncate">{title}</p><p className="text-xs text-white/40 mt-0.5">{description}</p></div>
      <span className="text-[10px] text-white/30 flex-shrink-0">{time}</span>
    </div>
  );
}

function ResourceBar({ label, used, total, color }: { label: string; used: number; total: number; color: string }) {
  const percentage = Math.round((used / total) * 100);
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between"><span className="text-xs text-white/50">{label}</span><span className="text-xs font-medium text-white/70">{used} / {total} GB</span></div>
      <div className="h-1.5 rounded-full bg-white/[0.06] overflow-hidden"><motion.div initial={{ width: 0 }} animate={{ width: `${percentage}%` }} transition={{ duration: 1, delay: 0.5, ease: [0.16, 1, 0.3, 1] }} className={`h-full rounded-full ${color}`} /></div>
    </div>
  );
}

export default function DashboardPage() {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  if (!mounted) return null;

  const metrics = [
    { title: "Total Users", value: 2847, change: 12.5, changeType: "up" as const, icon: Users, color: "bg-blue-500/20" },
    { title: "AI Agents", value: 156, change: 8.3, changeType: "up" as const, icon: Bot, color: "bg-purple-500/20" },
    { title: "Active Workflows", value: 89, change: -2.1, changeType: "down" as const, icon: Workflow, color: "bg-cyan-500/20" },
    { title: "Servers Online", value: 42, change: 0, changeType: "neutral" as const, icon: Server, color: "bg-green-500/20" },
    { title: "Databases", value: 18, change: 5.7, changeType: "up" as const, icon: Database, color: "bg-orange-500/20" },
    { title: "API Calls Today", value: 2847291, change: 23.4, changeType: "up" as const, icon: Zap, color: "bg-electric-500/20" },
  ];

  const activities = [
    { icon: CheckCircle2, title: "Deployment Complete", description: "Workflow 'Data Pipeline v2' deployed to production", time: "2m ago", color: "bg-green-500/20" },
    { icon: Bot, title: "New Agent Activated", description: "AI Agent 'Code Reviewer' is now processing tasks", time: "15m ago", color: "bg-purple-500/20" },
    { icon: AlertTriangle, title: "High CPU Alert", description: "Server prod-web-01 CPU usage at 87%", time: "32m ago", color: "bg-orange-500/20" },
    { icon: Shield, title: "Security Scan Complete", description: "Weekly security scan found 0 critical issues", time: "1h ago", color: "bg-blue-500/20" },
    { icon: Database, title: "Backup Successful", description: "Database backup completed in 4m 23s", time: "2h ago", color: "bg-cyan-500/20" },
    { icon: Users, title: "New Team Member", description: "Sarah Johnson joined Engineering team", time: "3h ago", color: "bg-pink-500/20" },
  ];

  const alerts = [
    { title: "High Memory Usage", severity: "warning" as const, message: "Server db-primary-01 memory at 92%", time: "5m ago" },
    { title: "Failed Login Attempts", severity: "error" as const, message: "15 failed attempts from IP 192.168.1.100", time: "12m ago" },
    { title: "SSL Expiring Soon", severity: "warning" as const, message: "Certificate for api.aionex.io expires in 7 days", time: "1h ago" },
  ];

  const quickActions: Array<{ icon: React.ElementType; label: string; color: string }> = [
    { icon: Plus, label: "New Project", color: "bg-blue-500/20 text-blue-400" },
    { icon: Bot, label: "New Agent", color: "bg-purple-500/20 text-purple-400" },
    { icon: Workflow, label: "New Workflow", color: "bg-cyan-500/20 text-cyan-400" },
    { icon: Server, label: "New Server", color: "bg-green-500/20 text-green-400" },
    { icon: FileText, label: "New Doc", color: "bg-orange-500/20 text-orange-400" },
    { icon: Calendar, label: "New Meeting", color: "bg-pink-500/20 text-pink-400" },
  ];

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} className="flex items-center justify-between">
        <div><h1 className="text-2xl font-bold text-white tracking-tight">Dashboard</h1><p className="text-sm text-white/40 mt-1">Welcome back, Alex. Here&apos;s what&apos;s happening today.</p></div>
        <div className="flex items-center gap-3"><span className="text-xs text-white/30">{new Date().toLocaleDateString("en-US", { weekday: "long", year: "numeric", month: "long", day: "numeric" })}</span></div>
      </motion.div>

      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, delay: 0.1 }} className="flex items-center gap-2 overflow-x-auto pb-2">
        {quickActions.map((action, i) => {
          const ActionIcon = action.icon;
          return <button key={i} className="flex items-center gap-2 px-4 py-2.5 rounded-xl glass hover:bg-white/[0.06] transition-all duration-200 group flex-shrink-0"><ActionIcon className={`w-4 h-4 ${action.color.split(" ")[1]}`} /><span className="text-xs font-medium text-white/70 group-hover:text-white transition-colors">{action.label}</span></button>;
        })}
      </motion.div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">{metrics.map((metric, i) => <MetricCard key={metric.title} {...metric} delay={i * 0.05} />)}</div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, delay: 0.3 }} className="glass-card p-5">
          <div className="flex items-center justify-between mb-5"><div className="flex items-center gap-2"><Activity className="w-4 h-4 text-electric-400" /><h2 className="text-sm font-semibold text-white">Infrastructure Health</h2></div><StatusBadge status="online" text="All Systems Operational" /></div>
          <div className="space-y-5"><ResourceBar label="CPU Usage" used={64} total={128} color="bg-gradient-to-r from-blue-500 to-cyan-500" /><ResourceBar label="Memory" used={256} total={512} color="bg-gradient-to-r from-purple-500 to-pink-500" /><ResourceBar label="Storage" used={1840} total={4096} color="bg-gradient-to-r from-green-500 to-emerald-500" /><ResourceBar label="Network I/O" used={892} total={2000} color="bg-gradient-to-r from-orange-500 to-yellow-500" /></div>
          <div className="grid grid-cols-2 gap-3 mt-5 pt-5 border-t border-white/[0.06]"><div className="text-center"><div className="text-lg font-bold text-white">99.99%</div><div className="text-[10px] text-white/40 uppercase tracking-wider mt-0.5">Uptime</div></div><div className="text-center"><div className="text-lg font-bold text-white">23ms</div><div className="text-[10px] text-white/40 uppercase tracking-wider mt-0.5">Latency</div></div></div>
        </motion.div>

        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, delay: 0.4 }} className="glass-card p-5">
          <div className="flex items-center justify-between mb-2"><div className="flex items-center gap-2"><Clock className="w-4 h-4 text-purple-400" /><h2 className="text-sm font-semibold text-white">Recent Activity</h2></div><button className="text-xs text-electric-400 hover:text-electric-300 transition-colors flex items-center gap-1">View All<ArrowUpRight className="w-3 h-3" /></button></div>
          <div>{activities.slice(0, 5).map((activity, i) => <ActivityItem key={i} {...activity} />)}</div>
        </motion.div>

        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, delay: 0.5 }} className="glass-card p-5">
          <div className="flex items-center justify-between mb-4"><div className="flex items-center gap-2"><AlertTriangle className="w-4 h-4 text-orange-400" /><h2 className="text-sm font-semibold text-white">Active Alerts</h2></div><span className="text-xs text-white/30">{alerts.length} active</span></div>
          <div className="space-y-3">{alerts.map((alert, i) => <div key={i} className="p-3 rounded-xl bg-white/[0.02] border border-white/[0.05]"><div className="flex items-start justify-between gap-2"><div className="flex-1"><div className="flex items-center gap-2 mb-1"><span className={`w-1.5 h-1.5 rounded-full ${alert.severity === "error" ? "bg-red-400" : "bg-orange-400"}`} /><span className="text-xs font-medium text-white">{alert.title}</span></div><p className="text-[11px] text-white/40 leading-relaxed">{alert.message}</p></div><span className="text-[10px] text-white/25 flex-shrink-0">{alert.time}</span></div></div>)}</div>
        </motion.div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, delay: 0.6 }} className="glass-card p-5"><div className="flex items-center justify-between mb-5"><div className="flex items-center gap-2"><Sparkles className="w-4 h-4 text-electric-400" /><h2 className="text-sm font-semibold text-white">AI Operations</h2></div><StatusBadge status="online" text="156 Agents Active" /></div><div className="grid grid-cols-2 sm:grid-cols-4 gap-3">{[{ icon: Bot, label: "Agents", value: "156", color: "text-purple-400" },{ icon: Workflow, label: "Workflows", value: "89", color: "text-cyan-400" },{ icon: Layers, label: "Models", value: "24", color: "text-blue-400" },{ icon: MessageSquare, label: "Tasks Today", value: "12.4K", color: "text-green-400" }].map((item, i) => <div key={i} className="p-3 rounded-xl bg-white/[0.02] border border-white/[0.04] text-center"><item.icon className={`w-5 h-5 mx-auto mb-2 ${item.color}`} /><div className="text-lg font-bold text-white">{item.value}</div><div className="text-[10px] text-white/40 mt-0.5">{item.label}</div></div>)}</div></motion.div>

        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, delay: 0.7 }} className="glass-card p-5"><div className="flex items-center justify-between mb-5"><div className="flex items-center gap-2"><BarChart3 className="w-4 h-4 text-green-400" /><h2 className="text-sm font-semibold text-white">System Overview</h2></div><span className="text-xs text-white/30">Last 24 hours</span></div><div className="grid grid-cols-3 gap-4"><div className="text-center p-3"><Globe className="w-5 h-5 text-blue-400 mx-auto mb-2" /><div className="text-lg font-bold text-white">8</div><div className="text-[10px] text-white/40">Regions</div></div><div className="text-center p-3 border-x border-white/[0.05]"><Cpu className="w-5 h-5 text-cyan-400 mx-auto mb-2" /><div className="text-lg font-bold text-white">1,024</div><div className="text-[10px] text-white/40">vCPUs</div></div><div className="text-center p-3"><HardDrive className="w-5 h-5 text-purple-400 mx-auto mb-2" /><div className="text-lg font-bold text-white">48TB</div><div className="text-[10px] text-white/40">Storage</div></div></div><div className="mt-4 pt-4 border-t border-white/[0.05] flex items-center justify-between"><div className="flex items-center gap-2"><Network className="w-4 h-4 text-electric-400" /><span className="text-xs text-white/50">Network Throughput</span></div><span className="text-sm font-semibold text-white">12.8 GB/s</span></div></motion.div>
      </div>
    </div>
  );
}
