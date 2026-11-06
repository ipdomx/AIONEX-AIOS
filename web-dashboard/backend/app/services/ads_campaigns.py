"""P4 create and activate Meta campaigns for users, under hard spend guards (4.5).

* Create: objective, budget (daily *or* lifetime), schedule, targeting and a
  creative from the user's own uploads/Studio images or from one of their
  published posts. Campaign, ad set, creative and ad are always created
  ``PAUSED``; each Graph id is committed as soon as Meta returns it, so a
  retry resumes instead of duplicating.
* Activate: a separate action that needs the typed phrase
  ``ACTIVATION_PHRASE`` plus the exact budget the user is confirming, the
  ``ads.manage`` entitlement, an ``ads_management`` grant and room under the
  Owner policy's per-user daily and lifetime caps.
* Auto-pause: the insights worker calls ``enforce_spend_guard`` after every
  sync; when a user's spend reaches a cap every live platform campaign of
  that user (in that currency) is paused on Meta.

Every create, activation, pause, refusal and guard decision is audited with
the numbers it used. Nothing here has been run against a live ad account yet
(owner decision 2026-11-06: live tests wait for the full web launch).
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord
from app.db.models import (
    AdAccountLink,
    AdCampaign,
    AdInsightDaily,
    GrowthSocialAccount,
    SocialConnection,
    SocialPostTarget,
)
from app.services import ads_accounts as accounts
from app.services import ads_entitlement as entitlement
from app.services import ads_metrics as metrics
from app.services import social_media_access as media_access
from app.services.ads_accounts import AdsError
from app.services.ads_insights import account_today
from app.services.ads_meta_graph import AdsGraphError, MetaAdsGraph
from app.services.social_connections import CONNECTED_VIA
from app.services.social_connectors import SocialConnectorError

ACTIVATION_PHRASE = "ACTIVATE AD SPEND"
OBJECTIVES: dict[str, dict[str, str]] = {
    "traffic": {"meta": "OUTCOME_TRAFFIC", "optimization_goal": "LINK_CLICKS", "billing_event": "IMPRESSIONS"},
    "awareness": {"meta": "OUTCOME_AWARENESS", "optimization_goal": "REACH", "billing_event": "IMPRESSIONS"},
    "engagement": {"meta": "OUTCOME_ENGAGEMENT", "optimization_goal": "POST_ENGAGEMENT", "billing_event": "IMPRESSIONS"},
}
# Sales and leads need a pixel / lead form set-up that is not part of P4.
NEEDS_CONVERSION_SETUP = ("sales", "leads")
CALL_TO_ACTIONS = ("LEARN_MORE", "SHOP_NOW", "SIGN_UP", "CONTACT_US", "BOOK_TRAVEL", "DOWNLOAD", "GET_OFFER")
PLATFORMS = ("facebook", "instagram")
LIVE_STATUSES = ("active",)
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
MAX_SCHEDULE_DAYS = 365


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def public_campaign(row: AdCampaign) -> dict[str, Any]:
    return {
        "id": row.id,
        "link_id": row.link_id,
        "name": row.name,
        "objective": row.objective,
        "status": row.status,
        "currency": row.currency,
        "daily_budget_minor": row.daily_budget_minor,
        "lifetime_budget_minor": row.lifetime_budget_minor,
        "start_time": row.start_time,
        "end_time": row.end_time,
        "targeting": dict(row.targeting or {}),
        "creative": {
            key: value
            for key, value in dict(row.creative or {}).items()
            if key in {"source", "message", "headline", "link_url", "call_to_action", "media_ref", "post_target_id"}
        },
        "provisioned": bool(row.meta_ad_id),
        "meta_campaign_id": row.meta_campaign_id,
        "spend_to_date": round(float(row.spend_to_date or 0.0), 2),
        "spend_today": round(float(row.spend_today or 0.0), 2),
        "activated_at": row.activated_at,
        "paused_at": row.paused_at,
        "pause_reason": row.pause_reason,
        "error_code": row.error_code,
        "created_at": row.created_at,
        "live_verified": False,
    }


# --- validation ------------------------------------------------------------------------


def validate_targeting(raw: dict[str, Any]) -> dict[str, Any]:
    countries = sorted({str(item).strip().upper() for item in raw.get("countries") or []})
    if not countries or len(countries) > 25 or not all(_COUNTRY_RE.fullmatch(item) for item in countries):
        raise AdsError("targeting-countries-invalid", status_code=422)
    try:
        age_min = int(raw.get("age_min") or 18)
        age_max = int(raw.get("age_max") or 65)
    except (TypeError, ValueError):
        raise AdsError("targeting-age-invalid", status_code=422) from None
    if not 18 <= age_min <= age_max <= 65:
        raise AdsError("targeting-age-invalid", status_code=422)
    genders = sorted({int(item) for item in raw.get("genders") or [] if str(item) in {"1", "2"}})
    platforms = [item for item in PLATFORMS if item in set(raw.get("publisher_platforms") or PLATFORMS)]
    if not platforms:
        raise AdsError("targeting-platforms-invalid", status_code=422)
    targeting: dict[str, Any] = {
        "geo_locations": {"countries": countries},
        "age_min": age_min,
        "age_max": age_max,
        "publisher_platforms": platforms,
        "targeting_automation": {"advantage_audience": 0},
    }
    if genders:
        targeting["genders"] = genders
    return targeting


def validate_budget(
    *,
    daily_budget_minor: int | None,
    lifetime_budget_minor: int | None,
    start_time: datetime | None,
    end_time: datetime | None,
    caps: metrics.Caps,
    now: datetime,
) -> tuple[datetime, datetime | None]:
    if (daily_budget_minor is None) == (lifetime_budget_minor is None):
        raise AdsError("budget-choose-daily-or-lifetime", status_code=422)
    start = _aware(start_time) or now
    end = _aware(end_time)
    if start < now - timedelta(minutes=5):
        raise AdsError("schedule-start-in-past", status_code=422)
    if end is not None and (end <= start or end - start > timedelta(days=MAX_SCHEDULE_DAYS)):
        raise AdsError("schedule-end-invalid", status_code=422)
    evidence = {"daily_cap_minor": caps.daily_minor, "lifetime_cap_minor": caps.lifetime_minor}
    if daily_budget_minor is not None:
        if not 0 < daily_budget_minor <= entitlement.MAX_MONEY_MINOR:
            raise AdsError("budget-invalid", status_code=422)
        if daily_budget_minor > caps.daily_minor:
            raise AdsError("ads-daily-cap-exceeded", status_code=422, extra=evidence)
    if lifetime_budget_minor is not None:
        if not 0 < lifetime_budget_minor <= entitlement.MAX_MONEY_MINOR:
            raise AdsError("budget-invalid", status_code=422)
        if end is None:
            raise AdsError("lifetime-budget-needs-end-time", status_code=422)
        if lifetime_budget_minor > caps.lifetime_minor:
            raise AdsError("ads-lifetime-cap-exceeded", status_code=422, extra=evidence)
    return start, end


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _https(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if not re.fullmatch(r"https://[^\s<>\"']{4,2000}", text):
        raise AdsError("creative-link-invalid", status_code=422)
    return text


async def _own_page(session: AsyncSession, actor: UserRecord, account_id: str) -> GrowthSocialAccount:
    row = await session.scalar(
        select(GrowthSocialAccount).where(
            GrowthSocialAccount.id == account_id,
            GrowthSocialAccount.organization_id == actor.organization_id,
            GrowthSocialAccount.created_by_id == actor.id,
            GrowthSocialAccount.connected_via == CONNECTED_VIA,
            GrowthSocialAccount.status == "active",
        )
    )
    if row is None:
        raise AdsError("creative-account-not-found", status_code=422)
    return row


async def validate_creative(
    session: AsyncSession, actor: UserRecord, raw: dict[str, Any], *, objective: str
) -> dict[str, Any]:
    source = str(raw.get("source") or "")
    if source == "post":
        target_id = str(raw.get("post_target_id") or "")
        if not _UUID_RE.fullmatch(target_id):
            raise AdsError("creative-post-invalid", status_code=422)
        target = await session.scalar(
            select(SocialPostTarget).where(
                SocialPostTarget.id == target_id,
                SocialPostTarget.organization_id == actor.organization_id,
                SocialPostTarget.user_id == actor.id,
                SocialPostTarget.status == "published",
            )
        )
        if target is None or not target.remote_post_id or target.account_id is None:
            raise AdsError("creative-post-not-found", status_code=422)
        account = await _own_page(session, actor, target.account_id)
        return {
            "source": "post",
            "post_target_id": target.id,
            "provider": target.provider,
            "remote_post_id": target.remote_post_id,
            "page_external_id": (
                account.external_account_id
                if account.provider == "facebook"
                else str((account.provider_metadata or {}).get("linked_external_id") or "")
            ),
            "instagram_external_id": account.external_account_id if account.provider == "instagram" else None,
        }
    if source not in {"upload", "studio"}:
        raise AdsError("creative-source-invalid", status_code=422)
    if objective == "engagement":
        raise AdsError("engagement-needs-existing-post", status_code=422)
    media_ref = str(raw.get("media_ref") or "")
    try:
        resolved = await media_access.resolve_media(
            session, organization_id=actor.organization_id, user_id=actor.id, refs=[media_ref]
        )
    except SocialConnectorError as exc:
        raise AdsError(exc.code, status_code=422) from None
    if resolved[0].info.kind != "image":
        raise AdsError("creative-video-not-supported-yet", status_code=422)
    page = await _own_page(session, actor, str(raw.get("page_account_id") or ""))
    if page.provider != "facebook":
        raise AdsError("creative-page-required", status_code=422)
    link_url = _https(raw.get("link_url"))
    if link_url is None:
        raise AdsError("creative-link-required", status_code=422)
    cta = str(raw.get("call_to_action") or "LEARN_MORE").upper()
    if cta not in CALL_TO_ACTIONS:
        raise AdsError("creative-cta-invalid", status_code=422)
    instagram_external_id = None
    if raw.get("instagram_account_id"):
        instagram = await _own_page(session, actor, str(raw.get("instagram_account_id")))
        if instagram.provider != "instagram":
            raise AdsError("creative-instagram-invalid", status_code=422)
        instagram_external_id = instagram.external_account_id
    message = _text(raw.get("message"), 2000)
    if not message:
        raise AdsError("creative-message-required", status_code=422)
    return {
        "source": source,
        "media_ref": media_ref,
        "page_external_id": page.external_account_id,
        "instagram_external_id": instagram_external_id,
        "message": message,
        "headline": _text(raw.get("headline"), 120),
        "link_url": link_url,
        "call_to_action": cta,
    }


# --- spend --------------------------------------------------------------------------


async def spend_by_campaign(
    session: AsyncSession, rows: list[AdCampaign], *, now: datetime
) -> dict[str, tuple[float, float]]:
    """(spend today, spend to date) per platform campaign, from stored Insights."""

    links = {
        link.id: link
        for link in (
            await session.scalars(
                select(AdAccountLink).where(AdAccountLink.id.in_({row.link_id for row in rows}))
            )
        ).all()
    } if rows else {}
    result: dict[str, tuple[float, float]] = {}
    for row in rows:
        if not row.meta_campaign_id or row.link_id not in links:
            result[row.id] = (0.0, 0.0)
            continue
        today = account_today(links[row.link_id].timezone_name, now)
        base = (
            AdInsightDaily.link_id == row.link_id,
            AdInsightDaily.level == "campaign",
            AdInsightDaily.breakdown == "none",
            AdInsightDaily.object_id == row.meta_campaign_id,
        )
        total = await session.scalar(select(func.coalesce(func.sum(AdInsightDaily.spend), 0.0)).where(*base))
        daily = await session.scalar(
            select(func.coalesce(func.sum(AdInsightDaily.spend), 0.0)).where(*base, AdInsightDaily.day == today)
        )
        result[row.id] = (float(daily or 0.0), float(total or 0.0))
    return result


async def _user_campaigns(
    session: AsyncSession, *, organization_id: str, user_id: str, for_update: bool = False
) -> list[AdCampaign]:
    stmt = select(AdCampaign).where(
        AdCampaign.organization_id == organization_id,
        AdCampaign.user_id == user_id,
        AdCampaign.meta_campaign_id.is_not(None),
    )
    if for_update:
        stmt = stmt.with_for_update()
    return list((await session.scalars(stmt)).all())


async def usage(session: AsyncSession, actor: UserRecord, *, currency: str, now: datetime | None = None) -> dict[str, Any]:
    moment = now or _now()
    rows = [row for row in await _user_campaigns(session, organization_id=actor.organization_id, user_id=actor.id) if row.currency == currency]
    spends = await spend_by_campaign(session, rows, now=moment)
    return {
        "currency": currency,
        "spend_today": round(sum(value[0] for value in spends.values()), 2),
        "spend_lifetime": round(sum(value[1] for value in spends.values()), 2),
        "active_daily_budgets_minor": sum(
            int(row.daily_budget_minor or 0) for row in rows if row.status in LIVE_STATUSES
        ),
        "active_campaigns": sum(1 for row in rows if row.status in LIVE_STATUSES),
    }


# --- create (always PAUSED) --------------------------------------------------------------


async def _manage_auth(session: AsyncSession, link: AdAccountLink) -> Any:
    if link.source == accounts.SOURCE_OAUTH:
        connection = await session.scalar(
            select(SocialConnection).where(
                SocialConnection.id == link.connection_id,
                SocialConnection.organization_id == link.organization_id,
                SocialConnection.user_id == link.user_id,
            )
        )
        if connection is None or not accounts.can_manage(connection):
            raise AdsError("ads-management-permission-not-granted", status_code=409)
    return await accounts.link_auth(session, link)


async def create_campaign(
    session: AsyncSession,
    actor: UserRecord,
    payload: dict[str, Any],
    *,
    graph: MetaAdsGraph,
) -> dict[str, Any]:
    access = await entitlement.resolve_access(session, actor)
    access.require()
    objective = str(payload.get("objective") or "")
    if objective in NEEDS_CONVERSION_SETUP:
        raise AdsError("objective-needs-conversion-setup", status_code=422)
    if objective not in OBJECTIVES:
        raise AdsError("objective-invalid", status_code=422)
    name = _text(payload.get("name"), 200)
    if not name:
        raise AdsError("campaign-name-required", status_code=422)
    key = str(payload.get("client_idempotency_key") or "").strip()[:80] or None
    if key is not None:
        existing = await session.scalar(
            select(AdCampaign).where(AdCampaign.user_id == actor.id, AdCampaign.client_idempotency_key == key)
        )
        if existing is not None:
            if existing.organization_id != actor.organization_id:
                raise AdsError("campaign-not-found", status_code=404)
            return await provision(session, actor, existing.id, graph=graph)
    link = await accounts.own_link(session, actor, str(payload.get("link_id") or ""))
    now = _now()
    start, end = validate_budget(
        daily_budget_minor=payload.get("daily_budget_minor"),
        lifetime_budget_minor=payload.get("lifetime_budget_minor"),
        start_time=payload.get("start_time"),
        end_time=payload.get("end_time"),
        caps=access.caps_for(actor.id),
        now=now,
    )
    targeting = validate_targeting(dict(payload.get("targeting") or {}))
    creative = await validate_creative(
        session, actor, dict(payload.get("creative") or {}), objective=objective
    )
    await _manage_auth(session, link)
    row = AdCampaign(
        organization_id=actor.organization_id,
        user_id=actor.id,
        link_id=link.id,
        name=name,
        objective=objective,
        status="draft",
        currency=link.currency,
        daily_budget_minor=payload.get("daily_budget_minor"),
        lifetime_budget_minor=payload.get("lifetime_budget_minor"),
        start_time=start,
        end_time=end,
        targeting=targeting,
        creative=creative,
        client_idempotency_key=key,
        spend_to_date=0.0,
        spend_today=0.0,
        version=1,
    )
    session.add(row)
    await session.flush()
    accounts.audit(
        session,
        organization_id=actor.organization_id,
        user_id=actor.id,
        action="ads.campaign.created",
        resource_type="ad_campaign",
        resource_id=row.id,
        details={
            "objective": objective,
            "currency": row.currency,
            "daily_budget_minor": row.daily_budget_minor,
            "lifetime_budget_minor": row.lifetime_budget_minor,
            "created_paused": True,
        },
    )
    # The draft (and its audit) is durable before any provider call.
    await session.commit()
    return await provision(session, actor, row.id, graph=graph)


async def own_campaign(
    session: AsyncSession, actor: UserRecord, campaign_id: str, *, for_update: bool = False
) -> AdCampaign:
    stmt = select(AdCampaign).where(
        AdCampaign.id == campaign_id,
        AdCampaign.organization_id == actor.organization_id,
        AdCampaign.user_id == actor.id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    row = await session.scalar(stmt)
    if row is None:
        raise AdsError("campaign-not-found", status_code=404)
    return row


def adset_form(row: AdCampaign) -> dict[str, Any]:
    spec = OBJECTIVES[row.objective]
    form: dict[str, Any] = {
        "name": f"{row.name} - ad set"[:240],
        "campaign_id": row.meta_campaign_id,
        "status": "PAUSED",
        "billing_event": spec["billing_event"],
        "optimization_goal": spec["optimization_goal"],
        "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
        "targeting": dict(row.targeting or {}),
        "start_time": (_aware(row.start_time) or _now()).isoformat(),
    }
    if row.daily_budget_minor is not None:
        form["daily_budget"] = int(row.daily_budget_minor)
    if row.lifetime_budget_minor is not None:
        form["lifetime_budget"] = int(row.lifetime_budget_minor)
    if row.end_time is not None:
        form["end_time"] = (_aware(row.end_time) or _now()).isoformat()
    return form


async def creative_form(session: AsyncSession, row: AdCampaign) -> dict[str, Any]:
    creative = dict(row.creative or {})
    name = f"{row.name} - creative"[:240]
    if creative.get("source") == "post":
        remote = str(creative.get("remote_post_id") or "")
        if creative.get("provider") == "instagram":
            return {
                "name": name,
                "object_id": creative.get("page_external_id"),
                "instagram_user_id": creative.get("instagram_external_id"),
                "source_instagram_media_id": remote,
            }
        story = remote if "_" in remote else f"{creative.get('page_external_id')}_{remote}"
        return {"name": name, "object_story_id": story}
    resolved = await media_access.resolve_media(
        session,
        organization_id=row.organization_id,
        user_id=row.user_id,
        refs=[str(creative.get("media_ref") or "")],
    )
    link_data: dict[str, Any] = {
        "link": creative.get("link_url"),
        "message": creative.get("message"),
        "picture": media_access.public_url(resolved[0]),
        "call_to_action": {
            "type": creative.get("call_to_action") or "LEARN_MORE",
            "value": {"link": creative.get("link_url")},
        },
    }
    if creative.get("headline"):
        link_data["name"] = creative.get("headline")
    form: dict[str, Any] = {
        "name": name,
        "object_story_spec": {"page_id": creative.get("page_external_id"), "link_data": link_data},
    }
    if creative.get("instagram_external_id"):
        form["object_story_spec"]["instagram_user_id"] = creative.get("instagram_external_id")
    return form


async def provision(
    session: AsyncSession, actor: UserRecord, campaign_id: str, *, graph: MetaAdsGraph
) -> dict[str, Any]:
    """Create (or finish creating) the PAUSED Meta objects, committing each id."""

    row = await own_campaign(session, actor, campaign_id)
    if row.meta_ad_id:
        return public_campaign(row)
    if row.status not in {"draft", "failed", "provisioning"}:
        raise AdsError("campaign-not-provisionable", status_code=409)
    link = await accounts.own_link(session, actor, row.link_id)
    auth = await _manage_auth(session, link)
    row.status = "provisioning"
    row.error_code = None
    await session.commit()
    try:
        if not row.meta_campaign_id:
            row.meta_campaign_id = await graph.create_campaign(
                auth, link.ad_account_id, name=row.name, objective=OBJECTIVES[row.objective]["meta"]
            )
            await session.commit()
        if not row.meta_adset_id:
            row.meta_adset_id = await graph.create_adset(auth, link.ad_account_id, form=adset_form(row))
            await session.commit()
        if not row.meta_creative_id:
            row.meta_creative_id = await graph.create_creative(
                auth, link.ad_account_id, form=await creative_form(session, row)
            )
            await session.commit()
        row.meta_ad_id = await graph.create_ad(
            auth,
            link.ad_account_id,
            name=f"{row.name} - ad"[:240],
            adset_id=str(row.meta_adset_id),
            creative_id=str(row.meta_creative_id),
        )
    except (AdsGraphError, SocialConnectorError) as exc:
        row.status = "failed"
        row.error_code = exc.code
        row.version += 1
        accounts.audit(
            session,
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="ads.campaign.provision_failed",
            resource_type="ad_campaign",
            resource_id=row.id,
            details={"error": exc.code, "campaign_created": bool(row.meta_campaign_id)},
        )
        await session.commit()
        raise AdsError(exc.code, status_code=502) from None
    row.status = "paused"
    row.paused_at = _now()
    row.pause_reason = "created-paused"
    row.version += 1
    accounts.audit(
        session,
        organization_id=actor.organization_id,
        user_id=actor.id,
        action="ads.campaign.provisioned_paused",
        resource_type="ad_campaign",
        resource_id=row.id,
        details={"objective": row.objective, "status_on_meta": "PAUSED"},
    )
    await session.commit()
    return public_campaign(row)


async def list_campaigns(session: AsyncSession, actor: UserRecord) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(AdCampaign)
            .where(AdCampaign.organization_id == actor.organization_id, AdCampaign.user_id == actor.id)
            .order_by(AdCampaign.created_at.desc())
            .limit(200)
        )
    ).all()
    return [public_campaign(row) for row in rows]


# --- activate / pause --------------------------------------------------------------------


async def activate(
    session: AsyncSession,
    actor: UserRecord,
    campaign_id: str,
    *,
    confirmation: str,
    confirmed_budget_minor: int,
    graph: MetaAdsGraph,
) -> dict[str, Any]:
    access = await entitlement.resolve_access(session, actor)
    access.require()
    await entitlement_lock(session, actor)
    row = await own_campaign(session, actor, campaign_id, for_update=True)

    def refuse(code: str, evidence: dict[str, Any], status_code: int = 409) -> AdsError:
        accounts.audit(
            session,
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="ads.campaign.activation_refused",
            resource_type="ad_campaign",
            resource_id=row.id,
            details={"reason": code, **evidence},
        )
        return AdsError(code, status_code=status_code, extra={"evidence": evidence})

    budget = int(row.daily_budget_minor or row.lifetime_budget_minor or 0)
    if confirmation.strip() != ACTIVATION_PHRASE or int(confirmed_budget_minor) != budget:
        error = refuse("activation-confirmation-mismatch", {"budget_minor": budget}, 422)
        await session.commit()
        raise error
    if not access.policy["activation_enabled"]:
        error = refuse("ads-activation-disabled-by-owner", {}, 403)
        await session.commit()
        raise error
    if row.status not in {"paused", "auto_paused"} or not row.meta_ad_id:
        raise AdsError("campaign-not-activatable", status_code=409)
    current = await usage(session, actor, currency=row.currency)
    if current["active_campaigns"] >= int(access.policy["max_active_campaigns_per_user"]):
        error = refuse("ads-active-campaign-limit", {"active_campaigns": current["active_campaigns"]})
        await session.commit()
        raise error
    end = _aware(row.end_time)
    if end is not None and end <= _now():
        raise AdsError("campaign-schedule-ended", status_code=409)
    decision = metrics.activation_decision(
        access.caps_for(actor.id),
        currency=row.currency,
        new_daily_budget_minor=int(row.daily_budget_minor or 0),
        new_lifetime_budget_minor=int(row.lifetime_budget_minor or 0),
        active_daily_budgets_minor=int(current["active_daily_budgets_minor"]),
        spend_today=float(current["spend_today"]),
        spend_lifetime=float(current["spend_lifetime"]),
    )
    if not decision.allowed:
        error = refuse(decision.code, decision.evidence)
        await session.commit()
        raise error
    link = await accounts.own_link(session, actor, row.link_id)
    auth = await _manage_auth(session, link)
    try:
        # Children first; the campaign switch is the one that starts delivery.
        await graph.set_status(auth, str(row.meta_ad_id), "ACTIVE")
        await graph.set_status(auth, str(row.meta_adset_id), "ACTIVE")
        await graph.set_status(auth, str(row.meta_campaign_id), "ACTIVE")
    except AdsGraphError as exc:
        row.error_code = exc.code
        accounts.audit(
            session,
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="ads.campaign.activation_failed",
            resource_type="ad_campaign",
            resource_id=row.id,
            details={"error": exc.code},
        )
        await session.commit()
        raise AdsError(exc.code, status_code=502) from None
    row.status = "active"
    row.activated_at = _now()
    row.pause_reason = None
    row.error_code = None
    row.version += 1
    link.next_sync_at = _now()
    accounts.audit(
        session,
        organization_id=actor.organization_id,
        user_id=actor.id,
        action="ads.campaign.activated",
        resource_type="ad_campaign",
        resource_id=row.id,
        details={"typed_confirmation": True, **decision.evidence},
    )
    await session.commit()
    return public_campaign(row)


async def entitlement_lock(session: AsyncSession, actor: UserRecord) -> None:
    """Serialize one user's activations so two requests cannot both fit under a cap."""

    from app.services.security_entitlement import lock_actor

    await lock_actor(session, actor)


async def pause(
    session: AsyncSession, actor: UserRecord, campaign_id: str, *, graph: MetaAdsGraph
) -> dict[str, Any]:
    row = await own_campaign(session, actor, campaign_id, for_update=True)
    if row.status != "active":
        raise AdsError("campaign-not-active", status_code=409)
    link = await accounts.own_link(session, actor, row.link_id)
    auth = await accounts.link_auth(session, link)
    try:
        await graph.set_status(auth, str(row.meta_campaign_id), "PAUSED")
    except AdsGraphError as exc:
        raise AdsError(exc.code, status_code=502) from None
    row.status = "paused"
    row.paused_at = _now()
    row.pause_reason = "paused-by-user"
    row.version += 1
    accounts.audit(
        session,
        organization_id=actor.organization_id,
        user_id=actor.id,
        action="ads.campaign.paused",
        resource_type="ad_campaign",
        resource_id=row.id,
        details={"reason": "paused-by-user"},
    )
    await session.commit()
    return public_campaign(row)


# --- spend guard (worker) ----------------------------------------------------------------


async def enforce_spend_guard(
    session: AsyncSession,
    *,
    user_id: str,
    organization_id: str,
    graph: MetaAdsGraph,
    now: datetime,
) -> list[dict[str, Any]]:
    """Refresh spend on the user's platform campaigns and auto-pause over a cap."""

    rows = await _user_campaigns(
        session, organization_id=organization_id, user_id=user_id, for_update=True
    )
    if not rows:
        return []
    spends = await spend_by_campaign(session, rows, now=now)
    for row in rows:
        row.spend_today, row.spend_to_date = spends.get(row.id, (0.0, 0.0))
        row.guard_checked_at = now
    policy = await entitlement.get_policy(session)
    access = entitlement.AdsAccess(None, None, "worker", policy=policy)
    caps = access.caps_for(user_id)
    by_currency: dict[str, list[AdCampaign]] = defaultdict(list)
    for row in rows:
        by_currency[row.currency].append(row)
    decisions: list[dict[str, Any]] = []
    for currency, group in by_currency.items():
        live = [row for row in group if row.status in LIVE_STATUSES]
        if not live:
            continue
        decision = metrics.pause_decision(
            caps,
            currency=currency,
            spend_today=sum(float(row.spend_today or 0.0) for row in group),
            spend_lifetime=sum(float(row.spend_to_date or 0.0) for row in group),
        )
        decisions.append({"currency": currency, "pause": decision.allowed, "code": decision.code})
        if not decision.allowed:
            continue
        for row in live:
            await _auto_pause(session, row, decision, graph=graph, now=now)
    await session.flush()
    return decisions


async def _auto_pause(
    session: AsyncSession,
    row: AdCampaign,
    decision: metrics.GuardDecision,
    *,
    graph: MetaAdsGraph,
    now: datetime,
) -> None:
    link = await session.get(AdAccountLink, row.link_id)
    try:
        if link is None:
            raise AdsError("ad-account-link-not-found", status_code=409)
        auth = await accounts.link_auth(session, link)
        await graph.set_status(auth, str(row.meta_campaign_id), "PAUSED")
    except (AdsError, AdsGraphError) as exc:
        row.error_code = exc.code
        if link is not None:
            # Retry the pause on the next tick instead of waiting a full interval.
            link.next_sync_at = now + timedelta(minutes=1)
        accounts.audit(
            session,
            organization_id=row.organization_id,
            user_id=row.user_id,
            action="ads.guard.pause_failed",
            resource_type="ad_campaign",
            resource_id=row.id,
            details={"reason": decision.code, "error": exc.code, **decision.evidence},
        )
        return
    row.status = "auto_paused"
    row.paused_at = now
    row.pause_reason = decision.code
    row.error_code = None
    row.version += 1
    accounts.audit(
        session,
        organization_id=row.organization_id,
        user_id=row.user_id,
        action="ads.guard.auto_paused",
        resource_type="ad_campaign",
        resource_id=row.id,
        details={"reason": decision.code, **decision.evidence},
    )
