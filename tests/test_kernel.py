from aios.kernel import AIOSKernel


def test_kernel_status():
    kernel = AIOSKernel()

    status = kernel.status()

    assert status["name"] == "AIOS"
    assert status["version"] == "2.3.0-beta.5"
    assert status["constitution"] == "enforced"
