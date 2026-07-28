from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable


@dataclass(slots=True)
class PluginExecutionContext:
    plugin_id: str
    owner_id: str
    project_id: str
    permissions: set[str] = field(default_factory=set)
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class PluginExecutionResult:
    plugin_id: str
    success: bool
    output: object | None = None
    error: str | None = None
    executed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class PluginRuntime:
    def __init__(self) -> None:
        self._handlers: dict[str, Callable[[PluginExecutionContext, dict[str, object]], object]] = {}

    def register_handler(
        self,
        plugin_id: str,
        handler: Callable[[PluginExecutionContext, dict[str, object]], object],
    ) -> None:
        if plugin_id in self._handlers:
            raise ValueError(f"handler already registered: {plugin_id}")
        self._handlers[plugin_id] = handler

    def execute(
        self,
        context: PluginExecutionContext,
        payload: dict[str, object],
    ) -> PluginExecutionResult:
        handler = self._handlers.get(context.plugin_id)
        if handler is None:
            return PluginExecutionResult(
                plugin_id=context.plugin_id,
                success=False,
                error="plugin handler is not registered",
            )
        try:
            output = handler(context, payload)
        except Exception as exc:
            return PluginExecutionResult(
                plugin_id=context.plugin_id,
                success=False,
                error=str(exc),
            )
        return PluginExecutionResult(
            plugin_id=context.plugin_id,
            success=True,
            output=output,
        )
