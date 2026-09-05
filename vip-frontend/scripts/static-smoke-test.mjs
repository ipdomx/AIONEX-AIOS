import { createServer } from "node:http";
import { readFile, readdir, stat } from "node:fs/promises";
import { extname, join, normalize } from "node:path";

const root = join(process.cwd(), process.env.STATIC_OUTPUT_ROOT || "out");
const locales = ["ar", "en", "fr", "de", "es", "tr"];
const localizedRoutes = [
  "",
  "about",
  "contact",
  "dashboard",
  "campaigns",
  "login",
  "register",
  "profile",
  "projects",
  "notifications",
  "support",
  "pricing",
  "legal/privacy",
  "legal/terms",
];
const expectedUrls = [
  "/",
  "/robots.txt",
  "/sitemap.xml",
  "/manifest.webmanifest",
  "/.well-known/assetlinks.json",
  "/sw.js",
  "/offline.html",
  "/icons/aionex-180.png",
  "/icons/aionex-192.png",
  "/icons/aionex-512.png",
  ...locales.flatMap((locale) =>
    localizedRoutes.map((route) => `/${locale}/${route ? `${route}/` : ""}`),
  ),
];

const mimeTypes = {
  ".css": "text/css",
  ".html": "text/html",
  ".js": "text/javascript",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".txt": "text/plain",
  ".webmanifest": "application/manifest+json",
  ".xml": "application/xml",
};

async function resolveRequest(pathname) {
  const decoded = decodeURIComponent(pathname).replace(/^\/+/, "");
  const safe = normalize(decoded).replace(/^(\.\.(\/|\\|$))+/, "");
  const candidate = join(root, safe);
  try {
    const details = await stat(candidate);
    if (details.isDirectory()) return join(candidate, "index.html");
    return candidate;
  } catch {
    if (!extname(candidate)) {
      try {
        await stat(`${candidate}.html`);
        return `${candidate}.html`;
      } catch {
        return join(root, "404.html");
      }
    }
    return join(root, "404.html");
  }
}

async function walk(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) files.push(...(await walk(path)));
    else files.push(path);
  }
  return files;
}

const server = createServer(async (request, response) => {
  try {
    const path = await resolveRequest(
      new URL(request.url || "/", "http://localhost").pathname,
    );
    const body = await readFile(path);
    response.writeHead(path.endsWith("404.html") ? 404 : 200, {
      "Content-Type": mimeTypes[extname(path)] || "application/octet-stream",
    });
    response.end(body);
  } catch {
    response.writeHead(500);
    response.end("Static smoke server error");
  }
});

await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const address = server.address();
if (!address || typeof address === "string")
  throw new Error("Smoke server failed");
const base = `http://127.0.0.1:${address.port}`;

try {
  for (const path of expectedUrls) {
    const response = await fetch(`${base}${path}`);
    if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  }
  const missing = await fetch(`${base}/definitely-missing-aionex-route/`);
  if (missing.status !== 404)
    throw new Error("Missing route did not return 404");

  const files = await walk(root);
  const sourceMaps = files.filter((path) => path.endsWith(".map"));
  if (sourceMaps.length) throw new Error("Public source maps were generated");
  const buildManifests = files.filter((path) =>
    path.endsWith("_buildManifest.js"),
  );
  if (buildManifests.length !== 1) {
    throw new Error(
      `Expected one production build manifest, found ${buildManifests.length}`,
    );
  }
  const rootHtml = await readFile(join(root, "index.html"), "utf8");
  if (!rootHtml.includes("/ar/"))
    throw new Error("Root Arabic redirect is missing");
  const bundleText = (
    await Promise.all(
      files
        .filter((path) => path.endsWith(".js"))
        .map((path) => readFile(path, "utf8")),
    )
  ).join("\n");
  if (!bundleText.includes("https://api.vip-e.net/api/v1")) {
    throw new Error("Static bundle does not target the production API");
  }
  if (bundleText.includes("https://api.ai.vip-e.net")) {
    throw new Error("Static bundle contains the rejected API host");
  }
  const manifest = JSON.parse(
    await readFile(join(root, "manifest.webmanifest"), "utf8"),
  );
  if (manifest.display !== "standalone" || manifest.start_url !== "/ar/") {
    throw new Error("Installable PWA manifest is incomplete");
  }
  const assetLinks = JSON.parse(
    await readFile(join(root, ".well-known", "assetlinks.json"), "utf8"),
  );
  if (
    !Array.isArray(assetLinks) ||
    assetLinks[0]?.target?.package_name !== "net.vipe.aionex" ||
    !assetLinks[0]?.target?.sha256_cert_fingerprints?.length
  ) {
    throw new Error("Android App Links declaration is incomplete");
  }
  const serviceWorker = await readFile(join(root, "sw.js"), "utf8");
  if (!serviceWorker.includes('url.pathname.startsWith("/api/")')) {
    throw new Error("Service worker does not exclude authenticated API requests");
  }
  const htaccess = await readFile(join(root, ".htaccess"), "utf8");
  if (!htaccess.includes('Service-Worker-Allowed "/"')) {
    throw new Error("Service worker scope header is missing");
  }
  if (
    !htaccess.includes("RewriteEngine On") ||
    !htaccess.includes("RewriteCond %{HTTPS} !=on") ||
    !htaccess.includes("RewriteCond %{HTTP:X-Forwarded-Proto} !https [NC]") ||
    !htaccess.includes(
      "RewriteRule ^ https://ai.vip-e.net%{REQUEST_URI} [R=301,L,NE]",
    )
  ) {
    throw new Error("HTTP to HTTPS deployment redirect is missing");
  }
  console.log(
    `Static smoke test passed: ${expectedUrls.length} URLs, PWA assets, 404 fallback, API target and deployment headers.`,
  );
} finally {
  await new Promise((resolve, reject) =>
    server.close((error) => (error ? reject(error) : resolve())),
  );
}
