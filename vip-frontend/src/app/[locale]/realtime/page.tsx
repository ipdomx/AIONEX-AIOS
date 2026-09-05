import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { RealtimeClient } from "@/components/pages/realtime-client";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("meta");
  return {
    title: t("realtimeTitle"),
    description: t("realtimeDescription"),
  };
}

export default function RealtimePage() {
  return <RealtimeClient />;
}
