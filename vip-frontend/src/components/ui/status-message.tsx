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
          "border-red-400/20 bg-red-500/10 text-red-100",
        tone === "info" &&
          "border-electric-300/20 bg-electric-500/[0.08] text-electric-50",
        className
      )}
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <div>{children}</div>
    </div>
  );
}
