"""Cross-layer source contract; runtime proofs live in dedicated backend tests."""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "web-dashboard/backend"


def test_governed_chat_has_real_routes_worker_and_lifespan_integration():
    routes = (BACKEND / "app/api/v1/router.py").read_text()
    lifecycle = (BACKEND / "main.py").read_text()
    worker = (BACKEND / "app/services/conversation_worker.py").read_text()
    assert "project_conversations.router" in routes
    assert "owner_conversation_governance.router" in routes
    assert "conversation_worker.start" in lifecycle
    assert "conversation_worker.stop" in lifecycle
    assert "await ai._execute_provider(" in worker
    assert 'Job.status == "queued"' in worker
    assert 'job.status != "queued"' in worker
    assert 'job.status = "running"' in worker
    assert "await session.commit()" in worker
    assert '"needs_review"' in worker


def test_budget_project_and_socket_paths_are_server_wired():
    for relative in ("app/api/v1/endpoints/project_executions.py", "app/api/v1/endpoints/ai_agents.py"):
        assert "await charge_project_request(" in (BACKEND / relative).read_text()
    assert "await project_capacity(" in (BACKEND / "app/api/v1/endpoints/projects.py").read_text()
    assert "await owner_project_capacity(" in (BACKEND / "app/api/owner/control_plane.py").read_text()
    assert "require_stream_allowed" in (BACKEND / "app/realtime/authorized_socket.py").read_text()


def test_portal_conversation_contract_is_complete_in_all_six_languages():
    source = (ROOT / "vip-frontend/src/components/pages/conversations-client.tsx").read_text()
    dictionaries = [json.loads((ROOT / f"vip-frontend/src/messages/{locale}.json").read_text())
                    for locale in ("en", "ar", "fr", "de", "es", "tr")]
    expected = set(dictionaries[0]["conversations"])
    for dictionary in dictionaries:
        assert set(dictionary["conversations"]) == expected
        assert dictionary["nav"]["conversations"]
        assert dictionary["projects"]["openConversations"]
    assert "performance.now()" in source
    assert "current.seconds_remaining" in source
    assert "confirm_external_processing" in (ROOT / "vip-frontend/src/lib/project-conversations.ts").read_text()
    assert "setInterval" in source and "conversationApi.history" in source
    assert (ROOT / "vip-frontend/src/app/[locale]/conversations/page.tsx").is_file()
    assert '"Conversation Governance"' in (ROOT / "web-dashboard/frontend/src/config/owner-navigation.ts").read_text()
    assert (ROOT / "web-dashboard/frontend/src/app/owner/conversation-governance/page.tsx").is_file()


def test_governance_source_receipt_does_not_claim_unperformed_production_release():
    plan = json.loads((ROOT / "docs/project/PLAN.json").read_text())
    batch = next(b for b in plan["batches"] if b["id"] == "FR-07")
    item = batch["governed_project_conversations_source"]
    assert item["source_part"] == "FR-07BCE"
    assert item["database_migration_required"] is False
    assert item["server_enforced_policy"] is True
    assert item["browser_provider_transport"] == "explicit_synthetic_http_fixture"
    assert item["live_ai_inference_certified"] is False
    assert item["production_deployed"] is False
    assert item["parent_batch_complete"] is False
    assert all((ROOT / name).is_file() for name in item["evidence"])


def test_new_async_test_names_do_not_silently_overwrite_previous_cases():
    for name in ("test_fr07_governed_conversations.py", "test_fr07_governance_review_regressions.py",
                 "test_fr07_governed_stream_policy.py", "test_fr07_governance_http.py"):
        tree = ast.parse((BACKEND / "tests" / name).read_text())
        names = [node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        assert len(names) == len(set(names)), name


def test_public_gateway_exposes_only_the_user_conversation_contract():
    import re
    source = (ROOT / "web-dashboard/docker/nginx.conf").read_text()
    pattern = next(line.split('"')[1] for line in source.splitlines()
                   if 'location ~ "^/api/v1/' in line and 'project-conversations' in line)
    for suffix in ("", "/policy", "/agents", "/a1234567-1234-5678-9012-123456789012/messages", "/a1234567-1234-5678-9012-123456789012/close"):
        assert re.fullmatch(pattern, "/api/v1/project-conversations" + suffix)
    for path in ("/api/v1/owner/conversation-governance", "/api/v1/project-conversations/owner", "/api/v1/project-conversations/../owner", "/api/v1/project-conversations/a1234567-1234-5678-9012-123456789012/reset"):
        assert re.fullmatch(pattern, path) is None


def test_frontend_runtime_tls_is_patched_without_removing_backend_build_tooling():
    for relative in ("web-dashboard/frontend/Dockerfile", "vip-frontend/Dockerfile"):
        source = (ROOT / relative).read_text()
        runtime = source.split(" AS runner", 1)[1]
        assert "'libcrypto3>=3.5.9-r0' 'libssl3>=3.5.9-r0'" in runtime
        assert 'test "${crypto#libcrypto3-}" = "${ssl#libssl3-}"' in runtime
        assert "/usr/local/lib/node_modules/npm /opt/yarn-*" in runtime
        assert 'CMD ["node", "server.js"]' in runtime
    backend = (BACKEND / "Dockerfile").read_text()
    assert "FROM runtime AS project-worker" in backend
    assert "chromium" in backend and "npm" in backend
