"use client";

import { usePathname } from "next/navigation";
import { Navbar } from "@/components/layout/navbar";

const portalRoute =
  /^\/(?:ar|en|fr|de|es|tr)\/(?:dashboard|projects|profile)(?:\/|$)/;

export function SiteFrame({
  children,
  footer,
}: {
  children: React.ReactNode;
  footer: React.ReactNode;
}) {
  const pathname = usePathname();
  const inUserPortal = portalRoute.test(pathname);

  return (
    <div className="site-frame flex min-h-screen flex-col overflow-x-clip">
      <Navbar />
      <main className="flex-1 pt-20">{children}</main>
      {!inUserPortal && footer}
    </div>
  );
}
