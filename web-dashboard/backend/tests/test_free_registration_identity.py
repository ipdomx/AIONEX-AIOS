from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException

from app.services.free_tier import _age_on, _assert_real_device_signals


def test_minimum_age_calculation_is_calendar_correct():
    assert _age_on(date(2000, 8, 1), date(2026, 7, 31)) == 25
    assert _age_on(date(2000, 7, 31), date(2026, 7, 31)) == 26


def test_real_device_signals_accept_supported_browser():
    _assert_real_device_signals(
        {
            "cookie_enabled": True,
            "webdriver": False,
            "hardware_concurrency": 8,
            "platform": "iPhone",
            "user_agent": "Mozilla/5.0 Mobile Safari/604.1",
        }
    )


def test_real_device_signals_fail_closed_for_headless_browser():
    with pytest.raises(HTTPException) as exc:
        _assert_real_device_signals(
            {
                "cookie_enabled": True,
                "hardware_concurrency": 8,
                "platform": "Linux x86_64",
                "user_agent": "HeadlessChrome",
            }
        )
    assert exc.value.status_code == 422
