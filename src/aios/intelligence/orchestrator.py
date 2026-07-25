from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Any


@dataclass(slots=True, frozen=True)
class TaskSpec:
    task_id: str
    topic: str
    function: Callable[[], Any]


@dataclass(slots=True, frozen=True)
class TaskResult:
    task_id: str
    topic: str
    success: bool
    value: Any = None
    error: str | None = None


class ConcurrentTaskOrchestrator:
    """Runs isolated independent tasks concurrently and returns deterministic ordering."""

    def __init__(self, max_workers: int = 4) -> None:
        self.max_workers = max(1, max_workers)

    def run(self, tasks: list[TaskSpec]) -> tuple[TaskResult, ...]:
        if len({item.task_id for item in tasks}) != len(tasks):
            raise ValueError('task_id values must be unique')
        results: dict[str, TaskResult] = {}
        with ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix='aios-cell') as pool:
            mapping = {pool.submit(item.function): item for item in tasks}
            for future in as_completed(mapping):
                item = mapping[future]
                try:
                    results[item.task_id] = TaskResult(item.task_id, item.topic, True, future.result())
                except Exception as exc:
                    results[item.task_id] = TaskResult(item.task_id, item.topic, False, error=str(exc))
        return tuple(results[item.task_id] for item in tasks)
