"""FR09 free project starts cannot invent external consent or paid attribution."""
from __future__ import annotations

import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.core.auth import UserRecord
from app.core.config import settings
from app.api.v1.endpoints import project_executions as endpoint


class AtVerifiedProjectLookup(RuntimeError):
    pass


def _actor(*, free=True):
    return UserRecord(
        id="synthetic-fr09-user", email="synthetic-fr09@example.invalid",
        name="Synthetic FR09", role="Free user" if free else "Paid user",
        password_hash="unused", organization_id="synthetic-fr09-org",
        organization_name="Synthetic FR09",
        organization_plan="free" if free else "enterprise",
        permissions=["projects:read", "projects:write"],
    )


def _access(
    *, access_class="free", provider="ollama", offline=True,
    privacy=True, budget=0.0, fallbacks=0, allow=True,
):
    return SimpleNamespace(
        access_class=access_class,
        policy=SimpleNamespace(
            offline_only=offline,
            privacy_mode=privacy,
            allowed_providers=frozenset({provider}),
            allowed_provider_models=frozenset(
                {f"{provider}:gemma3:4b"} if allow else set()
            ),
            max_total_estimated_cost_usd=budget,
            max_fallbacks=fallbacks,
        ),
    )


class AdmissionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        for obj, field, value in (
            (settings, "PROJECT_EXECUTION_ENABLED", True),
            (settings, "PROJECT_EXECUTION_RUNNER_MODE", "phase36c"),
            (settings, "PROJECT_AI_LIVE_RUNTIME_ENABLED", True),
        ):
            p=patch.object(obj,field,value)
            p.start()
            self.addCleanup(p.stop)

    def install(self, selected):
        calls = []
        async def resolved(_session, *, organization_id, user_id):
            calls.append((organization_id, user_id))
            return selected
        async def project_boundary(*args, **kwargs):
            raise AtVerifiedProjectLookup("no database or provider calls")
        for name, implementation in (
            ("resolve_project_ai_access", resolved),
            ("_project", project_boundary),
        ):
            p=patch.object(endpoint,name,implementation)
            p.start()
            self.addCleanup(p.stop)
        return calls

    async def test_free_full_mode_without_external_confirmation(self):
        calls=self.install(_access())
        with self.assertRaises(AtVerifiedProjectLookup):
            await endpoint.start_project_execution(
                "project",endpoint.ProjectExecutionStart(mode="full"),
                actor=_actor(),_admission=None,session=object(),
            )
        self.assertEqual(calls,[("synthetic-fr09-org","synthetic-fr09-user")])

    async def test_free_full_mode_with_confirmation_still_remains_local(self):
        calls=self.install(_access())
        with self.assertRaises(AtVerifiedProjectLookup):
            await endpoint.start_project_execution(
                "project",
                endpoint.ProjectExecutionStart(
                    mode="full", confirm_external_processing=True
                ),
                actor=_actor(),_admission=None,session=object(),
            )
        self.assertEqual(len(calls),1)

    async def test_free_planning_mode_works_without_external_confirmation(self):
        calls=self.install(_access())
        with self.assertRaises(AtVerifiedProjectLookup):
            await endpoint.start_project_execution(
                "project",endpoint.ProjectExecutionStart(mode="planning"),
                actor=_actor(),_admission=None,session=object(),
            )
        self.assertEqual(len(calls),1)

    async def test_free_policy_overrides_cannot_enable_external_or_billable_route(self):
        bad=[
            {"access_class":"paid"}, {"provider":"openai"},
            {"offline":False}, {"privacy":False},
            {"budget":0.01}, {"fallbacks":1}, {"allow":False},
        ]
        for changed in bad:
            with self.subTest(change=changed):
                # Rebuild stubs rather than touching any external DB.
                selected=_access(**changed)
                async def resolver(_session, **_kwargs):
                    return selected
                async def stop(*_a,**_kw):
                    raise AtVerifiedProjectLookup("must not be reached")
                with ExitStack() as stack:
                    stack.enter_context(
                        patch.object(endpoint,"resolve_project_ai_access",resolver)
                    )
                    stack.enter_context(
                        patch.object(endpoint,"_project",stop)
                    )
                    with self.assertRaises(HTTPException) as error:
                        await endpoint.start_project_execution(
                            "project",endpoint.ProjectExecutionStart(mode="full"),
                            actor=_actor(),_admission=None,session=object(),
                        )
                self.assertEqual(error.exception.status_code,503)
                self.assertEqual(
                    error.exception.detail["code"],
                    "FREE_PROJECT_AI_LOCAL_POLICY_REQUIRED",
                )

    async def test_unavailable_free_policy_fails_closed_without_error_leak(self):
        async def denied(*args,**kwargs):
            raise endpoint.ProjectAIAccessPolicyError("sensitive internal details")
        with patch.object(endpoint,"resolve_project_ai_access",denied):
            with self.assertRaises(HTTPException) as error:
                await endpoint.start_project_execution(
                    "project",endpoint.ProjectExecutionStart(mode="full"),
                    actor=_actor(),_admission=None,session=object(),
                )
        self.assertEqual(error.exception.status_code,503)
        self.assertEqual(
            error.exception.detail["code"],"FREE_PROJECT_AI_POLICY_UNAVAILABLE",
        )
        self.assertNotIn("sensitive",str(error.exception.detail))

    async def test_local_unarmed_refuses_before_policy_access(self):
        async def unreachable(*args,**kwargs):
            raise AssertionError("local provider should not be resolved")
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(settings,"PROJECT_EXECUTION_RUNNER_MODE","legacy")
            )
            stack.enter_context(
                patch.object(settings,"PROJECT_AI_LIVE_RUNTIME_ENABLED",False)
            )
            stack.enter_context(
                patch.object(endpoint,"resolve_project_ai_access",unreachable)
            )
            with self.assertRaises(HTTPException) as error:
                await endpoint.start_project_execution(
                    "project",endpoint.ProjectExecutionStart(mode="full"),
                    actor=_actor(),_admission=None,session=object(),
                )
        self.assertEqual(error.exception.status_code,503)
        self.assertEqual(
            error.exception.detail["code"],
            "FREE_PROJECT_AI_REQUIRES_LIVE_LOCAL_RUNTIME",
        )

    async def test_paid_without_explicit_consent_remains_denied(self):
        calls=self.install(_access())
        with self.assertRaises(HTTPException) as error:
            await endpoint.start_project_execution(
                "project",endpoint.ProjectExecutionStart(mode="full"),
                actor=_actor(free=False),_admission=None,session=object(),
            )
        self.assertEqual(error.exception.status_code,422)
        self.assertEqual(calls,[])

    async def test_paid_with_consent_preserves_old_handling(self):
        calls=self.install(_access())
        with self.assertRaises(AtVerifiedProjectLookup):
            await endpoint.start_project_execution(
                "project",
                endpoint.ProjectExecutionStart(
                    mode="full",confirm_external_processing=True
                ),
                actor=_actor(free=False),_admission=None,session=object(),
            )
        self.assertEqual(calls,[])

    async def test_free_3d_is_not_mislabeled_offline_or_without_consent(self):
        calls=self.install(_access())
        with self.assertRaises(HTTPException) as error:
            await endpoint.start_project_execution(
                "project",endpoint.ProjectExecutionStart(mode="3d_full"),
                actor=_actor(),_admission=None,session=object(),
            )
        self.assertEqual(error.exception.status_code,422)
        self.assertEqual(calls,[])

    async def test_provider_neutral_needs_no_free_provider_or_consent(self):
        calls=self.install(_access())
        with self.assertRaises(AtVerifiedProjectLookup):
            await endpoint.start_project_execution(
                "project",
                endpoint.ProjectExecutionStart(mode="provider_neutral"),
                actor=_actor(),_admission=None,session=object(),
            )
        self.assertEqual(calls,[])


class RecordingTests(unittest.TestCase):
    def test_free_governed_origin_stays_zero_cost_and_no_external_consent(self):
        self.assertEqual(
            endpoint._execution_origin_metadata(
                provider_neutral=False,local_free=True
            ),
            ("ollama",False,0.0),
        )

    def test_provider_neutral_metadata_remains_no_model_zero_cost(self):
        self.assertEqual(
            endpoint._execution_origin_metadata(
                provider_neutral=True,local_free=False
            ),
            ("provider-neutral",False,0.0),
        )

    def test_paid_preserves_explicit_external_processing_record(self):
        with patch.object(settings,"PROJECT_EXECUTION_BUDGET_CAP_USD",0.05):
            self.assertEqual(
                endpoint._execution_origin_metadata(
                    provider_neutral=False,local_free=False
                ),
                ("openai",True,0.05),
            )


if __name__ == "__main__":
    unittest.main()
