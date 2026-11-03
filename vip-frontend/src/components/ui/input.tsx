import { forwardRef, type InputHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export const Input = forwardRef<
  HTMLInputElement,
  InputHTMLAttributes<HTMLInputElement>
>(({ className, ...props }, ref) => (
  <input
    ref={ref}
    className={cn(
      "h-12 w-full rounded-xl border border-white/[0.14] bg-obsidian-700 px-4 text-sm text-white outline-none transition placeholder:text-zinc-500 focus:border-crimson-500 focus:ring-2 focus:ring-crimson-500 focus:ring-offset-2 focus:ring-offset-obsidian-950 disabled:cursor-not-allowed disabled:opacity-50",
      className
    )}
    {...props}
  />
));

Input.displayName = "Input";
