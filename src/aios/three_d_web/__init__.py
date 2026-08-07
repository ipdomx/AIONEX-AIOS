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

from .scaffold import RuntimeScaffold, ScaffoldFile, ThreeDRuntimeScaffoldBuilder

__all__ += ["RuntimeScaffold", "ScaffoldFile", "ThreeDRuntimeScaffoldBuilder"]

from .visual_qa import (
    BrowserAcceptancePlanner,
    BrowserRunReceipt,
    BrowserSpec,
    BrowserSupport,
    ConsoleRecord,
    DEFAULT_BROWSERS,
    DEFAULT_SCENARIOS,
    DEFAULT_VIEWPORTS,
    EvidenceEntry,
    EvidenceKind,
    EvidenceManifestBuilder,
    ScenarioResult,
    SmokeScenario,
    ViewportSpec,
    VisualQAEvidenceManifest,
    VisualQAGate,
    VisualQAPolicy,
    VisualQAVerdict,
    WebGLErrorRecord,
    checksum_bytes,
)

__all__ += [
    "BrowserAcceptancePlanner", "BrowserRunReceipt", "BrowserSpec", "BrowserSupport",
    "ConsoleRecord", "DEFAULT_BROWSERS", "DEFAULT_SCENARIOS", "DEFAULT_VIEWPORTS",
    "EvidenceEntry", "EvidenceKind", "EvidenceManifestBuilder", "ScenarioResult",
    "SmokeScenario", "ViewportSpec", "VisualQAEvidenceManifest", "VisualQAGate",
    "VisualQAPolicy", "VisualQAVerdict", "WebGLErrorRecord", "checksum_bytes",
]

from .performance import (
    DEFAULT_PERFORMANCE_BUDGETS,
    PerformanceBudget,
    PerformanceGate,
    PerformanceGateResult,
    PerformanceReceipt,
    PerformanceReceiptBuilder,
    PerformanceSample,
    PerformanceViolation,
    ReleaseEvidence,
    ReleaseGateResult,
    ThreeDReleaseGate,
)

__all__ += [
    "DEFAULT_PERFORMANCE_BUDGETS", "PerformanceBudget", "PerformanceGate",
    "PerformanceGateResult", "PerformanceReceipt", "PerformanceReceiptBuilder",
    "PerformanceSample", "PerformanceViolation", "ReleaseEvidence",
    "ReleaseGateResult", "ThreeDReleaseGate",
]

from .lifecycle import (
    ApprovalDecision,
    LifecycleInputs,
    LifecycleResult,
    LifecycleStage,
    OwnerEvidence,
    RemediationRecommendation,
    ThreeDProjectLifecycle,
)

__all__ += [
    "ApprovalDecision",
    "LifecycleInputs",
    "LifecycleResult",
    "LifecycleStage",
    "OwnerEvidence",
    "RemediationRecommendation",
    "ThreeDProjectLifecycle",
]
