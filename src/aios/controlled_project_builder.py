from __future__ import annotations

import asyncio
import hashlib
import html
import importlib.util
import json
import os
import re
import shutil
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .cloud_provider_sandbox import OpenAIOfficialHTTPTransport
from .providers import DataSensitivity, ModelCapability, ModelRequest
from .providers.adapters import OpenAIProvider


_EXECUTION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_FORBIDDEN_TEXT = re.compile(
    r"(?i)(?:https?://|javascript:|data:text/html|<script|</script|api[_-]?key\s*[=:]|password\s*[=:]|bearer\s+)"
)
StageCallback = Callable[[str, int], None]


class ControlledProjectBuildError(ValueError):
    """A provider specification or generated prototype violated the build contract."""


@dataclass(frozen=True, slots=True)
class ControlledProjectBuildResult:
    execution_id: str
    output_directory: Path
    manifest_path: Path
    report_path: Path
    archive_path: Path
    input_tokens: int
    output_tokens: int
    total_tokens: int
    calculated_cost: float
    total_duration: float
    tests_passed: bool
    rollback_tested: bool


class _PrototypeHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.scripts: list[dict[str, str | None]] = []
        self.stylesheets: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(str(values["id"]))
        if tag == "script":
            self.scripts.append(values)
        if tag == "link" and values.get("rel") == "stylesheet":
            self.stylesheets.append(str(values.get("href") or ""))


class ControlledProjectBuilder:
    """Generate one executable, network-isolated prototype from a validated spec.

    The cloud model supplies product copy and structure only. Executable source is
    emitted from reviewed deterministic templates, preventing model output from
    becoming arbitrary code.
    """

    MAX_OUTPUT_TOKENS = 1200
    MAX_INPUT_TOKENS = 4096
    REQUIRED_SECTIONS = ("overview", "workflow", "evidence")

    def __init__(
        self,
        transport: OpenAIOfficialHTTPTransport,
        *,
        model: str,
        input_cost_per_million: float,
        output_cost_per_million: float,
        remaining_budget_usd: float,
    ) -> None:
        if remaining_budget_usd <= 0:
            raise ControlledProjectBuildError("implementation budget is exhausted")
        self.transport = transport
        self.model = model
        self.input_cost_per_million = float(input_cost_per_million)
        self.output_cost_per_million = float(output_cost_per_million)
        self.remaining_budget_usd = float(remaining_budget_usd)
        worst_case = (
            self.MAX_INPUT_TOKENS * self.input_cost_per_million
            + self.MAX_OUTPUT_TOKENS * self.output_cost_per_million
        ) / 1_000_000
        if worst_case > self.remaining_budget_usd + 1e-12:
            raise ControlledProjectBuildError(
                "one worst-case implementation request exceeds the remaining budget"
            )
        capability = ModelCapability(
            provider="openai",
            model=model,
            tasks=frozenset({"coding", "reasoning"}),
            languages=frozenset({"ar", "en", "multilingual"}),
            supports_tools=False,
            local=False,
            max_context_tokens=self.MAX_INPUT_TOKENS,
            quality_score=0.9,
            latency_score=0.8,
            privacy_score=0.45,
            input_cost_per_million=self.input_cost_per_million,
            output_cost_per_million=self.output_cost_per_million,
        )
        self.provider = OpenAIProvider((capability,), raw_transport=transport)

    def execute(
        self,
        *,
        execution_id: str,
        project: str,
        objective: str,
        planning_directory: str | Path,
        output_root: str | Path,
        stage_callback: StageCallback | None = None,
    ) -> ControlledProjectBuildResult:
        safe_id = self._validate_execution_id(execution_id)
        selected_project = project.strip()
        selected_objective = objective.strip()
        if len(selected_project) < 2 or len(selected_objective) < 10:
            raise ControlledProjectBuildError("project and objective are required")
        root = self._prepare_root(output_root)
        destination = self._contained(root, root / safe_id)
        staging = self._contained(root, root / f".staging-{safe_id}")
        if destination.exists() or staging.exists():
            raise FileExistsError(f"controlled implementation already exists: {safe_id}")
        planning = Path(planning_directory).resolve(strict=True)
        planning_summary = self._planning_summary(planning)

        def stage(name: str, progress: int) -> None:
            if stage_callback is not None:
                stage_callback(name, progress)

        staging.mkdir(mode=0o700)
        started = time.monotonic()
        try:
            stage("implementation_specification", 62)
            response = asyncio.run(
                self.provider.generate(
                    ModelRequest(
                        task="coding",
                        prompt=self._prompt(
                            selected_project, selected_objective, planning_summary
                        ),
                        system_prompt=self._system_prompt(),
                        language="en",
                        sensitivity=DataSensitivity.INTERNAL,
                        max_cost=self.remaining_budget_usd,
                        max_tokens=self.MAX_OUTPUT_TOKENS,
                        temperature=0.0,
                        require_local=False,
                        metadata={
                            "tools": [],
                            "response_format": {
                                "type": "json_schema",
                                "json_schema": {
                                    "name": "aionex_controlled_prototype_spec",
                                    "strict": True,
                                    "schema": self._schema(),
                                },
                            },
                        },
                    ),
                    self.model,
                )
            )
            calculated_cost = float(response.cost or 0.0)
            if calculated_cost > self.remaining_budget_usd + 1e-12:
                raise ControlledProjectBuildError(
                    "implementation response exceeded the remaining budget"
                )
            spec = self._validate_spec(response.text)

            stage("implementation_generation", 68)
            source = staging / "source"
            source.mkdir(mode=0o700)
            files = self._render_files(
                selected_project,
                selected_objective,
                spec,
                planning_summary,
            )
            for relative, content in files.items():
                path = self._contained(source, source / relative)
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                self._atomic_write_text(path, content)

            stage("implementation_tests", 72)
            test_report = self._test_source(source, selected_project)
            self._atomic_write_text(
                staging / "TEST_REPORT.json", self._canonical_json(test_report)
            )
            if not test_report["passed"]:
                raise ControlledProjectBuildError(
                    "deterministic implementation tests failed"
                )

            hashes = {
                str(path.relative_to(source)): self._sha256(path)
                for path in sorted(source.rglob("*"))
                if path.is_file()
            }
            manifest = {
                "schema_version": 1,
                "mode": "controlled-full-stack-prototype",
                "execution_id": safe_id,
                "project": selected_project,
                "objective": selected_objective,
                "provider": "openai",
                "model": self.model,
                "provider_role": "structured product specification only",
                "executable_source_origin": "deterministic reviewed templates",
                "files": hashes,
                "specification": spec,
                "planning": planning_summary,
                "tests": test_report,
                "requests_count": 1,
                "input_tokens": int(response.input_tokens or 0),
                "output_tokens": int(response.output_tokens or 0),
                "total_tokens": int(
                    (response.metadata or {}).get(
                        "total_tokens",
                        int(response.input_tokens or 0)
                        + int(response.output_tokens or 0),
                    )
                ),
                "calculated_cost": calculated_cost,
                "budget_remaining_before_request": self.remaining_budget_usd,
                "fallback_used": False,
                "production_modified": False,
                "raw_prompt_stored": False,
                "raw_response_stored": False,
                "authorization_header_stored": False,
            }
            self._atomic_write_text(
                staging / "manifest.json", self._canonical_json(manifest)
            )
            self._atomic_write_text(staging / "REPORT.md", self._report(manifest))

            archive = staging / "project-prototype.zip"
            self._write_archive(archive, source)
            stage("rollback_verification", 76)
            rollback_tested = self._verify_archive(archive, hashes, staging)
            if not rollback_tested:
                raise ControlledProjectBuildError(
                    "implementation rollback archive verification failed"
                )
            manifest["rollback_tested"] = True
            manifest["archive_sha256"] = self._sha256(archive)
            manifest["total_duration"] = round(time.monotonic() - started, 6)
            self._atomic_write_text(
                staging / "manifest.json", self._canonical_json(manifest)
            )
            self._atomic_write_text(staging / "REPORT.md", self._report(manifest))
            os.replace(staging, destination)
            return ControlledProjectBuildResult(
                execution_id=safe_id,
                output_directory=destination,
                manifest_path=destination / "manifest.json",
                report_path=destination / "REPORT.md",
                archive_path=destination / "project-prototype.zip",
                input_tokens=int(response.input_tokens or 0),
                output_tokens=int(response.output_tokens or 0),
                total_tokens=int(manifest["total_tokens"]),
                calculated_cost=calculated_cost,
                total_duration=float(manifest["total_duration"]),
                tests_passed=True,
                rollback_tested=True,
            )
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    @classmethod
    def load_result(cls, directory: str | Path) -> ControlledProjectBuildResult:
        root = Path(directory).resolve(strict=True)
        manifest_path = root / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            manifest.get("mode") != "controlled-full-stack-prototype"
            or manifest.get("tests", {}).get("passed") is not True
            or manifest.get("rollback_tested") is not True
        ):
            raise ControlledProjectBuildError(
                "existing controlled implementation is incomplete"
            )
        return ControlledProjectBuildResult(
            execution_id=str(manifest["execution_id"]),
            output_directory=root,
            manifest_path=manifest_path,
            report_path=root / "REPORT.md",
            archive_path=root / "project-prototype.zip",
            input_tokens=int(manifest.get("input_tokens") or 0),
            output_tokens=int(manifest.get("output_tokens") or 0),
            total_tokens=int(manifest.get("total_tokens") or 0),
            calculated_cost=float(manifest.get("calculated_cost") or 0.0),
            total_duration=float(manifest.get("total_duration") or 0.0),
            tests_passed=True,
            rollback_tested=True,
        )

    @classmethod
    def _planning_summary(cls, directory: Path) -> dict[str, Any]:
        manifest_path = directory / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ControlledProjectBuildError("planning manifest is invalid") from exc
        records = manifest.get("artifacts")
        if (
            manifest.get("provider") != "openai"
            or manifest.get("fallback_used") is not False
            or not isinstance(records, list)
            or len(records) != 6
        ):
            raise ControlledProjectBuildError(
                "implementation requires six-department OpenAI planning evidence"
            )
        departments: list[dict[str, Any]] = []
        for record in records:
            relative = Path(str(record.get("path") or ""))
            path = cls._contained(directory, directory / relative)
            if not path.is_file() or path.is_symlink():
                raise ControlledProjectBuildError("planning artifact is missing")
            if cls._sha256(path) != str(record.get("sha256") or ""):
                raise ControlledProjectBuildError("planning artifact hash mismatch")
            payload = json.loads(path.read_text(encoding="utf-8"))
            output = payload.get("model_output") or {}
            departments.append(
                {
                    "department": payload.get("department"),
                    "summary": str(output.get("summary") or "")[:500],
                    "implementation_plan": [
                        str(item)[:300]
                        for item in (output.get("implementation_plan") or [])[:4]
                    ],
                    "risks": [
                        str(item.get("risk") or "")[:240]
                        for item in (output.get("risks") or [])[:3]
                        if isinstance(item, Mapping)
                    ],
                }
            )
        return {
            "manifest_sha256": cls._sha256(manifest_path),
            "provider": "openai",
            "model": manifest.get("model"),
            "departments": departments,
        }

    @classmethod
    def _prompt(
        cls, project: str, objective: str, planning_summary: Mapping[str, Any]
    ) -> str:
        compact = json.dumps(
            planning_summary["departments"], ensure_ascii=False, separators=(",", ":")
        )
        return (
            f"Project: {project}\nObjective: {objective}\n"
            "Create a concise product specification for a functional, self-contained "
            "web prototype generated by deterministic AIOS templates. The prototype "
            "must explain the value, workflow, governance evidence and next actions. "
            "Do not write code, HTML, URLs, credentials, deployment claims, test claims, "
            "or keys. Use plain text only and return exactly the JSON schema.\n"
            f"Department planning summaries: {compact}"
        )

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You are the controlled implementation specification cell of AIONEX AIOS. "
            "Return only truthful structured product copy. Never claim deployment, "
            "completed business integrations, executed tests, external research, or "
            "security certification. Never include code, markup, URLs, or secrets."
        )

    @classmethod
    def _schema(cls) -> dict[str, Any]:
        section = {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "title", "body", "items"],
            "properties": {
                "id": {"type": "string", "enum": list(cls.REQUIRED_SECTIONS)},
                "title": {"type": "string"},
                "body": {"type": "string"},
                "items": {"type": "array", "items": {"type": "string"}},
            },
        }
        return {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "schema_version",
                "title",
                "tagline",
                "summary",
                "audience",
                "features",
                "sections",
                "primary_action",
                "secondary_action",
                "limitations",
            ],
            "properties": {
                "schema_version": {"type": "integer", "enum": [1]},
                "title": {"type": "string"},
                "tagline": {"type": "string"},
                "summary": {"type": "string"},
                "audience": {"type": "string"},
                "features": {"type": "array", "items": {"type": "string"}},
                "sections": {"type": "array", "items": section},
                "primary_action": {"type": "string"},
                "secondary_action": {"type": "string"},
                "limitations": {"type": "array", "items": {"type": "string"}},
            },
        }

    @classmethod
    def _validate_spec(cls, text: str) -> dict[str, Any]:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ControlledProjectBuildError(
                "implementation specification is not valid JSON"
            ) from exc
        required = set(cls._schema()["required"])
        if not isinstance(payload, dict) or set(payload) != required:
            raise ControlledProjectBuildError(
                "implementation specification keys are invalid"
            )
        if payload["schema_version"] != 1:
            raise ControlledProjectBuildError(
                "implementation specification version is invalid"
            )
        scalar_limits = {
            "title": (2, 100),
            "tagline": (5, 180),
            "summary": (20, 800),
            "audience": (2, 200),
            "primary_action": (2, 80),
            "secondary_action": (2, 80),
        }
        for name, (minimum, maximum) in scalar_limits.items():
            cls._validate_text(payload[name], name, minimum, maximum)
        features = payload["features"]
        limitations = payload["limitations"]
        if not isinstance(features, list) or not 3 <= len(features) <= 8:
            raise ControlledProjectBuildError("features must contain three to eight items")
        if not isinstance(limitations, list) or not 1 <= len(limitations) <= 6:
            raise ControlledProjectBuildError("limitations must contain one to six items")
        for index, value in enumerate(features):
            cls._validate_text(value, f"features[{index}]", 3, 180)
        for index, value in enumerate(limitations):
            cls._validate_text(value, f"limitations[{index}]", 3, 220)
        sections = payload["sections"]
        if not isinstance(sections, list) or len(sections) != 3:
            raise ControlledProjectBuildError("exactly three sections are required")
        ids = []
        for index, section in enumerate(sections):
            if not isinstance(section, dict) or set(section) != {
                "id",
                "title",
                "body",
                "items",
            }:
                raise ControlledProjectBuildError("section schema is invalid")
            ids.append(section["id"])
            cls._validate_text(section["title"], f"section[{index}].title", 2, 100)
            cls._validate_text(section["body"], f"section[{index}].body", 10, 500)
            items = section["items"]
            if not isinstance(items, list) or not 2 <= len(items) <= 6:
                raise ControlledProjectBuildError(
                    "each section must contain two to six items"
                )
            for item_index, value in enumerate(items):
                cls._validate_text(
                    value, f"section[{index}].items[{item_index}]", 3, 180
                )
        if tuple(ids) != cls.REQUIRED_SECTIONS:
            raise ControlledProjectBuildError(
                "sections must be ordered as overview, workflow, evidence"
            )
        return payload

    @staticmethod
    def _validate_text(value: Any, name: str, minimum: int, maximum: int) -> None:
        if not isinstance(value, str):
            raise ControlledProjectBuildError(f"{name} must be text")
        normalized = value.strip()
        if not minimum <= len(normalized) <= maximum:
            raise ControlledProjectBuildError(f"{name} length is invalid")
        if _FORBIDDEN_TEXT.search(normalized) or "<" in normalized or ">" in normalized:
            raise ControlledProjectBuildError(f"{name} contains forbidden content")

    @classmethod
    def _render_files(
        cls,
        project: str,
        objective: str,
        spec: Mapping[str, Any],
        planning: Mapping[str, Any],
    ) -> dict[str, str]:
        safe_json = json.dumps(spec, ensure_ascii=False).replace("<", "\\u003c").replace(
            ">", "\\u003e"
        )
        title = html.escape(str(spec["title"]))
        tagline = html.escape(str(spec["tagline"]))
        html_text = f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="description" content="{html.escape(str(spec['summary']))}" />
  <meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'" />
  <title>{title}</title>
  <link rel="stylesheet" href="styles.css" />
</head>
<body>
  <header class="topbar">
    <strong>{title}</strong>
    <nav aria-label="Prototype navigation">
      <button type="button" data-target="overview">Overview</button>
      <button type="button" data-target="workflow">Workflow</button>
      <button type="button" data-target="evidence">Evidence</button>
      <button type="button" data-target="workspace">Workspace</button>
    </nav>
  </header>
  <main>
    <section class="hero" aria-labelledby="hero-title">
      <span class="eyebrow">AIONEX AIOS governed full-stack prototype</span>
      <h1 id="hero-title">{title}</h1>
      <p>{tagline}</p>
      <div class="actions">
        <button id="primary-action" type="button"></button>
        <button id="secondary-action" class="secondary" type="button"></button>
      </div>
    </section>
    <section class="search-panel" aria-label="Feature search">
      <label for="feature-search">Search prototype features</label>
      <input id="feature-search" type="search" autocomplete="off" />
      <p id="result-count" aria-live="polite"></p>
    </section>
    <div id="sections" class="sections"></div>
    <section id="workspace" class="workspace" aria-labelledby="workspace-title">
      <div>
        <span class="eyebrow">Local application data</span>
        <h2 id="workspace-title">Working records</h2>
        <p>Create and remove records through the built-in Python API and SQLite database.</p>
      </div>
      <form id="item-form">
        <label for="item-title">New record</label>
        <div class="form-row">
          <input id="item-title" name="title" required minlength="2" maxlength="120" autocomplete="off" />
          <button type="submit">Add record</button>
        </div>
      </form>
      <p id="api-status" class="api-status" aria-live="polite">Connecting to local API...</p>
      <ul id="item-list" class="item-list"></ul>
    </section>
    <section id="limitations" class="limitations" aria-labelledby="limitations-title">
      <h2 id="limitations-title">Controlled prototype boundaries</h2>
      <ul id="limitations-list"></ul>
    </section>
  </main>
  <footer>Generated from governed evidence. No production deployment is claimed.</footer>
  <script id="project-data" type="application/json">{safe_json}</script>
  <script src="app.js" defer></script>
</body>
</html>
'''
        css = '''
:root{font-family:Inter,ui-sans-serif,system-ui,sans-serif;color-scheme:dark;background:#050816;color:#f8fafc}*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(circle at 12% 8%,rgba(14,165,233,.2),transparent 30%),radial-gradient(circle at 90% 20%,rgba(124,58,237,.18),transparent 35%),#050816}.topbar{position:sticky;top:0;z-index:3;display:flex;align-items:center;justify-content:space-between;gap:1rem;padding:1rem clamp(1rem,5vw,5rem);border-bottom:1px solid rgba(255,255,255,.08);background:rgba(5,8,22,.86);backdrop-filter:blur(18px)}nav{display:flex;flex-wrap:wrap;gap:.5rem}button,input{font:inherit}button{cursor:pointer;border:1px solid rgba(255,255,255,.12);border-radius:999px;padding:.75rem 1rem;background:#38bdf8;color:#03111c;font-weight:700}nav button,.secondary{background:rgba(255,255,255,.04);color:#e2e8f0}main{width:min(1120px,calc(100% - 2rem));margin:auto}.hero{padding:clamp(5rem,12vw,9rem) 0 3rem}.eyebrow{text-transform:uppercase;letter-spacing:.18em;color:#7dd3fc;font-size:.75rem}.hero h1{max-width:900px;margin:.8rem 0;font-size:clamp(3rem,9vw,7rem);line-height:.92}.hero p{max-width:760px;color:#cbd5e1;font-size:clamp(1rem,2vw,1.35rem);line-height:1.7}.actions{display:flex;flex-wrap:wrap;gap:.8rem;margin-top:2rem}.search-panel,.card,.limitations,.workspace{border:1px solid rgba(255,255,255,.08);background:rgba(255,255,255,.035);border-radius:1.5rem;padding:1.4rem}.search-panel{display:grid;gap:.7rem;margin:1rem 0 2rem}input{width:100%;border:1px solid rgba(255,255,255,.12);border-radius:1rem;background:rgba(0,0,0,.25);color:#fff;padding:1rem}.sections{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:1rem}.card h2,.workspace h2{margin-top:0}.card p,.card li,.limitations li,.workspace p{color:#94a3b8;line-height:1.65}.card[hidden]{display:none}.workspace{margin:2rem 0}.form-row{display:grid;grid-template-columns:1fr auto;gap:.7rem}.item-list{display:grid;gap:.6rem;padding:0;list-style:none}.item{display:flex;align-items:center;justify-content:space-between;gap:1rem;border:1px solid rgba(255,255,255,.07);border-radius:1rem;padding:.8rem 1rem;background:rgba(0,0,0,.18)}.item button{padding:.45rem .75rem;background:rgba(248,113,113,.12);color:#fecaca}.api-status{min-height:1.5rem}.limitations{margin:2rem 0}.notice{margin-top:1rem;border-left:3px solid #38bdf8;padding:.75rem 1rem;background:rgba(56,189,248,.08);color:#bae6fd}footer{padding:3rem 1rem;text-align:center;color:#64748b}@media(max-width:700px){.topbar{align-items:flex-start;flex-direction:column}.hero{padding-top:4rem}.form-row{grid-template-columns:1fr}}
'''.strip() + "\n"
        javascript = '''
"use strict";
const specNode=document.getElementById("project-data");
const spec=JSON.parse(specNode.textContent);
const sectionsRoot=document.getElementById("sections");
const itemList=document.getElementById("item-list");
const apiStatus=document.getElementById("api-status");
const make=(tag,text)=>{const node=document.createElement(tag);node.textContent=text;return node};
const renderSections=(query="")=>{sectionsRoot.replaceChildren();let visible=0;for(const section of spec.sections){const searchable=[section.title,section.body,...section.items].join(" ").toLowerCase();const card=document.createElement("article");card.className="card";card.id=section.id;card.hidden=Boolean(query)&&!searchable.includes(query);card.append(make("h2",section.title),make("p",section.body));const list=document.createElement("ul");for(const item of section.items)list.append(make("li",item));card.append(list);sectionsRoot.append(card);if(!card.hidden)visible+=1}document.getElementById("result-count").textContent=`${visible} sections visible`};
const request=async(path,options={})=>{const response=await fetch(path,{...options,headers:{"Content-Type":"application/json",...(options.headers||{})}});const payload=await response.json();if(!response.ok)throw new Error(payload.error||"Request failed");return payload};
const renderItems=items=>{itemList.replaceChildren();for(const item of items){const row=document.createElement("li");row.className="item";row.append(make("span",item.title));const remove=make("button","Remove");remove.type="button";remove.addEventListener("click",async()=>{await request(`/api/items/${item.id}`,{method:"DELETE"});await loadItems()});row.append(remove);itemList.append(row)}};
const loadItems=async()=>{try{const payload=await request("/api/items");renderItems(payload.items);apiStatus.textContent=`Local API healthy · ${payload.items.length} records`}catch(error){apiStatus.textContent=error.message}};
document.getElementById("primary-action").textContent=spec.primary_action;
document.getElementById("secondary-action").textContent=spec.secondary_action;
const limitationList=document.getElementById("limitations-list");for(const item of spec.limitations)limitationList.append(make("li",item));
document.getElementById("feature-search").addEventListener("input",event=>renderSections(event.target.value.trim().toLowerCase()));
document.getElementById("item-form").addEventListener("submit",async event=>{event.preventDefault();const input=document.getElementById("item-title");const title=input.value.trim();if(!title)return;try{await request("/api/items",{method:"POST",body:JSON.stringify({title})});input.value="";await loadItems()}catch(error){apiStatus.textContent=error.message}});
for(const button of document.querySelectorAll("[data-target]"))button.addEventListener("click",()=>document.getElementById(button.dataset.target)?.scrollIntoView({behavior:"smooth"}));
for(const id of ["primary-action","secondary-action"])document.getElementById(id).addEventListener("click",event=>{const existing=document.querySelector(".notice");existing?.remove();const notice=make("p",`${event.currentTarget.textContent}: this governed prototype records intent without contacting an external service.`);notice.className="notice";event.currentTarget.closest(".hero").append(notice)});
renderSections();
loadItems();
'''.strip() + "\n"
        server = '''from __future__ import annotations

import json
import sqlite3
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
MAX_BODY_BYTES = 64 * 1024


def initialize(database_path: Path) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS items ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "title TEXT NOT NULL CHECK(length(title) BETWEEN 2 AND 120), "
            "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        connection.commit()


def build_handler(database_path: Path):
    initialize(database_path)

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(ROOT), **kwargs)

        def end_headers(self) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "connect-src 'self'; img-src 'self' data:; base-uri 'none'; "
                "frame-ancestors 'none'",
            )
            super().end_headers()

        def _json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _path(self) -> str:
            return urlsplit(self.path).path

        def do_GET(self) -> None:
            path = self._path()
            if path == "/api/health":
                self._json(200, {"status": "healthy"})
                return
            if path == "/api/items":
                with sqlite3.connect(database_path) as connection:
                    connection.row_factory = sqlite3.Row
                    rows = connection.execute(
                        "SELECT id, title, created_at FROM items ORDER BY id DESC LIMIT 100"
                    ).fetchall()
                self._json(200, {"items": [dict(row) for row in rows]})
                return
            super().do_GET()

        def do_POST(self) -> None:
            if self._path() != "/api/items":
                self._json(404, {"error": "Not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._json(400, {"error": "Invalid content length"})
                return
            if length <= 0 or length > MAX_BODY_BYTES:
                self._json(413, {"error": "Request body is invalid"})
                return
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._json(400, {"error": "Invalid JSON"})
                return
            title = str(payload.get("title") or "").strip()
            if not 2 <= len(title) <= 120:
                self._json(422, {"error": "Title must contain 2 to 120 characters"})
                return
            with sqlite3.connect(database_path) as connection:
                cursor = connection.execute(
                    "INSERT INTO items (title) VALUES (?)", (title,)
                )
                connection.commit()
                item_id = int(cursor.lastrowid)
            self._json(201, {"id": item_id, "title": title})

        def do_DELETE(self) -> None:
            prefix = "/api/items/"
            path = self._path()
            if not path.startswith(prefix):
                self._json(404, {"error": "Not found"})
                return
            try:
                item_id = int(path[len(prefix):])
            except ValueError:
                self._json(400, {"error": "Invalid record id"})
                return
            with sqlite3.connect(database_path) as connection:
                cursor = connection.execute("DELETE FROM items WHERE id = ?", (item_id,))
                connection.commit()
            self._json(200 if cursor.rowcount else 404, {"deleted": bool(cursor.rowcount)})

        def log_message(self, format: str, *args) -> None:
            return

    return Handler


def build_server(
    host: str = "127.0.0.1",
    port: int = 8088,
    database_path: Path | None = None,
) -> ThreadingHTTPServer:
    selected_database = database_path or (ROOT / "prototype.db")
    return ThreadingHTTPServer((host, port), build_handler(selected_database))


if __name__ == "__main__":
    server = build_server()
    print("AIONEX governed full-stack prototype: http://127.0.0.1:8088")
    server.serve_forever()
'''
        readme = f'''# {project}

This is a functional, self-contained full-stack web prototype produced by the AIONEX AIOS full governed project cycle.

## Objective

{objective}

## Run

```text
python3 server.py
```

Open `http://127.0.0.1:8088` locally. The prototype includes a local JSON API and SQLite persistence, binds to localhost, makes no external network calls and stores no credentials.

## Evidence

- Planning manifest: `{planning['manifest_sha256']}`
- Provider role: structured product content only
- Executable source: deterministic reviewed templates
- Automated validation: see `TEST_REPORT.json` in the parent evidence package
- Production deployment: not performed

## Boundaries

This artifact is an executable full-stack prototype. It is not represented as a hosted production service, real authentication platform, payment processor, native mobile application, or completed third-party integration.
'''
        return {
            "index.html": html_text,
            "styles.css": css,
            "app.js": javascript,
            "server.py": server,
            "README.md": readme,
        }

    @classmethod
    def _test_source(cls, source: Path, project: str) -> dict[str, Any]:
        required = {"index.html", "styles.css", "app.js", "server.py", "README.md"}
        actual = {
            str(path.relative_to(source))
            for path in source.rglob("*")
            if path.is_file()
        }
        findings: list[str] = []
        if actual != required:
            findings.append("source file set does not match the fixed allow-list")
        for relative in sorted(actual):
            path = source / relative
            if path.stat().st_size <= 0 or path.stat().st_size > 200_000:
                findings.append(f"invalid file size: {relative}")
            text = path.read_text(encoding="utf-8")
            network_scan = text.replace("http://127.0.0.1:8088", "")
            if relative != "README.md" and re.search(r"https?://", network_scan):
                findings.append(f"external network URL detected: {relative}")
            if re.search(
                r"(?i)(api[_-]?key|password|authorization)\s*[=:]\s*['\"][^'\"]+",
                text,
            ):
                findings.append(f"credential-like assignment detected: {relative}")
        html_text = (source / "index.html").read_text(encoding="utf-8")
        parser = _PrototypeHTMLParser()
        parser.feed(html_text)
        required_ids = {
            "hero-title",
            "primary-action",
            "secondary-action",
            "feature-search",
            "result-count",
            "sections",
            "workspace",
            "workspace-title",
            "item-form",
            "item-title",
            "api-status",
            "item-list",
            "limitations",
            "limitations-list",
            "project-data",
        }
        if not required_ids.issubset(parser.ids):
            findings.append("HTML is missing required accessible application regions")
        if parser.stylesheets != ["styles.css"]:
            findings.append("HTML stylesheet references are not fixed and local")
        external_scripts = [
            item for item in parser.scripts if item.get("src") not in {None, "app.js"}
        ]
        if external_scripts:
            findings.append("HTML contains an unapproved script reference")
        app = (source / "app.js").read_text(encoding="utf-8")
        for forbidden in (
            "eval(",
            "Function(",
            "XMLHttpRequest",
            "WebSocket",
            "document.write",
            "innerHTML",
            "localStorage",
            "sessionStorage",
        ):
            if forbidden in app:
                findings.append(f"forbidden JavaScript primitive: {forbidden}")
        for call in re.findall(r"fetch\(([^,\)]+)", app):
            normalized = call.strip()
            if not (
                normalized == "path"
                or normalized.startswith('"/api/')
                or normalized.startswith("`/api/")
            ):
                findings.append(
                    "JavaScript fetch target is not constrained to the local API"
                )
        server_source = (source / "server.py").read_text(encoding="utf-8")
        try:
            compile(server_source, "server.py", "exec")
        except SyntaxError as exc:
            findings.append(f"server.py syntax error at line {exc.lineno}")
        api_checks = cls._test_local_api(source)
        findings.extend(api_checks["findings"])
        if project not in (source / "README.md").read_text(encoding="utf-8"):
            findings.append("README does not identify the requested project")
        return {
            "passed": not findings,
            "checks": {
                "fixed_file_allowlist": actual == required,
                "html_structure": required_ids.issubset(parser.ids),
                "local_assets_only": not external_scripts,
                "javascript_static_safety": not any(
                    item.startswith("forbidden JavaScript")
                    or item.startswith("JavaScript fetch")
                    for item in findings
                ),
                "python_server_syntax": not any(
                    item.startswith("server.py syntax") for item in findings
                ),
                "credential_scan": not any(
                    item.startswith("credential-like") for item in findings
                ),
                "api_health": api_checks["health"],
                "api_create_read_delete": api_checks["crud"],
                "sqlite_persistence": api_checks["persistence"],
                "security_headers": api_checks["security_headers"],
            },
            "findings": findings,
        }

    @classmethod
    def _test_local_api(cls, source: Path) -> dict[str, Any]:
        findings: list[str] = []
        health = False
        crud = False
        persistence = False
        security_headers = False
        module_path = source / "server.py"
        module_name = (
            "aionex_generated_server_"
            + hashlib.sha256(str(source).encode()).hexdigest()[:12]
        )
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None or spec.loader is None:
            return {
                "health": False,
                "crud": False,
                "persistence": False,
                "security_headers": False,
                "findings": ["generated server module could not be loaded"],
            }
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory(prefix="aionex-prototype-api-") as temporary:
            database = Path(temporary) / "prototype.db"
            server = module.build_server(port=0, database_path=database)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                with urlopen(f"{base}/api/health", timeout=3) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    health = response.status == 200 and payload == {
                        "status": "healthy"
                    }
                    security_headers = (
                        response.headers.get("X-Content-Type-Options") == "nosniff"
                        and response.headers.get("X-Frame-Options") == "DENY"
                        and "default-src 'self'"
                        in str(response.headers.get("Content-Security-Policy"))
                    )
                create_request = Request(
                    f"{base}/api/items",
                    data=json.dumps(
                        {"title": "Validated project record"}
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(create_request, timeout=3) as response:
                    created = json.loads(response.read().decode("utf-8"))
                    item_id = int(created["id"])
                    created_ok = response.status == 201
                with urlopen(f"{base}/api/items", timeout=3) as response:
                    listed = json.loads(response.read().decode("utf-8"))
                    listed_ok = any(
                        item["id"] == item_id
                        and item["title"] == "Validated project record"
                        for item in listed["items"]
                    )
                delete_request = Request(
                    f"{base}/api/items/{item_id}", method="DELETE"
                )
                with urlopen(delete_request, timeout=3) as response:
                    deleted = json.loads(response.read().decode("utf-8"))
                    deleted_ok = (
                        response.status == 200 and deleted["deleted"] is True
                    )
                crud = created_ok and listed_ok and deleted_ok
                persistence = database.is_file() and database.stat().st_size > 0
                invalid = Request(
                    f"{base}/api/items",
                    data=b'{"title":"x"}',
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                try:
                    urlopen(invalid, timeout=3)
                    findings.append("local API accepted an invalid short title")
                except HTTPError as exc:
                    if exc.code != 422:
                        findings.append(
                            "local API returned an unexpected validation status"
                        )
            except Exception as exc:
                findings.append(
                    f"local API integration test failed: {type(exc).__name__}"
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
        if not health:
            findings.append("local API health check failed")
        if not crud:
            findings.append("local API CRUD test failed")
        if not persistence:
            findings.append("SQLite persistence test failed")
        if not security_headers:
            findings.append("local API security headers are incomplete")
        shutil.rmtree(source / "__pycache__", ignore_errors=True)
        return {
            "health": health,
            "crud": crud,
            "persistence": persistence,
            "security_headers": security_headers,
            "findings": findings,
        }

    @staticmethod
    def _write_archive(archive: Path, source: Path) -> None:
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for path in sorted(source.rglob("*")):
                if path.is_file() and not path.is_symlink():
                    bundle.write(path, path.relative_to(source))

    @classmethod
    def _verify_archive(
        cls, archive: Path, expected_hashes: Mapping[str, str], staging: Path
    ) -> bool:
        target = staging / ".rollback-check"
        target.mkdir(mode=0o700)
        try:
            with zipfile.ZipFile(archive) as bundle:
                for info in bundle.infolist():
                    candidate = cls._contained(target, target / info.filename)
                    if info.is_dir():
                        candidate.mkdir(parents=True, exist_ok=True)
                        continue
                    candidate.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(info) as source, candidate.open("xb") as output:
                        shutil.copyfileobj(source, output)
            actual = {
                str(path.relative_to(target)): cls._sha256(path)
                for path in target.rglob("*")
                if path.is_file()
            }
            return actual == dict(expected_hashes)
        finally:
            shutil.rmtree(target, ignore_errors=True)

    @staticmethod
    def _validate_execution_id(execution_id: str) -> str:
        if not _EXECUTION_ID.fullmatch(execution_id) or execution_id in {".", ".."}:
            raise ValueError("execution_id contains unsafe path characters")
        return execution_id

    @staticmethod
    def _prepare_root(output_root: str | Path) -> Path:
        raw = Path(output_root)
        if not raw.is_absolute():
            raise ValueError("output_root must be absolute")
        raw.mkdir(parents=True, exist_ok=True, mode=0o700)
        root = raw.resolve(strict=True)
        if not root.is_dir():
            raise NotADirectoryError(str(root))
        return root

    @staticmethod
    def _contained(root: Path, candidate: Path) -> Path:
        resolved = candidate.resolve(strict=False)
        if resolved == root or root not in resolved.parents:
            raise ValueError("path escapes allowed root")
        return resolved

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _canonical_json(payload: Mapping[str, Any]) -> str:
        return json.dumps(
            dict(payload), ensure_ascii=False, sort_keys=True, indent=2
        ) + "\n"

    @staticmethod
    def _atomic_write_text(path: Path, content: str) -> None:
        temporary = path.with_name(f".{path.name}.tmp")
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    @staticmethod
    def _report(manifest: Mapping[str, Any]) -> str:
        tests = manifest["tests"]
        return (
            "# Controlled Full-Stack Project Prototype\n\n"
            f"- Project: `{manifest['project']}`\n"
            f"- Provider model: `{manifest['model']}`\n"
            f"- Provider role: `{manifest['provider_role']}`\n"
            f"- Executable source origin: `{manifest['executable_source_origin']}`\n"
            f"- Tests passed: `{str(tests['passed']).lower()}`\n"
            f"- Rollback tested: `{str(manifest.get('rollback_tested', False)).lower()}`\n"
            f"- Cost: `${manifest['calculated_cost']:.10f}`\n"
            "- Fallback used: `false`\n"
            "- Production modified: `false`\n"
            "- Raw prompt/response/header stored: `false`\n"
        )
