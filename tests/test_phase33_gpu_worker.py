from __future__ import annotations

import pytest

from aios.gpu_worker import (
    HunyuanGPUWorkerController,
    HunyuanServerlessController,
    RunPodClient,
    RunPodServerlessClient,
)


def test_runpod_requires_key():
    with pytest.raises(ValueError):
        RunPodClient("")


def test_controller_requires_https():
    with pytest.raises(ValueError):
        HunyuanGPUWorkerController(RunPodClient("x"), pod_id="pod", api_url="http://example", worker_token="x")


def test_controller_requires_worker_token():
    with pytest.raises(ValueError):
        HunyuanGPUWorkerController(RunPodClient("x"), pod_id="pod", api_url="https://example")


def test_serverless_requires_endpoint():
    with pytest.raises(ValueError):
        RunPodServerlessClient("x", "")


def test_serverless_runtime_boundary():
    client = RunPodServerlessClient("x", "endpoint")
    with pytest.raises(ValueError):
        HunyuanServerlessController(client, max_runtime_seconds=30)
