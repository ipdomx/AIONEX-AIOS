"""Versioned, permission-governed plugin SDK."""

from .models import PluginManifest, PluginPackage, PluginState
from .permissions import PluginPermissionEvaluator, PluginPermissionPolicy
from .registry import PluginRegistry
from .runtime import PluginExecutionContext, PluginExecutionResult, PluginRuntime

__all__ = [
    "PluginExecutionContext",
    "PluginExecutionResult",
    "PluginManifest",
    "PluginPackage",
    "PluginPermissionEvaluator",
    "PluginPermissionPolicy",
    "PluginRegistry",
    "PluginRuntime",
    "PluginState",
]
