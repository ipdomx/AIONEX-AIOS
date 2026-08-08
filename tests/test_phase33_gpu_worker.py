from __future__ import annotations

import pytest

from aios.gpu_worker import HunyuanGPUWorkerController, RunPodClient


def test_runpod_requires_key():
    with pytest.raises(ValueError):
        RunPodClient("")


def test_controller_requires_https():
    with pytest.raises(ValueError):
        HunyuanGPUWorkerController(RunPodClient("x"), pod_id="pod", api_url="http://example")
