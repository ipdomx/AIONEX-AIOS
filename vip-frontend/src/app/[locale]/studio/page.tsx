import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { StudioClient } from "@/components/pages/studio-client";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("meta");
  return {
    title: t("studioTitle"),
    description: t("studioDescription"),
  };
}

export default function StudioPage() {
  return <StudioClient />;
}
