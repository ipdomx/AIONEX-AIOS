import asyncio

from app.core.ai_runtime import AIRuntimeState


def test_provider_agent_job_and_notification_flow():
    runtime = AIRuntimeState()
    organization_id = "aionex-org"

    providers = runtime.list_providers(organization_id)
    assert providers

    agent = runtime.create_agent(
        {
            "name": "Runtime Test Agent",
            "role": "Engineer",
            "department": "Engineering",
            "provider_id": providers[0]["id"],
            "model": "test-model",
            "system_prompt": "Test safely.",
            "workspace_id": None,
        },
        organization_id,
    )
    assert agent["name"] == "Runtime Test Agent"

    job = runtime.create_job(agent["id"], organization_id, "verify runtime execution")
    asyncio.run(runtime.run_job(job.id))
    assert runtime.jobs[job.id].status == "completed"
    assert runtime.jobs[job.id].result
    assert runtime.list_notifications(organization_id)


def test_provider_cannot_be_removed_while_assigned():
    runtime = AIRuntimeState()
    provider_id = next(iter(runtime.providers))
    try:
        runtime.delete_provider(provider_id, "aionex-org")
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 409
    else:
        raise AssertionError("assigned provider deletion should be rejected")
