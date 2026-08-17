"""Provider-neutral Production Studio generation and protected artifact storage.

Phase 29H deliberately generates deterministic, editable source packages without
calling an external model or media provider. Provider activation is reserved for
Phase 29J and cannot be inferred from these local artifacts.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import textwrap
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aios.design_factory import (
    BrandKit,
    DesignRequest,
    build_design_plan,
    editable_svg_template,
    prompt_pack_markdown,
)
from app.core.config import settings
from app.db.models import (
    ProjectStudioAttachment,
    StudioAsset,
    StudioAssetRevision,
    StudioJob,
    StudioSafetyReview,
)

DEPARTMENTS: tuple[dict[str, object], ...] = (
    {"id": "text", "name": "Text Studio", "asset_type": "text", "outputs": ["manuscript", "outline", "export"]},
    {"id": "website", "name": "Website Studio", "asset_type": "web", "outputs": ["HTML", "CSS", "JavaScript", "ZIP"]},
    {"id": "code", "name": "Code Studio", "asset_type": "code", "outputs": ["source", "tests", "README", "ZIP"]},
    {"id": "ui-ux", "name": "UI/UX Studio", "asset_type": "design", "outputs": ["design system", "wireframe", "prototype brief"]},
    {"id": "three-d", "name": "3D & Three.js Studio", "asset_type": "3d", "outputs": ["Three.js source", "GLTF-ready structure", "ZIP"]},
    {"id": "audio", "name": "Audio Studio", "asset_type": "audio", "outputs": ["script", "SSML", "cue sheet", "mix plan"]},
    {"id": "video", "name": "Video Studio", "asset_type": "video", "outputs": ["script", "shot list", "subtitles", "render plan"]},
    {"id": "animation", "name": "Animation Studio", "asset_type": "animation", "outputs": ["storyboard", "timing sheet", "scene plan"]},
    {"id": "advertising", "name": "Advertising Studio", "asset_type": "campaign", "outputs": ["campaign brief", "ad variants", "CTA plan"]},
    {"id": "documentary", "name": "Documentary Studio", "asset_type": "documentary", "outputs": ["research outline", "narration", "evidence checklist"]},
    {"id": "image", "name": "Image Studio", "asset_type": "image", "outputs": ["editable SVG", "prompt pack", "export guide"]},
    {"id": "branding", "name": "Branding Studio", "asset_type": "branding", "outputs": ["brand strategy", "identity tokens", "usage guide"]},
)
DEPARTMENT_IDS = frozenset(str(item["id"]) for item in DEPARTMENTS)
ASSET_TYPES = {str(item["id"]): str(item["asset_type"]) for item in DEPARTMENTS}
POLICY_VERSION = "29H.1"

# Deliberately narrow, high-confidence blockers. The local generator is not a
# general content classifier; ambiguous work remains editable and auditable.
BLOCK_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("credential_theft", "Requests to steal credentials are blocked.", re.compile(r"\b(?:steal|harvest|phish)\b.{0,80}\b(?:password|credential|login|token)\b", re.I | re.S)),
    ("malware", "Malware or ransomware production is blocked.", re.compile(r"\b(?:ransomware|credential stealer|keylogger|botnet|malware payload)\b", re.I)),
    ("child_exploitation", "Sexual exploitation of minors is blocked.", re.compile(r"\b(?:child|minor|underage)\b.{0,80}\b(?:sexual|explicit|pornographic)\b", re.I | re.S)),
    ("violent_wrongdoing", "Operational instructions for violent wrongdoing are blocked.", re.compile(r"\b(?:build|make|assemble)\b.{0,60}\b(?:bomb|explosive device|biological weapon)\b", re.I | re.S)),
)


@dataclass(frozen=True, slots=True)
class StudioSpec:
    department: str
    title: str
    brief: str
    language: str = "en-US"
    style: str = "modern"
    target: str | None = None
    programming_language: str | None = None


@dataclass(frozen=True, slots=True)
class BuiltArtifact:
    filename: str
    media_type: str
    content: bytes
    checksum: str
    size_bytes: int
    manifest: dict[str, Any]


def now() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def slug(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip()).strip("-").lower()
    return normalized[:70] or "aionex-project"


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def safety_review(spec: StudioSpec) -> dict[str, Any]:
    text = f"{spec.title}\n{spec.brief}\n{spec.target or ''}"
    findings: list[dict[str, str]] = []
    for category, message, pattern in BLOCK_PATTERNS:
        if pattern.search(text):
            findings.append({"category": category, "severity": "critical", "message": message})
    return {
        "policy_version": POLICY_VERSION,
        "status": "blocked" if findings else "passed",
        "categories": sorted({item["category"] for item in findings}),
        "findings": findings,
        "evidence": {
            "provider_neutral": True,
            "external_requests": 0,
            "input_sha256": sha256_bytes(text.encode("utf-8")),
        },
    }


def _readme(spec: StudioSpec) -> str:
    return textwrap.dedent(
        f"""\
        # {spec.title}

        Generated by AIONEX AIOS Production Studio.

        - Department: {spec.department}
        - Language: {spec.language}
        - Style: {spec.style}
        - Target: {spec.target or 'General audience'}
        - Provider mode: provider_neutral
        - External provider requests: 0
        - Generated: {now().isoformat()}

        ## Brief

        {spec.brief}

        ## Production boundary

        This package contains deterministic, editable source material. It does
        not claim that a paid image, audio, video, voice, hosting, or model
        provider rendered an external artifact. Provider activation is reserved
        for Phase 29J and requires explicit governance and credentials.
        """
    )


def _text_files(spec: StudioSpec) -> dict[str, str]:
    outline = [
        "Purpose and audience",
        "Opening context",
        "Core argument or narrative",
        "Evidence and examples",
        "Conclusion and next action",
    ]
    manuscript = [f"# {spec.title}", "", spec.brief, ""]
    for index, heading in enumerate(outline, 1):
        manuscript.extend([f"## {index}. {heading}", "", "[Develop this section with verified project evidence.]", ""])
    return {
        "manuscript.md": "\n".join(manuscript),
        "outline.json": json.dumps({"title": spec.title, "sections": outline, "language": spec.language}, ensure_ascii=False, indent=2),
        "plain-text.txt": f"{spec.title}\n\n{spec.brief}\n",
    }


def _website_files(spec: StudioSpec) -> dict[str, str]:
    safe_title = spec.title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    safe_brief = spec.brief.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html = f"""<!doctype html>
<html lang="{spec.language}">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{safe_title}</title><link rel="stylesheet" href="styles.css"></head>
<body><main class="hero"><span class="eyebrow">AIONEX AIOS · Website Studio</span><h1>{safe_title}</h1><p>{safe_brief}</p><button id="action">Explore project</button></main><script src="app.js"></script></body>
</html>
"""
    css = ":root{font-family:Inter,system-ui,sans-serif;color-scheme:dark}*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(circle at 20% 20%,#1d4ed8 0,transparent 35%),#050816;color:#fff}.hero{min-height:100vh;display:grid;place-content:center;gap:1.25rem;padding:8vw;max-width:1100px}.eyebrow{letter-spacing:.18em;text-transform:uppercase;opacity:.65}h1{font-size:clamp(3rem,8vw,7rem);line-height:.95;margin:0}p{font-size:clamp(1rem,2vw,1.35rem);line-height:1.7;max-width:760px;opacity:.78}button{width:max-content;border:0;border-radius:999px;padding:1rem 1.5rem;font-weight:700;cursor:pointer}\n"
    js = "document.querySelector('#action')?.addEventListener('click',()=>alert('AIONEX AIOS project is ready for customization.'));\n"
    return {"index.html": html, "styles.css": css, "app.js": js}


def _three_files(spec: StudioSpec) -> dict[str, str]:
    html = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0;background:#030712;color:#fff;font:16px system-ui}canvas{display:block;width:100vw;height:100vh}#label{position:fixed;z-index:2;padding:20px}</style></head><body><div id="label"></div><canvas id="scene"></canvas><script type="module" src="scene.js"></script></body></html>"""
    scene = f"""import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.169.0/build/three.module.js';
const canvas=document.querySelector('#scene');
const renderer=new THREE.WebGLRenderer({{canvas,antialias:true}});
const scene=new THREE.Scene(); const camera=new THREE.PerspectiveCamera(60,1,.1,100);
const object=new THREE.Mesh(new THREE.TorusKnotGeometry(1,.32,160,24),new THREE.MeshStandardMaterial({{color:0x38bdf8,metalness:.65,roughness:.2}}));
scene.add(object); scene.add(new THREE.HemisphereLight(0xffffff,0x111827,2.4)); camera.position.z=4;
document.querySelector('#label').textContent={json.dumps(spec.title)};
function resize(){{const w=innerWidth,h=innerHeight;renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix()}}
function frame(){{resize();object.rotation.x+=.004;object.rotation.y+=.008;renderer.render(scene,camera);requestAnimationFrame(frame)}}frame();
"""
    package = {"name": slug(spec.title), "private": True, "version": "1.0.0", "type": "module", "scripts": {"dev": "vite", "build": "vite build"}, "dependencies": {"three": "0.169.0"}, "devDependencies": {"vite": "6.1.0"}}
    return {"index.html": html, "scene.js": scene, "package.json": json.dumps(package, indent=2), "assets/README.md": "Place GLB/GLTF, textures and HDR environments in this directory.\n"}


def _audio_files(spec: StudioSpec) -> dict[str, str]:
    ssml = f"""<speak xml:lang="{spec.language}"><prosody rate="medium" pitch="medium">{spec.brief}</prosody></speak>"""
    cues = [
        {"cue": 1, "time": "00:00", "role": "intro", "direction": "Establish tone and identity"},
        {"cue": 2, "time": "00:08", "role": "narration", "direction": spec.brief[:240]},
        {"cue": 3, "time": "00:35", "role": "transition", "direction": "Short musical transition"},
        {"cue": 4, "time": "00:42", "role": "close", "direction": "Resolve and state next action"},
    ]
    return {
        "audio/narration.txt": spec.brief + "\n",
        "audio/narration.ssml": ssml,
        "audio/cue-sheet.json": json.dumps(cues, ensure_ascii=False, indent=2),
        "audio/mix-notes.md": f"# Mix notes\n\nStyle: {spec.style}\nTarget: {spec.target or 'general'}\n\nNo synthetic voice or music file is claimed without a configured provider.\n",
    }


def _video_files(spec: StudioSpec) -> dict[str, str]:
    shots = [
        {"shot": 1, "duration_seconds": 4, "visual": "Opening establishing shot", "audio": "Music rise"},
        {"shot": 2, "duration_seconds": 7, "visual": spec.brief[:240], "audio": "Primary narration"},
        {"shot": 3, "duration_seconds": 6, "visual": "Detail and proof sequence", "audio": "Narration with natural sound"},
        {"shot": 4, "duration_seconds": 5, "visual": "Resolution and call to action", "audio": "Music resolve"},
    ]
    srt = """1
00:00:00,000 --> 00:00:04,000
A new story begins.

2
00:00:04,000 --> 00:00:11,000
The central idea is introduced with clarity and purpose.

3
00:00:11,000 --> 00:00:17,000
Evidence, detail and human context build trust.

4
00:00:17,000 --> 00:00:22,000
The story closes with a memorable next step.
"""
    render = "#!/usr/bin/env bash\nset -euo pipefail\n# Replace shot files with approved generated or filmed media.\nffmpeg -f concat -safe 0 -i inputs.txt -vf subtitles=subtitles.srt -c:v libx264 -c:a aac -movflags +faststart final.mp4\n"
    return {
        "production/shot-list.json": json.dumps(shots, ensure_ascii=False, indent=2),
        "production/subtitles.srt": srt,
        "production/render.sh": render,
        "production/inputs.txt": "file 'shot-01.mp4'\nfile 'shot-02.mp4'\nfile 'shot-03.mp4'\nfile 'shot-04.mp4'\n",
        "production/provider-prompts.md": f"# Provider prompts\n\nStyle: {spec.style}\n\nAudience: {spec.target or 'general'}\n\nBrief: {spec.brief}\n",
    }


def _image_files(spec: StudioSpec) -> dict[str, str]:
    request = DesignRequest(
        title=spec.title,
        brief=spec.brief,
        use_case="experimental-graphic",
        preset_id="visual-landscape",
        style=spec.style,
        language=spec.language,
        target_audience=spec.target or "general",
        brand=BrandKit(spec.title[:120]),
    )
    plan = build_design_plan(request)
    return {
        "visual.svg": editable_svg_template(plan),
        "design-plan.json": json.dumps(plan.public_snapshot(), ensure_ascii=False, indent=2),
        "prompt-pack.md": prompt_pack_markdown(plan),
        "export-presets.json": json.dumps(
            {
                "editable": plan.editable_source,
                "raster": list(plan.raster_exports),
                "width": plan.preset.width,
                "height": plan.preset.height,
                "render_status": plan.render_status,
            },
            indent=2,
        ),
    }


def _strategy_files(spec: StudioSpec) -> dict[str, str]:
    sections = {
        "ui-ux": ["User problem", "Personas", "Information architecture", "Wireframes", "Design tokens", "Accessibility", "Usability tests"],
        "animation": ["Concept", "Characters", "Storyboard", "Timing", "Key poses", "Transitions", "Sound design"],
        "advertising": ["Product truth", "Audience", "Campaign promise", "Hooks", "Formats", "Calls to action", "Measurement"],
        "documentary": ["Central question", "Research sources", "Interview plan", "Narrative arc", "Fact checking", "Rights and releases", "Distribution"],
        "branding": ["Purpose", "Positioning", "Audience", "Voice", "Visual system", "Logo usage", "Launch plan"],
    }[spec.department]
    content = [f"# {spec.title}", "", f"Brief: {spec.brief}", "", f"Style: {spec.style}", ""]
    for index, section in enumerate(sections, start=1):
        content.extend([f"## {index}. {section}", "", "- Decision:", "- Evidence:", "- Deliverable:", ""])
    return {"production-plan.md": "\n".join(content)}


def _code_files(spec: StudioSpec) -> dict[str, str]:
    language = (spec.programming_language or "python").lower()
    if language in {"javascript", "typescript"}:
        extension = "ts" if language == "typescript" else "js"
        code = f"export function projectSummary() {{ return {json.dumps(spec.brief)}; }}\nconsole.log(projectSummary());\n"
        test = "import { projectSummary } from '../src/index';\nif (!projectSummary()) throw new Error('summary missing');\n"
        return {f"src/index.{extension}": code, f"tests/basic.{extension}": test, "package.json": json.dumps({"name": slug(spec.title), "version": "1.0.0", "private": True, "scripts": {"test": f"node tests/basic.{extension}"}}, indent=2)}
    code = f'''"""{spec.title}."""\n\ndef project_summary() -> str:\n    return {spec.brief!r}\n\nif __name__ == "__main__":\n    print(project_summary())\n'''
    test = "from src.main import project_summary\n\ndef test_project_summary():\n    assert project_summary().strip()\n"
    return {"src/main.py": code, "tests/test_main.py": test, "requirements.txt": "pytest==8.3.5\n"}


def department_files(spec: StudioSpec) -> dict[str, str]:
    if spec.department == "text":
        return _text_files(spec)
    if spec.department == "website":
        return _website_files(spec)
    if spec.department == "code":
        return _code_files(spec)
    if spec.department == "three-d":
        return _three_files(spec)
    if spec.department == "audio":
        return _audio_files(spec)
    if spec.department == "video":
        return _video_files(spec)
    if spec.department == "image":
        return _image_files(spec)
    return _strategy_files(spec)


def build_archive(spec: StudioSpec, *, job_id: str, revision_number: int) -> BuiltArtifact:
    if spec.department not in DEPARTMENT_IDS:
        raise ValueError("Unsupported studio department")
    review = safety_review(spec)
    if review["status"] != "passed":
        raise PermissionError("Studio safety review blocked this request")
    files = {"README.md": _readme(spec), **department_files(spec)}
    file_checksums = {path: sha256_bytes(content.encode("utf-8")) for path, content in files.items()}
    manifest = {
        "schema": "aionex.production-asset.v2",
        "job_id": job_id,
        "revision": revision_number,
        "department": spec.department,
        "asset_type": ASSET_TYPES[spec.department],
        "title": spec.title,
        "language": spec.language,
        "style": spec.style,
        "provider_mode": "provider_neutral",
        "provider": None,
        "model": None,
        "external_requests": 0,
        "external_tokens": 0,
        "external_cost_usd": 0,
        "safety": review,
        "created_at": now().isoformat(),
        "files": [{"path": path, "sha256": file_checksums[path], "size_bytes": len(files[path].encode('utf-8'))} for path in sorted(files)],
    }
    files["aionex-manifest.json"] = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(files):
            info = zipfile.ZipInfo(path, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            bundle.writestr(info, files[path])
    content = archive.getvalue()
    if len(content) > settings.STUDIO_MAX_ARTIFACT_BYTES:
        raise ValueError("Studio artifact exceeds the configured size limit")
    filename = f"{slug(spec.title)}-{spec.department}-r{revision_number}.zip"
    return BuiltArtifact(filename, "application/zip", content, sha256_bytes(content), len(content), manifest)


def protected_root() -> Path:
    root = Path(settings.STUDIO_ASSET_ROOT).resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass
    return root


def store_artifact(*, organization_id: str, asset_id: str, revision_number: int, artifact: BuiltArtifact) -> Path:
    root = protected_root()
    directory = (root / organization_id / asset_id / f"revision-{revision_number}").resolve()
    if root not in directory.parents:
        raise ValueError("Invalid Studio storage path")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / artifact.filename
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_bytes(artifact.content)
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    return path


def verify_artifact(path: str, checksum: str, size_bytes: int) -> Path:
    root = protected_root()
    candidate = Path(path).resolve()
    if root not in candidate.parents or not candidate.is_file():
        raise FileNotFoundError("Studio artifact is unavailable")
    stat = candidate.stat()
    if stat.st_size != size_bytes:
        raise ValueError("Studio artifact size verification failed")
    digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
    if digest != checksum:
        raise ValueError("Studio artifact checksum verification failed")
    return candidate


def job_snapshot(item: StudioJob) -> dict[str, Any]:
    return {
        "id": item.id,
        "organization_id": item.organization_id,
        "workspace_id": item.workspace_id,
        "project_id": item.project_id,
        "requested_by_id": item.requested_by_id,
        "revision_of_asset_id": item.revision_of_asset_id,
        "department": item.department,
        "output_kind": item.output_kind,
        "title": item.title,
        "brief": item.brief,
        "language": item.language,
        "style": item.style,
        "target": item.target,
        "programming_language": item.programming_language,
        "change_note": item.change_note,
        "provider_mode": item.provider_mode,
        "provider": item.provider,
        "model": item.model,
        "status": item.status,
        "progress": item.progress,
        "safety_status": item.safety_status,
        "safety_findings": item.safety_findings,
        "request_metadata": item.request_metadata,
        "result_metadata": item.result_metadata,
        "error_code": item.error_code,
        "error_message": item.error_message,
        "attempts": item.attempts,
        "max_attempts": item.max_attempts,
        "version": item.version,
        "started_at": iso(item.started_at),
        "completed_at": iso(item.completed_at),
        "cancelled_at": iso(item.cancelled_at),
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
    }


def asset_snapshot(item: StudioAsset, *, attached_projects: list[str] | None = None) -> dict[str, Any]:
    return {
        "id": item.id,
        "organization_id": item.organization_id,
        "job_id": item.job_id,
        "project_id": item.project_id,
        "created_by_id": item.created_by_id,
        "department": item.department,
        "asset_type": item.asset_type,
        "title": item.title,
        "filename": item.filename,
        "media_type": item.media_type,
        "checksum": item.checksum,
        "size_bytes": item.size_bytes,
        "status": item.status,
        "current_revision": item.current_revision,
        "metadata": item.asset_metadata,
        "attached_project_ids": attached_projects or [],
        "archived_at": iso(item.archived_at),
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
    }


def revision_snapshot(item: StudioAssetRevision) -> dict[str, Any]:
    return {
        "id": item.id,
        "asset_id": item.asset_id,
        "job_id": item.job_id,
        "created_by_id": item.created_by_id,
        "revision_number": item.revision_number,
        "filename": item.filename,
        "media_type": item.media_type,
        "checksum": item.checksum,
        "size_bytes": item.size_bytes,
        "change_note": item.change_note,
        "metadata": item.revision_metadata,
        "status": item.status,
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
    }


def safety_snapshot(item: StudioSafetyReview) -> dict[str, Any]:
    return {
        "id": item.id,
        "job_id": item.job_id,
        "asset_id": item.asset_id,
        "reviewer_id": item.reviewer_id,
        "policy_version": item.policy_version,
        "status": item.status,
        "categories": item.categories,
        "findings": item.findings,
        "evidence": item.evidence,
        "reviewed_at": iso(item.reviewed_at),
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
    }


def attachment_snapshot(item: ProjectStudioAttachment) -> dict[str, Any]:
    return {
        "id": item.id,
        "project_id": item.project_id,
        "asset_id": item.asset_id,
        "attached_by_id": item.attached_by_id,
        "status": item.status,
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
    }
