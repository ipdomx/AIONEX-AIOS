from __future__ import annotations
from dataclasses import asdict
from .models import OrchestratedTask, TaskState
from .done import DefinitionOfDoneEngine
from .integration import IntegrationJudge

class MasterOrchestrator:
    def __init__(self, engineering, contracts=None):
        self.engineering=engineering; self.done=DefinitionOfDoneEngine(); self.integration=IntegrationJudge(); self.contracts=contracts
    def decompose(self, project: str, objective: str, departments=None) -> tuple[OrchestratedTask,...]:
        blueprint=self.engineering.plan(project, objective, departments=departments)
        tasks=[]
        for d in blueprint.deliverables:
            tasks.append(OrchestratedTask(d.title,d.department,(d.department.lower(),)))
        return tuple(tasks)
    def ready(self, tasks: tuple[OrchestratedTask,...]) -> tuple[OrchestratedTask,...]:
        complete={t.id for t in tasks if t.state==TaskState.COMPLETE}
        for t in tasks:
            if t.state==TaskState.PLANNED and all(dep in complete for dep in t.dependencies): t.state=TaskState.READY
        return tasks
    def delivery_review(self, artifacts: dict[str,dict]) -> dict:
        integration=self.integration.evaluate(artifacts)
        done={k:self.done.evaluate(v) for k,v in artifacts.items()}
        approved=integration.approved and all(x.approved for x in done.values())
        return {'approved':approved,'integration':asdict(integration),'definition_of_done':{k:asdict(v) for k,v in done.items()}}
