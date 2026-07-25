from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from ..db import Database


@dataclass(slots=True, frozen=True)
class GraphNode:
    key: str
    kind: str
    label: str
    attributes: dict[str, Any]


class KnowledgeGraph:
    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def key(kind: str, identity: str) -> str:
        return sha256(f'{kind}:{identity}'.encode()).hexdigest()

    def upsert_node(self, kind: str, identity: str, label: str, attributes: dict | None = None) -> str:
        key = self.key(kind, identity)
        payload = json.dumps(attributes or {}, ensure_ascii=False, sort_keys=True)
        with self.db.connect() as conn:
            conn.execute(
                '''INSERT INTO knowledge_nodes(node_key, kind, label, attributes)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(node_key) DO UPDATE SET label=excluded.label,
                   attributes=excluded.attributes, updated_at=CURRENT_TIMESTAMP''',
                (key, kind, label, payload),
            )
        return key

    def relate(self, source_key: str, relation: str, target_key: str, evidence: str = '') -> None:
        with self.db.connect() as conn:
            conn.execute(
                '''INSERT INTO knowledge_edges(source_key, relation, target_key, evidence)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(source_key, relation, target_key) DO UPDATE SET
                   evidence=excluded.evidence, updated_at=CURRENT_TIMESTAMP''',
                (source_key, relation, target_key, evidence),
            )

    def neighbors(self, node_key: str, relation: str | None = None) -> list[dict]:
        query = '''SELECT e.relation, e.evidence, n.node_key, n.kind, n.label, n.attributes
                   FROM knowledge_edges e JOIN knowledge_nodes n ON n.node_key=e.target_key
                   WHERE e.source_key=?'''
        args: list[Any] = [node_key]
        if relation:
            query += ' AND e.relation=?'
            args.append(relation)
        with self.db.connect() as conn:
            rows = conn.execute(query, args).fetchall()
        return [
            {'relation': row['relation'], 'evidence': row['evidence'], 'key': row['node_key'],
             'kind': row['kind'], 'label': row['label'], 'attributes': json.loads(row['attributes'])}
            for row in rows
        ]

    def impact(self, node_key: str, depth: int = 3) -> list[dict]:
        seen = {node_key}
        frontier = [(node_key, 0)]
        result: list[dict] = []
        while frontier:
            current, level = frontier.pop(0)
            if level >= depth:
                continue
            for item in self.neighbors(current):
                if item['key'] in seen:
                    continue
                seen.add(item['key'])
                item['depth'] = level + 1
                result.append(item)
                frontier.append((item['key'], level + 1))
        return result
