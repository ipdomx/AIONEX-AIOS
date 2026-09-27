"""Owner policy authority cannot be revived by a preloaded ORM identity."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.db.models import User
from app.services import conversation_governance as governance
from tests import test_fr07_governed_conversations as base

case = base.case


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["update", "reset", "directory", "conversations"])
async def test_stale_owner_identity_is_revalidated_at_governance_service_boundary(case, operation):
    policy = await base.policy(case, {"messages_per_day": 3})
    async with case.sessions() as stale:
        held = await stale.get(User, case.owner.id)
        assert held.auth_version == case.owner.auth_version
        async with case.sessions() as other, other.begin():
            owner = await other.get(User, case.owner.id)
            owner.auth_version += 1
        with pytest.raises(HTTPException) as rejected:
            if operation == "update":
                await governance.update_policy(stale, case.owner, scope="global", identifier="default",
                    expected_version=policy["version"], values={"messages_per_day": 1000})
            elif operation == "reset":
                await governance.reset_policy(stale, case.owner, scope="global", identifier="default",
                    expected_version=policy["version"])
            elif operation == "directory":
                await governance.owner_directory(stale, case.owner)
            else:
                await governance.owner_conversations(stale, case.owner)
        assert rejected.value.status_code == 403
        await stale.rollback()
    async with case.sessions() as fresh:
        result = await governance.effective_policy(fresh, case.actor)
        assert result["values"]["messages_per_day"] == 3
