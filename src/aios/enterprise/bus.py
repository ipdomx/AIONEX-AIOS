from __future__ import annotations
from collections import defaultdict
from typing import Callable
from .contracts import ContractRegistry
from .models import Event

class ServiceBus:
    def __init__(self, contracts: ContractRegistry):
        self.contracts=contracts; self._handlers=defaultdict(list); self._seen=set(); self.history=[]
    def subscribe(self,event_name:str,consumer:str,handler:Callable[[Event],None])->None:
        self._handlers[event_name].append((consumer,handler))
    def publish(self,event:Event)->int:
        self.contracts.validate(event)
        dedupe=(event.tenant_id,event.correlation_id,event.name)
        if dedupe in self._seen: return 0
        self._seen.add(dedupe); delivered=0
        contract=self.contracts.get(event.name,event.contract_version)
        for consumer,handler in self._handlers[event.name]:
            if consumer not in contract.consumers: continue
            handler(event); delivered+=1
        self.history.append(event)
        return delivered
