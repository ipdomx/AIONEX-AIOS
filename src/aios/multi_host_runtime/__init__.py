from __future__ import annotations

from .auth import (
    HostRequestAuthenticator,
    MultiHostAuthenticationError,
    VerifiedHostRequest,
    certificate_sha256,
)
from .client import MultiHostClientError, MultiHostControlClient, MultiHostHTTPResponse
from .cycle import (
    DEFAULT_PHASE22D_SOURCE,
    DEFAULT_PHASE24B_OUTPUT,
    MultiHostCycleValidationError,
    MultiHostProjectCycle,
)
from .models import HostLeaderLease, HostRecord, HostState, MultiHostCycleResult
from .store import MultiHostControlStore

_LAZY_EXPORTS = {
    "HostSecretRegistry": (".control_plane", "HostSecretRegistry"),
    "MultiHostControlPlane": (".control_plane", "MultiHostControlPlane"),
    "MultiHostHTTPServer": (".control_plane", "MultiHostHTTPServer"),
    "MultiHostAgent": (".agent", "MultiHostAgent"),
    "MultiHostAgentConfig": (".agent", "MultiHostAgentConfig"),
}


def __getattr__(name: str):
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    from importlib import import_module

    module = import_module(target[0], __name__)
    value = getattr(module, target[1])
    globals()[name] = value
    return value


__all__ = [
    "DEFAULT_PHASE22D_SOURCE",
    "DEFAULT_PHASE24B_OUTPUT",
    "HostLeaderLease",
    "HostRecord",
    "HostRequestAuthenticator",
    "HostSecretRegistry",
    "HostState",
    "MultiHostAgent",
    "MultiHostAgentConfig",
    "MultiHostAuthenticationError",
    "MultiHostClientError",
    "MultiHostControlClient",
    "MultiHostControlPlane",
    "MultiHostControlStore",
    "MultiHostCycleResult",
    "MultiHostCycleValidationError",
    "MultiHostHTTPResponse",
    "MultiHostHTTPServer",
    "MultiHostProjectCycle",
    "VerifiedHostRequest",
    "certificate_sha256",
]
