"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  AudioLines,
  Film,
  ImageIcon,
  Languages,
  Loader2,
  Mic2,
  Music2,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  WandSparkles,
} from "lucide-react";

import {
  createLiveMedia,
  getLiveMediaCapabilities,
  listLiveMediaJobs,
  type LiveMediaCapabilities,
  type LiveMediaJob,
  type LiveMediaKind,
} from "@/lib/live-media-api";
import { listProjectOptions, type ProjectOption } from "@/lib/studio-api";

const inputClass =
  "glass-input w-full rounded-xl px-4 py-3 text-sm text-white outline-none disabled:cursor-not-allowed disabled:opacity-50";
const labelClass = "space-y-2 text-xs font-medium text-white/60";
const terminal = new Set(["completed", "failed", "cancelled", "blocked", "needs_review"]);

const kinds: Array<{
  id: LiveMediaKind;
  title: string;
  description: string;
  icon: typeof ImageIcon;
  capability: keyof Pick<
    LiveMediaCapabilities,
    "image" | "video" | "speech" | "transcript" | "dubbing" | "music" | "open_song"
  >;
}> = [
  { id: "image", title: "Image", description: "GPT Image 2 governed generation and edits", icon: ImageIcon, capability: "image" },
  { id: "video", title: "Video", description: "Sora 2 durable multi-scene generation", icon: Film, capability: "video" },
  { id: "speech", title: "Speech", description: "Pinned stock-voice narration", icon: Mic2, capability: "speech" },
  { id: "transcript", title: "Transcript", description: "Governed STT / diarization from a media node", icon: Languages, capability: "transcript" },
  { id: "dubbing", title: "Dubbing", description: "Translated stock-voice dubbing from transcript evidence", icon: AudioLines, capability: "dubbing" },
  { id: "music", title: "Music", description: "Replicate Lyria or Stability fixed-price generation", icon: Music2, capability: "music" },
  { id: "song", title: "Full Song", description: "RunPod ACE-Step full song + four stems", icon: Sparkles, capability: "open_song" },
];

function newKey(kind: LiveMediaKind) {
  const suffix = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
  return `studio-live-${kind}-${suffix}`;
}

function amount(value: string) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) throw new Error("Enter a valid positive cost approval.");
  return parsed;
}

function statusTone(status: string) {
  if (status === "completed") return "text-emerald-300";
  if (["failed", "cancelled", "blocked", "needs_review"].includes(status)) return "text-rose-300";
  if (["queued", "running", "rendering", "submitted"].includes(status)) return "text-amber-300";
  return "text-white/60";
}

export default function LiveMediaStudioPage() {
  const [kind, setKind] = useState<LiveMediaKind>("image");
  const [capabilities, setCapabilities] = useState<LiveMediaCapabilities | null>(null);
  const [projects, setProjects] = useState<ProjectOption[]>([]);
  const [jobs, setJobs] = useState<LiveMediaJob[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("Loading governed live-media runtime evidence...");

  const [projectId, setProjectId] = useState("");
  const [title, setTitle] = useState("AIONEX live media creation");
  const [brief, setBrief] = useState("Create an original polished asset for this project.");
  const [language, setLanguage] = useState("en-US");
  const [style, setStyle] = useState("modern cinematic");
  const [cost, setCost] = useState("0.05");

  const [imageUseCase, setImageUseCase] = useState("social-post");
  const [imagePreset, setImagePreset] = useState("social-square");
  const [imageOperation, setImageOperation] = useState("generate");
  const [referenceNode, setReferenceNode] = useState("");
  const [maskNode, setMaskNode] = useState("");

  const [videoOperation, setVideoOperation] = useState("text-to-video");
  const [videoUseCase, setVideoUseCase] = useState("advertisement");

  const [voice, setVoice] = useState("marin");
  const [instructions, setInstructions] = useState("Speak naturally, clearly, and at a comfortable pace.");

  const [sourceNode, setSourceNode] = useState("");
  const [transcriptOperation, setTranscriptOperation] = useState("transcribe");
  const [durationMs, setDurationMs] = useState("5000");
  const [sampleRate, setSampleRate] = useState("48000");
  const [channels, setChannels] = useState("1");

  const [targetLanguage, setTargetLanguage] = useState("en");
  const [voiceBindings, setVoiceBindings] = useState('{"speaker-1":"marin"}');
  const [translationCap, setTranslationCap] = useState("0.20");
  const [segmentCap, setSegmentCap] = useState("0.05");

  const [musicProvider, setMusicProvider] = useState("replicate");
  const [musicTier, setMusicTier] = useState("draft");
  const [lyrics, setLyrics] = useState("");
  const [rightsBasis, setRightsBasis] = useState("instrumental");
  const [rightsEvidence, setRightsEvidence] = useState("");
  const [priorDraft, setPriorDraft] = useState("");
  const [finalApprovalEvidence, setFinalApprovalEvidence] = useState("");

  const [songConcept, setSongConcept] = useState("Original cinematic electronic pop with a memorable chorus and a clean resolved ending.");
  const [songLyrics, setSongLyrics] = useState("[Verse]\nWrite an original verse here.\n[Chorus]\nWrite an original chorus here with enough content for generation.");
  const [songDuration, setSongDuration] = useState("30");
  const [bpm, setBpm] = useState("104");
  const [musicalKey, setMusicalKey] = useState("Am");
  const [monthlyCap, setMonthlyCap] = useState("0.40");

  const [commercialRights, setCommercialRights] = useState(false);
  const [providerTerms, setProviderTerms] = useState(false);
  const [disclosureAccepted, setDisclosureAccepted] = useState(false);

  const selected = useMemo(() => kinds.find((item) => item.id === kind) ?? kinds[0], [kind]);
  const currentCapability = capabilities?.[selected.capability];
  const activeJobs = jobs.some((job) => !terminal.has(job.status));

  const load = useCallback(async () => {
    try {
      const [caps, jobResult, projectRows] = await Promise.all([
        getLiveMediaCapabilities(),
        listLiveMediaJobs(),
        listProjectOptions(),
      ]);
      setCapabilities(caps);
      setJobs(jobResult.jobs);
      setProjects(projectRows);
      setMessage("Live provider evidence, worker state, projects, and durable jobs synchronized.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Live Media is unavailable.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!activeJobs) return;
    const timer = window.setInterval(() => void load(), 4000);
    return () => window.clearInterval(timer);
  }, [activeJobs, load]);

  useEffect(() => {
    if (kind === "video") setCost("2.40");
    else if (kind === "song") setCost("0.20");
    else if (kind === "music") setCost(musicProvider === "stability" ? "0.20" : "0.04");
    else if (kind === "speech") setCost("0.05");
    else setCost("0.10");
  }, [kind, musicProvider]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!currentCapability?.ready) {
      setMessage("This runtime is not currently live-ready for the selected provider/model evidence.");
      return;
    }
    setBusy(true);
    try {
      const common = {
        project_id: projectId || null,
        idempotency_key: newKey(kind),
      };
      let payload: Record<string, unknown>;
      if (kind === "image") {
        payload = {
          ...common,
          title,
          brief,
          use_case: imageUseCase,
          preset_id: imagePreset,
          operation: imageOperation,
          style,
          language,
          output_format: "png",
          reference_node_ids: referenceNode ? [referenceNode] : [],
          mask_node_id: maskNode || null,
          approved_max_cost_usd: amount(cost),
        };
      } else if (kind === "video") {
        payload = {
          ...common,
          title,
          brief,
          operation: videoOperation,
          use_case: videoUseCase,
          aspect_ratio: "16:9",
          resolution: "720p",
          language,
          style,
          reference_node_id: videoOperation === "text-to-video" ? null : referenceNode || null,
          approved_max_total_cost_usd: amount(cost),
        };
      } else if (kind === "speech") {
        payload = {
          ...common,
          title,
          text: brief,
          language,
          voice,
          instructions,
          speed: 1,
          approved_max_cost_usd: amount(cost),
        };
      } else if (kind === "transcript") {
        payload = {
          ...common,
          source_node_id: sourceNode,
          language: language.split("-")[0],
          operation: transcriptOperation,
          source_duration_ms: Number(durationMs),
          source_sample_rate_hz: Number(sampleRate),
          source_channels: Number(channels),
          approved_max_cost_usd: amount(cost),
        };
      } else if (kind === "dubbing") {
        let bindings: Record<string, string>;
        try {
          bindings = JSON.parse(voiceBindings) as Record<string, string>;
        } catch {
          throw new Error("Voice bindings must be a valid JSON object.");
        }
        payload = {
          ...common,
          source_transcript_node_id: sourceNode,
          target_language: targetLanguage,
          voice_bindings: bindings,
          output_profile_id: "wav-pcm-48k-stereo",
          max_translation_cost_usd: amount(translationCap),
          per_segment_speech_cap_usd: amount(segmentCap),
          approved_max_total_cost_usd: amount(cost),
        };
      } else if (kind === "music") {
        payload = {
          ...common,
          title,
          prompt: brief,
          language: language.split("-")[0],
          provider: musicProvider,
          tier: musicTier,
          instrumental_only: rightsBasis === "instrumental",
          lyrics,
          rights_basis: rightsBasis,
          rights_evidence_sha256: rightsEvidence || null,
          commercial_use_authorized: commercialRights,
          provider_terms_accepted: providerTerms,
          ai_generated_disclosure_accepted: disclosureAccepted,
          final_generation_approved: musicTier === "final",
          final_approval_evidence_sha256: finalApprovalEvidence || null,
          prior_draft_checksum: priorDraft || null,
          approved_max_cost_usd: amount(cost),
        };
      } else {
        payload = {
          ...common,
          title,
          concept: songConcept,
          lyrics: songLyrics,
          language: language.split("-")[0],
          duration_seconds: Number(songDuration),
          bpm: Number(bpm),
          musical_key: musicalKey,
          rights_basis: rightsBasis === "instrumental" ? "original" : rightsBasis.replace("original-user-owned", "original"),
          rights_evidence_sha256: rightsEvidence || null,
          commercial_use_authorized: commercialRights,
          provider_terms_accepted: providerTerms,
          ai_generated_disclosure_accepted: disclosureAccepted,
          approved_max_cost_usd: amount(cost),
          monthly_user_cap_usd: amount(monthlyCap),
        };
      }
      const result = await createLiveMedia(kind, payload);
      setMessage(`${selected.title} request admitted safely. Durable status: ${String(result.status ?? "accepted")}.`);
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Live media request failed.");
    } finally {
      setBusy(false);
    }
  }

  const needsRights = kind === "music" || kind === "song";

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-electric-300">AIONEX Production</p>
          <h1 className="mt-2 text-3xl font-bold text-white">Governed Live Media Studio</h1>
          <p className="mt-2 max-w-4xl text-sm leading-6 text-white/50">
            Real provider execution through the accepted Phase 36 authorities. Every paid request is tenant-scoped,
            idempotent, explicitly cost-approved, fail-closed, and never exposes provider credentials or raw job IDs.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link href="/studio" className="btn-secondary">Provider-neutral Studio</Link>
          <button type="button" className="btn-primary" disabled={loading} onClick={() => void load()}>
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /> Refresh
          </button>
        </div>
      </div>

      <div className="glass-card flex items-start gap-3 p-4 text-xs text-electric-300">
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" />
        <span>{message}</span>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
        {kinds.map((item) => {
          const Icon = item.icon;
          const state = capabilities?.[item.capability];
          const active = item.id === kind;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => setKind(item.id)}
              className={`glass-card p-4 text-left transition ${active ? "border-electric-400/50 bg-electric-500/10" : "hover:bg-white/[0.04]"}`}
            >
              <div className="flex items-center justify-between gap-2">
                <Icon className={`h-5 w-5 ${active ? "text-electric-300" : "text-white/40"}`} />
                <span className={`text-[10px] font-semibold uppercase ${state?.ready ? "text-emerald-300" : "text-rose-300"}`}>
                  {state?.ready ? "ready" : "gated"}
                </span>
              </div>
              <div className="mt-3 text-sm font-semibold text-white">{item.title}</div>
              <div className="mt-1 text-[11px] leading-4 text-white/40">{item.description}</div>
            </button>
          );
        })}
      </div>

      <form onSubmit={submit} className="glass-card grid gap-6 p-6 xl:grid-cols-[1fr_360px]">
        <div className="space-y-5">
          <div className="flex items-center gap-3">
            <WandSparkles className="h-5 w-5 text-electric-300" />
            <div>
              <h2 className="font-semibold text-white">{selected.title} request</h2>
              <p className="text-xs text-white/40">Worker: {currentCapability?.worker_live ? "live" : "disabled until deployment activation"}</p>
            </div>
          </div>

          {!["transcript", "dubbing"].includes(kind) && (
            <div className="grid gap-4 md:grid-cols-2">
              <label className={labelClass}>Title<input className={inputClass} value={title} onChange={(e) => setTitle(e.target.value)} /></label>
              <label className={labelClass}>Language<input className={inputClass} value={language} onChange={(e) => setLanguage(e.target.value)} /></label>
            </div>
          )}

          {!["transcript", "dubbing", "song"].includes(kind) && (
            <label className={labelClass}>Prompt / content<textarea className={`${inputClass} min-h-36`} value={brief} onChange={(e) => setBrief(e.target.value)} /></label>
          )}

          {kind === "image" && (
            <div className="grid gap-4 md:grid-cols-3">
              <label className={labelClass}>Operation<select className={inputClass} value={imageOperation} onChange={(e) => setImageOperation(e.target.value)}><option value="generate">Generate</option><option value="edit">Edit</option><option value="variation">Variation</option><option value="inpaint">Inpaint</option></select></label>
              <label className={labelClass}>Use case<select className={inputClass} value={imageUseCase} onChange={(e) => setImageUseCase(e.target.value)}><option value="social-post">Social post</option><option value="logo">Logo</option><option value="advertisement">Advertisement</option><option value="poster">Poster</option><option value="product-mockup">Product mockup</option><option value="infographic">Infographic</option><option value="diagram">Diagram</option></select></label>
              <label className={labelClass}>Preset<select className={inputClass} value={imagePreset} onChange={(e) => setImagePreset(e.target.value)}><option value="social-square">Social square</option><option value="social-portrait">Social portrait</option><option value="story-vertical">Story vertical</option><option value="ad-landscape">Ad landscape</option><option value="poster-portrait">Poster portrait</option><option value="logo-square">Logo square</option></select></label>
              {imageOperation !== "generate" && <label className={labelClass}>Reference media node<input className={inputClass} value={referenceNode} onChange={(e) => setReferenceNode(e.target.value)} /></label>}
              {imageOperation === "inpaint" && <label className={labelClass}>Mask media node<input className={inputClass} value={maskNode} onChange={(e) => setMaskNode(e.target.value)} /></label>}
              <label className={labelClass}>Style<input className={inputClass} value={style} onChange={(e) => setStyle(e.target.value)} /></label>
            </div>
          )}

          {kind === "video" && (
            <div className="grid gap-4 md:grid-cols-3">
              <label className={labelClass}>Operation<select className={inputClass} value={videoOperation} onChange={(e) => setVideoOperation(e.target.value)}><option value="text-to-video">Text to video</option><option value="image-to-video">Image to video</option><option value="logo-to-video">Logo to video</option><option value="reference-to-video">Reference to video</option><option value="remix">Remix</option></select></label>
              <label className={labelClass}>Use case<select className={inputClass} value={videoUseCase} onChange={(e) => setVideoUseCase(e.target.value)}><option value="advertisement">Advertisement</option><option value="explainer">Explainer</option><option value="product">Product</option><option value="social">Social</option><option value="cinematic">Cinematic</option><option value="logo-animation">Logo animation</option></select></label>
              {videoOperation !== "text-to-video" && <label className={labelClass}>Reference media node<input className={inputClass} value={referenceNode} onChange={(e) => setReferenceNode(e.target.value)} /></label>}
            </div>
          )}

          {kind === "speech" && (
            <div className="grid gap-4 md:grid-cols-2">
              <label className={labelClass}>Stock voice<select className={inputClass} value={voice} onChange={(e) => setVoice(e.target.value)}><option value="marin">Marin</option><option value="cedar">Cedar</option><option value="alloy">Alloy</option><option value="coral">Coral</option><option value="nova">Nova</option><option value="onyx">Onyx</option><option value="shimmer">Shimmer</option></select></label>
              <label className={labelClass}>Voice instructions<input className={inputClass} value={instructions} onChange={(e) => setInstructions(e.target.value)} /></label>
            </div>
          )}

          {kind === "transcript" && (
            <div className="grid gap-4 md:grid-cols-2">
              <label className={labelClass}>Source media node<input className={inputClass} required value={sourceNode} onChange={(e) => setSourceNode(e.target.value)} /></label>
              <label className={labelClass}>Operation<select className={inputClass} value={transcriptOperation} onChange={(e) => setTranscriptOperation(e.target.value)}><option value="transcribe">Single-speaker transcript</option><option value="diarize">Diarization</option></select></label>
              <label className={labelClass}>Duration ms<input className={inputClass} type="number" value={durationMs} onChange={(e) => setDurationMs(e.target.value)} /></label>
              <label className={labelClass}>Sample rate Hz<input className={inputClass} type="number" value={sampleRate} onChange={(e) => setSampleRate(e.target.value)} /></label>
              <label className={labelClass}>Channels<input className={inputClass} type="number" min="1" max="2" value={channels} onChange={(e) => setChannels(e.target.value)} /></label>
              <label className={labelClass}>Language<input className={inputClass} value={language} onChange={(e) => setLanguage(e.target.value)} /></label>
            </div>
          )}

          {kind === "dubbing" && (
            <div className="grid gap-4 md:grid-cols-2">
              <label className={labelClass}>Completed transcript node<input className={inputClass} required value={sourceNode} onChange={(e) => setSourceNode(e.target.value)} /></label>
              <label className={labelClass}>Target language<input className={inputClass} value={targetLanguage} onChange={(e) => setTargetLanguage(e.target.value)} /></label>
              <label className={`${labelClass} md:col-span-2`}>Speaker → stock voice JSON<textarea className={`${inputClass} min-h-24 font-mono text-xs`} value={voiceBindings} onChange={(e) => setVoiceBindings(e.target.value)} /></label>
              <label className={labelClass}>Translation cap USD<input className={inputClass} type="number" step="0.01" value={translationCap} onChange={(e) => setTranslationCap(e.target.value)} /></label>
              <label className={labelClass}>Per-segment speech cap USD<input className={inputClass} type="number" step="0.01" value={segmentCap} onChange={(e) => setSegmentCap(e.target.value)} /></label>
            </div>
          )}

          {kind === "music" && (
            <div className="grid gap-4 md:grid-cols-2">
              <label className={labelClass}>Provider<select className={inputClass} value={musicProvider} onChange={(e) => setMusicProvider(e.target.value)}><option value="replicate">Replicate / Lyria</option><option value="stability">Stability / Stable Audio 2.5</option></select></label>
              <label className={labelClass}>Tier<select className={inputClass} value={musicTier} onChange={(e) => setMusicTier(e.target.value)}><option value="draft">Draft</option>{musicProvider === "replicate" && <option value="final">Final</option>}</select></label>
              <label className={labelClass}>Rights basis<select className={inputClass} value={rightsBasis} onChange={(e) => setRightsBasis(e.target.value)}><option value="instrumental">Instrumental / no lyric rights claim</option><option value="original-user-owned">Original user-owned</option><option value="licensed">Licensed</option><option value="public-domain">Public domain</option></select></label>
              {rightsBasis !== "instrumental" && <label className={labelClass}>Rights evidence SHA-256<input className={inputClass} value={rightsEvidence} onChange={(e) => setRightsEvidence(e.target.value)} /></label>}
              {musicTier === "final" && <><label className={labelClass}>Prior draft checksum<input className={inputClass} value={priorDraft} onChange={(e) => setPriorDraft(e.target.value)} /></label><label className={labelClass}>Final approval evidence SHA-256<input className={inputClass} value={finalApprovalEvidence} onChange={(e) => setFinalApprovalEvidence(e.target.value)} /></label></>}
              {!rightsBasis.startsWith("instrumental") && <label className={`${labelClass} md:col-span-2`}>Lyrics<textarea className={`${inputClass} min-h-28`} value={lyrics} onChange={(e) => setLyrics(e.target.value)} /></label>}
            </div>
          )}

          {kind === "song" && (
            <div className="grid gap-4 md:grid-cols-2">
              <label className={`${labelClass} md:col-span-2`}>Song concept<textarea className={`${inputClass} min-h-24`} value={songConcept} onChange={(e) => setSongConcept(e.target.value)} /></label>
              <label className={`${labelClass} md:col-span-2`}>Original / licensed lyrics<textarea className={`${inputClass} min-h-48`} value={songLyrics} onChange={(e) => setSongLyrics(e.target.value)} /></label>
              <label className={labelClass}>Duration seconds<input className={inputClass} type="number" min="30" max="180" value={songDuration} onChange={(e) => setSongDuration(e.target.value)} /></label>
              <label className={labelClass}>BPM<input className={inputClass} type="number" min="40" max="240" value={bpm} onChange={(e) => setBpm(e.target.value)} /></label>
              <label className={labelClass}>Musical key<input className={inputClass} value={musicalKey} onChange={(e) => setMusicalKey(e.target.value)} /></label>
              <label className={labelClass}>Rights basis<select className={inputClass} value={rightsBasis === "instrumental" ? "original-user-owned" : rightsBasis} onChange={(e) => setRightsBasis(e.target.value)}><option value="original-user-owned">Original</option><option value="licensed">Licensed</option><option value="public-domain">Public domain</option></select></label>
              {rightsBasis !== "instrumental" && rightsBasis !== "original-user-owned" && <label className={`${labelClass} md:col-span-2`}>Rights evidence SHA-256<input className={inputClass} value={rightsEvidence} onChange={(e) => setRightsEvidence(e.target.value)} /></label>}
            </div>
          )}

          {needsRights && (
            <div className="grid gap-3 rounded-xl border border-white/10 bg-white/[0.025] p-4 text-xs text-white/60">
              <label className="flex items-start gap-3"><input type="checkbox" className="mt-0.5" checked={commercialRights} onChange={(e) => setCommercialRights(e.target.checked)} />I confirm I hold the required commercial-use rights for the submitted material.</label>
              <label className="flex items-start gap-3"><input type="checkbox" className="mt-0.5" checked={providerTerms} onChange={(e) => setProviderTerms(e.target.checked)} />I accept the selected provider&apos;s applicable terms.</label>
              <label className="flex items-start gap-3"><input type="checkbox" className="mt-0.5" checked={disclosureAccepted} onChange={(e) => setDisclosureAccepted(e.target.checked)} />I accept required AI-generated-content disclosure obligations.</label>
            </div>
          )}
        </div>

        <aside className="space-y-4">
          <div className="rounded-xl border border-white/10 bg-white/[0.025] p-4">
            <div className="text-xs font-semibold uppercase tracking-wider text-white/40">Admission & spend</div>
            <div className="mt-4 space-y-4">
              <label className={labelClass}>Project<select className={inputClass} value={projectId} onChange={(e) => setProjectId(e.target.value)}><option value="">No project attachment</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
              <label className={labelClass}>Approved maximum cost USD<input className={inputClass} type="number" min="0.01" step="0.01" value={cost} onChange={(e) => setCost(e.target.value)} /></label>
              {kind === "song" && <label className={labelClass}>Monthly user cap USD<input className={inputClass} type="number" step="0.01" value={monthlyCap} onChange={(e) => setMonthlyCap(e.target.value)} /></label>}
            </div>
            <div className="mt-4 space-y-1 text-[11px] leading-5 text-white/40">
              <div>• No blind provider retry or cross-provider fallback.</div>
              <div>• Cost approval is durable before a job becomes claimable.</div>
              <div>• Open Song balance is checked only inside its secret-bearing worker.</div>
              <div>• Provider credentials and raw remote job IDs never return to this UI.</div>
            </div>
          </div>
          <button type="submit" disabled={busy || !currentCapability?.ready} className="btn-primary w-full justify-center disabled:cursor-not-allowed disabled:opacity-40">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            {busy ? "Admitting request..." : `Approve & queue ${selected.title}`}
          </button>
        </aside>
      </form>

      <div className="glass-card p-5">
        <div className="flex items-center justify-between gap-3">
          <div><h2 className="font-semibold text-white">Recent live-media executions</h2><p className="mt-1 text-xs text-white/40">Durable tenant-scoped status only; provider secrets and raw remote IDs are excluded.</p></div>
          {activeJobs && <Loader2 className="h-4 w-4 animate-spin text-electric-300" />}
        </div>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[760px] text-left text-xs">
            <thead className="text-white/35"><tr><th className="pb-3">Kind</th><th className="pb-3">Provider / model</th><th className="pb-3">Status</th><th className="pb-3">Attempts</th><th className="pb-3">Actual cost</th><th className="pb-3">Created</th></tr></thead>
            <tbody className="divide-y divide-white/5">
              {jobs.slice(0, 40).map((job) => (
                <tr key={`${job.kind}-${job.id}`}>
                  <td className="py-3 font-medium capitalize text-white">{job.kind}{job.scene_key ? ` · ${job.scene_key}` : ""}</td>
                  <td className="py-3 text-white/50">{job.provider ?? "local"}{job.model ? ` / ${job.model}` : ""}</td>
                  <td className={`py-3 font-semibold ${statusTone(job.status)}`}>{job.status}</td>
                  <td className="py-3 text-white/50">{job.attempts}/{job.max_attempts}</td>
                  <td className="py-3 text-white/50">{job.actual_cost_usd == null ? "—" : `$${job.actual_cost_usd.toFixed(5)}`}</td>
                  <td className="py-3 text-white/40">{new Date(job.created_at).toLocaleString()}</td>
                </tr>
              ))}
              {!jobs.length && <tr><td colSpan={6} className="py-8 text-center text-white/35">No live-media executions yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
