from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from hashlib import sha256
import json
from pathlib import PurePosixPath
from typing import Iterable, Mapping


class BrowserSupport(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"


class EvidenceKind(str, Enum):
    SCREENSHOT = "screenshot"
    CONSOLE = "console"
    WEBGL = "webgl"
    ROUTE = "route"
    INTERACTION = "interaction"
    CAMERA = "camera"
    ASSET = "asset"


@dataclass(frozen=True, slots=True)
class ViewportSpec:
    viewport_id: str
    width: int
    height: int
    device_scale_factor: float = 1.0
    mobile: bool = False

    def validate(self) -> None:
        if not self.viewport_id.strip():
            raise ValueError("viewport_id is required")
        if self.width <= 0 or self.height <= 0 or self.device_scale_factor <= 0:
            raise ValueError("viewport dimensions and scale must be positive")


@dataclass(frozen=True, slots=True)
class BrowserSpec:
    browser_id: str
    engine: str
    support: BrowserSupport = BrowserSupport.SUPPORTED
    reason: str | None = None

    def validate(self) -> None:
        if not self.browser_id.strip() or not self.engine.strip():
            raise ValueError("browser_id and engine are required")
        if self.support != BrowserSupport.SUPPORTED and not (self.reason or "").strip():
            raise ValueError("unsupported/unavailable browsers require a reason")


@dataclass(frozen=True, slots=True)
class SmokeScenario:
    scenario_id: str
    kind: EvidenceKind
    target: str
    actions: tuple[str, ...]
    assertions: tuple[str, ...]
    required: bool = True

    def validate(self) -> None:
        if not self.scenario_id.strip() or not self.target.strip():
            raise ValueError("scenario identity and target are required")
        if not self.assertions:
            raise ValueError("scenario assertions are required")


@dataclass(frozen=True, slots=True)
class ConsoleRecord:
    level: str
    message: str
    source: str | None = None


@dataclass(frozen=True, slots=True)
class WebGLErrorRecord:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    scenario_id: str
    passed: bool
    details: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvidenceEntry:
    evidence_id: str
    kind: EvidenceKind
    path: str
    sha256: str
    viewport_id: str | None = None
    browser_id: str | None = None
    scenario_id: str | None = None

    def validate(self) -> None:
        if not self.evidence_id.strip() or not self.sha256.strip():
            raise ValueError("evidence id and checksum are required")
        path = PurePosixPath(self.path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("evidence path must be project-relative and traversal-safe")
        if len(self.sha256) != 64:
            raise ValueError("evidence checksum must be sha256")


@dataclass(frozen=True, slots=True)
class BrowserRunReceipt:
    browser: BrowserSpec
    viewport: ViewportSpec
    console: tuple[ConsoleRecord, ...]
    webgl_errors: tuple[WebGLErrorRecord, ...]
    scenarios: tuple[ScenarioResult, ...]
    evidence: tuple[EvidenceEntry, ...]

    @property
    def passed(self) -> bool:
        if self.browser.support != BrowserSupport.SUPPORTED:
            return False
        required_failed = any(not result.passed for result in self.scenarios)
        fatal_console = any(record.level.lower() in {"error", "fatal"} for record in self.console)
        return not required_failed and not self.webgl_errors and not fatal_console


@dataclass(frozen=True, slots=True)
class VisualQAEvidenceManifest:
    version: int
    browser_runs: tuple[BrowserRunReceipt, ...]
    aggregate_sha256: str

    def to_json(self) -> str:
        payload = {
            "version": self.version,
            "browser_runs": [asdict(run) for run in self.browser_runs],
            "aggregate_sha256": self.aggregate_sha256,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=lambda value: value.value)


@dataclass(frozen=True, slots=True)
class VisualQAPolicy:
    require_desktop: bool = True
    require_mobile: bool = True
    fail_on_console_error: bool = True
    fail_on_webgl_error: bool = True
    require_screenshot_per_supported_run: bool = True
    require_all_required_scenarios: bool = True


@dataclass(frozen=True, slots=True)
class VisualQAVerdict:
    passed: bool
    violations: tuple[str, ...]


DEFAULT_VIEWPORTS: tuple[ViewportSpec, ...] = (
    ViewportSpec("desktop-1440", 1440, 900, 1.0, False),
    ViewportSpec("mobile-390", 390, 844, 3.0, True),
)


DEFAULT_BROWSERS: tuple[BrowserSpec, ...] = (
    BrowserSpec("chromium", "chromium"),
    BrowserSpec("webkit", "webkit"),
)


DEFAULT_SCENARIOS: tuple[SmokeScenario, ...] = (
    SmokeScenario(
        "route-home",
        EvidenceKind.ROUTE,
        "/",
        ("navigate:/",),
        ("document-ready", "canvas-or-fallback-visible"),
    ),
    SmokeScenario(
        "asset-world",
        EvidenceKind.ASSET,
        "scene-assets",
        ("wait:required-assets",),
        ("required-assets-loaded",),
    ),
    SmokeScenario(
        "interaction-primary",
        EvidenceKind.INTERACTION,
        "player-controller",
        ("input:primary-navigation",),
        ("player-or-focus-state-changed",),
    ),
    SmokeScenario(
        "camera-follow-focus",
        EvidenceKind.CAMERA,
        "camera-controller",
        ("trigger:zone-focus",),
        ("camera-state-finite", "camera-target-reached"),
    ),
)


class BrowserAcceptancePlanner:
    """Creates deterministic browser QA contracts; execution belongs to a configured browser worker."""

    def plan(
        self,
        *,
        browsers: Iterable[BrowserSpec] = DEFAULT_BROWSERS,
        viewports: Iterable[ViewportSpec] = DEFAULT_VIEWPORTS,
        scenarios: Iterable[SmokeScenario] = DEFAULT_SCENARIOS,
    ) -> dict[str, tuple[object, ...]]:
        browser_tuple = tuple(browsers)
        viewport_tuple = tuple(viewports)
        scenario_tuple = tuple(scenarios)
        if not browser_tuple or not viewport_tuple or not scenario_tuple:
            raise ValueError("browser, viewport and scenario contracts are required")
        for browser in browser_tuple:
            browser.validate()
        for viewport in viewport_tuple:
            viewport.validate()
        scenario_ids: set[str] = set()
        for scenario in scenario_tuple:
            scenario.validate()
            if scenario.scenario_id in scenario_ids:
                raise ValueError("scenario IDs must be unique")
            scenario_ids.add(scenario.scenario_id)
        return {
            "browsers": browser_tuple,
            "viewports": viewport_tuple,
            "scenarios": scenario_tuple,
        }


class VisualQAGate:
    def evaluate(
        self,
        runs: Iterable[BrowserRunReceipt],
        *,
        policy: VisualQAPolicy = VisualQAPolicy(),
        scenario_requirements: Mapping[str, bool] | None = None,
    ) -> VisualQAVerdict:
        run_tuple = tuple(runs)
        violations: list[str] = []
        supported = tuple(run for run in run_tuple if run.browser.support == BrowserSupport.SUPPORTED)
        if policy.require_desktop and not any(not run.viewport.mobile for run in supported):
            violations.append("missing-supported-desktop-run")
        if policy.require_mobile and not any(run.viewport.mobile for run in supported):
            violations.append("missing-supported-mobile-run")
        for run in run_tuple:
            run.browser.validate()
            run.viewport.validate()
            for evidence in run.evidence:
                evidence.validate()
            if run.browser.support != BrowserSupport.SUPPORTED:
                violations.append(f"browser-{run.browser.browser_id}-{run.browser.support.value}:{run.browser.reason}")
                continue
            if policy.fail_on_console_error:
                for record in run.console:
                    if record.level.lower() in {"error", "fatal"}:
                        violations.append(f"console-error:{run.browser.browser_id}:{run.viewport.viewport_id}:{record.message}")
            if policy.fail_on_webgl_error:
                for error in run.webgl_errors:
                    violations.append(f"webgl-error:{run.browser.browser_id}:{run.viewport.viewport_id}:{error.code}")
            if policy.require_screenshot_per_supported_run and not any(
                evidence.kind == EvidenceKind.SCREENSHOT for evidence in run.evidence
            ):
                violations.append(f"missing-screenshot:{run.browser.browser_id}:{run.viewport.viewport_id}")
            required_map = scenario_requirements or {}
            for result in run.scenarios:
                required = required_map.get(result.scenario_id, True)
                if policy.require_all_required_scenarios and required and not result.passed:
                    violations.append(f"scenario-failed:{run.browser.browser_id}:{run.viewport.viewport_id}:{result.scenario_id}")
        return VisualQAVerdict(not violations, tuple(violations))


class EvidenceManifestBuilder:
    def build(self, runs: Iterable[BrowserRunReceipt]) -> VisualQAEvidenceManifest:
        normalized = tuple(sorted(runs, key=lambda run: (run.browser.browser_id, run.viewport.viewport_id)))
        for run in normalized:
            run.browser.validate()
            run.viewport.validate()
            for evidence in run.evidence:
                evidence.validate()
        canonical = json.dumps(
            [asdict(run) for run in normalized],
            sort_keys=True,
            separators=(",", ":"),
            default=lambda value: value.value,
        ).encode("utf-8")
        return VisualQAEvidenceManifest(1, normalized, sha256(canonical).hexdigest())


def checksum_bytes(raw: bytes) -> str:
    return sha256(raw).hexdigest()
