import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { IdentityMediaClient } from "@/components/pages/identity-media-client";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("identityMedia");
  return { title: t("title"), description: t("description") };
}

export default function IdentityMediaPage() {
  return <IdentityMediaClient />;
}
