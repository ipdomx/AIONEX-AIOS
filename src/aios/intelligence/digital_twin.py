from __future__ import annotations

import ast
import json
from dataclasses import dataclass, asdict
from hashlib import sha256
from pathlib import Path
from typing import Iterable

from .knowledge_graph import KnowledgeGraph


@dataclass(slots=True, frozen=True)
class FileRecord:
    path: str
    size: int
    sha256: str
    language: str
    imports: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class TwinSnapshot:
    project: str
    root: str
    fingerprint: str
    files: tuple[FileRecord, ...]
    languages: dict[str, int]
    dependency_count: int
    warnings: tuple[str, ...]

    def to_dict(self) -> dict:
        data = asdict(self)
        data['files'] = [asdict(item) for item in self.files]
        return data


class ProjectDigitalTwin:
    IGNORE = {'.git', '.hg', '.svn', 'node_modules', '.venv', 'venv', '__pycache__', 'dist', 'build'}
    EXTENSIONS = {
        '.py': 'python', '.js': 'javascript', '.ts': 'typescript', '.tsx': 'typescript',
        '.jsx': 'javascript', '.go': 'go', '.rs': 'rust', '.java': 'java', '.kt': 'kotlin',
        '.swift': 'swift', '.php': 'php', '.rb': 'ruby', '.cs': 'csharp', '.cpp': 'cpp',
        '.c': 'c', '.h': 'c', '.sql': 'sql', '.sh': 'shell', '.yaml': 'yaml', '.yml': 'yaml',
        '.json': 'json', '.toml': 'toml', '.md': 'markdown', '.html': 'html', '.css': 'css',
    }

    def __init__(self, graph: KnowledgeGraph | None = None, max_file_bytes: int = 2_000_000) -> None:
        self.graph = graph
        self.max_file_bytes = max_file_bytes

    def build(self, root: str | Path, project: str | None = None) -> TwinSnapshot:
        root = Path(root).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f'Project root does not exist: {root}')
        name = project or root.name
        records: list[FileRecord] = []
        languages: dict[str, int] = {}
        warnings: list[str] = []
        dependencies: set[str] = set()

        for path in self._files(root):
            rel = path.relative_to(root).as_posix()
            size = path.stat().st_size
            if size > self.max_file_bytes:
                warnings.append(f'Skipped oversized file: {rel}')
                continue
            data = path.read_bytes()
            language = self.EXTENSIONS.get(path.suffix.lower(), 'other')
            imports = self._imports(path, data, language)
            dependencies.update(imports)
            languages[language] = languages.get(language, 0) + 1
            record = FileRecord(rel, size, sha256(data).hexdigest(), language, imports)
            records.append(record)

        digest = sha256(json.dumps([asdict(item) for item in records], sort_keys=True).encode()).hexdigest()
        snapshot = TwinSnapshot(name, str(root), digest, tuple(records), languages, len(dependencies), tuple(warnings))
        if self.graph:
            self._index(snapshot)
        return snapshot

    def _files(self, root: Path) -> Iterable[Path]:
        for path in sorted(root.rglob('*')):
            if not path.is_file() or any(part in self.IGNORE for part in path.parts):
                continue
            yield path

    @staticmethod
    def _imports(path: Path, data: bytes, language: str) -> tuple[str, ...]:
        if language != 'python':
            return ()
        try:
            tree = ast.parse(data.decode('utf-8'))
        except (UnicodeDecodeError, SyntaxError):
            return ()
        found: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module.split('.')[0])
        return tuple(sorted(found))

    def _index(self, snapshot: TwinSnapshot) -> None:
        project_key = self.graph.upsert_node('project', snapshot.project, snapshot.project,
                                             {'root': snapshot.root, 'fingerprint': snapshot.fingerprint})
        by_module: dict[str, str] = {}
        for record in snapshot.files:
            file_key = self.graph.upsert_node('file', f'{snapshot.project}:{record.path}', record.path,
                                               {'size': record.size, 'sha256': record.sha256,
                                                'language': record.language})
            self.graph.relate(project_key, 'contains', file_key, 'digital twin scan')
            by_module[Path(record.path).stem] = file_key
        for record in snapshot.files:
            source = by_module.get(Path(record.path).stem)
            if not source:
                continue
            for dependency in record.imports:
                target = by_module.get(dependency) or self.graph.upsert_node('dependency', dependency, dependency)
                self.graph.relate(source, 'depends_on', target, f'import found in {record.path}')
