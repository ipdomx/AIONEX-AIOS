import { spawn } from "node:child_process";

const port = 3127;
const base = `http://127.0.0.1:${port}`;
const server = spawn(
  process.execPath,
  [
    "--require",
    "./scripts/process-memory-shim.cjs",
    "./node_modules/next/dist/bin/next",
    "start",
    "-p",
    String(port)
  ],
  { cwd: process.cwd(), env: { ...process.env, NEXT_TELEMETRY_DISABLED: "1" } }
);

let serverOutput = "";
server.stdout.on("data", (chunk) => { serverOutput += chunk.toString(); });
server.stderr.on("data", (chunk) => { serverOutput += chunk.toString(); });

async function waitUntilReady() {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (server.exitCode !== null) throw new Error(`Production server exited early.\n${serverOutput}`);
    try {
      const response = await fetch(base, { redirect: "manual" });
      if (response.status > 0) return;
    } catch {
      // The server is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(`Production server did not become ready.\n${serverOutput}`);
}

async function checkRoutes() {
  const locales = ["ar", "en", "fr", "de", "es", "tr"];
  const publicPaths = ["", "/about", "/contact", "/legal/privacy", "/legal/terms"];
  const privatePaths = ["/login", "/register", "/profile", "/projects"];
  const paths = new Set([
    "/robots.txt",
    "/sitemap.xml",
    "/manifest.webmanifest",
    "/brand/aionex-mark.svg"
  ]);
  for (const locale of locales) {
    for (const path of [...publicPaths, ...privatePaths]) paths.add(`/${locale}${path}`);
  }

  const failures = [];
  for (const path of paths) {
    const response = await fetch(base + path, { redirect: "follow" });
    const body = await response.text();
    if (!response.ok) failures.push(`${path}: HTTP ${response.status}`);
    const locale = path.match(/^\/(ar|en|fr|de|es|tr)(?:\/|$)/)?.[1];
    if (locale && !new RegExp(`<html[^>]*\\blang=["']${locale}["']`, "i").test(body)) {
      failures.push(`${path}: <html> language marker missing`);
    }
    if (locale && !new RegExp(`<html[^>]*\\bdir=["']${locale === "ar" ? "rtl" : "ltr"}["']`, "i").test(body)) {
      failures.push(`${path}: <html> text direction marker missing`);
    }
    if (privatePaths.some((item) => path.endsWith(item)) && !/name="robots" content="noindex/.test(body)) failures.push(`${path}: noindex missing`);
    if (locale && publicPaths.some((item) => path.endsWith(item)) && !/rel="canonical"/.test(body)) failures.push(`${path}: canonical URL missing`);
    if (body.includes('href="#"')) failures.push(`${path}: dead hash link`);
  }

  const unknownPaths = [
    "/ar/not-a-real-route",
    "/en/not-a-real-route",
    "/not-a-real-route"
  ];
  for (const path of unknownPaths) {
    const response = await fetch(base + path, { redirect: "follow" });
    const body = await response.text();
    if (response.status !== 404) failures.push(`${path}: expected HTTP 404, got ${response.status}`);
    if (!/name="robots" content="noindex/.test(body)) failures.push(`${path}: 404 noindex missing`);
  }

  const root = await fetch(base, { redirect: "manual" });
  if (root.status !== 200) failures.push(`/: expected HTTP 200, got ${root.status}`);
  if (failures.length) throw new Error(failures.join("\n"));
  console.log(`Smoke test passed: ${paths.size + unknownPaths.length + 1} production URLs, six locales, 404, RTL, canonical and noindex rules.`);
}

try {
  await waitUntilReady();
  await checkRoutes();
} finally {
  server.kill("SIGTERM");
}
