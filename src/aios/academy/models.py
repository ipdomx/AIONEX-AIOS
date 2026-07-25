from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class Course:
    course_id: str
    title: str
    competencies: tuple[str, ...]
    passing_score: float = 80.0

@dataclass(frozen=True)
class Certification:
    employee_id: str
    course_id: str
    score: float
    passed: bool
