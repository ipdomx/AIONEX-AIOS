from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True,slots=True)
class PluginManifest:
    plugin_id:str; version:str; api_version:str; capabilities:tuple[str,...]; signed:bool=False

class PluginRuntime:
    def __init__(self,api_version:str='2.0'): self.api_version=api_version; self._plugins={}
    def install(self,m:PluginManifest,require_signature:bool=True)->None:
        if m.api_version!=self.api_version: raise ValueError('incompatible plugin API')
        if require_signature and not m.signed: raise PermissionError('unsigned plugin')
        self._plugins[m.plugin_id]=m
    def list(self): return tuple(self._plugins.values())
