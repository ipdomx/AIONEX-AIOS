"use client";

import { useEffect, useMemo, useState } from "react";
import {
  CheckCircle2,
  Download,
  PackageCheck,
  RefreshCw,
  ShieldCheck,
  Smartphone,
} from "lucide-react";

import {
  downloadMobileArtifact,
  listMobileReleases,
  type MobileRelease,
} from "@/lib/owner-mobile-delivery";

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

export default function OwnerMobileDeliveryPage() {
  const [releases, setReleases] = useState<MobileRelease[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("Loading mobile release evidence...");

  async function load(signal?: AbortSignal) {
    setLoading(true);
    try {
      setReleases(await listMobileReleases(signal));
      setMessage("Mobile release evidence synchronized.");
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setReleases([]);
        setMessage("Mobile release evidence could not be loaded.");
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, []);

  const latest = useMemo(() => {
    const map = new Map<string, MobileRelease>();
    releases.forEach((release) => {
      if (!map.has(release.platform)) map.set(release.platform, release);
    });
    return map;
  }, [releases]);

  async function download(
    release: MobileRelease,
    artifactId: string,
    name: string,
  ) {
    setBusy(artifactId);
    setMessage("Downloading protected mobile artifact...");
    try {
      const blob = await downloadMobileArtifact(release.id, artifactId);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = name;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      setMessage(
        "Mobile artifact integrity was verified and the download started.",
      );
    } catch {
      setMessage(
        "Mobile artifact download failed integrity or access validation.",
      );
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs text-electric-300">
            <Smartphone className="h-3.5 w-3.5" /> Owner Mobile Delivery
          </div>
          <h1 className="text-3xl font-bold text-white">
            PWA, Android &amp; iOS Release Evidence
          </h1>
          <p className="mt-2 max-w-4xl text-sm leading-6 text-white/45">
            Verified install, update, offline, signing, artifact, and
            publication boundaries. App-store publication and the final
            ai.vip-e.net upload remain explicit external actions and are never
            reported as completed.
          </p>
        </div>
        <button
          type="button"
          disabled={loading}
          onClick={() => void load()}
          className="btn-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Refresh evidence
        </button>
      </div>

      <div className="glass-card p-4 text-xs text-electric-300">{message}</div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {(["pwa", "android", "ios"] as const).map((platform) => {
          const release = latest.get(platform);
          const passed =
            release?.validations.length &&
            release.validations.every((item) => item.status === "passed");
          return (
            <div key={platform} className="glass-card p-5">
              <Smartphone className="h-5 w-5 text-electric-300" />
              <div className="mt-4 text-xl font-bold uppercase text-white">
                {platform}
              </div>
              <div className="mt-1 text-sm text-white/50">
                {release
                  ? `v${release.version} · build ${release.build_number}`
                  : "No registered release"}
              </div>
              <div className="mt-4 flex flex-wrap gap-2 text-[11px]">
                <span className="rounded-full bg-white/[0.05] px-2.5 py-1 text-white/60">
                  {release?.status ?? "not built"}
                </span>
                <span className="rounded-full bg-white/[0.05] px-2.5 py-1 text-white/60">
                  {release?.signing_status ?? "unavailable"}
                </span>
                <span
                  className={`rounded-full px-2.5 py-1 ${passed ? "bg-green-500/10 text-green-300" : "bg-orange-500/10 text-orange-300"}`}
                >
                  {passed ? "Validations passed" : "Validation unavailable"}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      <div className="space-y-4">
        {releases.map((release) => (
          <section key={release.id} className="glass-card p-5">
            <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
              <div>
                <div className="flex items-center gap-2 text-lg font-semibold text-white">
                  <PackageCheck className="h-5 w-5 text-electric-300" />
                  {release.platform.toUpperCase()} v{release.version}
                </div>
                <p className="mt-1 text-xs text-white/40">
                  Build {release.build_number} · {release.channel} · commit{" "}
                  {release.source_commit.slice(0, 12)}
                </p>
              </div>
              <div className="flex flex-wrap gap-2 text-xs">
                <span className="rounded-full bg-green-500/10 px-3 py-1 text-green-300">
                  {release.status}
                </span>
                <span className="rounded-full bg-white/[0.05] px-3 py-1 text-white/60">
                  {release.publication_status}
                </span>
              </div>
            </div>

            <div className="mt-5 grid grid-cols-1 gap-3 lg:grid-cols-2">
              {release.artifacts.map((artifact) => (
                <div
                  key={artifact.id}
                  className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4"
                >
                  <div className="flex items-start gap-3">
                    <ShieldCheck className="mt-0.5 h-4 w-4 text-green-300" />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium text-white">
                        {artifact.filename}
                      </div>
                      <div className="mt-1 text-xs text-white/35">
                        {artifact.artifact_type} ·{" "}
                        {formatBytes(artifact.size_bytes)} ·{" "}
                        {artifact.signed ? "signed" : "unsigned boundary"}
                      </div>
                      <div className="mt-1 truncate font-mono text-[10px] text-white/25">
                        SHA-256 {artifact.checksum}
                      </div>
                    </div>
                    <button
                      type="button"
                      disabled={busy !== null}
                      onClick={() =>
                        void download(release, artifact.id, artifact.filename)
                      }
                      className="rounded-lg border border-electric-500/20 bg-electric-500/10 p-2 text-electric-300 disabled:opacity-40"
                      aria-label="Download verified artifact"
                    >
                      <Download
                        className={`h-4 w-4 ${busy === artifact.id ? "animate-pulse" : ""}`}
                      />
                    </button>
                  </div>
                </div>
              ))}
            </div>

            <div className="mt-5 space-y-2">
              {release.validations.map((validation) => (
                <div
                  key={validation.id}
                  className="flex items-center gap-3 rounded-lg border border-white/[0.05] bg-black/10 px-3 py-2 text-xs"
                >
                  <CheckCircle2 className="h-4 w-4 text-green-300" />
                  <span className="flex-1 text-white/65">
                    {validation.operation}
                  </span>
                  <span className="text-green-300">{validation.status}</span>
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
