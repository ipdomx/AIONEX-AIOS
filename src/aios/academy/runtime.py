from __future__ import annotations
from .models import Certification, Course

class Academy:
    def __init__(self) -> None:
        self._courses: dict[str, Course] = {}
        self._certifications: list[Certification] = []

    def register_course(self, course: Course) -> None:
        self._courses[course.course_id] = course

    def assess(self, employee_id: str, course_id: str, score: float) -> Certification:
        if not 0 <= score <= 100:
            raise ValueError('score must be between 0 and 100')
        course = self._courses[course_id]
        result = Certification(employee_id, course_id, score, score >= course.passing_score)
        self._certifications.append(result)
        return result

    def certifications_for(self, employee_id: str) -> tuple[Certification, ...]:
        return tuple(item for item in self._certifications if item.employee_id == employee_id)
