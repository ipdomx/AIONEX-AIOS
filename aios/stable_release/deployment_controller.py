from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class DeploymentStage(str, Enum):
    STAGING = "staging"
    CANARY = "canary"
    PRODUCTION = "production"
    ROLLED_BACK = "rolled_back"


@dataclass(slots=True)
class StableDeployment:
    deployment_id: str
    release_id: str
    owner_id: str
    stage: DeploymentStage = DeploymentStage.STAGING
    history: list[DeploymentStage] = field(default_factory=lambda: [DeploymentStage.STAGING])
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class StableDeploymentController:
    def __init__(self) -> None:
        self._deployments: dict[str, StableDeployment] = {}

    def create(self, deployment: StableDeployment) -> StableDeployment:
        if deployment.deployment_id in self._deployments:
            raise ValueError(f"duplicate deployment: {deployment.deployment_id}")
        self._deployments[deployment.deployment_id] = deployment
        return deployment

    def promote_to_canary(self, deployment_id: str, owner_id: str) -> StableDeployment:
        deployment = self._require_owner(deployment_id, owner_id)
        if deployment.stage is not DeploymentStage.STAGING:
            raise RuntimeError("deployment must be in staging before canary")
        return self._transition(deployment, DeploymentStage.CANARY)

    def promote_to_production(self, deployment_id: str, owner_id: str) -> StableDeployment:
        deployment = self._require_owner(deployment_id, owner_id)
        if deployment.stage is not DeploymentStage.CANARY:
            raise RuntimeError("deployment must be in canary before production")
        return self._transition(deployment, DeploymentStage.PRODUCTION)

    def rollback(self, deployment_id: str, owner_id: str) -> StableDeployment:
        deployment = self._require_owner(deployment_id, owner_id)
        if deployment.stage is DeploymentStage.ROLLED_BACK:
            return deployment
        return self._transition(deployment, DeploymentStage.ROLLED_BACK)

    def _transition(self, deployment: StableDeployment, stage: DeploymentStage) -> StableDeployment:
        deployment.stage = stage
        deployment.history.append(stage)
        deployment.updated_at = datetime.now(timezone.utc)
        return deployment

    def _require_owner(self, deployment_id: str, owner_id: str) -> StableDeployment:
        deployment = self._deployments[deployment_id]
        if deployment.owner_id != owner_id:
            raise PermissionError("deployment is not owned by this owner")
        return deployment
