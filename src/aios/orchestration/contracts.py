from __future__ import annotations
from .models import WorkContract

class ContractRegistry:
    def __init__(self) -> None: self._items: dict[str, WorkContract] = {}
    def register(self, contract: WorkContract) -> None:
        if contract.contract_id in self._items: raise ValueError(f'duplicate contract: {contract.contract_id}')
        self._items[contract.contract_id] = contract
    def get(self, contract_id: str) -> WorkContract: return self._items[contract_id]
    def validate(self, contract_id: str, payload: dict) -> tuple[bool, tuple[str, ...]]:
        c=self.get(contract_id); missing=tuple(x for x in c.outputs if x not in payload)
        return (not missing, missing)
    def all(self) -> tuple[WorkContract, ...]: return tuple(self._items.values())
