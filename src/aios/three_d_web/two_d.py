"""Deterministic Phase 36I 2D animation/game project runtime.

The builder is local-only: it emits self-contained HTML/JavaScript plus a
checksum-addressed manifest.  It never contacts a provider and never writes
outside the caller supplied project directory.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Final

from .expansion import InteractiveTarget

_SAFE_ID: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


class TwoDProjectError(ValueError):
    """A 2D project request violates a deterministic production boundary."""


@dataclass(frozen=True, slots=True)
class TwoDArtifact:
    path: str
    bytes: int
    sha256: str
    media_type: str


@dataclass(frozen=True, slots=True)
class TwoDProjectManifest:
    version: int
    project_id: str
    organization_fingerprint: str
    target: str
    template: str
    artifacts: tuple[TwoDArtifact, ...]
    aggregate_sha256: str
    provider_requests: int = 0
    external_spend_usd: float = 0.0

    def snapshot(self) -> dict[str, object]:
        return {
            **asdict(self),
            "artifacts": [asdict(item) for item in self.artifacts],
            "runtime_executed": False,
        }


class TwoDProjectBuilder:
    """Materialize governed 2D animation/game templates under one project root."""

    def build(
        self,
        *,
        organization_id: str,
        project_id: str,
        target: InteractiveTarget,
        destination: Path,
    ) -> TwoDProjectManifest:
        if target not in {InteractiveTarget.TWO_D_ANIMATION, InteractiveTarget.TWO_D_GAME}:
            raise TwoDProjectError("2D builder only accepts animation or game targets")
        if not _SAFE_ID.fullmatch(project_id):
            raise TwoDProjectError("project id contains unsafe characters")
        if not organization_id.strip():
            raise TwoDProjectError("organization id is required")
        root = destination.resolve()
        root.mkdir(parents=True, exist_ok=True)
        if any(root.iterdir()):
            raise TwoDProjectError("destination must be empty")

        template = "canvas-timeline-animation" if target == InteractiveTarget.TWO_D_ANIMATION else "canvas-game-loop"
        files = self._animation_files(project_id) if target == InteractiveTarget.TWO_D_ANIMATION else self._game_files(project_id)
        artifacts: list[TwoDArtifact] = []
        for relative, (content, media_type) in sorted(files.items()):
            path = self._resolve(root, relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = content.encode("utf-8")
            path.write_bytes(raw)
            artifacts.append(TwoDArtifact(relative, len(raw), sha256(raw).hexdigest(), media_type))

        canonical = json.dumps([asdict(item) for item in artifacts], sort_keys=True, separators=(",", ":")).encode()
        manifest = TwoDProjectManifest(
            version=1,
            project_id=project_id,
            organization_fingerprint=sha256(organization_id.encode()).hexdigest(),
            target=target.value,
            template=template,
            artifacts=tuple(artifacts),
            aggregate_sha256=sha256(canonical).hexdigest(),
        )
        manifest_path = self._resolve(root, "artifact-manifest.json")
        manifest_path.write_text(json.dumps(manifest.snapshot(), sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return manifest

    def verify(self, manifest: TwoDProjectManifest, destination: Path) -> tuple[str, ...]:
        root = destination.resolve()
        failures: list[str] = []
        for item in manifest.artifacts:
            try:
                raw = self._resolve(root, item.path).read_bytes()
            except (FileNotFoundError, TwoDProjectError):
                failures.append(item.path)
                continue
            if len(raw) != item.bytes or sha256(raw).hexdigest() != item.sha256:
                failures.append(item.path)
        return tuple(failures)

    @staticmethod
    def _resolve(root: Path, relative: str) -> Path:
        if not relative or relative.startswith(("/", "\\")):
            raise TwoDProjectError("artifact path must be relative")
        candidate = (root / relative).resolve()
        if candidate != root and root not in candidate.parents:
            raise TwoDProjectError("artifact path escapes project root")
        return candidate

    @staticmethod
    def _shell(title: str, body: str, script: str) -> str:
        return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>html,body{{margin:0;background:#111;color:#fff;font-family:system-ui}}main{{display:grid;place-items:center;min-height:100vh}}canvas{{max-width:96vw;border:1px solid #555}}</style></head>
<body><main>{body}</main><script src="{script}"></script></body></html>\n'''

    @classmethod
    def _animation_files(cls, project_id: str) -> dict[str, tuple[str, str]]:
        html = cls._shell(f"AIOS 2D Animation {project_id}", '<canvas id="stage" width="640" height="360" aria-label="2D animation stage"></canvas>', "animation.js")
        js = '''"use strict";
const canvas=document.getElementById("stage"),ctx=canvas.getContext("2d");
let frame=0,x=40; window.__AIOS_EVIDENCE__={kind:"2d-animation",ready:false,frames:0,x};
function draw(){ctx.clearRect(0,0,640,360);ctx.fillStyle="#20242a";ctx.fillRect(0,0,640,360);ctx.fillStyle="#f5f5f5";ctx.fillRect(x,150,48,48);frame++;x=40+(frame%180)*3;window.__AIOS_EVIDENCE__={kind:"2d-animation",ready:true,frames:frame,x};if(frame<240)requestAnimationFrame(draw)}
requestAnimationFrame(draw);\n'''
        return {"index.html": (html, "text/html"), "animation.js": (js, "text/javascript")}

    @classmethod
    def _game_files(cls, project_id: str) -> dict[str, tuple[str, str]]:
        html = cls._shell(f"AIOS 2D Game {project_id}", '<canvas id="game" width="640" height="360" tabindex="0" aria-label="2D game stage"></canvas>', "game.js")
        js = '''"use strict";
const canvas=document.getElementById("game"),ctx=canvas.getContext("2d");let x=80,y=280,score=0,frames=0;
window.__AIOS_EVIDENCE__={kind:"2d-game",ready:false,frames,x,y,score};
addEventListener("keydown",e=>{if(e.key==="ArrowRight")x=Math.min(600,x+12);if(e.key==="ArrowLeft")x=Math.max(0,x-12);if(e.key===" "){score++;e.preventDefault()}});
function loop(){ctx.clearRect(0,0,640,360);ctx.fillStyle="#18222d";ctx.fillRect(0,0,640,360);ctx.fillStyle="#58d68d";ctx.fillRect(x,y,32,32);ctx.fillStyle="#fff";ctx.fillText(`score:${score}`,16,24);frames++;window.__AIOS_EVIDENCE__={kind:"2d-game",ready:true,frames,x,y,score};if(frames<300)requestAnimationFrame(loop)}
canvas.focus();requestAnimationFrame(loop);\n'''
        manifest = json.dumps({"schema": 1, "controls": ["ArrowLeft", "ArrowRight", "Space"], "offline": True}, sort_keys=True) + "\n"
        return {"index.html": (html, "text/html"), "game.js": (js, "text/javascript"), "game-manifest.json": (manifest, "application/json")}
