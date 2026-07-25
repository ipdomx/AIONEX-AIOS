from __future__ import annotations

from dataclasses import dataclass
from .paths import ensure_layout


@dataclass(slots=True)
class UpdatePlan:
    component: str
    current_version: str
    target_version: str
    risk: str
    status: str


class SelfUpdatePlanner:
    def plan(self, component: str, current_version: str, target_version: str, risk: str = 'medium') -> UpdatePlan:
        plan = UpdatePlan(component, current_version, target_version, risk, 'planned')
        path = ensure_layout()['updates'] / f'{component}-{target_version}.plan'
        path.write_text(
            '1. Backup\n2. Isolated update\n3. Tests\n4. Approval\n5. Deploy\n6. Monitor\n7. Rollback if needed\n',
            encoding='utf-8',
        )
        return plan
