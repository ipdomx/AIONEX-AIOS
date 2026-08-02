import { getLocale, getTranslations } from "next-intl/server";
import Link from "next/link";

export default async function NotFound() {
  const locale = await getLocale();
  const t = await getTranslations("common");
  return (
    <section className="section-pad">
      <div className="page-shell max-w-2xl text-center">
        <p className="title-gradient text-7xl font-bold">404</p>
        <h1 className="mt-6 text-3xl font-semibold">{t("notFoundTitle")}</h1>
        <p className="section-copy mt-4">{t("notFoundCopy")}</p>
        <Link href={`/${locale}`} className="mt-8 inline-flex h-12 items-center justify-center rounded-xl bg-white px-6 text-sm font-bold text-ink-950">
          {t("backHome")}
        </Link>
      </div>
    </section>
  );
}
