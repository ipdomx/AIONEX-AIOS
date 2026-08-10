from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Final, Literal

BatchStatus = Literal["complete", "pending", "deferred"]
FeatureStatus = Literal["verified", "pending", "deferred"]


@dataclass(frozen=True, slots=True)
class CompletionFeature:
    feature_id: str
    batch_id: str
    title: str
    status: FeatureStatus
    acceptance: tuple[str, ...]
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CompletionBatch:
    batch_id: str
    sequence: int
    title: str
    status: BatchStatus
    objective: str
    feature_ids: tuple[str, ...]


FEATURES: Final[tuple[CompletionFeature, ...]] = (
    CompletionFeature(
        "completion-registry",
        "29A",
        "Authoritative platform completion registry",
        "verified",
        (
            "Every current AIOS module is assigned to exactly one completion batch.",
            "Every Owner page, public portal page, and backend endpoint is assigned.",
            "Unregistered future surfaces fail automated tests.",
        ),
        (
            "src/aios/completion_program.py",
            "tests/test_phase29_completion_program.py",
        ),
    ),
    CompletionFeature(
        "completion-control-plane",
        "29A",
        "Owner-visible completion program",
        "verified",
        (
            "The protected Owner finalization contract exposes batches and progress.",
            "The Completion Inventory distinguishes runtime readiness from program completion.",
        ),
        (
            "web-dashboard/backend/app/api/owner/control_plane.py",
            "web-dashboard/frontend/src/app/owner/completion/page.tsx",
        ),
    ),
    CompletionFeature(
        "completion-roadmap-ci",
        "29A",
        "No-omission roadmap and CI gate",
        "verified",
        (
            "Models and providers are the final batch.",
            "No batch may close with a pending feature.",
            "The roadmap is versioned and reviewed through GitHub.",
        ),
        ("docs/phase-29/PHASE_29_PLATFORM_COMPLETION_PROGRAM.md",),
    ),
    CompletionFeature(
        "public-portal-release",
        "29B",
        "Public portal and user experience activation",
        "verified",
        (
            "The current portal release is built as a complete direct-document-root artifact for the final shared-hosting upload.",
            "All six locales, mobile layouts, accessibility, PWA, SEO, and legal pages pass real-browser acceptance.",
            "The full project lifecycle, approval, and download controls are visible to normal users.",
        ),
        (
            "docs/phase-29/PHASE_29B_PUBLIC_PORTAL_ORIGIN.md",
            "tests/test_phase29b_portal_accessibility_contracts.py",
        ),
    ),
    CompletionFeature(
        "owner-portal-cms",
        "29B",
        "Owner-controlled portal CMS and publishing",
        "verified",
        (
            "Branding, pages, pricing, assets, translations, publish, and rollback work against retained production data.",
            "Public and private portal boundaries remain enforced.",
        ),
        (
            "docs/phase-29/PHASE_29B_PUBLIC_PORTAL_ORIGIN.md",
            "web-dashboard/backend/tests/test_portal_cms.py",
        ),
    ),
    CompletionFeature(
        "identity-tenancy",
        "29C",
        "Identity, organizations, workspaces, teams, roles, and permissions",
        "verified",
        (
            "Tenant isolation and role authority are proven end to end.",
            "User, organization, workspace, team, role, and permission lifecycles are complete.",
        ),
        (
            "web-dashboard/backend/tests/test_identity_sql_endpoints.py",
            "web-dashboard/backend/app/api/v1/endpoints/teams.py",
            "web-dashboard/frontend/src/lib/identity-api.ts",
        ),
    ),
    CompletionFeature(
        "authentication-security",
        "29C",
        "Authentication, sessions, recovery, passkeys, phone, and social login",
        "verified",
        (
            "Password, refresh, logout, recovery, MFA, revocation, passkey, phone, and configured social contracts pass acceptance.",
            "Suspension, password recovery, and authentication-generation changes invalidate every session.",
        ),
        (
            "web-dashboard/backend/tests/test_phase29c_account_security.py",
            "web-dashboard/backend/app/services/account_security.py",
            "vip-frontend/src/components/pages/login-client.tsx",
        ),
    ),
    CompletionFeature(
        "account-settings",
        "29C",
        "Account profile, preferences, language, security, and privacy",
        "verified",
        (
            "Profile, password, notification preferences, language, timezone, theme, MFA, passkeys, and session management are complete.",
        ),
        (
            "vip-frontend/src/components/pages/profile-client.tsx",
            "vip-frontend/src/components/auth/account-security-manager.tsx",
            "web-dashboard/backend/app/api/v1/endpoints/settings.py",
        ),
    ),
    CompletionFeature(
        "billing-licensing",
        "29D",
        "Billing, plans, licensing, seats, quotas, and metering",
        "verified",
        (
            "Plan, seat, quota, usage, suspension, restore, and cost-governance records agree across API and Owner UI.",
        ),
        (
            "docs/phase-29/PHASE_29D_BILLING_PAYMENTS_COMPLETION.md",
            "web-dashboard/backend/app/services/billing.py",
            "web-dashboard/frontend/src/app/owner/billing/page.tsx",
        ),
    ),
    CompletionFeature(
        "payments-commerce",
        "29D",
        "Payments, checkout, invoices, subscriptions, refunds, and webhooks",
        "verified",
        (
            "Sandbox and production-safe payment flows are idempotent, tenant-scoped, audited, and reconciled.",
            "Pricing shown publicly matches enforced entitlements.",
        ),
        (
            "web-dashboard/backend/tests/test_phase29d_billing_payments.py",
            "web-dashboard/backend/app/api/v1/endpoints/billing.py",
            "vip-frontend/src/components/pages/billing-client.tsx",
            "vip-frontend/src/components/pages/pricing-client.tsx",
        ),
    ),
    CompletionFeature(
        "notifications-channels",
        "29E",
        "Notification center and delivery channels",
        "verified",
        (
            "In-app, email, push, Telegram, and WhatsApp channel states are truthful and delivery is audited.",
            "Missing external credentials fail closed without losing durable notifications.",
        ),
        (
            "docs/phase-29/PHASE_29E_COMMUNICATIONS_GOVERNANCE_COMPLETION.md",
            "web-dashboard/backend/app/services/communications.py",
            "web-dashboard/backend/app/services/communication_worker.py",
            "vip-frontend/src/components/pages/notifications-client.tsx",
        ),
    ),
    CompletionFeature(
        "communications-support",
        "29E",
        "Communications, support, incidents, and escalation",
        "verified",
        (
            "User support, owner escalation, incidents, acknowledgements, retries, and delivery receipts are complete.",
        ),
        (
            "web-dashboard/backend/app/api/v1/endpoints/support.py",
            "web-dashboard/backend/app/api/v1/endpoints/incidents.py",
            "web-dashboard/frontend/src/app/owner/communications/page.tsx",
            "vip-frontend/src/components/pages/support-client.tsx",
        ),
    ),
    CompletionFeature(
        "meetings-approvals-governance",
        "29E",
        "Meetings, councils, policies, approvals, and government workflows",
        "verified",
        (
            "Meeting lifecycle and every approval decision are durable, tenant-safe, owner-governed, and audited.",
        ),
        (
            "web-dashboard/backend/app/services/governance.py",
            "web-dashboard/backend/app/api/v1/endpoints/meetings.py",
            "web-dashboard/backend/app/api/v1/endpoints/governance.py",
            "web-dashboard/backend/tests/test_phase29e_communications_governance.py",
            "web-dashboard/frontend/src/app/owner/governance/page.tsx",
        ),
    ),
    CompletionFeature(
        "project-work-management",
        "29F",
        "Projects, tasks, workflows, reports, and delivery history",
        "verified",
        (
            "Create, update, run, pause, resume, review, approve, archive, search, report, and download paths pass end to end.",
        ),
        (
            "docs/phase-29/PHASE_29F_PROJECTS_WORKFORCE_KNOWLEDGE_COMPLETION.md",
            "web-dashboard/backend/app/services/work_management.py",
            "web-dashboard/backend/app/api/v1/endpoints/project_executions.py",
            "web-dashboard/backend/tests/test_phase29f_projects_workforce_knowledge.py",
            "vip-frontend/src/components/pages/projects-client.tsx",
        ),
    ),
    CompletionFeature(
        "workforce-academy",
        "29F",
        "Digital workforce, HR, health, training, certification, and promotion",
        "verified",
        (
            "Assignment, performance, incidents, retraining, tests, certification, suspension, retirement, and promotion are durable.",
        ),
        (
            "web-dashboard/backend/app/services/workforce.py",
            "web-dashboard/backend/app/api/v1/endpoints/workforce.py",
            "web-dashboard/backend/app/api/v1/endpoints/academy.py",
            "web-dashboard/frontend/src/app/workforce/page.tsx",
            "web-dashboard/frontend/src/app/academy/page.tsx",
            "web-dashboard/frontend/src/app/owner/staff/page.tsx",
        ),
    ),
    CompletionFeature(
        "knowledge-learning",
        "29F",
        "Knowledge, memory, provenance, learning, and self-improvement evidence",
        "verified",
        (
            "Knowledge ingestion, verification, provenance, scoped memory, lessons, and outcome learning are tenant-safe and testable.",
        ),
        (
            "web-dashboard/backend/app/services/knowledge_learning.py",
            "web-dashboard/backend/app/api/v1/endpoints/knowledge.py",
            "web-dashboard/frontend/src/app/knowledge/page.tsx",
            "web-dashboard/backend/tests/test_phase29f_projects_workforce_knowledge.py",
        ),
    ),
    CompletionFeature(
        "infrastructure-operations",
        "29G",
        "Infrastructure inventory, runtime, queues, databases, containers, and multi-service operations",
        "verified",
        (
            "Every production component has truthful health, ownership, configuration, and failure handling.",
        ),
        (
            "docs/phase-29/PHASE_29G_OPERATIONS_SECURITY_RECOVERY_RELEASE_COMPLETION.md",
            "web-dashboard/backend/app/services/operations_assurance.py",
            "web-dashboard/backend/app/services/operations_observer.py",
            "web-dashboard/backend/app/api/v1/endpoints/servers.py",
            "web-dashboard/backend/app/api/v1/endpoints/containers.py",
            "web-dashboard/backend/app/api/v1/endpoints/databases.py",
        ),
    ),
    CompletionFeature(
        "observability-incidents",
        "29G",
        "Metrics, logs, traces, alerts, topology, incidents, and audit",
        "verified",
        (
            "Operational telemetry is live, searchable, retained, correlated, and drives incident workflows.",
        ),
        (
            "docs/phase-29/PHASE_29G_OPERATIONS_SECURITY_RECOVERY_RELEASE_COMPLETION.md",
            "web-dashboard/backend/app/api/v1/endpoints/monitoring.py",
            "web-dashboard/backend/app/api/owner/control_plane.py",
            "web-dashboard/backend/tests/test_phase29g_operations_security_recovery.py",
        ),
    ),
    CompletionFeature(
        "security-compliance",
        "29G",
        "Security, secrets, policies, threats, compliance, and evidence",
        "verified",
        (
            "Security and compliance controls use executed evidence, enforce tenant and owner boundaries, and fail closed.",
        ),
        (
            "docs/phase-29/PHASE_29G_OPERATIONS_SECURITY_RECOVERY_RELEASE_COMPLETION.md",
            "web-dashboard/backend/app/api/v1/endpoints/security.py",
            "web-dashboard/frontend/src/app/owner/secrets/page.tsx",
            "web-dashboard/frontend/src/app/owner/compliance-runtime/page.tsx",
            "web-dashboard/backend/tests/test_phase29g_operations_security_recovery.py",
        ),
    ),
    CompletionFeature(
        "backup-recovery-release",
        "29G",
        "Backups, restore, disaster recovery, release governance, and rollback",
        "verified",
        (
            "Backup, checksum, restore drill, recovery objectives, release gates, approval, deployment, and rollback are proven live.",
        ),
        (
            "docs/phase-29/PHASE_29G_OPERATIONS_SECURITY_RECOVERY_RELEASE_COMPLETION.md",
            "web-dashboard/backend/app/api/v1/endpoints/backups.py",
            "web-dashboard/backend/app/services/backup_worker.py",
            "web-dashboard/backend/app/api/owner/control_plane.py",
            "web-dashboard/frontend/src/app/owner/release-governance/page.tsx",
            "web-dashboard/backend/tests/test_phase29g_operations_security_recovery.py",
        ),
    ),
    CompletionFeature(
        "production-studio",
        "29H",
        "Production Studio for text, image, audio, video, web, and 3D artifacts",
        "verified",
        (
            "Provider-neutral contracts, jobs, assets, revisions, safety, download, and project attachment are complete.",
            "Provider activation remains reserved for batch 29J.",
        ),
        (
            "docs/phase-29/PHASE_29H_PRODUCTION_STUDIO_MOBILE_DELIVERY_COMPLETION.md",
            "web-dashboard/backend/app/services/production_studio.py",
            "web-dashboard/backend/app/services/studio_worker.py",
            "web-dashboard/backend/app/api/v1/endpoints/studio.py",
            "web-dashboard/frontend/src/app/studio/page.tsx",
            "web-dashboard/backend/tests/test_phase29h_studio_mobile_delivery.py",
        ),
    ),
    CompletionFeature(
        "mobile-pwa-delivery",
        "29H",
        "PWA, Android, iOS, mobile notifications, and release artifacts",
        "verified",
        (
            "Mobile and PWA builds, signing boundaries, install/update behavior, offline state, and release artifacts are verified.",
        ),
        (
            "docs/phase-29/PHASE_29H_PRODUCTION_STUDIO_MOBILE_DELIVERY_COMPLETION.md",
            "vip-frontend/public/sw.js",
            "scripts/mobile/build_android.sh",
            "scripts/mobile/build_phase29h_release.py",
            "scripts/mobile/validate_ios_source.py",
            "web-dashboard/backend/app/api/v1/endpoints/mobile_delivery.py",
            "web-dashboard/frontend/src/app/owner/mobile-delivery/page.tsx",
            "web-dashboard/backend/tests/test_phase29h_studio_mobile_delivery.py",
        ),
    ),
    CompletionFeature(
        "plugins-marketplace",
        "29I",
        "Plugin SDK, marketplace, installation, permissions, isolation, and lifecycle",
        "verified",
        (
            "Plugin publish, review, install, update, disable, uninstall, permission, audit, and rollback are complete.",
        ),
        ("docs/phase-29/PHASE_29I_PLUGINS_DISTRIBUTED_INTEGRATIONS_COMPLETION.md", "src/aios/phase29i.py", "tests/test_phase29i_completion.py"),
    ),
    CompletionFeature(
        "distributed-runtime",
        "29I",
        "Distributed workers, clusters, multi-host execution, leases, and recovery",
        "verified",
        (
            "Multi-node execution, fencing, scheduling, retries, cancellation, failover, evidence, and reconciliation pass live tests.",
        ),
        ("docs/phase-29/PHASE_29I_PLUGINS_DISTRIBUTED_INTEGRATIONS_COMPLETION.md", "src/aios/phase29i.py", "tests/test_phase29i_completion.py", "tests/test_phase23_distributed_execution_fabric.py", "tests/test_phase24a_multi_node_cluster_runtime.py", "tests/test_phase24b_multi_host_cluster_deployment.py"),
    ),
    CompletionFeature(
        "external-integrations",
        "29I",
        "Cloud, source control, storage, webhooks, calendars, messaging, and enterprise integrations",
        "verified",
        (
            "Each non-model integration has configuration, health, scopes, retries, audit, disable, and recovery behavior.",
            "External credentials remain truthful activation boundaries; missing credentials never report ready.",
        ),
        ("docs/phase-29/PHASE_29I_PLUGINS_DISTRIBUTED_INTEGRATIONS_COMPLETION.md", "src/aios/phase29i.py", "src/aios/infrastructure", "tests/test_phase29i_completion.py", "tests/test_phase8_part2_development_server_integrations.py", "tests/test_phase8_part3_cloud_platform_integrations.py"),
    ),
    CompletionFeature(
        "models-providers",
        "29J",
        "All models and external providers, routing, capabilities, budgets, and fallbacks",
        "verified",
        (
            "Every supported AI provider is explicitly represented by the final contract and can only become active when a credential reference or local runtime exists.",
            "Model discovery, capability routing, policy, budgets, rate limits, tools, streaming, structured output, embeddings, media, local/cloud modes, health, retries, safety, costs and fallback modes are covered by retained tests and UI/API surfaces.",
            "Unconfigured providers remain visibly unconfigured; no secret or unavailable provider is represented as active.",
        ),
        ("docs/phase-29/PHASE_29J_MODELS_PROVIDERS_FINAL_COMPLETION.md", "docs/phase-29/PHASE_29J_LIVE_ACCEPTANCE_2026-08-10.md", "src/aios/phase29j.py", "src/aios/providers", "web-dashboard/backend/app/services/ai_runtime_service.py", "web-dashboard/backend/app/api/v1/endpoints/ai_providers.py", "web-dashboard/backend/app/api/v1/endpoints/ai_agents.py", "web-dashboard/frontend/src/app/ai/providers/page.tsx", "web-dashboard/frontend/src/app/ai/models/page.tsx", "web-dashboard/frontend/src/app/ai/agents/page.tsx", "tests/test_phase29j_completion.py", "web-dashboard/backend/tests/test_phase29j_models_providers.py", "web-dashboard/backend/tests/test_batch3_ai_runtime.py"),
    ),
)


def _feature_ids(batch_id: str) -> tuple[str, ...]:
    return tuple(feature.feature_id for feature in FEATURES if feature.batch_id == batch_id)


BATCHES: Final[tuple[CompletionBatch, ...]] = (
    CompletionBatch("29A", 1, "Completion governance and exhaustive inventory", "complete", "Establish the no-omission completion contract and Owner visibility.", _feature_ids("29A")),
    CompletionBatch("29B", 2, "Public portal and product experience", "complete", "Deploy and verify every public and user-facing portal capability.", _feature_ids("29B")),
    CompletionBatch("29C", 3, "Identity, tenancy, access, and accounts", "complete", "Finish all identity and account lifecycles and prove isolation.", _feature_ids("29C")),
    CompletionBatch("29D", 4, "Billing, licensing, payments, and entitlements", "complete", "Finish commercial, quota, metering, and payment lifecycles.", _feature_ids("29D")),
    CompletionBatch("29E", 5, "Communications, notifications, meetings, and governance", "complete", "Finish human communication, escalation, councils, and approvals.", _feature_ids("29E")),
    CompletionBatch("29F", 6, "Projects, workforce, academy, knowledge, and workflows", "complete", "Finish daily project operations and the governed digital workforce.", _feature_ids("29F")),
    CompletionBatch("29G", 7, "Operations, observability, security, recovery, and release", "complete", "Prove the complete production operations and assurance plane.", _feature_ids("29G")),
    CompletionBatch("29H", 8, "Production Studio and mobile delivery", "complete", "Finish provider-neutral media production and mobile delivery surfaces.", _feature_ids("29H")),
    CompletionBatch("29I", 9, "Plugins, marketplace, distributed runtime, and integrations", "complete", "Extension, distribution, and non-model enterprise integrations are verified; external credentials remain truthful activation boundaries.", _feature_ids("29I")),
    CompletionBatch("29J", 10, "Models and providers — final batch", "complete", "Durable agent/provider execution, truthful activation, live provider verification, controlled production execution, and Owner action contracts are verified.", _feature_ids("29J")),
)


MODULE_BATCH: Final[dict[str, str]] = {
    "academy": "29F", "access": "29C", "api_experience": "29B", "api_gateway": "29G",
    "autonomy_governance": "29E", "cluster_runtime": "29I", "cognitive": "29E",
    "dashboard": "29B", "distributed": "29I", "distributed_runtime": "29I",
    "engineering_platform": "29F", "enterprise": "29I", "enterprise_continuity": "29G",
    "enterprise_hardening": "29G", "enterprise_intelligence": "29F",
    "enterprise_launch_operations": "29G", "enterprise_marketplace": "29I",
    "execution_fabric": "29I", "gateway": "29G", "global_communications": "29E",
    "government": "29E", "hr": "29F", "infrastructure": "29G", "intelligence": "29E",
    "interactions": "29C", "ios": "29H", "ios_app": "29H", "knowledge_learning": "29F",
    "languages": "29B", "meetings_access": "29E", "ministries": "29E",
    "mission_control": "29G", "mobile": "29H", "mobile_android": "29H",
    "mobile_ecosystem": "29H", "models": "29J", "multi_host_runtime": "29I",
    "notifications": "29E", "orchestration": "29F", "organization": "29C",
    "payments": "29D", "plugin_sdk": "29I", "plugins": "29I",
    "production_hardening": "29G", "providers": "29J", "release_candidate": "29G",
    "release_governance": "29G", "runtime": "29G", "security_platform": "29G",
    "self_evolution": "29F", "services": "29G", "stable_release": "29G",
    "telegram_bot": "29E", "three_d_web": "30A", "web_dashboard_integration": "29B", "web_integration": "29B",
    "workers": "29F", "workforce_health": "29F",
    "gpu_worker": "33",
}

OWNER_PAGE_BATCH: Final[dict[str, str]] = {
    "3d": "34B",
    "access": "29C", "approvals": "29E", "approvals-live": "29E", "audit": "29G",
    "billing": "29D", "communications": "29E", "completion": "29A", "compliance": "29G",
    "compliance-runtime": "29G", "costs": "29D", "executive": "29B", "executive-bi": "29B",
    "final-platform-integration": "29G", "finalization": "29G", "global-command": "29B",
    "governance": "29E", "health": "29G", "incidents": "29E", "integrations": "29I",
    "licensing": "29D", "mobile-delivery": "29H", "notification-runtime": "29E", "notifications": "29E",
    "operations": "29C", "operations-integration": "29G", "organizations": "29C",
    "platform-integration": "29G", "policies": "29E", "portal": "29B",
    "production-runtime": "29G", "projects": "29F", "realtime": "29G", "recovery": "29G",
    "release": "29G", "release-governance": "29G", "runtime": "29B", "search": "29B",
    "secrets": "29G", "security-integration": "29G", "security-lab": "34E", "services": "29G", "staff": "29F",
    "support": "29E", "system-map": "29G", "timeline": "29B",
}

VIP_PAGE_BATCH: Final[dict[str, str]] = {
    "(root)/page.tsx": "29B", "[locale]/about/page.tsx": "29B",
    "[locale]/billing/page.tsx": "29D",
    "[locale]/contact/page.tsx": "29E", "[locale]/dashboard/page.tsx": "29F",
    "[locale]/notifications/page.tsx": "29E", "[locale]/support/page.tsx": "29E",
    "[locale]/legal/privacy/page.tsx": "29B", "[locale]/legal/terms/page.tsx": "29B",
    "[locale]/forgot-password/page.tsx": "29C",
    "[locale]/login/page.tsx": "29C", "[locale]/page.tsx": "29B",
    "[locale]/pricing/page.tsx": "29D", "[locale]/profile/page.tsx": "29C",
    "[locale]/projects/page.tsx": "29F", "[locale]/register/page.tsx": "29C",
    "[locale]/reset-password/page.tsx": "29C",
    "[locale]/security-lab/page.tsx": "34E",
}

ENDPOINT_BATCH: Final[dict[str, str]] = {
    "academy": "29F", "ai_agents": "29J", "ai_providers": "29J", "auth": "29C", "backups": "29G",
    "billing": "29D", "mobile_store_billing": "29D", "communications": "29E",
    "capabilities": "29A", "containers": "29G", "dashboard": "29B", "databases": "29G",
    "final_integration": "29G", "firebase_phone": "29C", "governance": "29E",
    "identity": "29C", "incidents": "29E", "integration": "29I", "knowledge": "29F", "locale": "29B", "meetings": "29E",
    "mobile_delivery": "29H", "monitoring": "29G", "notifications": "29E", "organizations": "29C",
    "permissions": "29C", "portal": "29B", "project_executions": "29F", "projects": "29F",
    "reports": "29F", "roles": "29C", "search": "29B", "security": "29G", "security_lab": "34E",
    "servers": "29G", "settings": "29C", "studio": "29H", "support": "29E",
    "tasks": "29F", "teams": "29C", "three_d_jobs": "34D", "users": "29C", "websocket": "29E",
    "workflows": "29F", "workforce": "29F", "workspaces": "29C",
}


def completion_program_snapshot() -> dict[str, object]:
    completed = sum(feature.status == "verified" for feature in FEATURES)
    actionable = sum(feature.status != "deferred" for feature in FEATURES)
    batches = []
    for batch in BATCHES:
        features = [feature for feature in FEATURES if feature.batch_id == batch.batch_id]
        batches.append(
            {
                **asdict(batch),
                "features": [asdict(feature) for feature in features],
                "verified_features": sum(feature.status == "verified" for feature in features),
                "total_features": len(features),
            }
        )
    current = next((batch.batch_id for batch in BATCHES if batch.status in {"pending", "deferred"}), None)
    return {
        "program": "Phase 29 — Platform Completion Program",
        "completion": round(100 * completed / max(1, len(FEATURES))),
        "verified_features": completed,
        "actionable_features": actionable,
        "deferred_features": sum(feature.status == "deferred" for feature in FEATURES),
        "current_batch": current,
        "models_providers_batch": "29J",
        "batches": batches,
    }
