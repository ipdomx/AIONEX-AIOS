from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Final, Literal

Maturity = Literal[
    "specified",
    "source_built",
    "locally_executed",
    "provider_connected",
    "runtime_verified",
    "scaled",
    "production_ready",
]
BatchStatus = Literal["complete", "in_progress", "planned"]

MATURITY_ORDER: Final[tuple[Maturity, ...]] = (
    "specified",
    "source_built",
    "locally_executed",
    "provider_connected",
    "runtime_verified",
    "scaled",
    "production_ready",
)


@dataclass(frozen=True, slots=True)
class Phase36Capability:
    capability_id: str
    category: str
    title: str
    owner_batch: str
    maturity: Maturity
    evidence: tuple[str, ...] = ()
    external_gates: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Phase36Batch:
    batch_id: str
    sequence: int
    title: str
    status: BatchStatus


CAPABILITIES: Final[tuple[Phase36Capability, ...]] = (
    # Program / scale foundation.
    Phase36Capability("program-registry", "program", "Capability maturity registry and reporting invariant", "36A", "production_ready", ("docs/phase-36/PHASE_36_UNIVERSAL_CAPABILITY_SCALE_MASTER_ROADMAP.md",)),
    Phase36Capability("distributed-project-execution", "scale", "Distributed live project execution", "36B", "runtime_verified", ("docs/phase-23/PHASE_23_DISTRIBUTED_EXECUTION_FABRIC.md", "docs/phase-36/receipts/36B-2026-08-17-distributed-project-execution.md")),
    Phase36Capability("thousand-user-admission", "scale", "1000+ concurrent authenticated user and workflow admission", "36B", "locally_executed", ("docs/phase-36/receipts/36B-2026-08-17-distributed-project-execution.md",)),
    Phase36Capability("horizontal-worker-scaling", "scale", "Horizontal CPU/GPU/provider worker scaling", "36B", "runtime_verified", ("docs/phase-29/PHASE_29I_PLUGINS_DISTRIBUTED_INTEGRATIONS_COMPLETION.md", "docs/phase-36/receipts/36B-2026-08-17-distributed-project-execution.md")),
    Phase36Capability("multi-provider-project-routing", "ai", "Multi-provider/model project execution pools", "36C", "runtime_verified", ("docs/phase-29/PHASE_29J_MODELS_PROVIDERS_FINAL_COMPLETION.md", "docs/phase-36/receipts/36C-2026-08-17-multi-provider-execution-baseline.md"), ("owner-provider-funded-credit-thresholds",)),
    Phase36Capability("tenant-agent-memory-isolation", "ai", "Tenant/project-scoped agent and model memory isolation", "36C", "runtime_verified", ("docs/phase-36/receipts/36C-2026-08-17-multi-provider-execution-baseline.md",)),

    # Software / application engineering.
    Phase36Capability("web-saas-pwa", "software", "Websites, SaaS, portals and PWAs", "36C", "locally_executed", ("docs/phase-28/PHASE_28_FULL_PROJECT_LIFECYCLE.md",)),
    Phase36Capability("api-serverless", "software", "REST/domain APIs and serverless functions", "36C", "locally_executed", ("docs/phase-28/PHASE_28_FULL_PROJECT_LIFECYCLE.md",)),
    Phase36Capability("mobile-apps", "software", "Android/iOS application source and delivery", "36C", "locally_executed", ("docs/phase-29/PHASE_29H_PRODUCTION_STUDIO_MOBILE_DELIVERY_COMPLETION.md",), ("store-signing-and-publication",)),
    Phase36Capability("desktop-apps", "software", "Windows/macOS/Linux desktop source", "36C", "locally_executed", ("docs/phase-28/PHASE_28_FULL_PROJECT_LIFECYCLE.md",), ("platform-code-signing",)),
    Phase36Capability("browser-extensions", "software", "Browser extensions", "36C", "locally_executed"),
    Phase36Capability("data-database-etl", "software", "Databases, ETL, analytics and data pipelines", "36C", "locally_executed"),
    Phase36Capability("bots-automation-cli-sdk", "software", "Bots, automation, CLIs, SDKs and libraries", "36C", "locally_executed"),
    Phase36Capability("commerce-apps", "software", "Commerce, subscription and billing domain applications", "36C", "locally_executed", (), ("live-payment-provider-credential",)),
    Phase36Capability("iot-robotics-contracts", "software", "IoT/firmware simulation, robotics and smart contracts", "36C", "locally_executed", (), ("physical-device-or-chain-deployment-authority",)),

    # Creative/media graph and image/design.
    Phase36Capability("creative-asset-graph", "media", "Durable creative asset DAG, revisions and provenance", "36D", "runtime_verified", ("docs/phase-36/receipts/36D-2026-08-17-media-orchestrator.md",)),
    Phase36Capability("media-render-transcode", "media", "Real render/transcode and resumable assembly", "36D", "runtime_verified", ("docs/phase-36/receipts/36D-2026-08-17-media-orchestrator.md",)),
    Phase36Capability("object-storage-media", "media", "Scale object storage for media/artifacts", "36D", "runtime_verified", ("docs/phase-36/receipts/36D-2026-08-17-media-orchestrator.md",)),
    Phase36Capability("prompt-factory", "design", "Prompt generation, refinement and reusable packs", "36E", "runtime_verified", ("docs/phase-29/PHASE_29H_PRODUCTION_STUDIO_MOBILE_DELIVERY_COMPLETION.md", "docs/phase-36/receipts/36E-2026-08-18-design-image-foundation.md")),
    Phase36Capability("image-generation-editing", "design", "Image generation, editing, variants and upscale workflows", "36E", "runtime_verified", ("docs/phase-36/receipts/36E-2026-08-18-design-image-foundation.md",)),
    Phase36Capability("logo-branding", "design", "Logo systems, branding and brand kits", "36E", "runtime_verified", ("docs/phase-36/receipts/36E-2026-08-18-design-image-foundation.md",)),
    Phase36Capability("infographic-experimental-graphics", "design", "Infographics, diagrams and experimental graphics", "36E", "runtime_verified", ("docs/phase-36/receipts/36E-2026-08-18-design-image-foundation.md",)),
    Phase36Capability("editable-design-exports", "design", "Editable vector/raster source and export profiles", "36E", "runtime_verified", ("docs/phase-36/receipts/36E-2026-08-18-design-image-foundation.md",)),

    # Video/cinema/motion.
    Phase36Capability("text-image-logo-to-video", "video", "Text/image/logo-to-video generation", "36F", "runtime_verified", ("docs/phase-36/receipts/36F-2026-08-19-video-factory.md",)),
    Phase36Capability("long-form-ad-video", "video", "Long-form advertising and multi-scene video", "36F", "runtime_verified", ("docs/phase-36/receipts/36F-2026-08-19-video-factory.md",)),
    Phase36Capability("cinema-motion-vfx", "video", "Cinema, motion graphics, compositing and VFX", "36F", "specified"),
    Phase36Capability("video-continuity-resume", "video", "Scene continuity, resumable rendering and partial regeneration", "36F", "runtime_verified", ("docs/phase-36/receipts/36F-2026-08-19-video-factory.md",)),
    Phase36Capability("video-final-export", "video", "1080p/1440p/4K and governed final video exports", "36F", "source_built", ("docs/phase-36/receipts/36F-2026-08-19-video-factory.md",)),

    # Audio/music.
    Phase36Capability("stt-tts-dubbing", "audio", "Speech recognition, speech synthesis, dubbing and alignment", "36G", "source_built", ("docs/phase-36/receipts/36G-2026-08-21-audio-foundation.md",)),
    Phase36Capability("voice-transformation", "audio", "Consent-governed voice transformation", "36G", "specified", ("docs/phase-36/receipts/36G-2026-08-21-audio-foundation.md",), ("voice-rights-and-consent-evidence",)),
    Phase36Capability("audio-cleanup-master", "audio", "Audio cleanup, alignment, mixing, mastering and governed local export", "36G", "runtime_verified", ("docs/phase-36/receipts/36G-2026-08-21-audio-foundation.md",)),
    Phase36Capability("song-production", "audio", "Lyrics, composition, instruments, vocals, stems, mix and master", "36G", "specified", ("docs/phase-36/receipts/36G-2026-08-21-audio-foundation.md",)),
    Phase36Capability("podcast-jingle-narration", "audio", "Podcasts, jingles, narration and multi-speaker production", "36G", "source_built", ("docs/phase-36/receipts/36G-2026-08-21-audio-foundation.md",)),

    # Realtime and 2D/3D/XR.
    Phase36Capability("realtime-chat-calling", "realtime", "Realtime chat and 1:1/group voice-video calling", "36H", "source_built", ("docs/phase-28/PHASE_28_FULL_PROJECT_LIFECYCLE.md",), ("public-stun-turn-and-sfu-capacity",)),
    Phase36Capability("realtime-streaming-recording", "realtime", "Streaming, screen share and recording", "36H", "specified"),
    Phase36Capability("two-d-animation-games", "3d-xr", "2D animation and game production", "36I", "locally_executed"),
    Phase36Capability("three-d-production", "3d-xr", "3D assets, materials, animation, scenes and environments", "36I", "runtime_verified", ("docs/phase-34/PHASE_34G_PRODUCTION_E2E_COMPLETION.md",)),
    Phase36Capability("xr-ar-vr", "3d-xr", "WebXR, AR and VR experiences", "36I", "locally_executed", (), ("xr-device-validation",)),

    # Education / high-stakes / sector packs.
    Phase36Capability("course-factory", "education", "Complete multilingual course/curriculum factory", "36J", "source_built"),
    Phase36Capability("learning-assessment-certification", "education", "Learner progress, assessment, certification and analytics", "36J", "runtime_verified", ("docs/phase-29/PHASE_29F_PROJECTS_WORKFORCE_KNOWLEDGE_COMPLETION.md",)),
    Phase36Capability("healthcare-administration", "healthcare", "Clinic/hospital/medical administration systems", "36K", "source_built"),
    Phase36Capability("professional-evidence-assistance", "healthcare", "Evidence-grounded professional assistance", "36K", "specified", (), ("sector-evidence-and-human-review",)),
    Phase36Capability("high-stakes-human-review", "healthcare", "Human review and regulated-data controls", "36K", "specified"),
    Phase36Capability("retail-supermarket", "sectors", "Retail and supermarket pack", "36L", "source_built"),
    Phase36Capability("restaurant-hospitality", "sectors", "Restaurant and hospitality pack", "36L", "source_built"),
    Phase36Capability("pharmacy", "sectors", "Pharmacy pack", "36L", "source_built"),
    Phase36Capability("school-university", "sectors", "School, university and training-center pack", "36L", "source_built"),
    Phase36Capability("government-public-service", "sectors", "Government/public-service workflows", "36L", "source_built"),
    Phase36Capability("logistics-industry-realestate-professional", "sectors", "Logistics, manufacturing, real-estate and professional-service packs", "36L", "source_built"),
    Phase36Capability("custom-domain-composer", "sectors", "Unlisted lawful sector through Domain Blueprint v3", "36L", "locally_executed", ("docs/phase-28/PHASE_28_FULL_PROJECT_LIFECYCLE.md",)),

    # Product UX and final certification.
    Phase36Capability("unified-user-creative-studio", "product", "Unified user Project/Creative Studio", "36M", "specified"),
    Phase36Capability("owner-capability-governance", "product", "Owner quotas, policies, costs and capability controls", "36M", "source_built"),
    Phase36Capability("six-locale-mobile-ux", "product", "Six-locale mobile-first capability UX", "36M", "source_built"),
    Phase36Capability("scale-chaos-dr", "certification", "1000+ load, chaos, DR and final integrated certification", "36N", "specified"),
)

BATCHES: Final[tuple[Phase36Batch, ...]] = (
    Phase36Batch("36A", 1, "Program governance, registry and reporting invariant", "complete"),
    Phase36Batch("36B", 2, "Live distributed project execution and 1000-user admission", "complete"),
    Phase36Batch("36C", 3, "Multi-provider/model/agent execution pools", "complete"),
    Phase36Batch("36D", 4, "Universal Creative Asset Graph and Media Orchestrator", "complete"),
    Phase36Batch("36E", 5, "Image, design, branding, infographic and prompt factory", "complete"),
    Phase36Batch("36F", 6, "Video, cinema, motion graphics and advertising factory", "complete"),
    Phase36Batch("36G", 7, "Audio, voice, music, songs and podcast factory", "in_progress"),
    Phase36Batch("36H", 8, "Realtime communication, streaming and interactive media scale", "planned"),
    Phase36Batch("36I", 9, "2D/3D/XR/game/VFX production expansion", "planned"),
    Phase36Batch("36J", 10, "Education and complete course factory", "planned"),
    Phase36Batch("36K", 11, "Healthcare/professional and high-stakes controls", "planned"),
    Phase36Batch("36L", 12, "Universal business/institution/government sector packs", "planned"),
    Phase36Batch("36M", 13, "Unified User/Owner Creative and Project Studio", "planned"),
    Phase36Batch("36N", 14, "1000+ scale, chaos, cost, security, DR and final certification", "planned"),
)

MASTER_REPORT: Final[str] = "docs/phase-36/PHASE_36_UNIVERSAL_CAPABILITY_SCALE_MASTER_ROADMAP.md"
RECEIPT_PREFIX: Final[str] = "docs/phase-36/receipts/"
EXEMPTION_PREFIX: Final[str] = "docs/phase-36/exemptions/"

PHASE36_OWNED_PREFIXES: Final[tuple[str, ...]] = (
    "src/aios/phase36_",
    "src/aios/audio_factory.py",
    "src/aios/execution_fabric/",
    "src/aios/cluster_runtime/",
    "src/aios/multi_host_runtime/",
    "src/aios/universal_project_builder.py",
    "src/aios/controlled_project_builder.py",
    "src/aios/full_project_cycle.py",
    "src/aios/project_archetypes.py",
    "src/aios/providers/",
    "src/aios/three_d_web/",
    "web-dashboard/backend/app/services/project_execution",
    "web-dashboard/backend/app/services/audio_",
    "web-dashboard/backend/app/services/media_",
    "web-dashboard/backend/app/services/production_studio.py",
    "web-dashboard/backend/app/services/studio_worker.py",
    "web-dashboard/backend/scripts/verify_media_worker.py",
    "web-dashboard/backend/app/api/v1/endpoints/studio.py",
    "web-dashboard/backend/app/api/v1/endpoints/capabilities.py",
    "web-dashboard/frontend/src/app/studio/",
    "web-dashboard/frontend/src/app/owner/completion/",
    "vip-frontend/src/components/pages/projects-client.tsx",
    "tests/test_phase36",
    "scripts/check_phase36_reporting.py",
)


def is_phase36_owned_path(path: str) -> bool:
    normalized = path.strip().replace("\\", "/").lstrip("./")
    return any(normalized.startswith(prefix) for prefix in PHASE36_OWNED_PREFIXES)


def phase36_program_snapshot() -> dict[str, object]:
    counts = {maturity: 0 for maturity in MATURITY_ORDER}
    for capability in CAPABILITIES:
        counts[capability.maturity] += 1
    highest = MATURITY_ORDER[-1]
    production_ready = counts[highest]
    batches = []
    for batch in BATCHES:
        capabilities = [item for item in CAPABILITIES if item.owner_batch == batch.batch_id]
        batches.append({**asdict(batch), "capabilities": [asdict(item) for item in capabilities]})
    return {
        "program": "Phase 36 — Universal Capability, Creative Media & 1000+ User Scale",
        "authoritative": True,
        "minimum_concurrent_users": 1000,
        "current_batch": next((batch.batch_id for batch in BATCHES if batch.status != "complete"), None),
        "total_capabilities": len(CAPABILITIES),
        "production_ready_capabilities": production_ready,
        "completion": round(100 * production_ready / max(1, len(CAPABILITIES))),
        "maturity_order": list(MATURITY_ORDER),
        "maturity_counts": counts,
        "batches": batches,
    }


def reporting_evidence_present(paths: tuple[str, ...] | list[str]) -> bool:
    normalized = [item.strip().replace("\\", "/").lstrip("./") for item in paths]
    return any(
        item == MASTER_REPORT
        or item.startswith(RECEIPT_PREFIX)
        or item.startswith(EXEMPTION_PREFIX)
        for item in normalized
    )


def phase36_reporting_violation(paths: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    owned = tuple(sorted({path for path in paths if is_phase36_owned_path(path)}))
    if not owned or reporting_evidence_present(paths):
        return ()
    return owned
