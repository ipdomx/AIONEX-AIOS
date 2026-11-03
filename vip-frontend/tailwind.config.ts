import type { Config } from "tailwindcss";

/*
 * AIONEX AIOS visual identity v3 — "Obsidian & Crimson".
 * Mostly black, with crimson used deliberately as the energy and accent colour.
 * Runtime (owner CMS) colours flow through the CSS variables in globals.css;
 * these static scales exist for opacity utilities such as `bg-obsidian-950/80`.
 */
const config: Config = {
  darkMode: ["class"],
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}"
  ],
  theme: {
    extend: {
      colors: {
        obsidian: {
          950: "#050505",
          900: "#0B0B0D",
          800: "#111114",
          700: "#18181C",
          600: "#222227"
        },
        crimson: {
          50: "#FFF1F2",
          100: "#FF8A93",
          200: "#FF4D5A",
          300: "#FF3B4B",
          400: "#FF2D3F",
          500: "#E11D2E",
          600: "#9B0F1C",
          700: "#6E0A14",
          800: "#3D060B",
          900: "#1F0306"
        }
      },
      fontFamily: {
        sans: [
          "var(--portal-body-font)",
          "Inter",
          "Segoe UI",
          "Arial",
          "system-ui",
          "sans-serif"
        ],
        arabic: [
          "var(--portal-arabic-font)",
          "IBM Plex Sans Arabic",
          "Tahoma",
          "Arial",
          "system-ui",
          "sans-serif"
        ],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "monospace"]
      },
      borderRadius: {
        xl: "10px",
        "2xl": "14px",
        "3xl": "20px"
      },
      transitionDuration: {
        DEFAULT: "180ms"
      },
      transitionTimingFunction: {
        DEFAULT: "cubic-bezier(0, 0, 0.2, 1)"
      },
      animation: {
        "fade-in": "fadeIn 0.2s ease-out",
        "slide-up": "slideUp 0.2s ease-out"
      },
      keyframes: {
        fadeIn: { "0%": { opacity: "0" }, "100%": { opacity: "1" } },
        slideUp: {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" }
        }
      },
      boxShadow: {
        glow: "0 0 0 1px rgba(225, 29, 46, 0.18), 0 24px 80px -24px rgba(225, 29, 46, 0.35)",
        panel: "0 24px 64px -24px rgba(0, 0, 0, 0.7)"
      }
    }
  },
  plugins: []
};

export default config;
