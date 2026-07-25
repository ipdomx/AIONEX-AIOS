from __future__ import annotations
from .models import Contract, Event

class ContractRegistry:
    def __init__(self): self._contracts: dict[tuple[str,str],Contract]={}
    def register(self, contract: Contract) -> None:
        key=(contract.name,contract.version)
        if key in self._contracts and self._contracts[key] != contract:
            raise ValueError('contract version is immutable')
        self._contracts[key]=contract
    def get(self,name:str,version:str='1.0')->Contract: return self._contracts[(name,version)]
    def validate(self,event:Event)->None:
        c=self.get(event.name,event.contract_version)
        if event.source != c.producer: raise PermissionError('event producer not allowed')
        missing=[x for x in c.required_fields if x not in event.payload]
        if missing: raise ValueError(f'missing required fields: {missing}')
