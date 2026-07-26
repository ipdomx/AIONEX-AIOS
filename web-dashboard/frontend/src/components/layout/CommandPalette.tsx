"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Search,
  Command,
  FileText,
  Users,
  Bot,
  Workflow,
  Server,
  Settings,
  Plus,
  ArrowRight,
  Zap,
  LayoutDashboard,
  FolderOpen,
  BookOpen,
  Shield,
  Activity,
  Calendar,
  CheckSquare,
  BarChart3,
  CreditCard,
  LogOut,
  Moon,
  Sun,
  Globe,
  Keyboard,
  ChevronRight,
} from "lucide-react";

interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
}

interface CommandItem {
  id: string;
  name: string;
  icon: React.ElementType;
  shortcut?: string;
  category: string;
  action: () => void;
  keywords: string[];
}

const commands: CommandItem[] = [
  // Navigation
  { id: "nav-dashboard", name: "Go to Dashboard", icon: LayoutDashboard, shortcut: "G D", category: "Navigation", action: () => {}, keywords: ["home", "main", "overview"] },
  { id: "nav-projects", name: "Go to Projects", icon: FolderOpen, shortcut: "G P", category: "Navigation", action: () => {}, keywords: ["project", "work"] },
  { id: "nav-agents", name: "Go to AI Agents", icon: Bot, shortcut: "G A", category: "Navigation", action: () => {}, keywords: ["ai", "agent", "bot"] },
  { id: "nav-workflows", name: "Go to Workflows", icon: Workflow, shortcut: "G W", category: "Navigation", action: () => {}, keywords: ["flow", "pipeline", "automation"] },
  { id: "nav-servers", name: "Go to Servers", icon: Server, shortcut: "G S", category: "Navigation", action: () => {}, keywords: ["server", "infra", "host"] },
  { id: "nav-knowledge", name: "Go to Knowledge", icon: BookOpen, shortcut: "G K", category: "Navigation", action: () => {}, keywords: ["docs", "wiki", "knowledge"] },
  { id: "nav-security", name: "Go to Security", icon: Shield, shortcut: "G X", category: "Navigation", action: () => {}, keywords: ["security", "threat", "audit"] },
  { id: "nav-monitoring", name: "Go to Monitoring", icon: Activity, shortcut: "G M", category: "Navigation", action: () => {}, keywords: ["monitor", "metrics", "logs"] },
  { id: "nav-tasks", name: "Go to Tasks", icon: CheckSquare, shortcut: "G T", category: "Navigation", action: () => {}, keywords: ["task", "todo"] },
  { id: "nav-meetings", name: "Go to Meetings", icon: Calendar, shortcut: "G E", category: "Navigation", action: () => {}, keywords: ["meeting", "calendar", "event"] },
  { id: "nav-reports", name: "Go to Reports", icon: BarChart3, shortcut: "G R", category: "Navigation", action: () => {}, keywords: ["report", "analytics"] },
  { id: "nav-settings", name: "Go to Settings", icon: Settings, shortcut: "G ,", category: "Navigation", action: () => {}, keywords: ["setting", "config", "preference"] },

  // Create
  { id: "create-project", name: "Create New Project", icon: Plus, shortcut: "C P", category: "Create", action: () => {}, keywords: ["new", "project", "create"] },
  { id: "create-agent", name: "Create New Agent", icon: Bot, shortcut: "C A", category: "Create", action: () => {}, keywords: ["new", "agent", "ai", "bot", "create"] },
  { id: "create-workflow", name: "Create New Workflow", icon: Workflow, shortcut: "C W", category: "Create", action: () => {}, keywords: ["new", "workflow", "flow", "create"] },
  { id: "create-task", name: "Create New Task", icon: CheckSquare, shortcut: "C T", category: "Create", action: () => {}, keywords: ["new", "task", "todo", "create"] },
  { id: "create-meeting", name: "Create New Meeting", icon: Calendar, shortcut: "C M", category: "Create", action: () => {}, keywords: ["new", "meeting", "event", "create"] },
  { id: "create-document", name: "Create New Document", icon: FileText, shortcut: "C D", category: "Create", action: () => {}, keywords: ["new", "doc", "document", "create"] },

  // Actions
  { id: "action-deploy", name: "Deploy All Workflows", icon: Zap, category: "Actions", action: () => {}, keywords: ["deploy", "publish", "release"] },
  { id: "action-restart", name: "Restart All Services", icon: Zap, category: "Actions", action: () => {}, keywords: ["restart", "reboot", "service"] },
  { id: "action-backup", name: "Run Database Backup", icon: Server, category: "Actions", action: () => {}, keywords: ["backup", "db", "database"] },
  { id: "action-sync", name: "Sync Knowledge Base", icon: BookOpen, category: "Actions", action: () => {}, keywords: ["sync", "knowledge", "update"] },

  // Settings
  { id: "settings-theme", name: "Toggle Theme", icon: Sun, shortcut: "T", category: "Settings", action: () => {}, keywords: ["theme", "dark", "light", "mode"] },
  { id: "settings-language", name: "Switch Language", icon: Globe, category: "Settings", action: () => {}, keywords: ["language", "lang", "arabic", "english"] },
  { id: "settings-profile", name: "Open Profile", icon: Users, category: "Settings", action: () => {}, keywords: ["profile", "account", "user"] },
  { id: "settings-billing", name: "Open Billing", icon: CreditCard, category: "Settings", action: () => {}, keywords: ["billing", "payment", "invoice"] },
  { id: "settings-logout", name: "Sign Out", icon: LogOut, category: "Settings", action: () => {}, keywords: ["logout", "signout", "exit"] },
];

export default function CommandPalette({ isOpen, onClose }: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const filteredCommands = query.trim() === ""
    ? commands
    : commands.filter((cmd) =>
        cmd.name.toLowerCase().includes(query.toLowerCase()) ||
        cmd.keywords.some((k) => k.toLowerCase().includes(query.toLowerCase())) ||
        cmd.category.toLowerCase().includes(query.toLowerCase())
      );

  const groupedCommands = filteredCommands.reduce((acc, cmd) => {
    if (!acc[cmd.category]) acc[cmd.category] = [];
    acc[cmd.category].push(cmd);
    return acc;
  }, {} as Record<string, CommandItem[]>);

  const flatCommands = Object.values(groupedCommands).flat();

  useEffect(() => {
    if (isOpen) {
      setQuery("");
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }, [isOpen]);

  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (!isOpen) return;

      if (e.key === "Escape") {
        onClose();
        return;
      }

      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIndex((prev) => (prev + 1) % flatCommands.length);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIndex((prev) => (prev - 1 + flatCommands.length) % flatCommands.length);
      } else if (e.key === "Enter" && flatCommands[selectedIndex]) {
        e.preventDefault();
        flatCommands[selectedIndex].action();
        onClose();
      }
    },
    [isOpen, flatCommands, selectedIndex, onClose]
  );

  useEffect(() => {
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  useEffect(() => {
    if (listRef.current && flatCommands[selectedIndex]) {
      const selectedEl = listRef.current.querySelector(`[data-index="${selectedIndex}"]`);
      selectedEl?.scrollIntoView({ block: "nearest" });
    }
  }, [selectedIndex, flatCommands]);

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
          className="fixed inset-0 z-[100] flex items-start justify-center pt-[15vh]"
          onClick={onClose}
        >
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
          <motion.div
            initial={{ opacity: 0, y: -20, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -20, scale: 0.95 }}
            transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
            className="relative w-full max-w-2xl glass-card overflow-hidden shadow-modal"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Search Input */}
            <div className="flex items-center gap-3 px-4 py-4 border-b border-white/[0.06]">
              <Search className="w-5 h-5 text-white/30" />
              <input
                ref={inputRef}
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Type a command or search..."
                className="flex-1 bg-transparent text-white placeholder-white/30 text-sm outline-none"
              />
              <kbd className="px-2 py-1 rounded-md bg-white/[0.06] text-[10px] text-white/40 font-mono border border-white/[0.08]">
                ESC
              </kbd>
            </div>

            {/* Results */}
            <div ref={listRef} className="max-h-[60vh] overflow-y-auto py-2">
              {Object.entries(groupedCommands).map(([category, items]) => (
                <div key={category}>
                  <div className="px-4 py-1.5">
                    <span className="text-[10px] font-semibold text-white/30 uppercase tracking-wider">{category}</span>
                  </div>
                  {items.map((cmd) => {
                    const globalIndex = flatCommands.indexOf(cmd);
                    const isSelected = globalIndex === selectedIndex;
                    const Icon = cmd.icon;

                    return (
                      <button
                        key={cmd.id}
                        data-index={globalIndex}
                        onClick={() => {
                          cmd.action();
                          onClose();
                        }}
                        onMouseEnter={() => setSelectedIndex(globalIndex)}
                        className={`w-full flex items-center gap-3 px-4 py-2.5 text-left transition-all duration-150 ${
                          isSelected
                            ? "bg-white/[0.08] text-white"
                            : "text-white/60 hover:text-white/80 hover:bg-white/[0.03]"
                        }`}
                      >
                        <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${
                          isSelected ? "bg-white/[0.08]" : "bg-white/[0.04]"
                        }`}>
                          <Icon className="w-4 h-4" />
                        </div>
                        <span className="flex-1 text-sm font-medium">{cmd.name}</span>
                        {cmd.shortcut && (
                          <div className="flex items-center gap-1">
                            {cmd.shortcut.split(" ").map((key, i) => (
                              <kbd key={i} className="px-1.5 py-0.5 rounded-md bg-white/[0.06] text-[10px] text-white/40 font-mono border border-white/[0.08]">
                                {key}
                              </kbd>
                            ))}
                          </div>
                        )}
                        <ChevronRight className={`w-3.5 h-3.5 transition-opacity ${isSelected ? "opacity-100" : "opacity-0"}`} />
                      </button>
                    );
                  })}
                </div>
              ))}

              {flatCommands.length === 0 && (
                <div className="flex flex-col items-center justify-center py-12 text-center">
                  <Search className="w-8 h-8 text-white/20 mb-3" />
                  <p className="text-sm text-white/40">No commands found</p>
                  <p className="text-xs text-white/20 mt-1">Try a different search term</p>
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="flex items-center justify-between px-4 py-2.5 border-t border-white/[0.06] bg-white/[0.02]">
              <div className="flex items-center gap-4">
                <div className="flex items-center gap-1">
                  <kbd className="px-1.5 py-0.5 rounded bg-white/[0.06] text-[10px] text-white/40 font-mono border border-white/[0.08]">↑</kbd>
                  <kbd className="px-1.5 py-0.5 rounded bg-white/[0.06] text-[10px] text-white/40 font-mono border border-white/[0.08]">↓</kbd>
                  <span className="text-[10px] text-white/30 ml-1">Navigate</span>
                </div>
                <div className="flex items-center gap-1">
                  <kbd className="px-1.5 py-0.5 rounded bg-white/[0.06] text-[10px] text-white/40 font-mono border border-white/[0.08]">↵</kbd>
                  <span className="text-[10px] text-white/30 ml-1">Select</span>
                </div>
              </div>
              <span className="text-[10px] text-white/20">{flatCommands.length} commands</span>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
