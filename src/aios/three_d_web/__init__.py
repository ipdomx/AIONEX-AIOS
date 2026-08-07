"""Production contracts for AIOS 3D web project creation."""
from .contracts import (
    AssetKind,
    InteractionMode,
    PerformanceProfile,
    Project3DBlueprint,
    SceneAsset,
    SceneZone,
    ThreeDProjectPlanner,
)

__all__ = [
    "AssetKind",
    "InteractionMode",
    "PerformanceProfile",
    "Project3DBlueprint",
    "SceneAsset",
    "SceneZone",
    "ThreeDProjectPlanner",
]

from .assets import (
    ArtifactManifest, ArtifactManifestBuilder, AssetBudget, AssetBudgetGate, AssetBudgetResult,
    AssetInspector, AssetMetadata, BudgetViolation, CompressionKind, DEFAULT_BUDGETS,
    LOD_PROFILES, LODVariant, OptimizationAction, OptimizationPlan, OptimizationPlanner,
)

__all__ += [
    "ArtifactManifest", "ArtifactManifestBuilder", "AssetBudget", "AssetBudgetGate",
    "AssetBudgetResult", "AssetInspector", "AssetMetadata", "BudgetViolation",
    "CompressionKind", "DEFAULT_BUDGETS", "LOD_PROFILES", "LODVariant",
    "OptimizationAction", "OptimizationPlan", "OptimizationPlanner",
]
