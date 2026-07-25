from __future__ import annotations

from collections import defaultdict

from .models import CompetencyProfile, DigitalWorker, RoleLevel


class WorkforceRegistry:
    def __init__(self, workers: tuple[DigitalWorker, ...] | None = None) -> None:
        self._workers: dict[str, DigitalWorker] = {}
        for worker in workers or default_workforce():
            self.register(worker)

    def register(self, worker: DigitalWorker) -> None:
        if worker.worker_id in self._workers:
            raise ValueError(f'duplicate worker: {worker.worker_id}')
        self._workers[worker.worker_id] = worker

    def all(self) -> tuple[DigitalWorker, ...]:
        return tuple(self._workers.values())

    def department(self, name: str) -> tuple[DigitalWorker, ...]:
        return tuple(w for w in self._workers.values() if w.department == name)

    def best_match(self, department: str, required_domains: tuple[str, ...], role: RoleLevel) -> DigitalWorker:
        candidates = [w for w in self.department(department) if w.role == role]
        if not candidates:
            raise LookupError(f'no {role.value} registered for {department}')
        required = set(required_domains)
        return max(
            candidates,
            key=lambda w: (len(required.intersection(w.competency.domains)), w.competency.aggregate),
        )

    def organization_chart(self) -> dict[str, list[dict]]:
        chart: dict[str, list[dict]] = defaultdict(list)
        for worker in self._workers.values():
            chart[worker.department].append({
                'id': worker.worker_id,
                'name': worker.name,
                'role': worker.role.value,
                'competency': worker.competency.aggregate,
            })
        return dict(chart)


def _team(department: str, domains: tuple[str, ...], *, languages=(), frameworks=()) -> tuple[DigitalWorker, ...]:
    slug = department.lower().replace(' ', '-')
    profile = CompetencyProfile(domains, tuple(languages), tuple(frameworks), .86, .9, .86, .9)
    return (
        DigitalWorker(f'{slug}-specialist', f'{department} Specialist', RoleLevel.SPECIALIST, department, profile, ('implement', 'experiment')),
        DigitalWorker(f'{slug}-engineer', f'Senior {department} Engineer', RoleLevel.ENGINEER, department, profile, ('design', 'review', 'test')),
        DigitalWorker(f'{slug}-manager', f'{department} Manager', RoleLevel.MANAGER, department, profile, ('assign', 'approve_department', 'request_rework')),
    )


def default_workforce() -> tuple[DigitalWorker, ...]:
    workers: list[DigitalWorker] = []
    workers += _team('Architecture', ('architecture', 'distributed-systems', 'scalability'))
    workers += _team('Backend', ('backend', 'api', 'databases'), languages=('Python', 'Rust', 'Go', 'C++'))
    workers += _team('Frontend', ('frontend', 'ui', '3d-web'), languages=('TypeScript', 'JavaScript'), frameworks=('Three.js', 'WebGL', 'React'))
    workers += _team('Security', ('security', 'threat-modeling', 'incident-response'))
    workers += _team('Quality', ('testing', 'verification', 'reliability'))
    workers += _team('DevOps', ('infrastructure', 'containers', 'deployment'))
    workers += _team('Data', ('data', 'databases', 'analytics'))
    workers += _team('Research', ('research', 'evidence', 'experimentation'))
    chief = DigitalWorker(
        'chief-project-engineer', 'Chief Project Engineer', RoleLevel.CHIEF_ENGINEER,
        'Executive Engineering',
        CompetencyProfile(('architecture', 'security', 'quality', 'delivery', 'risk'), ('Python', 'Rust', 'C++', 'TypeScript'), (), .94, .96, .94, .96),
        ('final_review', 'reject_release', 'approve_release', 'request_rework'),
    )
    return tuple(workers) + (chief,)
