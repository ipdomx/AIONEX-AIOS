import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "@/styles/globals.css";
import RuntimeProvider from "@/components/providers/RuntimeProvider";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "AIONEX AIOS — Enterprise AI Operating System",
  description: "Enterprise AI Operating System dashboard for governed agents, workflows, infrastructure, organizations, and operations.",
  keywords: ["AI", "Enterprise", "Dashboard", "AIONEX", "AIOS", "Agents", "Workflows", "Infrastructure"],
  authors: [{ name: "AIONEX" }],
  creator: "AIONEX",
  publisher: "AIONEX",
  robots: "index, follow",
  openGraph: {
    type: "website",
    locale: "en_US",
    url: "https://aionex.io",
    siteName: "AIONEX AIOS",
    title: "AIONEX AIOS — Enterprise AI Operating System",
    description: "Enterprise AI Operating System dashboard.",
  },
  twitter: {
    card: "summary_large_image",
    title: "AIONEX AIOS",
    description: "Enterprise AI Operating System",
  },
  viewport: {
    width: "device-width",
    initialScale: 1,
    maximumScale: 1,
    userScalable: false,
  },
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#030308" },
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
  ],
  icons: {
    icon: "/favicon.ico",
    shortcut: "/favicon-16x16.png",
    apple: "/apple-touch-icon.png",
  },
  manifest: "/manifest.json",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${jetbrainsMono.variable}`} suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
      </head>
      <body className="antialiased">
        <RuntimeProvider>{children}</RuntimeProvider>
      </body>
    </html>
  );
}
