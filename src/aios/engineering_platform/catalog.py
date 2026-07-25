from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LanguageCapability:
    name: str
    extensions: tuple[str, ...]
    domains: tuple[str, ...]


class LanguageCapabilityRegistry:
    def __init__(self) -> None:
        self._items: dict[str, LanguageCapability] = {}

    def register(self, item: LanguageCapability) -> None:
        self._items[item.name.lower()] = item

    def get(self, name: str) -> LanguageCapability:
        return self._items[name.lower()]

    def supports(self, name: str) -> bool:
        return name.lower() in self._items

    def list(self) -> tuple[LanguageCapability, ...]:
        return tuple(sorted(self._items.values(), key=lambda item: item.name))


def build_default_language_registry() -> LanguageCapabilityRegistry:
    registry = LanguageCapabilityRegistry()
    definitions = (
        ("Python", (".py",), ("backend", "ai", "automation", "data")),
        ("TypeScript", (".ts", ".tsx"), ("frontend", "backend", "three.js")),
        ("JavaScript", (".js", ".jsx", ".mjs"), ("frontend", "backend", "three.js")),
        ("Rust", (".rs",), ("systems", "security", "performance")),
        ("Go", (".go",), ("backend", "cloud", "distributed")),
        ("Java", (".java",), ("enterprise", "backend", "android")),
        ("Kotlin", (".kt", ".kts"), ("android", "backend")),
        ("Swift", (".swift",), ("ios", "macos")),
        ("Dart", (".dart",), ("flutter", "mobile", "web")),
        ("C", (".c", ".h"), ("systems", "embedded")),
        ("C++", (".cc", ".cpp", ".hpp"), ("systems", "graphics", "games")),
        ("C#", (".cs",), ("enterprise", "games", "backend")),
        ("PHP", (".php",), ("web", "backend")),
        ("SQL", (".sql",), ("database", "analytics")),
    )
    for name, extensions, domains in definitions:
        registry.register(LanguageCapability(name, extensions, domains))
    return registry
