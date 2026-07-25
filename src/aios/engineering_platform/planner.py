from __future__ import annotations

from collections import defaultdict, deque

from .models import EngineeringRequirement, EngineeringTask, ProjectBlueprint, ProjectSize


class ProjectPlanner:
    """Creates deterministic engineering plans with dependency validation."""

    def build_blueprint(
        self,
        project: str,
        objective: str,
        requirements: tuple[EngineeringRequirement, ...],
        *,
        size: ProjectSize = ProjectSize.MEDIUM,
        languages: tuple[str, ...] = (),
        services: tuple[str, ...] = (),
    ) -> ProjectBlueprint:
        if not project.strip() or not objective.strip():
            raise ValueError("project and objective are required")
        if not requirements:
            raise ValueError("at least one requirement is required")

        tasks: list[EngineeringTask] = []
        previous: str | None = None
        for requirement in sorted(requirements, key=lambda item: (-item.priority, item.title)):
            department = self._department_for(requirement.tags)
            task = EngineeringTask(
                title=requirement.title,
                department=department,
                required_skills=self._skills_for(requirement.tags, languages),
                depends_on=(previous,) if previous else (),
                acceptance_criteria=requirement.acceptance_criteria,
            )
            tasks.append(task)
            previous = task.id

        risks = self._derive_risks(size, requirements, services)
        blueprint = ProjectBlueprint(
            project=project,
            objective=objective,
            size=size,
            requirements=requirements,
            tasks=tuple(tasks),
            languages=tuple(dict.fromkeys(languages)),
            services=tuple(dict.fromkeys(services)),
            risks=risks,
        )
        self.execution_order(blueprint)
        return blueprint

    def execution_order(self, blueprint: ProjectBlueprint) -> tuple[str, ...]:
        ids = {task.id for task in blueprint.tasks}
        graph: dict[str, list[str]] = defaultdict(list)
        indegree = {task.id: 0 for task in blueprint.tasks}
        for task in blueprint.tasks:
            for dependency in task.depends_on:
                if dependency not in ids:
                    raise ValueError(f"unknown dependency: {dependency}")
                graph[dependency].append(task.id)
                indegree[task.id] += 1
        queue = deque(sorted(task_id for task_id, degree in indegree.items() if degree == 0))
        ordered: list[str] = []
        while queue:
            current = queue.popleft()
            ordered.append(current)
            for child in sorted(graph[current]):
                indegree[child] -= 1
                if indegree[child] == 0:
                    queue.append(child)
        if len(ordered) != len(blueprint.tasks):
            raise ValueError("cyclic task dependency detected")
        return tuple(ordered)

    @staticmethod
    def _department_for(tags: tuple[str, ...]) -> str:
        lowered = {tag.lower() for tag in tags}
        if lowered & {"security", "auth", "secrets"}:
            return "security"
        if lowered & {"frontend", "ui", "ux", "three.js", "webgl"}:
            return "frontend"
        if lowered & {"database", "sql", "data"}:
            return "data"
        if lowered & {"devops", "docker", "kubernetes", "cloud"}:
            return "infrastructure"
        if lowered & {"testing", "quality", "qa"}:
            return "quality"
        return "engineering"

    @staticmethod
    def _skills_for(tags: tuple[str, ...], languages: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*languages, *tags))) or ("software-engineering",)

    @staticmethod
    def _derive_risks(size: ProjectSize, requirements, services) -> tuple[str, ...]:
        risks: list[str] = []
        if size in {ProjectSize.LARGE, ProjectSize.CRITICAL}:
            risks.append("coordination-complexity")
        if any("security" in {tag.lower() for tag in req.tags} for req in requirements):
            risks.append("security-sensitive")
        if len(services) > 5:
            risks.append("integration-complexity")
        return tuple(risks)
