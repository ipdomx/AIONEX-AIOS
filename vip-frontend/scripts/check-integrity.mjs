import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const root = process.cwd();
const sourceRoots = ["src", "public"];
const textExtensions = new Set([
  ".ts",
  ".tsx",
  ".js",
  ".mjs",
  ".json",
  ".css",
  ".svg",
  ".webmanifest",
]);

function extension(path) {
  const match = path.match(/(\.[^.\/]+)$/);
  return match?.[1] || "";
}

function walk(path) {
  return readdirSync(path, { withFileTypes: true }).flatMap((entry) => {
    const next = join(path, entry.name);
    return entry.isDirectory() ? walk(next) : [next];
  });
}

const files = sourceRoots
  .flatMap((folder) => walk(join(root, folder)))
  .filter((path) => textExtensions.has(extension(path)));
const violations = [];
const forbidden = [
  {
    label: "simulated data marker",
    pattern: /\b(?:mock|fake)[-_ ]?(?:api|data|token|user|response)?\b/i,
  },
  {
    label: "demonstration account marker",
    pattern: /\bdemo[-_ ]?(?:account|user|token|data)\b/i,
  },
  { label: "dead hash link", pattern: /href\s*=\s*["']#["']/i },
  { label: "unrelated legacy brand", pattern: /trendboost/i },
  { label: "incorrect API host", pattern: /https:\/\/api\.ai\.vip-e\.net/i },
  {
    label: "public source repository link",
    pattern: /github\.com\/ipdomx\/AIONEX-AIOS/i,
  },
];

for (const file of files) {
  const content = readFileSync(file, "utf8");
  for (const rule of forbidden) {
    if (rule.pattern.test(content))
      violations.push(`${relative(root, file)}: ${rule.label}`);
  }
}

const requiredFiles = [
  "src/app/layout.tsx",
  "src/app/[locale]/page.tsx",
  "src/app/[locale]/about/page.tsx",
  "src/app/[locale]/contact/page.tsx",
  "src/app/[locale]/dashboard/page.tsx",
  "src/app/[locale]/login/page.tsx",
  "src/app/[locale]/register/page.tsx",
  "src/app/[locale]/profile/page.tsx",
  "src/app/[locale]/projects/page.tsx",
  "src/app/[locale]/legal/privacy/page.tsx",
  "src/app/[locale]/legal/terms/page.tsx",
  "src/lib/api.ts",
  "src/lib/firebase-phone-auth.ts",
  "src/lib/firebase-social-auth.ts",
  "src/lib/metadata.ts",
  "src/lib/passkeys.ts",
  "src/lib/site.ts",
  "src/lib/utils.ts",
  "public/brand/aionex-mark.svg",
];

for (const path of requiredFiles) {
  try {
    if (!statSync(join(root, path)).isFile())
      violations.push(`${path}: required file is missing`);
  } catch {
    violations.push(`${path}: required file is missing`);
  }
}

function flatten(value, prefix = "", output = []) {
  for (const [key, item] of Object.entries(value)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (item && typeof item === "object" && !Array.isArray(item))
      flatten(item, path, output);
    else output.push(path);
  }
  return output.sort();
}

const messageDirectory = join(root, "src/messages");
const messageFiles = readdirSync(messageDirectory)
  .filter((name) => name.endsWith(".json"))
  .sort();
const expectedLocales = [
  "ar.json",
  "de.json",
  "en.json",
  "es.json",
  "fr.json",
  "tr.json",
];
if (JSON.stringify(messageFiles) !== JSON.stringify(expectedLocales)) {
  violations.push(`src/messages: expected ${expectedLocales.join(", ")}`);
}
const referenceKeys = flatten(
  JSON.parse(readFileSync(join(messageDirectory, "en.json"), "utf8")),
);
for (const name of messageFiles) {
  const keys = flatten(
    JSON.parse(readFileSync(join(messageDirectory, name), "utf8")),
  );
  if (JSON.stringify(keys) !== JSON.stringify(referenceKeys)) {
    violations.push(
      `src/messages/${name}: translation keys do not match en.json`,
    );
  }
}

const apiSource = readFileSync(join(root, "src/lib/api.ts"), "utf8");
for (const route of [
  "/auth/login",
  "/auth/register/free",
  "/auth/logout",
  "/auth/refresh",
  "/auth/me",
  "/auth/free-tier/public",
  "/auth/firebase/phone/public",
  "/auth/firebase/social/public",
  "/auth/firebase/social/session",
  "/auth/firebase/social/registration/prepare",
  "/auth/passkeys/public",
  "/auth/passkeys/authentication/options",
  "/auth/passkeys/authentication/verify",
  "/auth/passkeys/registration/options",
  "/auth/passkeys/registration/verify",
  "/settings/password",
  "/support/requests",
  "/workspaces",
  "/projects",
]) {
  if (!apiSource.includes(route))
    violations.push(`src/lib/api.ts: confirmed route missing: ${route}`);
}

if (violations.length) {
  console.error(
    "Integrity check failed:\n" +
      violations.map((item) => `- ${item}`).join("\n"),
  );
  process.exit(1);
}

console.log(
  `Integrity check passed: ${files.length} files, ${messageFiles.length} complete locales, no simulated data markers.`,
);
