from __future__ import annotations
from .models import IntegrationVerdict

class IntegrationJudge:
    def evaluate(self, artifacts: dict[str, dict], contracts=()) -> IntegrationVerdict:
        findings=[]; actions=[]
        for name,data in artifacts.items():
            if not data.get('tests_passed'): findings.append(f'{name}: tests missing'); actions.append(f'{name}: pass integration tests')
            if data.get('interface_conflicts'): findings.append(f'{name}: interface conflicts'); actions.append(f'{name}: resolve contract mismatches')
            if data.get('security_regression'): findings.append(f'{name}: security regression'); actions.append(f'{name}: remediate and retest security')
        total=max(1,len(artifacts)*3); score=round(max(0.0,1-len(findings)/total),4)
        return IntegrationVerdict(not findings,score,tuple(findings),tuple(actions))
