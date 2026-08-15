"use client";

import { usePathname } from "next/navigation";
import { Navbar } from "@/components/layout/navbar";
import { AnnouncementBanner } from "@/components/portal/announcement-banner";
import { usePortalExperience } from "@/components/portal/portal-experience-provider";

const portalRoute =
  /^\/(?:ar|en|fr|de|es|tr)\/(?:dashboard|projects|campaigns|profile)(?:\/|$)/;

export function SiteFrame({
  children,
  footer,
}: {
  children: React.ReactNode;
  footer: React.ReactNode;
}) {
  const pathname = usePathname();
  const inUserPortal = portalRoute.test(pathname);
  const { configuration } = usePortalExperience();
  const announcementVisible = configuration?.announcement.enabled === true;

  return (
    <div className="site-frame flex min-h-screen flex-col overflow-x-clip">
      <div className="fixed inset-x-0 top-0 z-50"><AnnouncementBanner /><Navbar /></div>
      <main className={`flex-1 ${announcementVisible ? "pt-[7.25rem]" : "pt-20"}`}>{children}</main>
      {!inUserPortal && footer}
    </div>
  );
}
