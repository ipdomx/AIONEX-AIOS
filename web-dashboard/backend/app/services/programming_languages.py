"""Governed programming-language capability registry.

The registry is descriptive and policy-oriented: it tells projects which source
languages AIOS understands, how files are identified, and whether an isolated
runner is configured. It does not execute untrusted code by itself.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ProgrammingLanguage:
    id: str
    name: str
    aliases: tuple[str, ...]
    extensions: tuple[str, ...]
    family: str
    runner: str | None
    formatter: str | None
    linter: str | None


LANGUAGES: tuple[ProgrammingLanguage, ...] = (
    ProgrammingLanguage("python", "Python", ("py",), (".py",), "general", "python3", "black", "ruff"),
    ProgrammingLanguage("javascript", "JavaScript", ("js", "node"), (".js", ".mjs", ".cjs"), "web", "node", "prettier", "eslint"),
    ProgrammingLanguage("typescript", "TypeScript", ("ts",), (".ts", ".tsx"), "web", "tsx", "prettier", "eslint"),
    ProgrammingLanguage("java", "Java", ("jdk",), (".java",), "jvm", "java", "google-java-format", "checkstyle"),
    ProgrammingLanguage("csharp", "C#", ("c#", "dotnet"), (".cs",), "dotnet", "dotnet", "dotnet format", "dotnet format"),
    ProgrammingLanguage("go", "Go", ("golang",), (".go",), "systems", "go run", "gofmt", "go vet"),
    ProgrammingLanguage("rust", "Rust", ("rs",), (".rs",), "systems", "cargo run", "rustfmt", "clippy"),
    ProgrammingLanguage("cpp", "C++", ("c++", "cplusplus"), (".cpp", ".cc", ".hpp"), "systems", "g++", "clang-format", "clang-tidy"),
    ProgrammingLanguage("c", "C", (), (".c", ".h"), "systems", "gcc", "clang-format", "clang-tidy"),
    ProgrammingLanguage("php", "PHP", (), (".php",), "web", "php", "php-cs-fixer", "phpstan"),
    ProgrammingLanguage("ruby", "Ruby", ("rb",), (".rb",), "general", "ruby", "rubocop", "rubocop"),
    ProgrammingLanguage("kotlin", "Kotlin", ("kt",), (".kt", ".kts"), "jvm", "kotlinc", "ktfmt", "detekt"),
    ProgrammingLanguage("swift", "Swift", (), (".swift",), "apple", "swift", "swift-format", "swiftlint"),
    ProgrammingLanguage("dart", "Dart", ("flutter",), (".dart",), "mobile", "dart run", "dart format", "dart analyze"),
    ProgrammingLanguage("sql", "SQL", (), (".sql",), "data", None, "sqlfluff", "sqlfluff"),
    ProgrammingLanguage("bash", "Shell", ("shell", "sh"), (".sh", ".bash"), "automation", "bash", "shfmt", "shellcheck"),
    ProgrammingLanguage("powershell", "PowerShell", ("pwsh",), (".ps1",), "automation", "pwsh", None, "PSScriptAnalyzer"),
    ProgrammingLanguage("r", "R", (), (".r", ".R"), "data", "Rscript", "styler", "lintr"),
    ProgrammingLanguage("scala", "Scala", (), (".scala",), "jvm", "scala", "scalafmt", "scalafix"),
    ProgrammingLanguage("elixir", "Elixir", ("ex",), (".ex", ".exs"), "beam", "elixir", "mix format", "credo"),
)


def programming_language_manifest() -> list[dict[str, object]]:
    return [asdict(language) for language in LANGUAGES]


def identify_language(filename: str) -> ProgrammingLanguage | None:
    lowered = filename.lower()
    for language in LANGUAGES:
        if any(lowered.endswith(extension.lower()) for extension in language.extensions):
            return language
    return None
