import { AlertCircle, CheckCircle2, Info } from "lucide-react";
import { cn } from "@/lib/utils";

export function StatusMessage({
  children,
  tone = "info",
  className
}: {
  children: React.ReactNode;
  tone?: "info" | "success" | "error";
  className?: string;
}) {
  const Icon =
    tone === "success" ? CheckCircle2 : tone === "error" ? AlertCircle : Info;
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={cn(
        "flex items-start gap-3 rounded-xl border px-4 py-3 text-sm",
        tone === "success" &&
          "border-emerald-400/20 bg-emerald-500/10 text-emerald-100",
        tone === "error" &&
          "border-rose-400/25 bg-rose-500/10 text-rose-100",
        tone === "info" &&
          "border-white/10 bg-obsidian-700 text-zinc-200",
        className
      )}
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <div>{children}</div>
    </div>
  );
}
