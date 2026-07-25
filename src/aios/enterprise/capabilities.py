from __future__ import annotations
from .models import Capability

class CapabilityRegistry:
    def __init__(self): self._items: dict[str,Capability]={}
    def register(self,c:Capability)->None: self._items[c.capability_id]=c
    def select(self,skills:tuple[str,...],language:str|None=None)->tuple[Capability,...]:
        need=set(x.lower() for x in skills)
        out=[]
        for c in self._items.values():
            if not c.available: continue
            have=set(x.lower() for x in c.skills)
            if not need.issubset(have): continue
            if language and language.lower() not in {x.lower() for x in c.languages}: continue
            out.append(c)
        return tuple(sorted(out,key=lambda x:x.trust_score,reverse=True))
