"""Pure P4 Meta Ads metric logic: parsing, throttling, KPIs, alerts and guards.

Everything here is deterministic and free of I/O so it can be tested without a
database or a provider. Money from the Graph API arrives as decimal strings in
the ad account's currency (major units); budgets and caps use the currency's
minimum denomination ("minor" units, Meta's currency offset).
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Iterable, Mapping

LEVELS = ("campaign", "adset", "ad")
BREAKDOWNS: dict[str, tuple[str, ...]] = {
    "age": ("age",),
    "gender": ("gender",),
    "country": ("country",),
    # Meta only accepts platform_position together with publisher_platform.
    "platform_position": ("publisher_platform", "platform_position"),
}
INSIGHT_FIELDS = (
    "campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,spend,impressions,"
    "reach,clicks,inline_link_clicks,ctr,cpc,cpm,frequency,actions,action_values,"
    "date_start,date_stop,account_currency"
)
# Meta "offset 1" currencies: amounts are already in whole units.
ZERO_DECIMAL_CURRENCIES = frozenset(
    {"CLP", "COP", "CRC", "HUF", "ISK", "IDR", "JPY", "KRW", "PYG", "TWD", "VND"}
)
# First present action type wins inside a group, so overlapping pixel/omni
# counters are never added together.
PURCHASE_ACTIONS = ("omni_purchase", "purchase", "offsite_conversion.fb_pixel_purchase")
LEAD_ACTIONS = ("lead", "onsite_conversion.lead_grouped", "offsite_conversion.fb_pixel_lead")
# Graph error codes that mean "throttled; back off".
THROTTLE_ERROR_CODES = frozenset({4, 17, 32, 613, 80000, 80003, 80004, 80014})
_ID_RE = re.compile(r"^\d{1,32}$")
_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MAX_ACTION_KEYS = 40


class MetricError(ValueError):
    """A provider row that cannot be trusted; it is skipped, never guessed."""


def currency_offset(currency: str) -> int:
    return 1 if (currency or "").upper() in ZERO_DECIMAL_CURRENCIES else 100


def to_minor(amount: float, currency: str) -> int:
    return int(round(float(amount) * currency_offset(currency)))


def to_major(amount_minor: int, currency: str) -> float:
    return float(amount_minor) / currency_offset(currency)


def _number(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise MetricError("metric-not-numeric") from None
    if not math.isfinite(number) or number < 0:
        raise MetricError("metric-out-of-range")
    return number


def _optional_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return _number(value)


def _integer(value: Any) -> int:
    return int(round(_number(value)))


def _clean(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _action_map(raw: Any) -> dict[str, float]:
    values: dict[str, float] = {}
    if not isinstance(raw, list):
        return values
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = str(item.get("action_type") or "")
        if not re.fullmatch(r"[a-z0-9_.]{1,80}", key) or len(values) >= _MAX_ACTION_KEYS:
            continue
        try:
            values[key] = values.get(key, 0.0) + _number(item.get("value"))
        except MetricError:
            continue
    return values


def _first(values: Mapping[str, float], keys: tuple[str, ...]) -> tuple[str | None, float]:
    for key in keys:
        if key in values:
            return key, values[key]
    return None, 0.0


def conversions_from(actions: Mapping[str, float], action_values: Mapping[str, float]) -> tuple[float, float]:
    """Return (conversions, conversion value): purchases plus leads, value of purchases."""

    purchase_key, purchases = _first(actions, PURCHASE_ACTIONS)
    _lead_key, leads = _first(actions, LEAD_ACTIONS)
    value = action_values.get(purchase_key, 0.0) if purchase_key else 0.0
    if not value:
        _value_key, value = _first(action_values, PURCHASE_ACTIONS)
    return purchases + leads, value


def parse_day(value: Any) -> date:
    text = str(value or "")
    if not _DAY_RE.fullmatch(text):
        raise MetricError("insight-date-invalid")
    return date.fromisoformat(text)


def breakdown_value(raw: Mapping[str, Any], breakdown: str) -> str:
    if breakdown == "none":
        return ""
    keys = BREAKDOWNS.get(breakdown)
    if keys is None:
        raise MetricError("breakdown-unsupported")
    parts = [_clean(raw.get(key), 40).lower() or "unknown" for key in keys]
    return ":".join(parts)[:80]


def parse_insight_row(raw: Mapping[str, Any], *, level: str, breakdown: str = "none") -> dict[str, Any]:
    """Normalize one Graph Insights row; raises MetricError when it is unusable."""

    if level not in LEVELS:
        raise MetricError("level-unsupported")
    object_id = str(raw.get(f"{level}_id") or "")
    if not _ID_RE.fullmatch(object_id):
        raise MetricError("insight-object-id-invalid")
    campaign_id = str(raw.get("campaign_id") or "") or None
    adset_id = str(raw.get("adset_id") or "") or None
    if campaign_id is not None and not _ID_RE.fullmatch(campaign_id):
        campaign_id = None
    if adset_id is not None and not _ID_RE.fullmatch(adset_id):
        adset_id = None
    actions = _action_map(raw.get("actions"))
    action_values = _action_map(raw.get("action_values"))
    conversions, value = conversions_from(actions, action_values)
    return {
        "level": level,
        "object_id": object_id,
        "object_name": _clean(raw.get(f"{level}_name"), 240),
        "campaign_id": campaign_id,
        "adset_id": adset_id,
        "day": parse_day(raw.get("date_start")),
        "breakdown": breakdown,
        "breakdown_value": breakdown_value(raw, breakdown),
        "spend": round(_number(raw.get("spend")), 6),
        "impressions": _integer(raw.get("impressions")),
        "reach": _integer(raw.get("reach")),
        "clicks": _integer(raw.get("clicks")),
        "link_clicks": _integer(raw.get("inline_link_clicks")),
        "conversions": round(conversions, 6),
        "conversion_value": round(value, 6),
        "frequency": _optional_number(raw.get("frequency")),
        "ctr": _optional_number(raw.get("ctr")),
        "cpc": _optional_number(raw.get("cpc")),
        "cpm": _optional_number(raw.get("cpm")),
        "actions": {key: round(amount, 6) for key, amount in actions.items()},
    }


# --- throttling ---------------------------------------------------------------------


@dataclass(frozen=True)
class Throttle:
    usage_pct: float = 0.0
    retry_after_seconds: int = 0
    sources: tuple[str, ...] = ()

    def exceeded(self, threshold_pct: float) -> bool:
        return self.retry_after_seconds > 0 or self.usage_pct >= threshold_pct

    def as_dict(self) -> dict[str, Any]:
        return {
            "usage_pct": round(self.usage_pct, 2),
            "retry_after_seconds": self.retry_after_seconds,
            "sources": list(self.sources),
        }


def _json_header(headers: Mapping[str, str], name: str) -> Any:
    raw = headers.get(name)
    if not raw or len(raw) > 16_384:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _pct(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) and number > 0 else 0.0


def parse_throttle(headers: Mapping[str, str]) -> Throttle:
    """Read Meta's usage headers (app, ad account, business use case, insights)."""

    lowered = {str(key).lower(): str(value) for key, value in headers.items()}
    usage = 0.0
    retry = 0
    sources: list[str] = []
    app = _json_header(lowered, "x-app-usage")
    if isinstance(app, dict):
        usage = max(usage, *(_pct(app.get(key)) for key in ("call_count", "total_time", "total_cputime")))
        sources.append("app")
    account = _json_header(lowered, "x-ad-account-usage")
    if isinstance(account, dict):
        usage = max(usage, _pct(account.get("acc_id_util_pct")))
        retry = max(retry, int(_pct(account.get("reset_time_duration"))))
        sources.append("ad_account")
    insights = _json_header(lowered, "x-fb-ads-insights-throttle")
    if isinstance(insights, dict):
        usage = max(usage, _pct(insights.get("app_id_util_pct")), _pct(insights.get("acc_id_util_pct")))
        sources.append("insights")
    business = _json_header(lowered, "x-business-use-case-usage")
    if isinstance(business, dict):
        for entries in business.values():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                usage = max(
                    usage,
                    *(_pct(entry.get(key)) for key in ("call_count", "total_time", "total_cputime")),
                )
                minutes = _pct(entry.get("estimated_time_to_regain_access"))
                retry = max(retry, int(minutes * 60))
        sources.append("business_use_case")
    return Throttle(usage_pct=usage, retry_after_seconds=retry, sources=tuple(sources))


def backoff_seconds(throttle: Throttle, *, minimum: int = 300, maximum: int = 6 * 3600) -> int:
    return max(minimum, min(maximum, throttle.retry_after_seconds or minimum))


# --- sync windows -------------------------------------------------------------------


def sync_window(
    today: date,
    synced_through: date | None,
    *,
    initial_backfill_days: int,
    lookback_days: int,
    max_backfill_days: int = 400,
) -> tuple[date, date]:
    """Incremental window: re-read the attribution lookback, never beyond the cap."""

    earliest = today - timedelta(days=max_backfill_days)
    if synced_through is None:
        start = today - timedelta(days=max(0, initial_backfill_days - 1))
    else:
        start = min(synced_through, today) - timedelta(days=lookback_days)
    return max(start, earliest), today


def days_in(date_from: date, date_to: date) -> int:
    return (date_to - date_from).days + 1


# --- aggregation and KPIs ------------------------------------------------------------


@dataclass
class Totals:
    spend: float = 0.0
    impressions: int = 0
    reach: int = 0
    clicks: int = 0
    link_clicks: int = 0
    conversions: float = 0.0
    conversion_value: float = 0.0

    def add(self, row: Mapping[str, Any]) -> None:
        self.spend += float(row.get("spend") or 0.0)
        self.impressions += int(row.get("impressions") or 0)
        self.reach += int(row.get("reach") or 0)
        self.clicks += int(row.get("clicks") or 0)
        self.link_clicks += int(row.get("link_clicks") or 0)
        self.conversions += float(row.get("conversions") or 0.0)
        self.conversion_value += float(row.get("conversion_value") or 0.0)

    def metrics(self) -> dict[str, float | None]:
        return {
            "spend": round(self.spend, 2),
            "impressions": float(self.impressions),
            "reach": float(self.reach),
            "clicks": float(self.clicks),
            "link_clicks": float(self.link_clicks),
            "conversions": round(self.conversions, 2),
            "conversion_value": round(self.conversion_value, 2),
            "ctr": _ratio(self.clicks * 100.0, self.impressions),
            "cpc": _ratio(self.spend, self.clicks),
            "cpm": _ratio(self.spend * 1000.0, self.impressions),
            "cpa": _ratio(self.spend, self.conversions),
            "roas": _ratio(self.conversion_value, self.spend),
            # Daily reach is not additive; this is impressions per daily-reach unit.
            "frequency": _ratio(float(self.impressions), self.reach),
        }


def _ratio(numerator: float, denominator: float) -> float | None:
    if not denominator:
        return None
    return round(numerator / denominator, 4)


def totals(rows: Iterable[Mapping[str, Any]]) -> Totals:
    total = Totals()
    for row in rows:
        total.add(row)
    return total


KPI_KEYS = (
    "spend", "impressions", "reach", "clicks", "ctr", "cpc", "cpm",
    "conversions", "cpa", "roas", "frequency",
)


def _change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return round((current - previous) * 100.0 / abs(previous), 2)


def compare_kpis(
    current_rows: Iterable[Mapping[str, Any]], previous_rows: Iterable[Mapping[str, Any]]
) -> dict[str, dict[str, float | None]]:
    current = totals(current_rows).metrics()
    previous = totals(previous_rows).metrics()
    return {
        key: {
            "value": current[key],
            "previous": previous[key],
            "change_pct": _change(current[key], previous[key]),
        }
        for key in KPI_KEYS
    }


def previous_period(date_from: date, date_to: date) -> tuple[date, date]:
    length = days_in(date_from, date_to)
    end = date_from - timedelta(days=1)
    return end - timedelta(days=length - 1), end


def daily_trend(
    rows: Iterable[Mapping[str, Any]], date_from: date, date_to: date
) -> list[dict[str, Any]]:
    by_day: dict[date, Totals] = {}
    for row in rows:
        by_day.setdefault(row["day"], Totals()).add(row)
    series: list[dict[str, Any]] = []
    day = date_from
    while day <= date_to:
        metrics = by_day.get(day, Totals()).metrics()
        series.append(
            {
                "day": day.isoformat(),
                "spend": metrics["spend"],
                "impressions": metrics["impressions"],
                "clicks": metrics["clicks"],
                "conversions": metrics["conversions"],
                "ctr": metrics["ctr"],
                "cpa": metrics["cpa"],
                "roas": metrics["roas"],
            }
        )
        day += timedelta(days=1)
    return series


def by_object(rows: Iterable[Mapping[str, Any]]) -> dict[str, tuple[str, Totals]]:
    grouped: dict[str, tuple[str, Totals]] = {}
    for row in rows:
        key = str(row["object_id"])
        name, total = grouped.get(key, (str(row.get("object_name") or key), Totals()))
        total.add(row)
        grouped[key] = (str(row.get("object_name") or name), total)
    return grouped


def rank_campaigns(rows: Iterable[Mapping[str, Any]], *, limit: int = 5) -> dict[str, Any]:
    """Top and bottom campaigns by ROAS when values exist, else by CPA, else by CTR."""

    grouped = by_object(rows)
    items = []
    for object_id, (name, total) in grouped.items():
        metrics = total.metrics()
        if not total.spend and not total.impressions:
            continue
        items.append({"campaign_id": object_id, "name": name, **metrics})
    basis = "ctr"
    if any((item["roas"] or 0) > 0 for item in items):
        basis = "roas"
    elif any(item["cpa"] is not None for item in items):
        basis = "cpa"

    def score(item: dict[str, Any]) -> float:
        value = item[basis]
        if basis == "cpa":
            return -(value if value is not None else math.inf)
        return value if value is not None else -math.inf

    ordered = sorted(items, key=score, reverse=True)
    top = ordered[:limit]
    bottom = [item for item in reversed(ordered) if item not in top][:limit]
    return {"basis": basis, "top": top, "bottom": bottom, "count": len(items)}


def breakdown_summary(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, dict[str, Totals]] = {}
    for row in rows:
        breakdown = str(row.get("breakdown") or "none")
        if breakdown == "none":
            continue
        grouped.setdefault(breakdown, {}).setdefault(
            str(row.get("breakdown_value") or "unknown"), Totals()
        ).add(row)
    summary: dict[str, list[dict[str, Any]]] = {}
    for breakdown, values in grouped.items():
        items = [
            {"value": value, **total.metrics()} for value, total in values.items()
        ]
        items.sort(key=lambda item: item["spend"] or 0.0, reverse=True)
        summary[breakdown] = items[:20]
    return summary


# --- alerts -------------------------------------------------------------------------

SPEND_SPIKE_RATIO = 1.5
SPEND_SPIKE_MIN_MAJOR = 5.0
FATIGUE_FREQUENCY = 3.0
FATIGUE_CTR_DROP_PCT = 20.0


def alerts(
    campaign_rows: list[Mapping[str, Any]],
    *,
    as_of: date,
    cpa_target: float | None,
) -> list[dict[str, Any]]:
    """Spend spike, CPA above target and frequency fatigue, each with its numbers."""

    found: list[dict[str, Any]] = []
    last_day = [row for row in campaign_rows if row["day"] == as_of]
    prior = [row for row in campaign_rows if as_of - timedelta(days=7) <= row["day"] < as_of]
    last_spend = totals(last_day).spend
    prior_days = {row["day"] for row in prior}
    if prior_days:
        average = totals(prior).spend / 7.0
        if last_spend >= SPEND_SPIKE_MIN_MAJOR and average > 0 and last_spend > average * SPEND_SPIKE_RATIO:
            found.append(
                {
                    "type": "spend_spike",
                    "severity": "warning",
                    "evidence": {
                        "day": as_of.isoformat(),
                        "spend": round(last_spend, 2),
                        "average_prior_7_days": round(average, 2),
                        "ratio": round(last_spend / average, 2),
                    },
                }
            )
    week = [row for row in campaign_rows if as_of - timedelta(days=6) <= row["day"] <= as_of]
    week_before = [
        row for row in campaign_rows if as_of - timedelta(days=13) <= row["day"] <= as_of - timedelta(days=7)
    ]
    current = by_object(week)
    previous = by_object(week_before)
    for object_id, (name, total) in current.items():
        metrics = total.metrics()
        cpa = metrics["cpa"]
        if cpa_target and cpa is not None and cpa > cpa_target:
            found.append(
                {
                    "type": "cpa_above_target",
                    "severity": "warning",
                    "campaign_id": object_id,
                    "name": name,
                    "evidence": {
                        "cpa_last_7_days": cpa,
                        "cpa_target": round(cpa_target, 2),
                        "spend_last_7_days": metrics["spend"],
                        "conversions_last_7_days": metrics["conversions"],
                    },
                }
            )
        frequency = metrics["frequency"]
        before = previous.get(object_id)
        ctr_now = metrics["ctr"]
        ctr_before = before[1].metrics()["ctr"] if before else None
        drop = _change(ctr_now, ctr_before)
        if (
            frequency is not None
            and frequency >= FATIGUE_FREQUENCY
            and drop is not None
            and drop <= -FATIGUE_CTR_DROP_PCT
        ):
            found.append(
                {
                    "type": "frequency_fatigue",
                    "severity": "info",
                    "campaign_id": object_id,
                    "name": name,
                    "evidence": {
                        "frequency_last_7_days": frequency,
                        "ctr_last_7_days": ctr_now,
                        "ctr_previous_7_days": ctr_before,
                        "ctr_change_pct": drop,
                    },
                }
            )
    return found


# --- spend guard --------------------------------------------------------------------


@dataclass(frozen=True)
class Caps:
    daily_minor: int
    lifetime_minor: int


@dataclass(frozen=True)
class GuardDecision:
    allowed: bool
    code: str
    evidence: dict[str, Any] = field(default_factory=dict)


def activation_decision(
    caps: Caps,
    *,
    currency: str,
    new_daily_budget_minor: int,
    new_lifetime_budget_minor: int,
    active_daily_budgets_minor: int,
    spend_today: float,
    spend_lifetime: float,
) -> GuardDecision:
    """May one more campaign go live without breaking the user's caps?"""

    spend_today_minor = to_minor(spend_today, currency)
    spend_lifetime_minor = to_minor(spend_lifetime, currency)
    evidence = {
        "currency": currency,
        "daily_cap_minor": caps.daily_minor,
        "lifetime_cap_minor": caps.lifetime_minor,
        "active_daily_budgets_minor": active_daily_budgets_minor,
        "new_daily_budget_minor": new_daily_budget_minor,
        "new_lifetime_budget_minor": new_lifetime_budget_minor,
        "spend_today_minor": spend_today_minor,
        "spend_lifetime_minor": spend_lifetime_minor,
    }
    if caps.daily_minor <= 0 or caps.lifetime_minor <= 0:
        return GuardDecision(False, "ads-spend-cap-not-configured", evidence)
    if spend_today_minor >= caps.daily_minor:
        return GuardDecision(False, "ads-daily-cap-reached", evidence)
    if spend_lifetime_minor >= caps.lifetime_minor:
        return GuardDecision(False, "ads-lifetime-cap-reached", evidence)
    if active_daily_budgets_minor + new_daily_budget_minor > caps.daily_minor:
        return GuardDecision(False, "ads-daily-cap-exceeded", evidence)
    if spend_lifetime_minor + new_lifetime_budget_minor > caps.lifetime_minor:
        return GuardDecision(False, "ads-lifetime-cap-exceeded", evidence)
    return GuardDecision(True, "ads-within-caps", evidence)


def pause_decision(
    caps: Caps, *, currency: str, spend_today: float, spend_lifetime: float
) -> GuardDecision:
    """Must the user's live campaigns be paused now?"""

    spend_today_minor = to_minor(spend_today, currency)
    spend_lifetime_minor = to_minor(spend_lifetime, currency)
    evidence = {
        "currency": currency,
        "daily_cap_minor": caps.daily_minor,
        "lifetime_cap_minor": caps.lifetime_minor,
        "spend_today_minor": spend_today_minor,
        "spend_lifetime_minor": spend_lifetime_minor,
    }
    if caps.daily_minor <= 0 or caps.lifetime_minor <= 0:
        return GuardDecision(True, "ads-spend-cap-not-configured", evidence)
    if spend_lifetime_minor >= caps.lifetime_minor:
        return GuardDecision(True, "ads-lifetime-cap-reached", evidence)
    if spend_today_minor >= caps.daily_minor:
        return GuardDecision(True, "ads-daily-cap-reached", evidence)
    return GuardDecision(False, "ads-within-caps", evidence)


# --- recommendation grounding --------------------------------------------------------

RECOMMENDATION_TYPES = ("budget_shift", "creative_fatigue", "audience", "bid_or_schedule", "other")
MAX_RECOMMENDATIONS = 8


def flatten_facts(grounding: Mapping[str, Any]) -> dict[str, Any]:
    """Every numeric fact in the grounding, addressable by a dotted key."""

    facts: dict[str, Any] = {}

    def walk(prefix: str, value: Any) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                walk(f"{prefix}.{key}" if prefix else str(key), item)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(f"{prefix}.{index}", item)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            facts[prefix] = value

    walk("", grounding)
    return facts


def validate_recommendations(raw: Any, grounding: Mapping[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """Keep only recommendations whose cited evidence exists in the grounding.

    The numbers shown with a recommendation are copied from the stored metrics,
    never from the model's text. Returns (accepted, rejected_count).
    """

    facts = flatten_facts(grounding)
    accepted: list[dict[str, Any]] = []
    rejected = 0
    items = raw if isinstance(raw, list) else []
    for item in items[: MAX_RECOMMENDATIONS * 2]:
        if not isinstance(item, Mapping):
            rejected += 1
            continue
        kind = str(item.get("type") or "").strip().lower()
        title = _clean(item.get("title"), 160)
        action = _clean(item.get("action"), 600)
        rationale = _clean(item.get("rationale"), 900)
        cited = item.get("evidence")
        keys = [str(key).strip() for key in cited] if isinstance(cited, list) else []
        evidence = {key: facts[key] for key in dict.fromkeys(keys) if key in facts}
        if kind not in RECOMMENDATION_TYPES or not title or not action or not evidence:
            rejected += 1
            continue
        if len(evidence) < len(set(keys)):
            # A cited number that does not exist means the model invented it.
            rejected += 1
            continue
        accepted.append(
            {
                "type": kind,
                "title": title,
                "action": action,
                "rationale": rationale,
                "evidence": evidence,
                "advisory_only": True,
                "auto_apply": False,
            }
        )
        if len(accepted) >= MAX_RECOMMENDATIONS:
            break
    return accepted, rejected
