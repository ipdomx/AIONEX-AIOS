from __future__ import annotations
from dataclasses import dataclass

@dataclass(slots=True,frozen=True)
class InteractionEnvelope:
    modality:str; language:str; dialect:str|None; content:str; transcript_confidence:float=1.0

class InteractionNormalizer:
    def normalize(self, content:str, *, modality='text', language='ar', dialect=None, transcript_confidence=1.0):
        if modality not in {'text','voice'}: raise ValueError('unsupported modality')
        if not content.strip(): raise ValueError('empty interaction')
        return InteractionEnvelope(modality,language,dialect,content.strip(),transcript_confidence)
