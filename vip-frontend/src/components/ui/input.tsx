import { forwardRef, type InputHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export const Input = forwardRef<
  HTMLInputElement,
  InputHTMLAttributes<HTMLInputElement>
>(({ className, ...props }, ref) => (
  <input
    ref={ref}
    className={cn(
      "h-12 w-full rounded-xl border border-white/10 bg-black/20 px-4 text-sm text-white outline-none transition placeholder:text-white/25 focus:border-electric-300/50 focus:ring-2 focus:ring-electric-400/15 disabled:cursor-not-allowed disabled:opacity-50",
      className
    )}
    {...props}
  />
));

Input.displayName = "Input";
