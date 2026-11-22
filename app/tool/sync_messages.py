#!/usr/bin/env python3
"""Build the app's ARB translation files from the website's messages.

The website (vip-frontend/src/messages/<lang>.json) is the single source of
every user-facing sentence, so a wording fix there reaches the app too.
Strings that exist only in the app live in app/l10n_extra/<lang>.json.

    python3 app/tool/sync_messages.py          # write app/lib/l10n/*.arb
    python3 app/tool/sync_messages.py --check  # CI: fail if the ARB files are stale

Nested keys are flattened with "_" (auth.signIn -> auth_signIn) and app-only
keys get the "app_" prefix (systemLanguage -> app_systemLanguage).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEBSITE_MESSAGES = ROOT / "vip-frontend" / "src" / "messages"
APP_EXTRA = ROOT / "app" / "l10n_extra"
ARB_DIR = ROOT / "app" / "lib" / "l10n"
LANGUAGES = ("en", "ar", "de", "es", "fr", "tr")
TEMPLATE = "en"
_IDENTIFIER = re.compile(r"^[a-z][A-Za-z0-9_]*$")


def _segment(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]", "_", name)
    return cleaned or "x"


def flatten(tree: object, prefix: str = "") -> dict[str, str]:
    """Flatten a nested message tree into ARB-safe identifiers."""

    if isinstance(tree, str):
        return {prefix: tree}
    if not isinstance(tree, dict):
        raise TypeError(f"{prefix or '<root>'}: unsupported value {type(tree).__name__}")
    flat: dict[str, str] = {}
    for name, value in tree.items():
        key = f"{prefix}_{_segment(name)}" if prefix else _segment(name)
        for flat_key, text in flatten(value, key).items():
            if flat_key in flat:
                raise ValueError(f"duplicate key after flattening: {flat_key}")
            flat[flat_key] = text
    return flat


def _identifier(key: str) -> str:
    candidate = key[0].lower() + key[1:]
    if not _IDENTIFIER.match(candidate):
        candidate = "k_" + candidate
    if not _IDENTIFIER.match(candidate):
        raise ValueError(f"cannot turn {key!r} into a Dart identifier")
    return candidate


def load_language(language: str) -> dict[str, str]:
    website = json.loads((WEBSITE_MESSAGES / f"{language}.json").read_text("utf-8"))
    messages = {_identifier(key): text for key, text in flatten(website).items()}
    extra_path = APP_EXTRA / f"{language}.json"
    if extra_path.exists():
        extra = json.loads(extra_path.read_text("utf-8"))
        for key, text in flatten(extra).items():
            app_key = _identifier(f"app_{key}")
            if app_key in messages:
                raise ValueError(f"app key {app_key} collides with a website key")
            messages[app_key] = text
    return messages


def render(language: str, messages: dict[str, str]) -> str:
    document: dict[str, str] = {"@@locale": language}
    for key in sorted(messages):
        document[key] = messages[key]
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail when ARB files are out of date")
    args = parser.parse_args()

    template_keys = set(load_language(TEMPLATE))
    stale: list[str] = []
    ARB_DIR.mkdir(parents=True, exist_ok=True)
    for language in LANGUAGES:
        messages = load_language(language)
        unknown = sorted(set(messages) - template_keys)
        if unknown:
            print(f"{language}: keys missing from {TEMPLATE}: {', '.join(unknown[:10])}", file=sys.stderr)
            return 1
        target = ARB_DIR / f"app_{language}.arb"
        content = render(language, messages)
        if args.check:
            if not target.exists() or target.read_text("utf-8") != content:
                stale.append(target.relative_to(ROOT).as_posix())
            continue
        target.write_text(content, "utf-8")
        print(f"{target.relative_to(ROOT)}: {len(messages)} messages")
    if stale:
        print("Out of date (run python3 app/tool/sync_messages.py):", *stale, sep="\n  ", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
