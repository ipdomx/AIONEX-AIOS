from __future__ import annotations
from .models import DeliveryVerdict

class DefinitionOfDoneEngine:
    DEFAULT=('tests_passed','security_reviewed','documentation_complete','rollback_tested','acceptance_proven')
    def evaluate(self, evidence: dict, required: tuple[str,...]|None=None) -> DeliveryVerdict:
        req=required or self.DEFAULT
        missing=tuple(k for k in req if not evidence.get(k, False))
        score=round((len(req)-len(missing))/len(req),4) if req else 0.0
        return DeliveryVerdict(not missing, score, missing, 'Ready for delivery.' if not missing else 'Delivery blocked until all required evidence is present.')
