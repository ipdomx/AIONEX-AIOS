from __future__ import annotations
from .models import EmployeeRecord, EmploymentState

class CareerSystem:
    def __init__(self) -> None:
        self._records: dict[str, EmployeeRecord] = {}

    def hire(self, record: EmployeeRecord) -> EmployeeRecord:
        if record.employee_id in self._records:
            raise ValueError('employee already exists')
        self._records[record.employee_id] = record
        return record

    def get(self, employee_id: str) -> EmployeeRecord:
        return self._records[employee_id]

    def promote(self, employee_id: str, *, actor_is_owner: bool, minimum_successes: int = 3) -> EmployeeRecord:
        if not actor_is_owner:
            raise PermissionError('owner approval required')
        item = self.get(employee_id)
        if item.success_count < minimum_successes or item.failure_count > item.success_count:
            raise ValueError('promotion evidence is insufficient')
        item.grade += 1
        return item

    def restrict(self, employee_id: str, reason: str, state: EmploymentState = EmploymentState.SUPERVISED) -> EmployeeRecord:
        item = self.get(employee_id)
        item.state = state
        item.warnings.append(reason)
        return item

    def record_result(self, employee_id: str, success: bool) -> None:
        item = self.get(employee_id)
        if success:
            item.success_count += 1
        else:
            item.failure_count += 1

    def list(self) -> tuple[EmployeeRecord, ...]:
        return tuple(self._records.values())
