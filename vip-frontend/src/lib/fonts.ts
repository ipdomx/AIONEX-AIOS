import { IBM_Plex_Sans_Arabic, Inter } from "next/font/google";

// Self-hosted at build time by next/font, so no third-party font request is
// made at runtime and the portal CSP (font-src 'self') stays unchanged.
export const interFont = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-inter",
});

export const plexArabicFont = IBM_Plex_Sans_Arabic({
  subsets: ["arabic"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
  variable: "--font-plex-arabic",
});
