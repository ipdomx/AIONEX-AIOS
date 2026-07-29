"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Activity,
  ArrowRight,
  BarChart3,
  BookOpen,
  Bot,
  Calendar,
  CheckSquare,
  FolderOpen,
  Gauge,
  Search,
  Server,
  Settings,
  Shield,
  Workflow,
  X,
  Zap,
} from "lucide-react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/components/providers/AuthProvider";
import { ownerNavigationItems } from "@/config/owner-navigation";

interface GlobalSearchProps {
  isOpen: boolean;
  onClose: () => void;
}

interface SearchResult {
  id: string;
  title: string;
  subtitle: string;
  icon: React.ElementType;
  url: string;
  type: "page" | "owner";
}

const platformPages: SearchResult[] = [
  {
    id: "page-projects",
    title: "Projects",
    subtitle: "Project workspace and delivery",
    icon: FolderOpen,
    url: "/projects",
    type: "page",
  },
  {
    id: "page-agents",
    title: "AI Agents",
    subtitle: "Agent registry and activity",
    icon: Bot,
    url: "/ai/agents",
    type: "page",
  },
  {
    id: "page-providers",
    title: "AI Providers",
    subtitle: "Provider registry and routing",
    icon: Zap,
    url: "/ai/providers",
    type: "page",
  },
  {
    id: "page-workflows",
    title: "Workflows",
    subtitle: "Automation and execution",
    icon: Workflow,
    url: "/workflows",
    type: "page",
  },
  {
    id: "page-knowledge",
    title: "Knowledge",
    subtitle: "Documents and shared memory",
    icon: BookOpen,
    url: "/knowledge",
    type: "page",
  },
  {
    id: "page-servers",
    title: "Servers",
    subtitle: "Infrastructure inventory",
    icon: Server,
    url: "/infrastructure/servers",
    type: "page",
  },
  {
    id: "page-monitoring",
    title: "Monitoring",
    subtitle: "Metrics, logs, alerts, and events",
    icon: Activity,
    url: "/monitoring/metrics",
    type: "page",
  },
  {
    id: "page-security",
    title: "Security",
    subtitle: "Threats, audit, sessions, and policies",
    icon: Shield,
    url: "/security/threats",
    type: "page",
  },
  {
    id: "page-tasks",
    title: "Tasks",
    subtitle: "Assigned and tracked work",
    icon: CheckSquare,
    url: "/tasks",
    type: "page",
  },
  {
    id: "page-meetings",
    title: "Meetings",
    subtitle: "Meetings and decisions",
    icon: Calendar,
    url: "/meetings",
    type: "page",
  },
  {
    id: "page-reports",
    title: "Reports",
    subtitle: "Reporting and analytics",
    icon: BarChart3,
    url: "/reports",
    type: "page",
  },
  {
    id: "page-settings",
    title: "Settings",
    subtitle: "Platform configuration",
    icon: Settings,
    url: "/settings",
    type: "page",
  },
];

export default function GlobalSearch({ isOpen, onClose }: GlobalSearchProps) {
  const router = useRouter();
  const { user } = useAuth();
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const results = useMemo(() => {
    if (user?.role !== "Super Owner") return platformPages;
    return [
      ...platformPages,
      {
        id: "search-owner-root",
        title: "Owner Center",
        subtitle: "Super Owner command and navigation center",
        icon: Gauge,
        url: "/owner",
        type: "owner" as const,
      },
      ...ownerNavigationItems.map<SearchResult>((item) => ({
        id: `search-${item.id}`,
        title: item.label,
        subtitle: item.description,
        icon: item.icon,
        url: item.href,
        type: "owner",
      })),
    ];
  }, [user?.role]);

  const filteredResults = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return results;
    return results.filter(
      (result) =>
        result.title.toLowerCase().includes(normalized) ||
        result.subtitle.toLowerCase().includes(normalized) ||
        result.type.includes(normalized),
    );
  }, [query, results]);

  useEffect(() => {
    if (!isOpen) return;
    setQuery("");
    setSelectedIndex(0);
    window.setTimeout(() => inputRef.current?.focus(), 100);
  }, [isOpen]);

  const openResult = useCallback(
    (result: SearchResult) => {
      router.push(result.url);
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
      if (filteredResults.length === 0) return;
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setSelectedIndex((current) => (current + 1) % filteredResults.length);
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        setSelectedIndex(
          (current) =>
            (current - 1 + filteredResults.length) % filteredResults.length,
        );
      } else if (event.key === "Enter") {
        event.preventDefault();
        openResult(filteredResults[selectedIndex] ?? filteredResults[0]);
      }
    },
    [filteredResults, isOpen, onClose, openResult, selectedIndex],
  );

  useEffect(() => {
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

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
                onChange={(event) => {
                  setQuery(event.target.value);
                  setSelectedIndex(0);
                }}
                placeholder="Search pages and Owner modules…"
                className="flex-1 bg-transparent text-sm text-white outline-none placeholder:text-white/30"
              />
              {query && (
                <button
                  type="button"
                  onClick={() => {
                    setQuery("");
                    inputRef.current?.focus();
                  }}
                  aria-label="Clear search"
                >
                  <X className="h-4 w-4 text-white/30 hover:text-white/60" />
                </button>
              )}
              <kbd className="rounded-md border border-white/[0.08] bg-white/[0.06] px-2 py-1 font-mono text-[10px] text-white/40">
                ESC
              </kbd>
            </div>

            <div className="max-h-[65vh] overflow-y-auto py-2">
              {filteredResults.map((result, index) => {
                const Icon = result.icon;
                const selected = index === selectedIndex;
                return (
                  <button
                    key={result.id}
                    type="button"
                    onMouseEnter={() => setSelectedIndex(index)}
                    onClick={() => openResult(result)}
                    className={`flex w-full items-center gap-3 px-4 py-3 text-left transition ${
                      selected ? "bg-white/[0.08]" : "hover:bg-white/[0.03]"
                    }`}
                  >
                    <span
                      className={`flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg ${
                        result.type === "owner"
                          ? "bg-electric-500/20 text-electric-400"
                          : "bg-white/[0.05] text-white/55"
                      }`}
                    >
                      <Icon className="h-4 w-4" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-medium text-white">
                        {result.title}
                      </span>
                      <span className="mt-0.5 block truncate text-xs text-white/40">
                        {result.subtitle}
                      </span>
                    </span>
                    <span className="rounded bg-white/[0.05] px-1.5 py-0.5 text-[10px] uppercase text-white/35">
                      {result.type}
                    </span>
                    <ArrowRight
                      className={`h-3.5 w-3.5 text-white/20 ${
                        selected ? "opacity-100" : "opacity-0"
                      }`}
                    />
                  </button>
                );
              })}
              {filteredResults.length === 0 && (
                <div className="py-16 text-center">
                  <Search className="mx-auto mb-3 h-9 w-9 text-white/15" />
                  <p className="text-sm text-white/35">
                    No matching page found.
                  </p>
                </div>
              )}
            </div>
            <div className="border-t border-white/[0.06] bg-white/[0.02] px-4 py-2.5 text-right text-[10px] text-white/25">
              {filteredResults.length} reachable pages
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
