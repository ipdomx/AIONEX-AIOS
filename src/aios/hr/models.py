from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum

class EmploymentState(str, Enum):
    ACTIVE='active'
    SUPERVISED='supervised'
    SUSPENDED='suspended'
    RETRAINING='retraining'
    RETIRED='retired'

@dataclass
class EmployeeRecord:
    employee_id: str
    role: str
    ministry_id: str
    grade: int = 1
    state: EmploymentState = EmploymentState.ACTIVE
    skills: set[str] = field(default_factory=set)
    certifications: set[str] = field(default_factory=set)
    success_count: int = 0
    failure_count: int = 0
    warnings: list[str] = field(default_factory=list)
