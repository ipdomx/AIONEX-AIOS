from __future__ import annotations
from dataclasses import dataclass

@dataclass(slots=True,frozen=True)
class ProgrammingLanguageProfile:
    name:str; extensions:tuple[str,...]; domains:tuple[str,...]; toolchains:tuple[str,...]=()

class ProgrammingLanguageRegistry:
    def __init__(self): self._items={p.name.lower():p for p in defaults()}
    def register(self,p): self._items[p.name.lower()]=p
    def get(self,name): return self._items[name.lower()]
    def all(self): return tuple(self._items.values())

def defaults():
    return (
      ProgrammingLanguageProfile('Python',('.py',),('ai','backend','automation'),('pytest','ruff')),
      ProgrammingLanguageProfile('TypeScript',('.ts','.tsx'),('frontend','backend','three.js'),('tsc','vitest')),
      ProgrammingLanguageProfile('JavaScript',('.js','.jsx'),('frontend','three.js','node'),('eslint','vitest')),
      ProgrammingLanguageProfile('Rust',('.rs',),('systems','security','performance'),('cargo','clippy')),
      ProgrammingLanguageProfile('C++',('.cpp','.hpp','.cc'),('systems','graphics','engines'),('cmake','clang')),
      ProgrammingLanguageProfile('Go',('.go',),('cloud','backend','distributed-systems'),('go test','go vet')),
      ProgrammingLanguageProfile('Java',('.java',),('enterprise','android','backend'),('maven','gradle')),
      ProgrammingLanguageProfile('Kotlin',('.kt',),('android','backend'),('gradle',)),
      ProgrammingLanguageProfile('Swift',('.swift',),('ios','macos'),('xcodebuild',)),
      ProgrammingLanguageProfile('Dart',('.dart',),('flutter','mobile'),('flutter test',)),
      ProgrammingLanguageProfile('C#',('.cs',),('enterprise','games','unity'),('dotnet test',)),
      ProgrammingLanguageProfile('PHP',('.php',),('web','backend'),('phpunit',)),
      ProgrammingLanguageProfile('SQL',('.sql',),('data','databases'),()),
    )
