from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from aios.three_d_web.expansion import InteractiveTarget
from aios.three_d_web.two_d import TwoDProjectBuilder


_CANVAS_RUNTIME = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const {source, scenario} = JSON.parse(fs.readFileSync(0, "utf8"));
const callbacks = [];
const listeners = new Map();
let rects = [], texts = [], scheduled = 0, prevented = 0;
const context = {
  fillStyle: "",
  clearRect() { rects = []; texts = []; },
  fillRect(x, y, width, height) {
    rects.push({x, y, width, height, color: this.fillStyle});
  },
  fillText(text, x, y) { texts.push({text, x, y}); }
};
const canvas = {getContext() { return context; }, focus() {}};
const sandbox = {
  window: {},
  document: {getElementById() { return canvas; }},
  addEventListener(type, callback) { listeners.set(type, callback); },
  requestAnimationFrame(callback) { callbacks.push(callback); return ++scheduled; }
};
vm.createContext(sandbox);
vm.runInContext(source, sandbox, {timeout: 1000});
function advance(count) {
  let executed = 0;
  for (; executed < count; executed++) {
    const next = callbacks.shift();
    if (!next) break;
    next(executed * 1000 / 60);
  }
  return executed;
}
function snapshot() {
  return JSON.parse(JSON.stringify({
    evidence: sandbox.window.__AIOS_EVIDENCE__, rects, texts,
    pending: callbacks.length, prevented
  }));
}
function key(value) {
  const handler = listeners.get("keydown");
  if (!handler) throw new Error("No keyboard handler");
  handler({key: value, preventDefault() { prevented++; }});
}
let result;
if (scenario === "animation") {
  const firstAdvanced = advance(600);
  const first = snapshot();
  const secondAdvanced = advance(50);
  result = {firstAdvanced, first, secondAdvanced, second: snapshot()};
} else if (scenario === "game") {
  const firstAdvanced = advance(600);
  const first = snapshot();
  key("ArrowRight");
  const rightAdvanced = advance(1);
  const right = snapshot();
  key("ArrowLeft");
  key(" ");
  const finalAdvanced = advance(3);
  result = {firstAdvanced, first, rightAdvanced, right, finalAdvanced, final: snapshot()};
} else {
  throw new Error("Unknown scenario");
}
process.stdout.write(JSON.stringify(result));
"""


def _execute_canvas_runtime(script: Path, scenario: str) -> dict[str, object]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to execute the generated 2D JavaScript")
    completed = subprocess.run(
        [node, "-e", _CANVAS_RUNTIME],
        input=json.dumps({"source": script.read_text(encoding="utf-8"), "scenario": scenario}),
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
        timeout=10,
    )
    return json.loads(completed.stdout)


def test_animation_keeps_rendering_after_extended_playback(tmp_path: Path) -> None:
    destination = tmp_path / "animation"
    TwoDProjectBuilder().build(
        organization_id="tenant-animation", project_id="continuous-animation",
        target=InteractiveTarget.TWO_D_ANIMATION, destination=destination,
    )
    result = _execute_canvas_runtime(destination / "animation.js", "animation")
    assert result["firstAdvanced"] == 600
    assert result["secondAdvanced"] == 50
    first, second = result["first"], result["second"]
    assert first["evidence"]["ready"] is True
    assert second["evidence"]["frames"] == 650
    assert first["pending"] == second["pending"] == 1
    assert first["evidence"]["x"] != second["evidence"]["x"]
    assert first["rects"][-1]["x"] != second["rects"][-1]["x"]


def test_game_keeps_rendering_late_keyboard_input(tmp_path: Path) -> None:
    destination = tmp_path / "game"
    TwoDProjectBuilder().build(
        organization_id="tenant-game", project_id="continuous-game",
        target=InteractiveTarget.TWO_D_GAME, destination=destination,
    )
    result = _execute_canvas_runtime(destination / "game.js", "game")
    assert result["firstAdvanced"] == 600
    assert result["rightAdvanced"] == 1
    assert result["finalAdvanced"] == 3
    first, right, final = result["first"], result["right"], result["final"]
    assert final["evidence"]["frames"] == 604
    assert first["pending"] == right["pending"] == final["pending"] == 1
    assert right["evidence"]["x"] == first["evidence"]["x"] + 12
    assert right["rects"][-1]["x"] == right["evidence"]["x"]
    assert final["evidence"]["x"] == first["evidence"]["x"]
    assert final["rects"][-1]["x"] == final["evidence"]["x"]
    assert final["evidence"]["score"] == first["evidence"]["score"] + 1
    assert final["texts"][-1]["text"] == f"score:{final['evidence']['score']}"
    assert final["prevented"] == 1
