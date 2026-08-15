from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord
from app.services import growth_access
from app.services import growth_advanced_integrations as advanced
from app.services import growth_analytics_learning as analytics
from app.services import growth_campaign_intelligence as campaigns
from app.services import growth_content_operations as content
from app.services import growth_lead_intelligence as leads
from app.services import growth_paid_campaigns as paid
from app.services import growth_social_accounts as social
from app.services import growth_unified_inbox as inbox


class GrowthFullSystemAcceptanceError(RuntimeError):
    """GS-11 synthetic acceptance contract failure."""


GRANTED_CAPABILITIES = tuple(growth_access.CAPABILITIES)
APPROVAL_CAPABILITIES = {
    "content.publish",
    "leads.manage",
    "ads.manage",
    "automations.manage",
    "integrations.manage",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _assert(condition: bool, reason: str) -> None:
    if not condition:
        raise GrowthFullSystemAcceptanceError(reason)


async def _grant_all(
    session: AsyncSession, owner: UserRecord, actor: UserRecord
) -> None:
    for capability in GRANTED_CAPABILITIES:
        await growth_access.set_owner_override(
            session,
            owner,
            scope="user",
            subject_id=actor.id,
            capability=capability,
            allowed=True,
            approval_required=capability in APPROVAL_CAPABILITIES,
            limits={"synthetic_acceptance": True},
        )


async def _revoke_all(
    session: AsyncSession, owner: UserRecord, actor: UserRecord
) -> None:
    for capability in GRANTED_CAPABILITIES:
        await growth_access.set_owner_override(
            session,
            owner,
            scope="user",
            subject_id=actor.id,
            capability=capability,
            allowed=False,
            approval_required=False,
            limits={"synthetic_acceptance": True},
        )


async def run_synthetic_acceptance(
    session: AsyncSession,
    *,
    owner: UserRecord,
    actor: UserRecord,
    isolation_actor: UserRecord,
    seed: str = "gs11",
) -> dict[str, Any]:
    """Exercise GS-01..GS-10 using local/simulated paths only.

    The caller owns the transaction and must roll it back after acceptance. The
    returned evidence intentionally excludes synthetic PII and provider/account
    identifiers so it is safe to persist in reports.
    """

    if owner.organization_id != actor.organization_id:
        raise GrowthFullSystemAcceptanceError("owner-actor-organization-mismatch")
    if isolation_actor.organization_id == actor.organization_id:
        raise GrowthFullSystemAcceptanceError("isolation-actor-must-use-other-tenant")

    initial = await growth_access.effective_access(session, actor, "campaign.research")
    _assert(not initial.allowed, "synthetic-actor-must-start-denied")

    await _grant_all(session, owner, actor)
    granted = await growth_access.snapshot(session, actor)
    _assert(
        all(item["allowed"] for item in granted["capabilities"]),
        "not-all-capabilities-granted",
    )

    account = await social.register_account(
        session,
        actor,
        {
            "provider": "reddit",
            "account_kind": "community",
            "external_account_id": f"synthetic-{seed}",
            "display_name": "GS-11 Synthetic Community",
            "credential_ref": f"secret-ref:synthetic-{seed}",
            "token_expires_at": _now() + timedelta(days=30),
            "provider_metadata": {"synthetic": True},
            "settings": {"acceptance": "gs11"},
        },
    )
    health = await social.simulate_health(session, actor, account.id)
    capability = await social.simulate_capability(
        session, actor, account.id, "content.publish"
    )
    _assert(health["health_state"] == "healthy", "synthetic-account-not-healthy")
    _assert(capability["live_provider_call"] is False, "provider-call-enabled")
    _assert(capability["live_verified"] is False, "synthetic-capability-live-verified")

    brief = await campaigns.create_brief(
        session,
        actor,
        {
            "name": "GS-11 Synthetic Campaign",
            "objective": "qualified_leads",
            "product_summary": "Synthetic product used only for full-system acceptance.",
            "target_markets": ["AE"],
            "audience_hypotheses": [
                {
                    "segment": "small-business-operators",
                    "rationale": "Synthetic segment for GS-11 acceptance",
                }
            ],
            "competitor_hypotheses": [
                {
                    "name": "manual-workflows",
                    "rationale": "Synthetic competitor hypothesis",
                }
            ],
            "offer_hypotheses": [
                {
                    "name": "guided-automation",
                    "rationale": "Synthetic offer hypothesis",
                }
            ],
            "channel_hypotheses": [
                {
                    "channel": "reddit",
                    "rationale": "Synthetic channel hypothesis",
                }
            ],
            "budget_minor": 100000,
            "currency": "AED",
            "evidence": [{"source": "synthetic", "reliability": 0.95}],
        },
    )
    campaign_sim_1 = await campaigns.simulate_brief(
        session, actor, brief.id, "conservative"
    )
    campaign_sim_2 = await campaigns.simulate_brief(
        session, actor, brief.id, "conservative"
    )
    _assert(
        campaign_sim_1.result == campaign_sim_2.result,
        "campaign-simulation-not-deterministic",
    )
    _assert(campaign_sim_1.real_spend_allowed is False, "campaign-real-spend-enabled")

    await growth_access.set_owner_override(
        session,
        isolation_actor,
        scope="user",
        subject_id=isolation_actor.id,
        capability="campaign.simulation",
        allowed=True,
        approval_required=False,
        limits={"synthetic_isolation_check": True},
    )
    isolation_blocked = False
    try:
        await campaigns.simulate_brief(
            session, isolation_actor, brief.id, "conservative"
        )
    except campaigns.GrowthCampaignError as exc:
        isolation_blocked = str(exc) == "brief-not-found"
    _assert(isolation_blocked, "tenant-isolation-not-enforced")

    content_item = await content.create_content(
        session,
        actor,
        {
            "title": "GS-11 Synthetic Creative",
            "content_type": "text",
            "base_text": "Synthetic acceptance content. No provider delivery occurs.",
            "link_url": "https://example.invalid/gs11",
            "tags": ["synthetic", "gs11"],
            "content_metadata": {"synthetic": True},
        },
    )
    variant = await content.create_variant(
        session,
        actor,
        content_item.id,
        {
            "provider": "reddit",
            "account_id": account.id,
            "text": "Synthetic acceptance variant.",
            "hashtags": ["gs11"],
        },
    )
    await content.request_approval(session, actor, content_item.id)
    await content.decide_approval(
        session,
        actor,
        content_item.id,
        approved=True,
        note="GS-11 synthetic approval",
    )
    scheduled = await content.schedule_variant(
        session,
        actor,
        variant.id,
        {
            "scheduled_for": _now() - timedelta(seconds=1),
            "timezone": "UTC",
            "recurrence": "none",
            "priority": 90,
        },
    )
    publish_sim = await content.simulate_schedule(
        session, actor, scheduled.id, now=_now()
    )
    _assert(
        publish_sim.status == "simulated_success", "content-simulation-not-successful"
    )
    _assert(publish_sim.live_publish_allowed is False, "live-publish-enabled")

    paid_campaign = await paid.create_campaign(
        session,
        actor,
        {
            "brief_id": brief.id,
            "name": "GS-11 Paid Simulation",
            "objective": "leads",
            "currency": "AED",
            "total_budget_minor": 100000,
            "daily_budget_cap_minor": 25000,
            "stop_loss_policy": {"max_cpa_minor": 5000, "min_roas": 1.25},
            "metadata": {"synthetic": True},
        },
    )
    ad_set = await paid.add_ad_set(
        session,
        actor,
        paid_campaign.id,
        {
            "name": "GS-11 Reddit",
            "provider": "reddit",
            "audience": {"country": "AE", "synthetic": True},
            "placements": ["feed"],
            "daily_budget_cap_minor": 20000,
        },
    )
    creative_a = await paid.add_creative(
        session,
        actor,
        paid_campaign.id,
        {"name": "A", "format": "text", "headline": "Synthetic A", "approved": True},
    )
    creative_b = await paid.add_creative(
        session,
        actor,
        paid_campaign.id,
        {"name": "B", "format": "text", "headline": "Synthetic B", "approved": True},
    )
    ad_a = await paid.add_ad(
        session,
        actor,
        paid_campaign.id,
        {"name": "Ad A", "ad_set_id": ad_set.id, "creative_id": creative_a.id},
    )
    ad_b = await paid.add_ad(
        session,
        actor,
        paid_campaign.id,
        {"name": "Ad B", "ad_set_id": ad_set.id, "creative_id": creative_b.id},
    )
    await paid.create_experiment(
        session,
        actor,
        paid_campaign.id,
        {
            "name": "GS-11 A/B",
            "hypothesis": "Synthetic A/B allocation is deterministic",
            "variant_ad_ids": [ad_b.id, ad_a.id],
        },
    )
    await paid.approve_campaign(session, owner, paid_campaign.id)
    paid_sim_1, paid_decision_1 = await paid.simulate_launch(
        session, actor, paid_campaign.id, days=3
    )
    paid_sim_2, paid_decision_2 = await paid.simulate_launch(
        session, actor, paid_campaign.id, days=3
    )
    _assert(paid_sim_1.seed == paid_sim_2.seed, "paid-seed-not-deterministic")
    _assert(paid_sim_1.result == paid_sim_2.result, "paid-results-not-deterministic")
    _assert(
        paid_decision_1.action == paid_decision_2.action,
        "paid-decision-not-deterministic",
    )
    _assert(paid_sim_1.real_spend_allowed is False, "paid-real-spend-enabled")
    _assert(paid_sim_1.live_provider_call is False, "paid-live-provider-call-enabled")
    _assert(paid_sim_1.live_campaign_mutation is False, "paid-live-mutation-enabled")
    _assert(
        paid_decision_1.automatic_execution_allowed is False,
        "paid-auto-execution-enabled",
    )

    lead, lead_created = await leads.upsert_lead(
        session,
        actor,
        {
            "source_type": "first_party_form",
            "collection_method": "consented_form",
            "source_ref": f"synthetic-form:{seed}",
            "display_name": "Synthetic Lead",
            "email": f"gs11-{seed}@example.invalid",
            "company_name": "Synthetic Company",
            "country_code": "AE",
            "attributes": {"synthetic": True},
        },
    )
    _assert(lead_created, "synthetic-lead-not-created")
    await leads.set_consent(
        session,
        actor,
        lead.id,
        {
            "purpose": "marketing",
            "lawful_basis": "consent",
            "evidence": {"source": "synthetic-form", "accepted": True},
            "expires_at": _now() + timedelta(days=30),
        },
    )
    lead_eligibility = await leads.eligibility(
        session, actor, lead.id, purpose="marketing", channel="social"
    )
    _assert(lead_eligibility["eligible"] is True, "synthetic-lead-not-eligible")
    _assert(
        lead_eligibility["live_provider_call"] is False, "lead-provider-call-enabled"
    )
    _assert(
        lead_eligibility["outbound_outreach_allowed"] is False, "lead-outreach-enabled"
    )

    thread, message, thread_created = await inbox.ingest_simulated_event(
        session,
        actor,
        {
            "provider": "reddit",
            "account_id": account.id,
            "external_thread_ref": f"synthetic-thread-{seed}",
            "external_message_ref": f"synthetic-message-{seed}",
            "thread_type": "dm",
            "message_type": "dm",
            "participant_ref": f"synthetic-participant-{seed}",
            "participant_name": "Synthetic Participant",
            "body": "I love this synthetic offer and want more information.",
        },
    )
    _assert(thread_created, "synthetic-thread-not-created")
    _assert(message.simulated is True, "inbox-message-not-simulated")
    await inbox.link_lead(session, actor, thread.id, lead.id)
    await inbox.mark_read(session, actor, thread.id, True)
    quick_reply = await inbox.create_quick_reply_draft(
        session,
        actor,
        thread.id,
        body="Synthetic reply draft only; no external send.",
        template_key="gs11",
        ai_suggested=True,
    )
    _assert(quick_reply.external_send_allowed is False, "inbox-external-send-enabled")

    failure_observation = await analytics.record_observation(
        session,
        actor,
        {
            "subject_type": "campaign",
            "subject_id": paid_campaign.id,
            "provider": "reddit",
            "source": "simulation",
            "period_start": _now() - timedelta(days=1),
            "period_end": _now(),
            "currency": "AED",
            "impressions": 20000,
            "reach": 15000,
            "engagements": 50,
            "clicks": 30,
            "conversions": 0,
            "spend_minor": 10000,
            "revenue_minor": 0,
            "evidence": [{"source": "synthetic", "reliability": 0.95}],
            "context": {
                "objective": "qualified_leads",
                "audience_key": "gs11-failure",
                "creative_key": "weak",
                "targets": {
                    "min_impressions": 1000,
                    "min_ctr": 0.01,
                    "min_conversion_rate": 0.02,
                    "max_cpa_minor": 5000,
                    "min_roas": 1.5,
                },
            },
        },
    )
    failure_learning, failure_recommendation = await analytics.analyze_observation(
        session, actor, failure_observation.id
    )
    _assert(failure_learning.outcome == "failure", "failure-learning-not-failure")
    _assert(failure_recommendation.action == "iterate", "first-failure-not-iterate")
    _assert(
        failure_recommendation.auto_optimization_allowed is False,
        "auto-optimization-enabled",
    )

    success_observation = await analytics.record_observation(
        session,
        actor,
        {
            "subject_type": "campaign",
            "subject_id": paid_campaign.id,
            "provider": "reddit",
            "source": "simulation",
            "period_start": _now() - timedelta(days=1),
            "period_end": _now(),
            "currency": "AED",
            "impressions": 20000,
            "reach": 17000,
            "engagements": 2200,
            "clicks": 1200,
            "conversions": 120,
            "spend_minor": 120000,
            "revenue_minor": 480000,
            "evidence": [{"source": "synthetic", "reliability": 0.95}],
            "context": {
                "objective": "qualified_leads",
                "audience_key": "gs11-success",
                "creative_key": "winner",
                "offer_key": "guided-automation",
                "geo_key": "AE",
                "placement_key": "feed",
                "targets": {
                    "min_impressions": 1000,
                    "min_ctr": 0.02,
                    "min_conversion_rate": 0.04,
                    "max_cpa_minor": 2000,
                    "min_roas": 2.0,
                },
            },
        },
    )
    success_learning, replay_recommendation = await analytics.analyze_observation(
        session, actor, success_observation.id
    )
    _assert(success_learning.outcome == "success", "success-learning-not-success")
    _assert(
        replay_recommendation.action == "replay_candidate",
        "success-not-replay-candidate",
    )
    _assert(
        replay_recommendation.replay_eligible is True, "replay-candidate-not-eligible"
    )
    _assert(
        replay_recommendation.auto_replay_allowed is False, "automatic-replay-enabled"
    )

    integration = await advanced.create_integration(
        session,
        actor,
        {
            "integration_type": "webhook",
            "provider": "generic",
            "name": f"GS-11 Synthetic Integration {seed}",
            "config": {"endpoint": "https://example.invalid/gs11"},
            "capabilities": ["report.delivery"],
        },
    )
    integration_evidence = await advanced.simulate_integration(
        session, actor, integration.id
    )
    _assert(
        integration_evidence["provider_call_allowed"] is False,
        "integration-provider-call-enabled",
    )
    _assert(
        integration_evidence["external_delivery_allowed"] is False,
        "integration-delivery-enabled",
    )

    team_assignment = await advanced.upsert_team_assignment(
        session,
        actor,
        {
            "user_id": actor.id,
            "scope_type": "reports",
            "scope_id": f"gs11-{seed}",
            "role_key": "reviewer",
            "permissions": ["read", "export"],
            "approval_required": True,
        },
    )
    routing = await advanced.simulate_team_routing(
        session, actor, "reports", f"gs11-{seed}"
    )
    _assert(routing["matched_assignments"] == 1, "team-routing-no-match")
    _assert(routing["assignment_applied"] is False, "team-routing-applied-mutation")
    _assert(team_assignment.active is True, "team-assignment-not-active")

    report_definition = await advanced.create_report_definition(
        session,
        actor,
        {
            "name": "GS-11 Synthetic Executive Report",
            "report_type": "executive",
            "formats": ["json", "csv", "xlsx", "pdf"],
            "schedule_kind": "manual",
            "timezone": "UTC",
            "brand_name": "AIONEX AIOS",
            "branding": {"synthetic": True},
        },
    )
    report_run = await advanced.run_report(session, actor, report_definition.id)
    _assert(report_run.simulated is True, "report-not-simulated")
    _assert(
        report_run.external_delivery_allowed is False,
        "report-external-delivery-enabled",
    )
    artifact_formats = {item["format"] for item in report_run.artifact_manifest}
    _assert(
        artifact_formats == {"json", "csv", "xlsx", "pdf"},
        "report-artifacts-incomplete",
    )
    for format_name in sorted(artifact_formats):
        artifact, media_type, filename = await advanced.report_artifact(
            session, actor, report_run.id, format_name
        )
        _assert(bool(artifact), f"empty-report-artifact:{format_name}")
        _assert(bool(media_type), f"missing-report-media-type:{format_name}")
        _assert(
            filename.endswith(f".{format_name}"),
            f"report-filename-mismatch:{format_name}",
        )

    await _revoke_all(session, owner, actor)
    revoked = await growth_access.snapshot(session, actor)
    _assert(
        all(not item["allowed"] for item in revoked["capabilities"]),
        "owner-revocation-not-immediate",
    )
    access_blocked_after_revoke = False
    try:
        await campaigns.list_briefs(session, actor)
    except campaigns.GrowthCampaignError as exc:
        access_blocked_after_revoke = str(exc) == "access-denied:owner-deny"
    _assert(access_blocked_after_revoke, "revoked-capability-still-usable")

    return {
        "status": "GS11_SYNTHETIC_ACCEPTANCE_OK",
        "capabilities_granted": len(GRANTED_CAPABILITIES),
        "capabilities_revoked": len(GRANTED_CAPABILITIES),
        "tenant_isolation_enforced": True,
        "account_health": health["health_state"],
        "account_capability_simulated": capability["verification_state"] == "simulated",
        "campaign_simulation_deterministic": True,
        "content_publish_simulated": publish_sim.status == "simulated_success",
        "paid_campaign_simulation_deterministic": True,
        "paid_decision": paid_decision_1.action,
        "lead_eligible": bool(lead_eligibility["eligible"]),
        "inbox_event_simulated": bool(message.simulated),
        "quick_reply_external_send_allowed": False,
        "failure_learning_action": failure_recommendation.action,
        "successful_replay_action": replay_recommendation.action,
        "successful_replay_eligible": bool(replay_recommendation.replay_eligible),
        "auto_replay_allowed": False,
        "auto_optimization_allowed": False,
        "integration_external_delivery_allowed": False,
        "team_routing_mutation_applied": False,
        "report_formats": sorted(artifact_formats),
        "report_aggregate_only": bool(
            report_run.data_snapshot.get("privacy", {}).get("aggregate_only")
        ),
        "raw_credentials_exported": False,
        "lead_contact_pii_exported": False,
        "live_provider_call": False,
        "live_publish_allowed": False,
        "external_send_allowed": False,
        "live_audience_upload_allowed": False,
        "live_campaign_mutation": False,
        "real_spend_allowed": False,
        "automatic_execution_allowed": False,
        "owner_revocation_enforced": True,
        "transaction_cleanup_required": True,
    }
