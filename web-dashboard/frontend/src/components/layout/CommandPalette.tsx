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
  FolderOpen,
  Gauge,
  LayoutDashboard,
  Search,
  Server,
  Settings,
  Shield,
  Workflow,
  Zap,
} from "lucide-react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/components/providers/AuthProvider";
import { ownerNavigationItems } from "@/config/owner-navigation";

interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
}

interface CommandItem {
  id: string;
  name: string;
  icon: React.ElementType;
  category: "Navigation" | "Owner";
  href: string;
  keywords: string[];
}

const navigationCommands: CommandItem[] = [
  {
    id: "nav-dashboard",
    name: "Go to Overview",
    icon: LayoutDashboard,
    category: "Navigation",
    href: "/",
    keywords: ["home", "dashboard"],
  },
  {
    id: "nav-projects",
    name: "Go to Projects",
    icon: FolderOpen,
    category: "Navigation",
    href: "/projects",
    keywords: ["project", "work"],
  },
  {
    id: "nav-agents",
    name: "Go to AI Agents",
    icon: Bot,
    category: "Navigation",
    href: "/ai/agents",
    keywords: ["ai", "agents"],
  },
  {
    id: "nav-providers",
    name: "Go to AI Providers",
    icon: Zap,
    category: "Navigation",
    href: "/ai/providers",
    keywords: ["ai", "models", "provider"],
  },
  {
    id: "nav-workflows",
    name: "Go to Workflows",
    icon: Workflow,
    category: "Navigation",
    href: "/workflows",
    keywords: ["automation", "pipeline"],
  },
  {
    id: "nav-knowledge",
    name: "Go to Knowledge",
    icon: BookOpen,
    category: "Navigation",
    href: "/knowledge",
    keywords: ["docs", "memory"],
  },
  {
    id: "nav-servers",
    name: "Go to Servers",
    icon: Server,
    category: "Navigation",
    href: "/infrastructure/servers",
    keywords: ["infrastructure", "hosts"],
  },
  {
    id: "nav-monitoring",
    name: "Go to Monitoring",
    icon: Activity,
    category: "Navigation",
    href: "/monitoring/metrics",
    keywords: ["metrics", "logs", "alerts"],
  },
  {
    id: "nav-security",
    name: "Go to Security",
    icon: Shield,
    category: "Navigation",
    href: "/security/threats",
    keywords: ["threats", "audit"],
  },
  {
    id: "nav-tasks",
    name: "Go to Tasks",
    icon: CheckSquare,
    category: "Navigation",
    href: "/tasks",
    keywords: ["todo"],
  },
  {
    id: "nav-meetings",
    name: "Go to Meetings",
    icon: Calendar,
    category: "Navigation",
    href: "/meetings",
    keywords: ["calendar"],
  },
  {
    id: "nav-reports",
    name: "Go to Reports",
    icon: BarChart3,
    category: "Navigation",
    href: "/reports",
    keywords: ["analytics"],
  },
  {
    id: "nav-settings",
    name: "Go to Settings",
    icon: Settings,
    category: "Navigation",
    href: "/settings",
    keywords: ["configuration"],
  },
];

export default function CommandPalette({
  isOpen,
  onClose,
}: CommandPaletteProps) {
  const router = useRouter();
  const { user } = useAuth();
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const commands = useMemo(() => {
    if (user?.role !== "Super Owner") return navigationCommands;
    return [
      ...navigationCommands,
      {
        id: "command-owner-root",
        name: "Owner Center",
        icon: Gauge,
        category: "Owner" as const,
        href: "/owner",
        keywords: ["owner", "dashboard", "control"],
      },
      ...ownerNavigationItems.map<CommandItem>((item) => ({
        id: `command-${item.id}`,
        name: item.label,
        icon: item.icon,
        category: "Owner",
        href: item.href,
        keywords: ["owner", item.description],
      })),
    ];
  }, [user?.role]);

  const filteredCommands = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return commands;
    return commands.filter(
      (command) =>
        command.name.toLowerCase().includes(normalized) ||
        command.category.toLowerCase().includes(normalized) ||
        command.keywords.some((keyword) =>
          keyword.toLowerCase().includes(normalized),
        ),
    );
  }, [commands, query]);

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

  useEffect(() => {
    if (!isOpen) return;
    setQuery("");
    setSelectedIndex(0);
    window.setTimeout(() => inputRef.current?.focus(), 100);
  }, [isOpen]);

  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  const openCommand = useCallback(
    (command: CommandItem) => {
      router.push(command.href);
      onClose();
    },
    [onClose, router],
  );

  const handleKeyDown = useCallback(
    (event: KeyboardEvent) => {
      if (!isOpen) return;
      if (event.key === "Escape") {
        onClose();
        return;
      }
      if (filteredCommands.length === 0) return;
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setSelectedIndex((current) => (current + 1) % filteredCommands.length);
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        setSelectedIndex(
          (current) =>
            (current - 1 + filteredCommands.length) % filteredCommands.length,
        );
      } else if (event.key === "Enter") {
        event.preventDefault();
        openCommand(filteredCommands[selectedIndex] ?? filteredCommands[0]);
      }
    },
    [filteredCommands, isOpen, onClose, openCommand, selectedIndex],
  );

  useEffect(() => {
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  useEffect(() => {
    const selected = listRef.current?.querySelector(
      `[data-index="${selectedIndex}"]`,
    );
    selected?.scrollIntoView({ block: "nearest" });
  }, [selectedIndex]);

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-[100] flex items-start justify-center px-4 pt-[12vh]"
          onClick={onClose}
        >
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
          <motion.div
            initial={{ opacity: 0, y: -20, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -20, scale: 0.95 }}
            className="glass-card relative w-full max-w-2xl overflow-hidden shadow-modal"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center gap-3 border-b border-white/[0.06] px-4 py-4">
              <Search className="h-5 w-5 text-white/30" />
              <input
                ref={inputRef}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Navigate to a page or Owner module…"
                className="flex-1 bg-transparent text-sm text-white outline-none placeholder:text-white/30"
              />
              <kbd className="rounded-md border border-white/[0.08] bg-white/[0.06] px-2 py-1 font-mono text-[10px] text-white/40">
                ESC
              </kbd>
            </div>

            <div ref={listRef} className="max-h-[65vh] overflow-y-auto py-2">
              {Object.entries(groupedCommands).map(([category, items]) => (
                <section key={category}>
                  <div className="px-4 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-white/30">
                    {category}
                  </div>
                  {items.map((command) => {
                    const index = filteredCommands.indexOf(command);
                    const selected = index === selectedIndex;
                    const Icon = command.icon;
                    return (
                      <button
                        key={command.id}
                        type="button"
                        data-index={index}
                        onMouseEnter={() => setSelectedIndex(index)}
                        onClick={() => openCommand(command)}
                        className={`flex w-full items-center gap-3 px-4 py-2.5 text-left transition ${
                          selected
                            ? "bg-white/[0.08] text-white"
                            : "text-white/60 hover:bg-white/[0.03] hover:text-white/80"
                        }`}
                      >
                        <span className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-white/[0.04]">
                          <Icon className="h-4 w-4" />
                        </span>
                        <span className="flex-1 text-sm font-medium">
                          {command.name}
                        </span>
                        <ChevronRight
                          className={`h-3.5 w-3.5 ${selected ? "opacity-100" : "opacity-0"}`}
                        />
                      </button>
                    );
                  })}
                </section>
              ))}
              {filteredCommands.length === 0 && (
                <div className="py-12 text-center text-sm text-white/40">
                  No matching page found.
                </div>
              )}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
