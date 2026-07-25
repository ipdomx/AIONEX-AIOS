from __future__ import annotations
from dataclasses import dataclass

@dataclass(slots=True,frozen=True)
class Persona:
    persona_id:str; title:str; level:str; capabilities:tuple[str,...]; paid:bool

class PersonaRegistry:
    def __init__(self):
        self._items={p.persona_id:p for p in (
            Persona('project-staff','Project Staff','staff',('status','basic_guidance'),False),
            Persona('specialist','Specialist','specialist',('implementation','analysis'),True),
            Persona('senior-engineer','Senior Engineer','engineer',('design','review','debugging'),True),
            Persona('manager','Department Manager','manager',('planning','prioritization','approval'),True),
            Persona('chief-engineer','Chief Project Engineer','chief',('final_review','architecture','risk'),True),)}
    def get(self,pid): return self._items[pid]
    def all(self): return tuple(self._items.values())
