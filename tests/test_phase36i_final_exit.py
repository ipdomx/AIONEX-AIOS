from aios.three_d_web.contracts import PerformanceProfile
from aios.three_d_web.performance import PerformanceGateResult
from aios.three_d_web.vfx_exit import (
    LODCompressionEvidence,
    Phase36IExitGate,
    Phase36IExitError,
    VFXCompositePlan,
    VFXRuntimeEvidence,
)
import pytest


def _vfx(**overrides):
    values = dict(ffmpeg_version="9.0", output_sha256="a"*64, output_bytes=1000,
                  width=1280, height=720, fps=30.0, duration_seconds=3.0, codec="h264",
                  frames=90, chroma_key_applied=True, overlay_applied=True,
                  network_used=False, provider_used=False)
    values.update(overrides)
    return VFXRuntimeEvidence(**values)


def _lod(**overrides):
    values = dict(source_sha256="a"*64, desktop_sha256="b"*64, mobile_sha256="c"*64,
                  low_power_sha256="d"*64, source_bytes=5000, desktop_bytes=4000,
                  mobile_bytes=3000, low_power_bytes=2500, meshopt_present=True, network_used=False)
    values.update(overrides)
    return LODCompressionEvidence(**values)


def _perf():
    return tuple(PerformanceGateResult(profile, True, ()) for profile in PerformanceProfile)


def test_vfx_plan_and_runtime_are_fail_closed():
    plan = VFXCompositePlan()
    plan.validate()
    _vfx().validate(plan)
    with pytest.raises(Phase36IExitError, match="network/provider"):
        _vfx(network_used=True).validate(plan)
    with pytest.raises(Phase36IExitError, match="resolution"):
        VFXCompositePlan(width=640).validate()


def test_lod_requires_real_meshopt_and_nonempty_artifacts():
    _lod().validate()
    with pytest.raises(Phase36IExitError, match="Meshopt"):
        _lod(meshopt_present=False).validate()


def test_exit_gate_closes_local_work_but_preserves_physical_xr_gate():
    decision = Phase36IExitGate().evaluate(
        vfx=_vfx(), vfx_plan=VFXCompositePlan(), lod=_lod(), performance_results=_perf(),
        browser_qa_passed=True, blender_3d_passed=True, two_d_passed=True,
        webxr_secure_context_passed=True, physical_xr_device_tested=False,
    )
    assert decision.passed is True
    assert decision.local_complete is True
    assert decision.external_gate_preserved is True
    assert decision.reasons == ()
    assert len(decision.receipt_sha256) == 64


def test_exit_gate_rejects_missing_performance_profile():
    decision = Phase36IExitGate().evaluate(
        vfx=_vfx(), vfx_plan=VFXCompositePlan(), lod=_lod(), performance_results=_perf()[:2],
        browser_qa_passed=True, blender_3d_passed=True, two_d_passed=True,
        webxr_secure_context_passed=True, physical_xr_device_tested=False,
    )
    assert decision.passed is False
    assert decision.local_complete is False
