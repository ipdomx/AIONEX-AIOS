const withoutTrailingSlash = (value: string) => value.replace(/\/$/, "");

export const SITE_URL = withoutTrailingSlash(
  process.env.NEXT_PUBLIC_SITE_URL || "https://ai.vip-e.net",
);
