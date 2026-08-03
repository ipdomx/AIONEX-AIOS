import { spawn } from "node:child_process";
import { readFileSync, readdirSync, rmSync } from "node:fs";
import { join } from "node:path";

rmSync(join(process.cwd(), "out"), { recursive: true, force: true });
rmSync(join(process.cwd(), ".next"), { recursive: true, force: true });

const command = process.execPath;
const args = [
  "--require",
  "./scripts/process-memory-shim.cjs",
  "./node_modules/next/dist/bin/next",
  "build",
];

const child = spawn(command, args, {
  cwd: process.cwd(),
  env: {
    ...process.env,
    AIOS_VIP_STATIC_EXPORT: "true",
    NEXT_PUBLIC_API_URL:
      process.env.NEXT_PUBLIC_API_URL || "https://api.vip-e.net/api/v1",
    NEXT_PUBLIC_SITE_URL:
      process.env.NEXT_PUBLIC_SITE_URL || "https://ai.vip-e.net",
    NEXT_TELEMETRY_DISABLED: "1",
  },
  stdio: "inherit",
});

function pruneStaleBuildIds() {
  const buildId = readFileSync(
    join(process.cwd(), ".next", "BUILD_ID"),
    "utf8",
  ).trim();
  const staticRoot = join(process.cwd(), "out", "_next", "static");
  for (const entry of readdirSync(staticRoot, { withFileTypes: true })) {
    if (
      entry.isDirectory() &&
      entry.name !== buildId &&
      readdirSync(join(staticRoot, entry.name)).includes("_buildManifest.js")
    ) {
      rmSync(join(staticRoot, entry.name), { recursive: true, force: true });
    }
  }
  const nextRoot = join(process.cwd(), "out", "_next");
  for (const entry of readdirSync(nextRoot, { withFileTypes: true })) {
    if (
      entry.isDirectory() &&
      entry.name !== "static" &&
      entry.name !== buildId
    ) {
      rmSync(join(nextRoot, entry.name), { recursive: true, force: true });
    }
  }
}

child.on("exit", (code, signal) => {
  if (signal) {
    console.error(`Static build stopped by ${signal}`);
    process.exit(1);
  }
  if (code === 0) pruneStaleBuildIds();
  process.exit(code ?? 1);
});
