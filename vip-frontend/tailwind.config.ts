import type { Config } from "tailwindcss";

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
        ink: {
          950: "#03050a",
          900: "#070b14",
          800: "#0c1220",
          700: "#111a2c",
          600: "#17233a"
        },
        electric: {
          50: "#e8fbff",
          100: "#c8f6ff",
          200: "#91edff",
          300: "#52dfff",
          400: "#20ccf4",
          500: "#00add4",
          600: "#0789aa",
          700: "#0d6d89"
        },
        violet: { 400: "#a78bfa", 500: "#8b5cf6", 600: "#7c3aed" }
      },
      fontFamily: {
        sans: ["Inter", "Segoe UI", "Arial", "system-ui", "sans-serif"],
        arabic: ["Tahoma", "Arial", "system-ui", "sans-serif"]
      },
      animation: {
        "fade-in": "fadeIn 0.5s ease-out",
        "slide-up": "slideUp 0.55s cubic-bezier(0.16, 1, 0.3, 1)",
        "pulse-slow": "pulse 4s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        float: "float 7s ease-in-out infinite",
        orbit: "orbit 18s linear infinite",
        scan: "scan 5s ease-in-out infinite"
      },
      keyframes: {
        fadeIn: { "0%": { opacity: "0" }, "100%": { opacity: "1" } },
        slideUp: {
          "0%": { opacity: "0", transform: "translateY(22px)" },
          "100%": { opacity: "1", transform: "translateY(0)" }
        },
        float: {
          "0%, 100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-14px)" }
        },
        orbit: {
          "0%": { transform: "rotate(0deg)" },
          "100%": { transform: "rotate(360deg)" }
        },
        scan: {
          "0%, 100%": { transform: "translateY(-140%)", opacity: "0" },
          "20%, 80%": { opacity: "0.65" },
          "50%": { transform: "translateY(140%)", opacity: "0.35" }
        }
      },
      boxShadow: {
        glow: "0 0 70px rgba(32, 204, 244, 0.2)",
        panel: "0 24px 90px rgba(0, 0, 0, 0.38)"
      }
    }
  },
  plugins: []
};

export default config;
