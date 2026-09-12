import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "web-dashboard" / "frontend"


def _major(spec: str) -> int:
    digits = "".join(ch for ch in spec.lstrip("^~>=< ") if ch.isdigit() or ch == ".")
    return int(digits.split(".", 1)[0])


def test_typescript_eslint_plugin_and_parser_share_supported_major() -> None:
    package = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))
    dev = package["devDependencies"]
    plugin = dev["@typescript-eslint/eslint-plugin"]
    parser = dev["@typescript-eslint/parser"]
    assert _major(plugin) == _major(parser) == 8


def test_lockfile_resolves_plugin_and_parser_to_same_major() -> None:
    lock = json.loads((FRONTEND / "package-lock.json").read_text(encoding="utf-8"))
    packages = lock["packages"]
    plugin = packages["node_modules/@typescript-eslint/eslint-plugin"]["version"]
    parser = packages["node_modules/@typescript-eslint/parser"]["version"]
    assert plugin.split(".", 1)[0] == parser.split(".", 1)[0] == "8"
