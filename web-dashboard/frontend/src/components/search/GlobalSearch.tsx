"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Search,
  X,
  FolderOpen,
  Bot,
  Workflow,
  FileText,
  Users,
  Server,
  CheckSquare,
  ArrowRight,
} from "lucide-react";

interface GlobalSearchProps {
  isOpen: boolean;
  onClose: () => void;
}

interface SearchResult {
  id: string;
  type: "project" | "agent" | "workflow" | "document" | "user" | "server" | "task";
  title: string;
  subtitle: string;
  icon: React.ElementType;
  url: string;
}

const mockResults: SearchResult[] = [
  { id: "1", type: "project", title: "Data Pipeline v2", subtitle: "Active Project • Engineering", icon: FolderOpen, url: "/projects/1" },
  { id: "2", type: "agent", title: "Code Reviewer AI", subtitle: "Active Agent • 89 tasks completed", icon: Bot, url: "/ai/agents/1" },
  { id: "3", type: "workflow", title: "Customer Onboarding", subtitle: "Active Workflow • 24 executions", icon: Workflow, url: "/workflows/1" },
  { id: "4", type: "document", title: "API Documentation", subtitle: "Knowledge Base • Updated 2h ago", icon: FileText, url: "/knowledge/1" },
  { id: "5", type: "user", title: "Sarah Johnson", subtitle: "Senior Engineer • Engineering Team", icon: Users, url: "/users/1" },
  { id: "6", type: "server", title: "prod-web-01", subtitle: "Online • CPU 67% • Memory 82%", icon: Server, url: "/infrastructure/servers/1" },
  { id: "7", type: "task", title: "Fix Authentication Bug", subtitle: "High Priority • Due in 2 days", icon: CheckSquare, url: "/tasks/1" },
  { id: "8", type: "project", title: "AI Model Training", subtitle: "Active Project • Research", icon: FolderOpen, url: "/projects/2" },
  { id: "9", type: "agent", title: "Data Analyzer", subtitle: "Active Agent • Processing", icon: Bot, url: "/ai/agents/2" },
  { id: "10", type: "workflow", title: "Nightly Backup", subtitle: "Scheduled • Daily at 2:00 AM", icon: Workflow, url: "/workflows/2" },
];

const typeColors: Record<string, string> = {
  project: "bg-blue-500/20 text-blue-400",
  agent: "bg-purple-500/20 text-purple-400",
  workflow: "bg-cyan-500/20 text-cyan-400",
  document: "bg-orange-500/20 text-orange-400",
  user: "bg-green-500/20 text-green-400",
  server: "bg-electric-500/20 text-electric-400",
  task: "bg-pink-500/20 text-pink-400",
};

export default function GlobalSearch({ isOpen, onClose }: GlobalSearchProps) {
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const filteredResults = query.trim() === ""
    ? mockResults
    : mockResults.filter(
        (r) =>
          r.title.toLowerCase().includes(query.toLowerCase()) ||
          r.subtitle.toLowerCase().includes(query.toLowerCase()) ||
          r.type.toLowerCase().includes(query.toLowerCase())
      );

  useEffect(() => {
    if (isOpen) {
      setQuery("");
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }, [isOpen]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (!isOpen) return;
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIndex((prev) => (prev + 1) % filteredResults.length);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIndex((prev) => (prev - 1 + filteredResults.length) % filteredResults.length);
      } else if (e.key === "Enter" && filteredResults[selectedIndex]) {
        e.preventDefault();
        window.location.href = filteredResults[selectedIndex].url;
        onClose();
      }
    },
    [isOpen, filteredResults, selectedIndex, onClose]
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
            <div className="flex items-center gap-3 px-4 py-4 border-b border-white/[0.06]">
              <Search className="w-5 h-5 text-white/30" />
              <input
                ref={inputRef}
                type="text"
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setSelectedIndex(0);
                }}
                placeholder="Search projects, agents, workflows, documents, users, servers..."
                className="flex-1 bg-transparent text-white placeholder-white/30 text-sm outline-none"
              />
              {query && (
                <button onClick={() => { setQuery(""); inputRef.current?.focus(); }}>
                  <X className="w-4 h-4 text-white/30 hover:text-white/60" />
                </button>
              )}
              <kbd className="px-2 py-1 rounded-md bg-white/[0.06] text-[10px] text-white/40 font-mono border border-white/[0.08]">
                ESC
              </kbd>
            </div>
            <div className="max-h-[60vh] overflow-y-auto">
              {filteredResults.length > 0 ? (
                <div className="py-2">
                  {filteredResults.map((result, index) => {
                    const Icon = result.icon;
                    const isSelected = index === selectedIndex;
                    return (
                      <a
                        key={result.id}
                        href={result.url}
                        onMouseEnter={() => setSelectedIndex(index)}
                        onClick={() => onClose()}
                        className={`flex items-center gap-3 px-4 py-3 transition-all duration-150 ${
                          isSelected ? "bg-white/[0.08]" : "hover:bg-white/[0.03]"
                        }`}
                      >
                        <div className={`w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 ${typeColors[result.type]}`}>
                          <Icon className="w-4 h-4" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-medium text-white">{result.title}</span>
                            <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium uppercase ${typeColors[result.type]}`}>
                              {result.type}
                            </span>
                          </div>
                          <p className="text-xs text-white/40 mt-0.5">{result.subtitle}</p>
                        </div>
                        <ArrowRight className={`w-3.5 h-3.5 text-white/20 transition-opacity ${isSelected ? "opacity-100" : "opacity-0"}`} />
                      </a>
                    );
                  })}
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center py-16 text-center">
                  <Search className="w-10 h-10 text-white/15 mb-4" />
                  <p className="text-sm text-white/30">No results found</p>
                  <p className="text-xs text-white/20 mt-1">Try a different search term</p>
                </div>
              )}
            </div>
            <div className="flex items-center justify-between px-4 py-2.5 border-t border-white/[0.06] bg-white/[0.02]">
              <div className="flex items-center gap-4">
                <div className="flex items-center gap-1">
                  <kbd className="px-1.5 py-0.5 rounded bg-white/[0.06] text-[10px] text-white/40 font-mono border border-white/[0.08]">↑↓</kbd>
                  <span className="text-[10px] text-white/30 ml-1">Navigate</span>
                </div>
                <div className="flex items-center gap-1">
                  <kbd className="px-1.5 py-0.5 rounded bg-white/[0.06] text-[10px] text-white/40 font-mono border border-white/[0.08]">↵</kbd>
                  <span className="text-[10px] text-white/30 ml-1">Open</span>
                </div>
              </div>
              <span className="text-[10px] text-white/20">{filteredResults.length} results</span>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
