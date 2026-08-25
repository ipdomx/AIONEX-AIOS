import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { AcademyClient } from "@/components/pages/academy-client";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("meta");
  return {
    title: t("academyTitle"),
    description: t("academyDescription"),
  };
}

export default function AcademyPage() {
  return <AcademyClient />;
}
