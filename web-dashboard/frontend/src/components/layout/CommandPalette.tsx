"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Activity,
  BarChart3,
  BookOpen,
  Bot,
  Calendar,
  CheckSquare,
  ChevronRight,
  CreditCard,
  FolderOpen,
  Globe,
  LayoutDashboard,
  LogOut,
  Plus,
  Search,
  Server,
  Settings,
  Shield,
  Sun,
  Workflow,
  Zap,
} from "lucide-react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/components/providers/AuthProvider";
import {
  ownerNavigationGroups,
  ownerRootNavigationItem,
} from "@/config/owner-navigation";
import { isOwnerRole } from "@/config/owner-access";

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
  href?: string;
  action?: "logout";
  ownerOnly?: boolean;
  keywords: string[];
}

const ownerCommands: CommandItem[] = ownerNavigationGroups.flatMap((group) =>
  group.items.map((item) => ({
    id: `nav-${item.id}`,
    name: `Open ${item.label}`,
    icon: item.icon,
    category: group.label,
    href: item.href,
    ownerOnly: true,
    keywords: [
      "owner",
      item.label.toLowerCase(),
      item.description.toLowerCase(),
      item.href,
    ],
  })),
);

const commands: CommandItem[] = [
  {
    id: "nav-dashboard",
    name: "Go to Dashboard",
    icon: LayoutDashboard,
    shortcut: "G D",
    category: "Navigation",
    href: "/",
    keywords: ["home", "main", "overview"],
  },
  {
    id: `nav-${ownerRootNavigationItem.id}`,
    name: `Go to ${ownerRootNavigationItem.label}`,
    icon: ownerRootNavigationItem.icon,
    shortcut: "G O",
    category: "Navigation",
    href: ownerRootNavigationItem.href,
    ownerOnly: true,
    keywords: [
      "owner",
      "command",
      "control",
      ownerRootNavigationItem.description.toLowerCase(),
    ],
  },
  {
    id: "nav-projects",
    name: "Go to Projects",
    icon: FolderOpen,
    shortcut: "G P",
    category: "Navigation",
    href: "/projects",
    keywords: ["project", "work"],
  },
  {
    id: "nav-agents",
    name: "Go to AI Agents",
    icon: Bot,
    shortcut: "G A",
    category: "Navigation",
    href: "/ai/agents",
    keywords: ["ai", "agent", "bot"],
  },
  {
    id: "nav-workflows",
    name: "Go to Workflows",
    icon: Workflow,
    shortcut: "G W",
    category: "Navigation",
    href: "/workflows",
    keywords: ["flow", "pipeline", "automation"],
  },
  {
    id: "nav-servers",
    name: "Go to Servers",
    icon: Server,
    shortcut: "G S",
    category: "Navigation",
    href: "/infrastructure/servers",
    keywords: ["server", "infrastructure", "host"],
  },
  {
    id: "nav-knowledge",
    name: "Go to Knowledge",
    icon: BookOpen,
    shortcut: "G K",
    category: "Navigation",
    href: "/knowledge",
    keywords: ["docs", "wiki", "knowledge"],
  },
  {
    id: "nav-security",
    name: "Go to Security",
    icon: Shield,
    shortcut: "G X",
    category: "Navigation",
    href: "/security/threats",
    keywords: ["security", "threat", "audit"],
  },
  {
    id: "nav-monitoring",
    name: "Go to Monitoring",
    icon: Activity,
    shortcut: "G M",
    category: "Navigation",
    href: "/monitoring/metrics",
    keywords: ["monitor", "metrics", "logs"],
  },
  {
    id: "nav-tasks",
    name: "Go to Tasks",
    icon: CheckSquare,
    shortcut: "G T",
    category: "Navigation",
    href: "/tasks",
    keywords: ["task", "todo"],
  },
  {
    id: "nav-meetings",
    name: "Go to Meetings",
    icon: Calendar,
    shortcut: "G E",
    category: "Navigation",
    href: "/meetings",
    keywords: ["meeting", "calendar", "event"],
  },
  {
    id: "nav-reports",
    name: "Go to Reports",
    icon: BarChart3,
    shortcut: "G R",
    category: "Navigation",
    href: "/reports",
    keywords: ["report", "analytics"],
  },
  {
    id: "nav-settings",
    name: "Go to Settings",
    icon: Settings,
    shortcut: "G ,",
    category: "Navigation",
    href: "/settings",
    keywords: ["setting", "config", "preference"],
  },
  ...ownerCommands,
  {
    id: "create-project",
    name: "Create New Project",
    icon: Plus,
    shortcut: "C P",
    category: "Create",
    href: "/projects?create=1",
    keywords: ["new", "project", "create"],
  },
  {
    id: "action-release",
    name: "Open Release Authority",
    icon: Zap,
    category: "Owner Actions",
    href: "/owner/release",
    ownerOnly: true,
    keywords: ["deploy", "publish", "release"],
  },
  {
    id: "action-services",
    name: "Open Service Control",
    icon: Zap,
    category: "Owner Actions",
    href: "/owner/services",
    ownerOnly: true,
    keywords: ["restart", "service", "control"],
  },
  {
    id: "action-backup",
    name: "Open Recovery Center",
    icon: Server,
    category: "Owner Actions",
    href: "/owner/recovery",
    ownerOnly: true,
    keywords: ["backup", "restore", "database"],
  },
  {
    id: "settings-theme",
    name: "Open Appearance Settings",
    icon: Sun,
    category: "Settings",
    href: "/settings",
    keywords: ["theme", "dark", "light", "mode"],
  },
  {
    id: "settings-language",
    name: "Open Language Settings",
    icon: Globe,
    category: "Settings",
    href: "/settings",
    keywords: ["language", "arabic", "english"],
  },
  {
    id: "settings-billing",
    name: "Open Billing",
    icon: CreditCard,
    category: "Settings",
    href: "/owner/billing",
    ownerOnly: true,
    keywords: ["billing", "payment", "invoice"],
  },
  {
    id: "settings-logout",
    name: "Sign Out",
    icon: LogOut,
    category: "Settings",
    action: "logout",
    keywords: ["logout", "signout", "exit"],
  },
];

export default function CommandPalette({
  isOpen,
  onClose,
}: CommandPaletteProps) {
  const router = useRouter();
  const { logout, user } = useAuth();
  const canAccessOwner = isOwnerRole(user?.role);
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const filteredCommands = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    const visibleCommands = commands.filter(
      (command) => !command.ownerOnly || canAccessOwner,
    );
    if (!normalized) return visibleCommands;
    return visibleCommands.filter(
      (command) =>
        command.name.toLowerCase().includes(normalized) ||
        command.keywords.some((keyword) => keyword.includes(normalized)) ||
        command.category.toLowerCase().includes(normalized),
    );
  }, [canAccessOwner, query]);

  const groupedCommands = useMemo(
    () =>
      filteredCommands.reduce<Record<string, CommandItem[]>>(
        (groups, command) => {
          (groups[command.category] ??= []).push(command);
          return groups;
        },
        {},
      ),
    [filteredCommands],
  );

  const flatCommands = useMemo(
    () => Object.values(groupedCommands).flat(),
    [groupedCommands],
  );

  const executeCommand = useCallback(
    async (command: CommandItem) => {
      onClose();
      if (command.href) {
        router.push(command.href);
        return;
      }
      if (command.action === "logout") {
        await logout();
        router.replace("/");
      }
    },
    [logout, onClose, router],
  );

  useEffect(() => {
    if (!isOpen) return;
    setQuery("");
    setSelectedIndex(0);
    const timer = window.setTimeout(() => inputRef.current?.focus(), 100);
    return () => window.clearTimeout(timer);
  }, [isOpen]);

  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (!isOpen) return;
      if (event.key === "Escape") {
        onClose();
        return;
      }
      if (!flatCommands.length) return;
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setSelectedIndex((current) => (current + 1) % flatCommands.length);
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        setSelectedIndex(
          (current) =>
            (current - 1 + flatCommands.length) % flatCommands.length,
        );
      } else if (event.key === "Enter" && flatCommands[selectedIndex]) {
        event.preventDefault();
        void executeCommand(flatCommands[selectedIndex]);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [executeCommand, flatCommands, isOpen, onClose, selectedIndex]);

  useEffect(() => {
    if (!flatCommands[selectedIndex]) return;
    listRef.current
      ?.querySelector(`[data-index="${selectedIndex}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [flatCommands, selectedIndex]);

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
            className="relative w-full max-w-2xl overflow-hidden glass-card shadow-modal"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center gap-3 border-b border-white/[0.06] px-4 py-4">
              <Search className="h-5 w-5 text-white/30" />
              <input
                ref={inputRef}
                type="text"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Navigate to any Owner page or platform module..."
                className="flex-1 bg-transparent text-sm text-white outline-none placeholder-white/30"
              />
              <kbd className="rounded-md border border-white/[0.08] bg-white/[0.06] px-2 py-1 font-mono text-[10px] text-white/40">
                ESC
              </kbd>
            </div>

            <div ref={listRef} className="max-h-[60vh] overflow-y-auto py-2">
              {Object.entries(groupedCommands).map(([category, items]) => (
                <div key={category}>
                  <div className="px-4 py-1.5">
                    <span className="text-[10px] font-semibold uppercase tracking-wider text-white/30">
                      {category}
                    </span>
                  </div>
                  {items.map((command) => {
                    const globalIndex = flatCommands.indexOf(command);
                    const selected = globalIndex === selectedIndex;
                    const Icon = command.icon;
                    return (
                      <button
                        key={command.id}
                        data-index={globalIndex}
                        type="button"
                        onClick={() => void executeCommand(command)}
                        onMouseEnter={() => setSelectedIndex(globalIndex)}
                        className={`flex w-full items-center gap-3 px-4 py-2.5 text-left transition ${
                          selected
                            ? "bg-white/[0.08] text-white"
                            : "text-white/60 hover:bg-white/[0.03] hover:text-white/80"
                        }`}
                      >
                        <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-white/[0.04]">
                          <Icon className="h-4 w-4" />
                        </div>
                        <span className="flex-1 text-sm font-medium">
                          {command.name}
                        </span>
                        {command.shortcut ? (
                          <div className="flex items-center gap-1">
                            {command.shortcut.split(" ").map((key) => (
                              <kbd
                                key={key}
                                className="rounded-md border border-white/[0.08] bg-white/[0.06] px-1.5 py-0.5 font-mono text-[10px] text-white/40"
                              >
                                {key}
                              </kbd>
                            ))}
                          </div>
                        ) : null}
                        <ChevronRight
                          className={`h-3.5 w-3.5 transition-opacity ${
                            selected ? "opacity-100" : "opacity-0"
                          }`}
                        />
                      </button>
                    );
                  })}
                </div>
              ))}

              {!flatCommands.length && (
                <div className="flex flex-col items-center justify-center py-12 text-center">
                  <Search className="mb-3 h-8 w-8 text-white/20" />
                  <p className="text-sm text-white/40">No commands found</p>
                </div>
              )}
            </div>

            <div className="flex items-center justify-between border-t border-white/[0.06] bg-white/[0.02] px-4 py-2.5">
              <span className="text-[10px] text-white/30">
                ↑↓ Navigate · ↵ Open
              </span>
              <span className="text-[10px] text-white/20">
                {flatCommands.length} commands
              </span>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
