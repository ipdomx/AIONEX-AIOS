import type { Metadata, Viewport } from "next";
import "@/styles/globals.css";

export const metadata: Metadata = {
  metadataBase: new URL(
    process.env.NEXT_PUBLIC_SITE_URL || "https://vip-e.net"
  ),
  applicationName: "AIONEX AIOS",
  title: "AIONEX AIOS",
  icons: {
    icon: "/brand/aionex-mark.svg",
    shortcut: "/brand/aionex-mark.svg",
    apple: "/brand/aionex-mark.svg"
  },
  manifest: "/manifest.webmanifest"
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#03050a",
  colorScheme: "dark light"
};

export default function RootRedirectLayout({
  children
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ar" dir="rtl" suppressHydrationWarning>
      <body>{children}</body>
    </html>
  );
}
