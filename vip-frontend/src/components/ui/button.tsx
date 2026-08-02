import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md" | "lg";
}

const variants = {
  primary:
    "border-electric-300/30 bg-gradient-to-r from-electric-500 to-violet-500 text-white shadow-lg shadow-electric-500/15 hover:brightness-110",
  secondary:
    "border-white/10 bg-white/[0.06] text-white hover:border-electric-300/25 hover:bg-white/[0.1]",
  ghost:
    "border-transparent bg-transparent text-white/70 hover:bg-white/[0.06] hover:text-white",
  danger: "border-red-400/25 bg-red-500/10 text-red-200 hover:bg-red-500/20"
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
        "inline-flex items-center justify-center gap-2 rounded-xl border font-semibold transition duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-electric-300 focus-visible:ring-offset-2 focus-visible:ring-offset-ink-950 disabled:cursor-not-allowed disabled:opacity-45",
        variants[variant],
        sizes[size],
        className
      )}
      {...props}
    />
  )
);

Button.displayName = "Button";
