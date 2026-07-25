from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterable


class ValidationSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    message: str
    severity: ValidationSeverity = ValidationSeverity.ERROR
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ValidationReport:
    valid: bool
    issues: tuple[ValidationIssue, ...]


class InfrastructureValidator:
    def __init__(self) -> None:
        self._checks: list[Callable[[dict[str, Any]], ValidationIssue | None]] = []

    def register(self, check: Callable[[dict[str, Any]], ValidationIssue | None]) -> None:
        self._checks.append(check)

    def validate(self, configuration: dict[str, Any]) -> ValidationReport:
        issues = tuple(issue for check in self._checks if (issue := check(configuration)) is not None)
        valid = not any(issue.severity is ValidationSeverity.ERROR for issue in issues)
        return ValidationReport(valid, issues)

    @classmethod
    def default(cls) -> "InfrastructureValidator":
        validator = cls()

        def require_environment(config: dict[str, Any]) -> ValidationIssue | None:
            return None if config.get("environment") else ValidationIssue("environment.missing", "environment is required")

        def require_image(config: dict[str, Any]) -> ValidationIssue | None:
            image = str(config.get("image", ""))
            return None if image and ":" in image else ValidationIssue("image.invalid", "immutable image tag is required")

        def require_replicas(config: dict[str, Any]) -> ValidationIssue | None:
            replicas = config.get("replicas", 0)
            return None if isinstance(replicas, int) and replicas > 0 else ValidationIssue("replicas.invalid", "replicas must be positive")

        def warn_latest(config: dict[str, Any]) -> ValidationIssue | None:
            image = str(config.get("image", ""))
            if image.endswith(":latest"):
                return ValidationIssue("image.latest", "latest tag is not recommended", ValidationSeverity.WARNING)
            return None

        for check in (require_environment, require_image, require_replicas, warn_latest):
            validator.register(check)
        return validator
