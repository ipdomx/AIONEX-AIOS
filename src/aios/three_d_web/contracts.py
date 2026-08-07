from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from typing import Iterable


class AssetKind(str, Enum):
    GLB = "glb"
    GLTF = "gltf"
    TEXTURE = "texture"
    AUDIO = "audio"
    SHADER = "shader"


class InteractionMode(str, Enum):
    KEYBOARD = "keyboard"
    POINTER = "pointer"
    TOUCH = "touch"
    WHEEL = "wheel"
    RAYCAST = "raycast"
    AUTO_TRAVEL = "auto_travel"


class PerformanceProfile(str, Enum):
    DESKTOP = "desktop"
    MOBILE = "mobile"
    LOW_POWER = "low_power"


@dataclass(frozen=True, slots=True)
class SceneAsset:
    asset_id: str
    kind: AssetKind
    path: str
    required: bool = True
    lazy: bool = True
    lod_group: str | None = None
    checksum: str | None = None

    def validate(self) -> None:
        if not self.asset_id.strip():
            raise ValueError("asset_id is required")
        path = PurePosixPath(self.path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("asset path must be project-relative and traversal-safe")
        expected = {
            AssetKind.GLB: {".glb"}, AssetKind.GLTF: {".gltf"},
            AssetKind.TEXTURE: {".png", ".jpg", ".jpeg", ".webp", ".ktx2", ".avif"},
            AssetKind.AUDIO: {".mp3", ".ogg", ".wav", ".m4a"},
            AssetKind.SHADER: {".glsl", ".vert", ".frag"},
        }[self.kind]
        if path.suffix.lower() not in expected:
            raise ValueError(f"invalid extension for {self.kind.value}: {path.suffix}")


@dataclass(frozen=True, slots=True)
class SceneZone:
    zone_id: str
    title: str
    position: tuple[float, float, float]
    radius: float
    asset_ids: tuple[str, ...] = ()
    interactions: frozenset[InteractionMode] = frozenset({InteractionMode.RAYCAST})
    mobile_scale: float = 1.0
    desktop_scale: float = 1.0

    def validate(self) -> None:
        if not self.zone_id.strip() or not self.title.strip():
            raise ValueError("zone_id and title are required")
        if self.radius <= 0:
            raise ValueError("zone radius must be positive")
        if self.mobile_scale <= 0 or self.desktop_scale <= 0:
            raise ValueError("zone scale must be positive")


@dataclass(frozen=True, slots=True)
class Project3DBlueprint:
    project_id: str
    title: str
    objective: str
    player_controller: str
    camera_mode: str
    zones: tuple[SceneZone, ...]
    assets: tuple[SceneAsset, ...]
    interactions: frozenset[InteractionMode]
    performance_profiles: frozenset[PerformanceProfile]
    requirements: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]

    def validate(self) -> None:
        if not self.project_id.strip() or not self.title.strip() or not self.objective.strip():
            raise ValueError("project identity, title and objective are required")
        if not self.zones:
            raise ValueError("at least one scene zone is required")
        if not self.performance_profiles:
            raise ValueError("at least one performance profile is required")
        asset_ids = {asset.asset_id for asset in self.assets}
        if len(asset_ids) != len(self.assets):
            raise ValueError("asset IDs must be unique")
        zone_ids = {zone.zone_id for zone in self.zones}
        if len(zone_ids) != len(self.zones):
            raise ValueError("zone IDs must be unique")
        for asset in self.assets:
            asset.validate()
        for zone in self.zones:
            zone.validate()
            unknown = set(zone.asset_ids) - asset_ids
            if unknown:
                raise ValueError(f"zone {zone.zone_id} references unknown assets: {sorted(unknown)}")


class ThreeDProjectPlanner:
    """Creates a deterministic 3D-web blueprint suitable for downstream AIOS workers."""

    DEFAULT_ACCEPTANCE = (
        "Production build succeeds without unresolved WebGL or JavaScript runtime errors.",
        "Keyboard, pointer and touch navigation have deterministic acceptance scenarios.",
        "Required scene assets are registered, checksum-addressable and project-relative.",
        "Desktop, mobile and low-power performance profiles have explicit budgets.",
        "HTML content remains accessible independently of WebGL presentation.",
        "Release evidence includes asset, visual-QA, performance and rollback receipts.",
    )

    def plan(
        self,
        *,
        project_id: str,
        title: str,
        objective: str,
        zones: Iterable[SceneZone],
        assets: Iterable[SceneAsset] = (),
        player_controller: str = "vehicle",
        camera_mode: str = "follow-and-focus",
    ) -> Project3DBlueprint:
        blueprint = Project3DBlueprint(
            project_id=project_id,
            title=title,
            objective=objective,
            player_controller=player_controller,
            camera_mode=camera_mode,
            zones=tuple(zones),
            assets=tuple(assets),
            interactions=frozenset({
                InteractionMode.KEYBOARD, InteractionMode.POINTER, InteractionMode.TOUCH,
                InteractionMode.WHEEL, InteractionMode.RAYCAST, InteractionMode.AUTO_TRAVEL,
            }),
            performance_profiles=frozenset({
                PerformanceProfile.DESKTOP, PerformanceProfile.MOBILE, PerformanceProfile.LOW_POWER,
            }),
            requirements=(
                "Three.js or React Three Fiber scene runtime",
                "zone/world manager",
                "player or vehicle controller",
                "camera controller",
                "asset registry with lazy loading",
                "HTML overlay/content layer",
                "visual QA evidence",
                "3D performance gate",
            ),
            acceptance_criteria=self.DEFAULT_ACCEPTANCE,
        )
        blueprint.validate()
        return blueprint
