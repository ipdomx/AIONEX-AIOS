// Build-time assertion only: never execute generated bundle content.
const expectedApi = "https://api.vip-e.net/api/v1";
const rejectedHostname = "api.ai.vip-e.net";

export function assertProductionApiBundle(bundleText) {
  let productionApiFound = false;
  const literals = bundleText.matchAll(/(["'`])(https?:\/\/[^"'`\s\\]*)\1/gi);
  for (const match of literals) {
    let url;
    try {
      url = new URL(match[2]);
    } catch {
      continue;
    }
    if (url.hostname.replace(/\.$/, "") === rejectedHostname) {
      throw new Error("Static bundle contains the rejected API host");
    }
    if (url.href === expectedApi && !url.username && !url.password) {
      productionApiFound = true;
    }
  }
  if (!productionApiFound) {
    throw new Error("Static bundle does not target the production API");
  }
  return true;
}
