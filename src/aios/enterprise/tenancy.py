from __future__ import annotations

class TenantContext:
    def __init__(self): self._members: dict[str,set[str]]={}
    def add_member(self,tenant_id:str,subject_id:str)->None: self._members.setdefault(tenant_id,set()).add(subject_id)
    def require(self,tenant_id:str,subject_id:str)->None:
        if subject_id not in self._members.get(tenant_id,set()): raise PermissionError('tenant isolation violation')
    def scoped_key(self,tenant_id:str,key:str)->str: return f'{tenant_id}:{key}'
