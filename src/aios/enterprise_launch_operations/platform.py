from __future__ import annotations

from dataclasses import dataclass

from .adoption import AdoptionTracker
from .launch import EnterpriseLaunchManager
from .rollout import RolloutCoordinator
from .support import SupportQueue


@dataclass
class EnterpriseLaunchOperationsPlatform:
    launches: EnterpriseLaunchManager
    rollout: RolloutCoordinator
    adoption: AdoptionTracker
    support: SupportQueue

    @classmethod
    def build_default(cls) -> "EnterpriseLaunchOperationsPlatform":
        return cls(
            launches=EnterpriseLaunchManager(),
            rollout=RolloutCoordinator(),
            adoption=AdoptionTracker(),
            support=SupportQueue(),
        )

    def validate(self) -> dict[str, bool]:
        checks = {
            "launch_manager": self.launches is not None,
            "rollout_coordinator": self.rollout is not None,
            "adoption_tracker": self.adoption is not None,
            "support_queue": self.support is not None,
        }
        checks["ready"] = all(checks.values())
        return checks
