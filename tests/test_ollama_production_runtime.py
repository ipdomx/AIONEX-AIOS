from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "ollama/ollama@sha256:1685741456770df6e3cceb2a945a5f75e020f658d1701509668d6f4688f1dd3f"


def test_live_production_compose_keeps_ollama_private_and_pinned() -> None:
    compose = (ROOT / "web-dashboard/docker-compose.production.yml").read_text()
    assert f"  ollama:\n    image: {IMAGE}" in compose
    block = compose[compose.index("  ollama:\n"):compose.index("  ollama-model-bootstrap:\n")]
    assert "ports:" not in block
    assert "expose:" not in block
    assert "ollama_model_data:/root/.ollama" in block
    assert 'OLLAMA_CONTEXT_LENGTH: "8192"' in block
    assert 'cpus: "6.0"' in block
    assert "mem_limit: 8g" in block
    assert 'cap_drop: ["ALL"]' in block
    assert 'command: ["pull", "gemma3:4b"]' in compose
    assert "OLLAMA_HOST: http://ollama:11434" in compose


def test_alternative_production_compose_keeps_same_private_ollama_contract() -> None:
    compose = (ROOT / "deploy/production/docker-compose.production.yml").read_text()
    assert f"  ollama:\n    image: {IMAGE}" in compose
    block = compose[compose.index("  ollama:\n"):compose.index("  ollama-model-bootstrap:\n")]
    assert "ports:" not in block
    assert "expose:" not in block
    assert "ollama_model_data:/root/.ollama" in block
    assert 'command: ["pull", "gemma3:4b"]' in compose
