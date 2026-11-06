"""P4 pure metric units: Insights parsing, throttling, windows, KPIs, alerts, guards.

No database and no provider: these are the deterministic rules the insights
worker, the analytics API, the spend guard and the AI grounding rely on.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from app.services import ads_metrics as metrics


def _raw(day: str, **values):
    base = {
        "campaign_id": "120000000000001",
        "campaign_name": "Spring sale",
        "adset_id": "120000000000002",
        "ad_id": "120000000000003",
        "date_start": day,
        "date_stop": day,
        "spend": "12.50",
        "impressions": "1000",
        "reach": "800",
        "clicks": "40",
        "inline_link_clicks": "30",
        "ctr": "4.0",
        "cpc": "0.3125",
        "cpm": "12.5",
        "frequency": "1.25",
        "actions": [
            {"action_type": "omni_purchase", "value": "3"},
            {"action_type": "purchase", "value": "3"},
            {"action_type": "offsite_conversion.fb_pixel_purchase", "value": "3"},
            {"action_type": "lead", "value": "2"},
            {"action_type": "link_click", "value": "30"},
        ],
        "action_values": [{"action_type": "omni_purchase", "value": "75.00"}],
    }
    base.update(values)
    return base


def _row(day: date, campaign: str = "1", **values):
    row = {
        "object_id": campaign,
        "object_name": f"Campaign {campaign}",
        "day": day,
        "breakdown": "none",
        "breakdown_value": "",
        "spend": 10.0,
        "impressions": 1000,
        "reach": 500,
        "clicks": 20,
        "link_clicks": 15,
        "conversions": 2.0,
        "conversion_value": 40.0,
    }
    row.update(values)
    return row


def test_insight_row_is_normalized_and_conversions_are_not_double_counted() -> None:
    row = metrics.parse_insight_row(_raw("2026-11-01"), level="campaign")
    assert row["object_id"] == "120000000000001" and row["day"] == date(2026, 11, 1)
    assert row["spend"] == 12.5 and row["impressions"] == 1000 and row["link_clicks"] == 30
    # omni_purchase wins over purchase and the pixel counter; leads are added.
    assert row["conversions"] == 5.0 and row["conversion_value"] == 75.0
    assert row["breakdown"] == "none" and row["breakdown_value"] == ""
    adset = metrics.parse_insight_row(_raw("2026-11-01"), level="adset")
    assert adset["object_id"] == "120000000000002" and adset["campaign_id"] == "120000000000001"


def test_breakdowns_and_bad_rows_fail_closed() -> None:
    row = metrics.parse_insight_row(
        _raw("2026-11-01", publisher_platform="Instagram", platform_position="Reels"),
        level="campaign",
        breakdown="platform_position",
    )
    assert row["breakdown_value"] == "instagram:reels"
    for bad in (
        _raw("2026-11-01", campaign_id="act_1"),
        _raw("11/01/2026"),
        _raw("2026-11-01", spend="-1"),
        _raw("2026-11-01", impressions="NaN"),
    ):
        try:
            metrics.parse_insight_row(bad, level="campaign")
        except metrics.MetricError:
            continue
        raise AssertionError(f"row should be rejected: {bad}")


def test_throttle_headers_are_read_from_every_meta_usage_header() -> None:
    headers = {
        "X-App-Usage": json.dumps({"call_count": 12, "total_time": 30, "total_cputime": 5}),
        "x-ad-account-usage": json.dumps({"acc_id_util_pct": 81.5, "reset_time_duration": 120}),
        "x-business-use-case-usage": json.dumps(
            {"123": [{"type": "ads_insights", "call_count": 40, "total_time": 90, "estimated_time_to_regain_access": 7}]}
        ),
        "x-fb-ads-insights-throttle": json.dumps({"app_id_util_pct": 20, "acc_id_util_pct": 10}),
    }
    throttle = metrics.parse_throttle(headers)
    assert throttle.usage_pct == 90 and throttle.retry_after_seconds == 420
    assert set(throttle.sources) == {"app", "ad_account", "business_use_case", "insights"}
    assert throttle.exceeded(75) and metrics.backoff_seconds(throttle) == 420
    calm = metrics.parse_throttle({"x-app-usage": '{"call_count": 3}', "x-ad-account-usage": "not json"})
    assert not calm.exceeded(75) and metrics.backoff_seconds(calm) == 300


def test_sync_window_is_incremental_with_attribution_lookback() -> None:
    today = date(2026, 11, 6)
    first = metrics.sync_window(today, None, initial_backfill_days=30, lookback_days=3)
    assert first == (date(2026, 10, 8), today) and metrics.days_in(*first) == 30
    later = metrics.sync_window(today, date(2026, 11, 5), initial_backfill_days=30, lookback_days=3)
    assert later == (date(2026, 11, 2), today)
    capped = metrics.sync_window(today, date(2020, 1, 1), initial_backfill_days=30, lookback_days=3)
    assert capped[0] == today - timedelta(days=400)


def test_kpis_compare_periods_and_derive_ratios() -> None:
    start, end = date(2026, 11, 1), date(2026, 11, 7)
    assert metrics.previous_period(start, end) == (date(2026, 10, 25), date(2026, 10, 31))
    current = [_row(start + timedelta(days=offset)) for offset in range(7)]
    previous = [_row(date(2026, 10, 25) + timedelta(days=offset), spend=5.0) for offset in range(7)]
    kpis = metrics.compare_kpis(current, previous)
    assert kpis["spend"] == {"value": 70.0, "previous": 35.0, "change_pct": 100.0}
    assert kpis["ctr"]["value"] == 2.0 and kpis["cpm"]["value"] == 10.0
    assert kpis["cpa"]["value"] == 5.0 and kpis["roas"]["value"] == 4.0
    empty = metrics.compare_kpis([], [])
    assert empty["cpa"] == {"value": None, "previous": None, "change_pct": None}
    trend = metrics.daily_trend(current[:2], start, start + timedelta(days=2))
    assert [item["day"] for item in trend] == ["2026-11-01", "2026-11-02", "2026-11-03"]
    assert trend[2]["spend"] == 0.0


def test_ranking_uses_roas_then_cpa() -> None:
    day = date(2026, 11, 1)
    rows = [
        _row(day, "1", conversion_value=100.0),
        _row(day, "2", conversion_value=10.0),
        _row(day, "3", conversion_value=50.0),
    ]
    ranked = metrics.rank_campaigns(rows, limit=1)
    assert ranked["basis"] == "roas"
    assert ranked["top"][0]["campaign_id"] == "1" and ranked["bottom"][0]["campaign_id"] == "2"
    by_cpa = metrics.rank_campaigns(
        [_row(day, "1", conversion_value=0.0, conversions=1.0), _row(day, "2", conversion_value=0.0, conversions=5.0)]
    )
    assert by_cpa["basis"] == "cpa" and by_cpa["top"][0]["campaign_id"] == "2"


def test_breakdown_summary_groups_by_value() -> None:
    day = date(2026, 11, 1)
    rows = [
        _row(day, breakdown="age", breakdown_value="25-34", spend=30.0),
        _row(day, breakdown="age", breakdown_value="18-24", spend=10.0),
        _row(day, breakdown="age", breakdown_value="25-34", spend=5.0),
        _row(day),
    ]
    summary = metrics.breakdown_summary(rows)
    assert list(summary) == ["age"]
    assert summary["age"][0]["value"] == "25-34" and summary["age"][0]["spend"] == 35.0


def test_alerts_spend_spike_cpa_target_and_frequency_fatigue() -> None:
    as_of = date(2026, 11, 14)
    rows = []
    for offset in range(1, 14):
        day = as_of - timedelta(days=offset)
        # Previous week: healthy CTR. Last week: same spend, high frequency, CTR down.
        if offset >= 7:
            rows.append(_row(day, clicks=40, reach=900))
        else:
            rows.append(_row(day, clicks=10, reach=250))
    rows.append(_row(as_of, spend=40.0, clicks=10, reach=250))
    found = {alert["type"]: alert for alert in metrics.alerts(rows, as_of=as_of, cpa_target=4.0)}
    assert found["spend_spike"]["evidence"]["spend"] == 40.0
    assert found["spend_spike"]["evidence"]["average_prior_7_days"] == 10.0
    assert found["cpa_above_target"]["evidence"]["cpa_target"] == 4.0
    fatigue = found["frequency_fatigue"]["evidence"]
    assert fatigue["frequency_last_7_days"] >= 3.0 and fatigue["ctr_change_pct"] <= -20.0
    quiet = metrics.alerts([_row(as_of)], as_of=as_of, cpa_target=None)
    assert quiet == []


def test_spend_guard_activation_and_pause_decisions() -> None:
    caps = metrics.Caps(daily_minor=5000, lifetime_minor=50000)
    ok = metrics.activation_decision(
        caps, currency="USD", new_daily_budget_minor=2000, new_lifetime_budget_minor=0,
        active_daily_budgets_minor=2000, spend_today=10.0, spend_lifetime=100.0,
    )
    assert ok.allowed and ok.evidence["spend_today_minor"] == 1000
    over = metrics.activation_decision(
        caps, currency="USD", new_daily_budget_minor=3500, new_lifetime_budget_minor=0,
        active_daily_budgets_minor=2000, spend_today=0.0, spend_lifetime=0.0,
    )
    assert not over.allowed and over.code == "ads-daily-cap-exceeded"
    lifetime = metrics.activation_decision(
        caps, currency="USD", new_daily_budget_minor=0, new_lifetime_budget_minor=20000,
        active_daily_budgets_minor=0, spend_today=0.0, spend_lifetime=400.0,
    )
    assert lifetime.code == "ads-lifetime-cap-exceeded"
    unset = metrics.activation_decision(
        metrics.Caps(0, 0), currency="USD", new_daily_budget_minor=1, new_lifetime_budget_minor=0,
        active_daily_budgets_minor=0, spend_today=0.0, spend_lifetime=0.0,
    )
    assert unset.code == "ads-spend-cap-not-configured"
    assert metrics.pause_decision(caps, currency="USD", spend_today=50.0, spend_lifetime=60.0).code == "ads-daily-cap-reached"
    assert metrics.pause_decision(caps, currency="USD", spend_today=1.0, spend_lifetime=500.0).code == "ads-lifetime-cap-reached"
    assert not metrics.pause_decision(caps, currency="USD", spend_today=49.99, spend_lifetime=60.0).allowed
    # Zero-decimal currencies use Meta's offset of 1.
    assert metrics.to_minor(1500, "JPY") == 1500 and metrics.to_minor(15.0, "AED") == 1500


def test_recommendations_must_cite_existing_facts_and_never_auto_apply() -> None:
    grounding = {
        "kpis": {"cpa": {"value": 12.5, "previous": 9.0}},
        "campaigns": [{"campaign_id": "1", "name": "A", "spend": 300.0, "roas": 0.8}],
    }
    raw = [
        {
            "type": "budget_shift",
            "title": "Move budget away from A",
            "action": "Lower A's daily budget by 20%",
            "rationale": "ROAS below 1",
            "evidence": ["campaigns.0.roas", "campaigns.0.spend"],
        },
        {"type": "audience", "title": "Invented", "action": "x", "evidence": ["campaigns.0.ctr"]},
        {"type": "budget_shift", "title": "Partly invented", "action": "y", "evidence": ["kpis.cpa.value", "kpis.ctr.value"]},
        {"type": "unknown", "title": "t", "action": "a", "evidence": ["kpis.cpa.value"]},
        "not a dict",
    ]
    accepted, rejected = metrics.validate_recommendations(raw, grounding)
    assert rejected == 4 and len(accepted) == 1
    item = accepted[0]
    assert item["evidence"] == {"campaigns.0.roas": 0.8, "campaigns.0.spend": 300.0}
    assert item["advisory_only"] is True and item["auto_apply"] is False
    assert metrics.validate_recommendations("nope", grounding) == ([], 0)
