"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { Box, Code2, Download, Film, Image, Layout, Loader2, Megaphone, Palette, Sparkles } from "lucide-react";

const departments = [
  { id: "website", name: "Website Studio", description: "Responsive sites and downloadable web projects", icon: Layout },
  { id: "code", name: "Code Studio", description: "Source code, tests and project packages", icon: Code2 },
  { id: "ui-ux", name: "UI/UX Studio", description: "Design systems, wireframes and accessibility plans", icon: Palette },
  { id: "three-d", name: "3D & Three.js", description: "Live Three.js scenes and GLTF-ready structures", icon: Box },
  { id: "video", name: "Video Studio", description: "Scripts, shots, subtitles and FFmpeg render plans", icon: Film },
  { id: "animation", name: "Animation Studio", description: "Storyboards, timing sheets and scene direction", icon: Sparkles },
  { id: "advertising", name: "Advertising Studio", description: "Campaigns, product ads and conversion variants", icon: Megaphone },
  { id: "documentary", name: "Documentary Studio", description: "Research, interviews, narration and evidence plans", icon: Film },
  { id: "image", name: "Image Studio", description: "Editable SVG visuals and provider-ready prompt packs", icon: Image },
  { id: "branding", name: "Branding Studio", description: "Identity strategy, tokens and usage systems", icon: Palette },
] as const;

type Department = (typeof departments)[number]["id"];

function filenameFromDisposition(value: string | null, fallback: string) {
  const match = value?.match(/filename="?([^";]+)"?/i);
  return match?.[1] || fallback;
}

export default function StudioPage() {
  const [department, setDepartment] = useState<Department>("website");
  const [title, setTitle] = useState("");
  const [brief, setBrief] = useState("");
  const [style, setStyle] = useState("modern cinematic");
  const [target, setTarget] = useState("");
  const [language, setLanguage] = useState("en-US");
  const [programmingLanguage, setProgrammingLanguage] = useState("python");
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const selected = useMemo(() => departments.find((item) => item.id === department)!, [department]);

  useEffect(() => {
    setLanguage(document.documentElement.lang || "en-US");
  }, []);

  async function generate(event: FormEvent) {
    event.preventDefault();
    setGenerating(true);
    setError(null);
    try {
      const token = window.localStorage.getItem("aionex.access_token");
      const response = await fetch("/api/v1/studio/generate", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          department,
          title,
          brief,
          language,
          style,
          target: target || null,
          programming_language: department === "code" ? programmingLanguage : null,
        }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || "Production failed");
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filenameFromDisposition(response.headers.get("content-disposition"), `${title || "aionex-project"}.zip`);
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Production failed");
    } finally {
      setGenerating(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-electric-300">AIONEX Production</p>
        <h1 className="mt-2 text-3xl font-bold text-white">Creative & Developer Studio</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-white/50">Choose one specialist department. Each department produces its own editable, downloadable package instead of mixing unrelated tools in one workflow.</p>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-5">
        {departments.map((item) => {
          const Icon = item.icon;
          const active = item.id === department;
          return (
            <button key={item.id} type="button" onClick={() => setDepartment(item.id)} className={`glass-card p-4 text-left transition ${active ? "border-electric-400/50 bg-electric-500/10" : "hover:bg-white/[0.04]"}`}>
              <Icon className={`h-5 w-5 ${active ? "text-electric-300" : "text-white/40"}`} />
              <div className="mt-3 text-sm font-semibold text-white">{item.name}</div>
              <div className="mt-1 text-xs leading-5 text-white/40">{item.description}</div>
            </button>
          );
        })}
      </div>

      <form onSubmit={generate} className="glass-card grid gap-5 p-6 lg:grid-cols-[1fr_320px]">
        <div className="space-y-4">
          <div>
            <h2 className="text-lg font-semibold text-white">{selected.name}</h2>
            <p className="mt-1 text-sm text-white/40">{selected.description}</p>
          </div>
          <input required minLength={2} value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Project title" className="glass-input w-full rounded-xl px-4 py-3 text-sm text-white outline-none" />
          <textarea required minLength={8} value={brief} onChange={(event) => setBrief(event.target.value)} placeholder="Describe exactly what you want, audience, colors, scenes, features, dimensions and output requirements..." className="glass-input min-h-48 w-full rounded-xl px-4 py-3 text-sm text-white outline-none" />
          <div className="grid gap-3 sm:grid-cols-2">
            <input value={style} onChange={(event) => setStyle(event.target.value)} placeholder="Style" className="glass-input rounded-xl px-4 py-3 text-sm text-white outline-none" />
            <input value={target} onChange={(event) => setTarget(event.target.value)} placeholder="Target audience or platform" className="glass-input rounded-xl px-4 py-3 text-sm text-white outline-none" />
          </div>
          {department === "code" && (
            <select value={programmingLanguage} onChange={(event) => setProgrammingLanguage(event.target.value)} className="glass-input w-full rounded-xl px-4 py-3 text-sm text-white outline-none">
              {['python','typescript','javascript','go','rust','java','csharp','php','swift','kotlin','dart'].map((item) => <option key={item} value={item} className="bg-space-900">{item}</option>)}
            </select>
          )}
          {error && <div className="rounded-xl border border-red-500/20 bg-red-500/10 p-3 text-sm text-red-300">{error}</div>}
          <button disabled={generating} className="btn-primary">
            {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
            {generating ? "Producing package..." : "Generate & Download ZIP"}
          </button>
        </div>
        <aside className="rounded-2xl border border-white/[0.06] bg-black/20 p-5">
          <div className="text-xs font-semibold uppercase tracking-wider text-white/35">Live output</div>
          <div className="mt-4 space-y-3 text-sm text-white/60">
            <p>✓ Separate department workflow</p>
            <p>✓ Editable source files</p>
            <p>✓ AIONEX manifest</p>
            <p>✓ ZIP download in browser</p>
            <p>✓ Language and RTL metadata</p>
            <p>✓ Provider-ready production prompts</p>
          </div>
          <p className="mt-5 text-xs leading-5 text-amber-200/70">Rendered AI media requires an approved image/video/voice provider. The studio still creates a complete editable production package when no paid provider is configured.</p>
        </aside>
      </form>
    </div>
  );
}
