import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md" | "lg";
}

const variants = {
  primary:
    "border-transparent bg-crimson-500 text-white hover:bg-crimson-400 hover:shadow-[0_0_0_1px_rgba(255,45,63,0.4),0_8px_28px_-6px_rgba(225,29,46,0.35)] active:bg-crimson-600",
  secondary:
    "border-white/[0.14] bg-obsidian-700 text-white hover:border-white/25 hover:bg-obsidian-600",
  ghost:
    "border-transparent bg-transparent text-zinc-400 hover:bg-white/[0.06] hover:text-white",
  danger: "border-rose-400/25 bg-rose-500/10 text-rose-200 hover:bg-rose-500/20"
};

const sizes = {
  sm: "h-9 px-3 text-xs",
  md: "h-11 px-5 text-sm",
  lg: "h-[52px] px-6 text-base"
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "primary", size = "md", type = "button", ...props }, ref) => (
    <button
      ref={ref}
      type={type}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-xl border font-semibold transition duration-200 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crimson-500 focus-visible:ring-offset-2 focus-visible:ring-offset-obsidian-950 disabled:cursor-not-allowed disabled:opacity-45",
        variants[variant],
        sizes[size],
        className
      )}
      {...props}
    />
  )
);

Button.displayName = "Button";
