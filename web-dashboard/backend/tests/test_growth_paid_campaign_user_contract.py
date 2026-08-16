from __future__ import annotations

from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.api.v1.router import api_router


def _effective_routes(app: FastAPI):
    for candidate in app.routes:
        route_contexts = getattr(candidate, "effective_route_contexts", None)
        if callable(route_contexts):
            yield from (
                route
                for route in route_contexts()
                if getattr(route, "dependant", None) is not None
            )
        elif isinstance(candidate, APIRoute):
            yield candidate


def test_paid_campaign_user_api_has_atomic_advisor_but_no_user_approval_route() -> None:
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    routes = {
        (method, route.path)
        for route in _effective_routes(app)
        for method in route.methods
        if method in {"GET", "POST", "PATCH", "PUT", "DELETE"}
    }
    assert (
        "POST",
        "/api/v1/growth-social/paid-campaigns/prepare-and-simulate",
    ) in routes
    assert (
        "GET",
        "/api/v1/growth-social/paid-campaigns/readiness",
    ) in routes
    assert not any(
        path.startswith("/api/v1/growth-social/paid-campaigns/")
        and path.endswith("/approve")
        for method, path in routes
        if method == "POST"
    )
    assert (
        "POST",
        "/api/v1/owner/growth-social/paid-campaigns/{campaign_id}/approve",
    ) in routes


def test_user_paid_campaign_delivery_status_is_read_only_and_redacted() -> None:
    from types import SimpleNamespace

    from app.api.v1.endpoints import growth_paid_campaigns as user_api

    campaign = SimpleNamespace(
        id="campaign-1",
        name="Campaign",
        objective="traffic",
        status="pending_owner",
        approval_status="pending_owner",
        currency="EUR",
        total_budget_minor=1500,
        daily_budget_cap_minor=400,
        simulated_spend_minor=0,
        campaign_metadata={},
    )
    pending = user_api._user_campaign_payload(campaign)
    assert pending["delivery_stage"] == "awaiting_owner"
    assert pending["automatic_execution_allowed"] is False
    assert pending["spend_executed"] is False

    campaign.approval_status = "approved"
    approved = user_api._user_campaign_payload(campaign)
    assert approved["delivery_stage"] == "owner_approved"

    campaign.campaign_metadata = {"live_execution_plan": {"plan_digest": "a" * 64}}
    planned = user_api._user_campaign_payload(campaign)
    assert planned["delivery_stage"] == "live_plan_ready"
    assert planned["live_plan_prepared"] is True

    execution = SimpleNamespace(
        status="paused_ready",
        manual_review_required=False,
        spend_executed=False,
        scope_ref="accountref://meta/sha256/" + "b" * 64,
        provider_object_id="123456789012345",
    )
    delivered = user_api._user_campaign_payload(campaign, execution)
    assert delivered["delivery_stage"] == "paused_on_meta"
    assert delivered["provider_prepared"] is True
    assert "scope_ref" not in delivered
    assert "provider_object_id" not in delivered

    execution.status = "manual_review"
    execution.manual_review_required = True
    review = user_api._user_campaign_payload(campaign, execution)
    assert review["delivery_stage"] == "manual_review"
    assert review["manual_review_required"] is True


def test_user_paid_campaign_api_exposes_no_live_execution_mutation_route() -> None:
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    routes = {
        (method, route.path)
        for route in _effective_routes(app)
        for method in route.methods
        if method in {"GET", "POST", "PATCH", "PUT", "DELETE"}
    }
    assert not any(
        path.startswith("/api/v1/growth-social/paid-campaigns/")
        and "/live-execution" in path
        for _, path in routes
    )


def test_user_paid_campaign_requests_bind_to_linked_ad_account() -> None:
    from app.api.v1.endpoints.growth_paid_campaigns import (
        AdSetRequest,
        CampaignPreparationRequest,
        CampaignRequest,
    )

    assert "social_account_id" in CampaignPreparationRequest.model_fields
    assert "currency" not in CampaignPreparationRequest.model_fields
    assert "provider" not in CampaignPreparationRequest.model_fields
    assert "social_account_id" in CampaignRequest.model_fields
    assert "currency" not in CampaignRequest.model_fields
    assert "provider" not in AdSetRequest.model_fields
