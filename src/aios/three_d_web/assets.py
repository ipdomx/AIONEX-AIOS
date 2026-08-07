from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import struct
from typing import Iterable, Mapping

from .contracts import AssetKind, PerformanceProfile, SceneAsset


class CompressionKind(str, Enum):
    NONE = "none"
    DRACO = "draco"
    MESHOPT = "meshopt"
    KTX2 = "ktx2"
    BASIS = "basis"


@dataclass(frozen=True, slots=True)
class AssetMetadata:
    asset_id: str
    kind: AssetKind
    path: str
    bytes: int
    checksum_sha256: str
    meshes: int | None = None
    materials: int | None = None
    textures: int | None = None
    animations: int | None = None
    triangles: int | None = None
    images: int | None = None
    nodes: int | None = None
    scenes: int | None = None
    compression: frozenset[CompressionKind] = frozenset()
    metadata_available: bool = False


@dataclass(frozen=True, slots=True)
class AssetBudget:
    max_asset_bytes: int
    max_total_bytes: int
    max_meshes: int | None = None
    max_materials: int | None = None
    max_textures: int | None = None
    max_animations: int | None = None
    max_triangles: int | None = None


DEFAULT_BUDGETS: Mapping[PerformanceProfile, AssetBudget] = {
    PerformanceProfile.DESKTOP: AssetBudget(
        max_asset_bytes=24 * 1024 * 1024,
        max_total_bytes=80 * 1024 * 1024,
        max_meshes=500,
        max_materials=300,
        max_textures=256,
        max_animations=128,
        max_triangles=2_500_000,
    ),
    PerformanceProfile.MOBILE: AssetBudget(
        max_asset_bytes=10 * 1024 * 1024,
        max_total_bytes=35 * 1024 * 1024,
        max_meshes=250,
        max_materials=160,
        max_textures=128,
        max_animations=64,
        max_triangles=900_000,
    ),
    PerformanceProfile.LOW_POWER: AssetBudget(
        max_asset_bytes=6 * 1024 * 1024,
        max_total_bytes=20 * 1024 * 1024,
        max_meshes=140,
        max_materials=90,
        max_textures=72,
        max_animations=32,
        max_triangles=450_000,
    ),
}


@dataclass(frozen=True, slots=True)
class BudgetViolation:
    asset_id: str | None
    metric: str
    actual: int
    limit: int


@dataclass(frozen=True, slots=True)
class AssetBudgetResult:
    profile: PerformanceProfile
    passed: bool
    violations: tuple[BudgetViolation, ...]
    total_bytes: int


@dataclass(frozen=True, slots=True)
class OptimizationAction:
    asset_id: str
    action: str
    reason: str
    target: str
    required: bool = False


@dataclass(frozen=True, slots=True)
class OptimizationPlan:
    profile: PerformanceProfile
    actions: tuple[OptimizationAction, ...]


@dataclass(frozen=True, slots=True)
class LODVariant:
    profile: PerformanceProfile
    suffix: str
    triangle_ratio: float
    texture_max_dimension: int
    optional_assets: bool


LOD_PROFILES: Mapping[PerformanceProfile, LODVariant] = {
    PerformanceProfile.DESKTOP: LODVariant(PerformanceProfile.DESKTOP, "desktop", 1.0, 4096, True),
    PerformanceProfile.MOBILE: LODVariant(PerformanceProfile.MOBILE, "mobile", 0.45, 2048, True),
    PerformanceProfile.LOW_POWER: LODVariant(PerformanceProfile.LOW_POWER, "low", 0.22, 1024, False),
}


@dataclass(frozen=True, slots=True)
class ArtifactManifestEntry:
    asset_id: str
    kind: str
    path: str
    bytes: int
    sha256: str
    lod_group: str | None
    required: bool


@dataclass(frozen=True, slots=True)
class ArtifactManifest:
    version: int
    entries: tuple[ArtifactManifestEntry, ...]
    aggregate_sha256: str
    total_bytes: int

    def to_json(self) -> str:
        return json.dumps(
            {
                "version": self.version,
                "entries": [asdict(entry) for entry in self.entries],
                "aggregate_sha256": self.aggregate_sha256,
                "total_bytes": self.total_bytes,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


class AssetInspector:
    """Inspects registered 3D assets without executing or mutating them."""

    GLB_MAGIC = b"glTF"
    GLB_JSON_CHUNK = 0x4E4F534A

    def inspect(self, asset: SceneAsset, project_root: Path) -> AssetMetadata:
        asset.validate()
        path = self._resolve(asset.path, project_root)
        raw = path.read_bytes()
        digest = sha256(raw).hexdigest()
        base = {
            "asset_id": asset.asset_id,
            "kind": asset.kind,
            "path": asset.path,
            "bytes": len(raw),
            "checksum_sha256": digest,
        }
        if asset.kind == AssetKind.GLB:
            doc = self._read_glb_json(raw)
            return AssetMetadata(**base, **self._metadata_from_gltf(doc), metadata_available=True)
        if asset.kind == AssetKind.GLTF:
            doc = json.loads(raw.decode("utf-8"))
            if not isinstance(doc, dict):
                raise ValueError("gltf root must be an object")
            return AssetMetadata(**base, **self._metadata_from_gltf(doc), metadata_available=True)
        return AssetMetadata(**base, metadata_available=False)

    @staticmethod
    def _resolve(relative: str, project_root: Path) -> Path:
        rel = PurePosixPath(relative)
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError("asset path must stay inside project root")
        root = project_root.resolve()
        path = (root / Path(*rel.parts)).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("asset path escapes project root") from exc
        if not path.is_file():
            raise FileNotFoundError(path)
        return path

    def _read_glb_json(self, raw: bytes) -> dict[str, object]:
        if len(raw) < 20:
            raise ValueError("invalid GLB: too small")
        magic, version, declared_length = struct.unpack_from("<4sII", raw, 0)
        if magic != self.GLB_MAGIC or version != 2 or declared_length != len(raw):
            raise ValueError("invalid GLB header")
        chunk_length, chunk_type = struct.unpack_from("<II", raw, 12)
        if chunk_type != self.GLB_JSON_CHUNK or 20 + chunk_length > len(raw):
            raise ValueError("invalid GLB JSON chunk")
        payload = raw[20 : 20 + chunk_length].rstrip(b"\x00 \t\r\n")
        doc = json.loads(payload.decode("utf-8"))
        if not isinstance(doc, dict):
            raise ValueError("GLB JSON root must be an object")
        return doc

    @staticmethod
    def _metadata_from_gltf(doc: Mapping[str, object]) -> dict[str, object]:
        def count(name: str) -> int:
            value = doc.get(name, [])
            return len(value) if isinstance(value, list) else 0

        triangles: int | None = 0
        accessors = doc.get("accessors", [])
        meshes = doc.get("meshes", [])
        if not isinstance(accessors, list) or not isinstance(meshes, list):
            triangles = None
        else:
            try:
                for mesh in meshes:
                    if not isinstance(mesh, dict):
                        continue
                    primitives = mesh.get("primitives", [])
                    if not isinstance(primitives, list):
                        continue
                    for primitive in primitives:
                        if not isinstance(primitive, dict):
                            continue
                        mode = int(primitive.get("mode", 4))
                        if mode != 4:  # TRIANGLES only; other primitive modes are not safely estimated.
                            triangles = None
                            break
                        accessor_index = primitive.get("indices")
                        if accessor_index is None:
                            attrs = primitive.get("attributes", {})
                            accessor_index = attrs.get("POSITION") if isinstance(attrs, dict) else None
                        if accessor_index is None:
                            triangles = None
                            break
                        accessor = accessors[int(accessor_index)]
                        if not isinstance(accessor, dict) or "count" not in accessor:
                            triangles = None
                            break
                        triangles += int(accessor["count"]) // 3
                    if triangles is None:
                        break
            except (IndexError, KeyError, TypeError, ValueError):
                triangles = None

        extensions = doc.get("extensionsUsed", [])
        used = {str(item) for item in extensions} if isinstance(extensions, list) else set()
        compression: set[CompressionKind] = set()
        if "KHR_draco_mesh_compression" in used:
            compression.add(CompressionKind.DRACO)
        if "EXT_meshopt_compression" in used:
            compression.add(CompressionKind.MESHOPT)
        if "KHR_texture_basisu" in used:
            compression.update({CompressionKind.KTX2, CompressionKind.BASIS})

        return {
            "meshes": count("meshes"),
            "materials": count("materials"),
            "textures": count("textures"),
            "animations": count("animations"),
            "triangles": triangles,
            "images": count("images"),
            "nodes": count("nodes"),
            "scenes": count("scenes"),
            "compression": frozenset(compression),
        }


class AssetBudgetGate:
    def __init__(self, budgets: Mapping[PerformanceProfile, AssetBudget] | None = None) -> None:
        self.budgets = dict(budgets or DEFAULT_BUDGETS)

    def evaluate(self, metadata: Iterable[AssetMetadata], profile: PerformanceProfile) -> AssetBudgetResult:
        items = tuple(metadata)
        budget = self.budgets[profile]
        violations: list[BudgetViolation] = []
        total_bytes = sum(item.bytes for item in items)
        if total_bytes > budget.max_total_bytes:
            violations.append(BudgetViolation(None, "total_bytes", total_bytes, budget.max_total_bytes))
        fields = (
            ("bytes", "max_asset_bytes"),
            ("meshes", "max_meshes"),
            ("materials", "max_materials"),
            ("textures", "max_textures"),
            ("animations", "max_animations"),
            ("triangles", "max_triangles"),
        )
        for item in items:
            for actual_name, limit_name in fields:
                actual = getattr(item, actual_name)
                limit = getattr(budget, limit_name)
                if actual is not None and limit is not None and actual > limit:
                    violations.append(BudgetViolation(item.asset_id, actual_name, int(actual), int(limit)))
        return AssetBudgetResult(profile, not violations, tuple(violations), total_bytes)


class OptimizationPlanner:
    """Produces truthful optimization work; it never claims an optimizer was executed."""

    def plan(self, metadata: Iterable[AssetMetadata], profile: PerformanceProfile) -> OptimizationPlan:
        actions: list[OptimizationAction] = []
        lod = LOD_PROFILES[profile]
        for item in metadata:
            if item.kind in {AssetKind.GLB, AssetKind.GLTF}:
                if not ({CompressionKind.DRACO, CompressionKind.MESHOPT} & item.compression):
                    actions.append(OptimizationAction(
                        item.asset_id,
                        "mesh-compression",
                        "geometry is not declared as Draco or Meshopt compressed",
                        "meshopt-or-draco",
                        required=profile != PerformanceProfile.DESKTOP,
                    ))
                if item.triangles is not None and lod.triangle_ratio < 1.0:
                    actions.append(OptimizationAction(
                        item.asset_id,
                        "generate-lod",
                        f"{profile.value} profile targets lower geometric complexity",
                        f"triangle-ratio<={lod.triangle_ratio:.2f}",
                        required=True,
                    ))
                if item.textures and CompressionKind.KTX2 not in item.compression:
                    actions.append(OptimizationAction(
                        item.asset_id,
                        "texture-compression",
                        "model references textures without KTX2/Basis declaration",
                        f"ktx2-max-{lod.texture_max_dimension}px",
                        required=profile != PerformanceProfile.DESKTOP,
                    ))
            elif item.kind == AssetKind.TEXTURE and item.path.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                actions.append(OptimizationAction(
                    item.asset_id,
                    "texture-transcode",
                    "runtime texture can use GPU-native KTX2/Basis delivery",
                    f"ktx2-max-{lod.texture_max_dimension}px",
                    required=profile != PerformanceProfile.DESKTOP,
                ))
        return OptimizationPlan(profile, tuple(actions))


class ArtifactManifestBuilder:
    def build(self, assets: Iterable[SceneAsset], project_root: Path) -> ArtifactManifest:
        inspector = AssetInspector()
        entries: list[ArtifactManifestEntry] = []
        for asset in sorted(tuple(assets), key=lambda item: item.asset_id):
            metadata = inspector.inspect(asset, project_root)
            entries.append(ArtifactManifestEntry(
                asset_id=asset.asset_id,
                kind=asset.kind.value,
                path=asset.path,
                bytes=metadata.bytes,
                sha256=metadata.checksum_sha256,
                lod_group=asset.lod_group,
                required=asset.required,
            ))
        canonical = json.dumps([asdict(item) for item in entries], sort_keys=True, separators=(",", ":")).encode()
        return ArtifactManifest(
            version=1,
            entries=tuple(entries),
            aggregate_sha256=sha256(canonical).hexdigest(),
            total_bytes=sum(item.bytes for item in entries),
        )

    def verify(self, manifest: ArtifactManifest, project_root: Path) -> tuple[str, ...]:
        failures: list[str] = []
        root = project_root.resolve()
        for entry in manifest.entries:
            try:
                path = AssetInspector._resolve(entry.path, root)
                raw = path.read_bytes()
            except (FileNotFoundError, ValueError):
                failures.append(entry.asset_id)
                continue
            if len(raw) != entry.bytes or sha256(raw).hexdigest() != entry.sha256:
                failures.append(entry.asset_id)
        return tuple(failures)
