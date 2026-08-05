from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .auth import (
    ClusterAuthenticationError,
    ClusterAuthenticator,
    VerifiedClusterIdentity,
)
from .client import ClusterClientError, ClusterHTTPResponse, SecureClusterClient
from .cycle import (
    ClusterCycleValidationError,
    MultiNodeProjectCycle,
    Phase24AResult,
)
from .state import (
    ClusterNodeRecord,
    ClusterNodeState,
    ClusterStateStore,
    LeaderLease,
    PeerObservation,
)

if TYPE_CHECKING:
    from .node import ClusterNodeConfig, ClusterNodeRuntime

__all__ = [
    "ClusterAuthenticationError",
    "ClusterAuthenticator",
    "VerifiedClusterIdentity",
    "ClusterClientError",
    "ClusterHTTPResponse",
    "SecureClusterClient",
    "ClusterCycleValidationError",
    "MultiNodeProjectCycle",
    "Phase24AResult",
    "ClusterNodeConfig",
    "ClusterNodeRuntime",
    "ClusterNodeRecord",
    "ClusterNodeState",
    "ClusterStateStore",
    "LeaderLease",
    "PeerObservation",
]


def __getattr__(name: str) -> Any:
    if name in {"ClusterNodeConfig", "ClusterNodeRuntime"}:
        from .node import ClusterNodeConfig, ClusterNodeRuntime

        return {
            "ClusterNodeConfig": ClusterNodeConfig,
            "ClusterNodeRuntime": ClusterNodeRuntime,
        }[name]
    raise AttributeError(name)
