export type SupportedLocale =
  | "en-US"
  | "ar-EG"
  | "ar-AE"
  | "ar-SA"
  | "ar-MA"
  | "fr-FR"
  | "es-ES"
  | "de-DE"
  | "hi-IN"
  | "ur-PK"
  | "tr-TR"
  | "zh-CN";

export type ArabicDialect =
  | "msa"
  | "egyptian"
  | "gulf"
  | "saudi"
  | "levantine"
  | "iraqi"
  | "maghrebi";

export type LocaleEvidence = {
  explicitLocale?: string | null;
  accountLocale?: string | null;
  browserLocales?: readonly string[] | null;
  phoneCountry?: string | null;
  ipCountry?: string | null;
  textSample?: string | null;
};

export type LocaleDecision = {
  locale: SupportedLocale;
  dialect: ArabicDialect | null;
  direction: "ltr" | "rtl";
  source: "explicit" | "account" | "browser" | "phone-country" | "ip-country" | "fallback";
  confidence: number;
};

export const SUPPORTED_LOCALES: readonly SupportedLocale[] = [
  "en-US",
  "ar-EG",
  "ar-AE",
  "ar-SA",
  "ar-MA",
  "fr-FR",
  "es-ES",
  "de-DE",
  "hi-IN",
  "ur-PK",
  "tr-TR",
  "zh-CN",
] as const;

const COUNTRY_DEFAULTS: Record<string, SupportedLocale> = {
  AE: "ar-AE",
  EG: "ar-EG",
  SA: "ar-SA",
  MA: "ar-MA",
  DZ: "ar-MA",
  TN: "ar-MA",
  FR: "fr-FR",
  ES: "es-ES",
  DE: "de-DE",
  IN: "hi-IN",
  PK: "ur-PK",
  TR: "tr-TR",
  CN: "zh-CN",
  US: "en-US",
  GB: "en-US",
  CA: "en-US",
  AU: "en-US",
};

const LANGUAGE_DEFAULTS: Record<string, SupportedLocale> = {
  ar: "ar-AE",
  en: "en-US",
  fr: "fr-FR",
  es: "es-ES",
  de: "de-DE",
  hi: "hi-IN",
  ur: "ur-PK",
  tr: "tr-TR",
  zh: "zh-CN",
};

const DIALECT_MARKERS: Record<Exclude<ArabicDialect, "msa">, readonly string[]> = {
  egyptian: ["إزاي", "ازاي", "عايز", "عاوز", "مش", "دلوقتي", "ليه", "كده", "تمام يا"],
  gulf: ["شلون", "وش", "وايد", "مب", "الحين", "يالس", "أبغي", "ابغي"],
  saudi: ["وش", "مره", "الحين", "أبغى", "ابغى", "علومك", "هذي"],
  levantine: ["شو", "هلق", "كتير", "مو", "بدي", "ليش", "هيك"],
  iraqi: ["شلونك", "هواية", "زين", "مو", "هسه", "أريد"],
  maghrebi: ["بزاف", "دابا", "شنو", "واش", "ماشي", "برشة", "توا"],
};

function normalizeLocale(value?: string | null): string | null {
  if (!value) return null;
  const normalized = value.trim().replace("_", "-");
  if (!normalized) return null;
  try {
    return new Intl.Locale(normalized).toString();
  } catch {
    return null;
  }
}

export function matchSupportedLocale(value?: string | null): SupportedLocale | null {
  const normalized = normalizeLocale(value);
  if (!normalized) return null;
  const exact = SUPPORTED_LOCALES.find(
    (candidate) => candidate.toLowerCase() === normalized.toLowerCase(),
  );
  if (exact) return exact;
  const parsed = new Intl.Locale(normalized);
  const language = parsed.language.toLowerCase();
  const region = parsed.region?.toUpperCase();
  if (language === "ar" && region && COUNTRY_DEFAULTS[region]?.startsWith("ar-")) {
    return COUNTRY_DEFAULTS[region];
  }
  return LANGUAGE_DEFAULTS[language] ?? null;
}

export function detectArabicDialect(text?: string | null): ArabicDialect | null {
  const sample = text?.trim();
  if (!sample || !/[\u0600-\u06ff]/u.test(sample)) return null;
  let best: ArabicDialect = "msa";
  let bestScore = 0;
  for (const [dialect, markers] of Object.entries(DIALECT_MARKERS)) {
    const score = markers.reduce(
      (total, marker) => total + (sample.includes(marker) ? 1 : 0),
      0,
    );
    if (score > bestScore) {
      best = dialect as ArabicDialect;
      bestScore = score;
    }
  }
  return best;
}

function localeFromCountry(country?: string | null): SupportedLocale | null {
  if (!country) return null;
  return COUNTRY_DEFAULTS[country.trim().toUpperCase()] ?? null;
}

function finish(
  locale: SupportedLocale,
  source: LocaleDecision["source"],
  confidence: number,
  sample?: string | null,
): LocaleDecision {
  const isRtl = locale.startsWith("ar-") || locale === "ur-PK";
  return {
    locale,
    dialect: locale.startsWith("ar-") ? detectArabicDialect(sample) ?? "msa" : null,
    direction: isRtl ? "rtl" : "ltr",
    source,
    confidence,
  };
}

export function decideLocale(evidence: LocaleEvidence): LocaleDecision {
  const explicit = matchSupportedLocale(evidence.explicitLocale);
  if (explicit) return finish(explicit, "explicit", 1, evidence.textSample);

  const account = matchSupportedLocale(evidence.accountLocale);
  if (account) return finish(account, "account", 0.98, evidence.textSample);

  for (const browserLocale of evidence.browserLocales ?? []) {
    const matched = matchSupportedLocale(browserLocale);
    if (matched) return finish(matched, "browser", 0.9, evidence.textSample);
  }

  const phone = localeFromCountry(evidence.phoneCountry);
  if (phone) return finish(phone, "phone-country", 0.82, evidence.textSample);

  const ip = localeFromCountry(evidence.ipCountry);
  if (ip) return finish(ip, "ip-country", 0.62, evidence.textSample);

  return finish("en-US", "fallback", 0.3, evidence.textSample);
}

export function dialectLocale(locale: SupportedLocale, dialect: ArabicDialect): SupportedLocale {
  if (!locale.startsWith("ar-")) return locale;
  if (dialect === "egyptian") return "ar-EG";
  if (dialect === "gulf") return "ar-AE";
  if (dialect === "saudi") return "ar-SA";
  if (dialect === "maghrebi") return "ar-MA";
  return locale;
}
