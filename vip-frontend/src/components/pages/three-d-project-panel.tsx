"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Box, Download, LoaderCircle, RefreshCw, RotateCcw, ShieldCheck, Square, Upload } from "lucide-react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { Button } from "@/components/ui/button";
import { StatusMessage } from "@/components/ui/status-message";
import {
  cancelProjectThreeDJob,
  clarifyProjectThreeDJob,
  createProjectThreeDJob,
  getProjectThreeDAccess,
  getProjectThreeDArtifactLinks,
  listProjectThreeDJobs,
} from "@/lib/api";
import type { Project, ThreeDAccess, ThreeDArtifactLinks, ThreeDGenerationJob } from "@/types";

function errorText(cause: unknown, fallback: string): string {
  return cause instanceof Error && cause.message ? cause.message : fallback;
}

function disposeObject(root: THREE.Object3D) {
  root.traverse((object) => {
    if (!(object instanceof THREE.Mesh)) return;
    object.geometry?.dispose();
    const materials = Array.isArray(object.material) ? object.material : [object.material];
    for (const material of materials) {
      for (const value of Object.values(material)) {
        if (value instanceof THREE.Texture) value.dispose();
      }
      material.dispose();
    }
  });
}

function ThreeDViewer({ url, label }: { url: string; label: string }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !url) return;
    setFailed(false);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(40, 1, 0.01, 1000);
    camera.position.set(2.5, 1.8, 2.5);
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1;
    container.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minDistance = 0.25;
    controls.maxDistance = 20;
    scene.add(new THREE.HemisphereLight(0xffffff, 0x444444, 2));
    const key = new THREE.DirectionalLight(0xffffff, 2.5);
    key.position.set(4, 6, 4);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0xffffff, 1.25);
    fill.position.set(-4, 2, -3);
    scene.add(fill);

    let model: THREE.Object3D | null = null;
    let frame = 0;
    let disposed = false;
    const resize = () => {
      const width = Math.max(1, container.clientWidth);
      const height = Math.max(1, container.clientHeight);
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(container);
    resize();

    new GLTFLoader().load(
      url,
      (gltf) => {
        if (disposed) {
          disposeObject(gltf.scene);
          return;
        }
        model = gltf.scene;
        scene.add(model);
        const box = new THREE.Box3().setFromObject(model);
        const sphere = box.getBoundingSphere(new THREE.Sphere());
        const radius = Math.max(sphere.radius, 0.1);
        model.position.sub(sphere.center);
        camera.near = Math.max(radius / 100, 0.001);
        camera.far = Math.max(radius * 100, 100);
        camera.position.set(radius * 2.4, radius * 1.6, radius * 2.4);
        camera.updateProjectionMatrix();
        controls.target.set(0, 0, 0);
        controls.update();
      },
      undefined,
      () => {
        if (!disposed) setFailed(true);
      },
    );

    const animate = () => {
      controls.update();
      renderer.render(scene, camera);
      frame = window.requestAnimationFrame(animate);
    };
    animate();
    return () => {
      disposed = true;
      window.cancelAnimationFrame(frame);
      observer.disconnect();
      controls.dispose();
      if (model) disposeObject(model);
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [url]);

  return (
    <div className="relative mt-4 overflow-hidden rounded-2xl border border-white/[0.08] bg-black/20">
      <div ref={containerRef} className="h-72 w-full sm:h-80" aria-label={label} />
      {failed && <div className="absolute inset-0 grid place-items-center bg-ink-950/90 px-8 text-center text-xs text-white/55">{label}</div>}
    </div>
  );
}

export function ThreeDProjectPanel({
  project,
  canWrite,
}: {
  project: Project;
  canWrite: boolean;
}) {
  const t = useTranslations("projects");
  const locale = useLocale();
  const [access, setAccess] = useState<ThreeDAccess | null>(null);
  const [jobs, setJobs] = useState<ThreeDGenerationJob[]>([]);
  const [links, setLinks] = useState<ThreeDArtifactLinks | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [clarificationFile, setClarificationFile] = useState<File | null>(null);
  const [textureSize, setTextureSize] = useState(1024);
  const [termsAccepted, setTermsAccepted] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const latest = jobs[0] || null;
  const active = useMemo(
    () => jobs.some((job) => ["queued", "running", "cancel_requested"].includes(job.status)),
    [jobs],
  );

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const [nextAccess, nextJobs] = await Promise.all([
        getProjectThreeDAccess(project.id),
        listProjectThreeDJobs(project.id, 10),
      ]);
      setAccess((current) => {
        if (
          current?.third_party_terms_version !== nextAccess.third_party_terms_version ||
          current?.model_provider !== nextAccess.model_provider
        ) {
          setTermsAccepted(false);
        }
        return nextAccess;
      });
      setJobs(nextJobs);
      setTextureSize((current) => Math.min(current, nextAccess.max_texture_size));
      setError("");
    } catch (cause) {
      if (!quiet) setError(errorText(cause, t("threeD.loadError")));
    } finally {
      if (!quiet) setLoading(false);
    }
  }, [project.id, t]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => void load(true), 5000);
    return () => window.clearInterval(timer);
  }, [active, load]);

  useEffect(() => {
    if (!latest?.has_artifact || latest.status !== "completed") {
      setLinks(null);
      return;
    }
    let cancelled = false;
    getProjectThreeDArtifactLinks(project.id, latest.id)
      .then((value) => {
        if (!cancelled) setLinks(value);
      })
      .catch(() => {
        if (!cancelled) setLinks(null);
      });
    return () => {
      cancelled = true;
    };
  }, [latest?.has_artifact, latest?.id, latest?.status, project.id]);

  function validateClientFile(value: File | null): boolean {
    if (!value || !access) return false;
    if (!["image/png", "image/jpeg", "image/webp"].includes(value.type)) {
      setError(t("threeD.invalidType"));
      return false;
    }
    if (value.size > access.max_input_megabytes * 1024 * 1024) {
      setError(t("threeD.tooLarge", { max: access.max_input_megabytes }));
      return false;
    }
    setError("");
    return true;
  }

  async function generate() {
    if (!validateClientFile(file) || !file || !access) return;
    if (!termsAccepted) {
      setError(t("threeD.termsRequired"));
      return;
    }
    setBusy(true);
    try {
      const job = await createProjectThreeDJob(project.id, file, {
        textureSize,
        termsAccepted,
        termsVersion: access.third_party_terms_version,
      });
      setJobs((current) => [job, ...current.filter((item) => item.id !== job.id)]);
      setFile(null);
      setTermsAccepted(false);
      setLinks(null);
      await load(true);
    } catch (cause) {
      setError(errorText(cause, t("threeD.createError")));
    } finally {
      setBusy(false);
    }
  }

  async function cancel(job: ThreeDGenerationJob) {
    setBusy(true);
    try {
      const value = await cancelProjectThreeDJob(project.id, job.id);
      setJobs((current) => current.map((item) => (item.id === value.id ? value : item)));
      await load(true);
    } catch (cause) {
      setError(errorText(cause, t("threeD.cancelError")));
    } finally {
      setBusy(false);
    }
  }

  async function clarify(job: ThreeDGenerationJob) {
    if (!validateClientFile(clarificationFile) || !clarificationFile || !access) return;
    if (!termsAccepted) {
      setError(t("threeD.termsRequired"));
      return;
    }
    setBusy(true);
    try {
      const value = await clarifyProjectThreeDJob(
        project.id,
        job.id,
        clarificationFile,
        {
          termsAccepted,
          termsVersion: access.third_party_terms_version,
        },
      );
      setJobs((current) => current.map((item) => (item.id === value.id ? value : item)));
      setClarificationFile(null);
      setTermsAccepted(false);
      await load(true);
    } catch (cause) {
      setError(errorText(cause, t("threeD.clarifyError")));
    } finally {
      setBusy(false);
    }
  }

  async function refreshLinks() {
    if (!latest) return;
    setBusy(true);
    try {
      setLinks(await getProjectThreeDArtifactLinks(project.id, latest.id));
    } catch (cause) {
      setError(errorText(cause, t("threeD.linkError")));
    } finally {
      setBusy(false);
    }
  }

  if (loading && !access) {
    return <div className="mt-7 rounded-2xl border border-white/[0.06] p-5 text-xs text-white/40"><LoaderCircle className="mr-2 inline h-4 w-4 animate-spin" />{t("threeD.loading")}</div>;
  }

  return (
    <div className="mt-7 rounded-2xl border border-violet-300/10 bg-violet-300/[0.035] p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Box className="h-4 w-4 text-violet-200" />
          <p className="text-sm font-semibold">{t("threeD.title")}</p>
        </div>
        <div className="flex items-center gap-2 text-[11px] text-white/35">
          <ShieldCheck className="h-3.5 w-3.5" />
          {t("threeD.ownerManaged")}
          <button onClick={() => void load()} aria-label={t("refresh")} className="ml-2 rounded-md p-1 hover:bg-white/5"><RefreshCw className="h-3.5 w-3.5" /></button>
        </div>
      </div>

      {error && <StatusMessage tone="error" className="mt-4">{error}</StatusMessage>}

      {access && !access.eligible ? (
        <StatusMessage className="mt-4">{t("threeD.unavailable")}</StatusMessage>
      ) : access ? (
        <>
          <div className="mt-4 grid gap-2 text-[11px] text-white/40 sm:grid-cols-3">
            <span>{t("threeD.quota", { used: access.monthly_used, total: access.monthly_quota })}</span>
            <span>{t("threeD.concurrency", { active: access.active_jobs, total: access.max_concurrent_jobs })}</span>
            <span>{t("threeD.inputLimit", { max: access.max_input_megabytes })}</span>
          </div>
          <div className="mt-3 rounded-xl border border-white/[0.06] bg-black/10 p-3 text-[11px] leading-5 text-white/40">
            <div>
              {t("threeD.provider", {
                model: access.model_disclosure.model,
                license: access.model_disclosure.license,
              })}
            </div>
            <div>
              {t("threeD.jurisdiction", {
                country: access.jurisdiction_country || t("threeD.countryUnknown"),
              })}
            </div>
            {access.model_provider === "hunyuan3d" && (
              <div>{t("threeD.hunyuanNoAffiliation", { operator: access.model_disclosure.operator })}</div>
            )}
          </div>

          {latest && (
            <div className="mt-4 rounded-xl bg-black/10 p-4">
              <div className="flex items-center justify-between gap-3 text-xs">
                <span className="font-medium text-white/65">{t(`threeD.status.${latest.status}`)}</span>
                <span className="text-white/35">{latest.progress}%</span>
              </div>
              <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
                <div className="h-full rounded-full bg-gradient-to-r from-violet-400 to-cyan-400" style={{ width: `${Math.max(0, Math.min(100, latest.progress))}%` }} />
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-3 text-[11px] text-white/35">
                <span>{t("threeD.stage", { stage: latest.stage.replaceAll("_", " ") })}</span>
                <span>{t("threeD.attempt", { attempt: latest.attempts, total: latest.max_attempts })}</span>
                <span>{t("threeD.cost", { cost: latest.estimated_cost_usd.toFixed(4) })}</span>
              </div>
              {latest.error_message && <StatusMessage tone={latest.status === "failed" ? "error" : "info"} className="mt-4">{latest.error_message}</StatusMessage>}
              {["queued", "running", "cancel_requested"].includes(latest.status) && canWrite && (
                <Button variant="secondary" className="mt-4" disabled={busy || latest.status === "cancel_requested"} onClick={() => void cancel(latest)}>
                  <Square className="h-3.5 w-3.5" />{t("threeD.cancel")}
                </Button>
              )}
              {latest.status === "needs_clarification" && canWrite && (
                <div className="mt-4 space-y-3">
                  <input type="file" accept="image/png,image/jpeg,image/webp" className="field-control text-xs" onChange={(event) => setClarificationFile(event.target.files?.[0] || null)} />
                  <label className="flex items-start gap-2 text-[11px] leading-5 text-white/45">
                    <input
                      type="checkbox"
                      className="mt-1"
                      checked={termsAccepted}
                      onChange={(event) => setTermsAccepted(event.target.checked)}
                    />
                    <span>
                      {t("threeD.termsConsent")}{" "}
                      <a
                        className="text-violet-200 underline underline-offset-2"
                        href={`/${locale}/legal/terms`}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {t("threeD.termsLink")}
                      </a>
                    </span>
                  </label>
                  <Button disabled={busy || !clarificationFile || !termsAccepted} onClick={() => void clarify(latest)}><RotateCcw className="h-4 w-4" />{t("threeD.submitClarification")}</Button>
                </div>
              )}
            </div>
          )}

          {links && latest?.status === "completed" && (
            <div className="mt-4">
              <div className="flex flex-wrap gap-2">
                <a href={links.download_url} rel="noreferrer"><Button><Download className="h-4 w-4" />{t("threeD.download")}</Button></a>
                <Button variant="secondary" disabled={busy} onClick={() => void refreshLinks()}><RefreshCw className="h-4 w-4" />{t("threeD.refreshLink")}</Button>
              </div>
              <p className="mt-2 text-[11px] text-white/30">{t("threeD.linkExpiry", { minutes: Math.max(1, Math.round(links.expires_in / 60)) })}</p>
              <ThreeDViewer url={links.view_url} label={t("threeD.previewError")} />
            </div>
          )}

          {canWrite && !active && latest?.status !== "needs_clarification" && (
            <div className="mt-5 space-y-4 border-t border-white/[0.06] pt-5">
              <div className="grid gap-3 sm:grid-cols-[1fr_150px]">
                <input type="file" accept="image/png,image/jpeg,image/webp" className="field-control text-xs" onChange={(event) => setFile(event.target.files?.[0] || null)} />
                <select className="field-control text-xs" value={textureSize} onChange={(event) => setTextureSize(Number(event.target.value))}>
                  {[512, 1024, 2048, 4096].filter((value) => value <= access.max_texture_size).map((value) => <option key={value} value={value} className="bg-ink-900">{value}px</option>)}
                </select>
              </div>
              <label className="flex items-start gap-2 text-[11px] leading-5 text-white/45">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={termsAccepted}
                  onChange={(event) => setTermsAccepted(event.target.checked)}
                />
                <span>
                  {t("threeD.termsConsent")} {" "}
                  <a
                    className="text-violet-200 underline underline-offset-2"
                    href={`/${locale}/legal/terms`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {t("threeD.termsLink")}
                  </a>
                </span>
              </label>
              <Button disabled={busy || !file || !termsAccepted || access.monthly_remaining <= 0} onClick={() => void generate()}>
                {busy ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                {busy ? t("threeD.submitting") : t("threeD.generate")}
              </Button>
            </div>
          )}
        </>
      ) : null}
    </div>
  );
}
