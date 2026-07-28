from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class ApiVersion:
    name: str
    released_on: date
    deprecated_on: date | None = None
    sunset_on: date | None = None

    def is_deprecated(self, today: date) -> bool:
        return self.deprecated_on is not None and today >= self.deprecated_on

    def is_sunset(self, today: date) -> bool:
        return self.sunset_on is not None and today >= self.sunset_on


class ApiVersionRegistry:
    def __init__(self) -> None:
        self._versions: dict[str, ApiVersion] = {}
        self._default: str | None = None

    def register(self, version: ApiVersion, *, default: bool = False) -> ApiVersion:
        if version.name in self._versions:
            raise ValueError(f"duplicate API version: {version.name}")
        if version.sunset_on and version.deprecated_on and version.sunset_on < version.deprecated_on:
            raise ValueError("sunset date cannot precede deprecation date")
        self._versions[version.name] = version
        if default or self._default is None:
            self._default = version.name
        return version

    def resolve(self, requested: str | None, *, today: date) -> ApiVersion:
        name = requested or self._default
        if name is None or name not in self._versions:
            raise KeyError(f"unknown API version: {name}")
        version = self._versions[name]
        if version.is_sunset(today):
            raise RuntimeError(f"API version is sunset: {name}")
        return version
