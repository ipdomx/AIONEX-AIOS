from __future__ import annotations
from dataclasses import dataclass

@dataclass(slots=True,frozen=True)
class LocaleProfile:
    language:str; locale:str; dialects:tuple[str,...]=(); direction:str='ltr'

class HumanLanguageRegistry:
    def __init__(self):
        self._items={x.locale:x for x in (
            LocaleProfile('Arabic','ar',('Egyptian','Saidi Egyptian','Gulf','Levantine'),'rtl'),
            LocaleProfile('English','en',('US','UK')), LocaleProfile('French','fr'), LocaleProfile('German','de'),
            LocaleProfile('Spanish','es'), LocaleProfile('Italian','it'), LocaleProfile('Turkish','tr'),
            LocaleProfile('Hindi','hi'), LocaleProfile('Chinese','zh'), LocaleProfile('Japanese','ja'))}
    def resolve(self,locale): return self._items.get(locale,self._items['en'])
