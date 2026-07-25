from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from .storage import HashChainedJsonl


@dataclass(frozen=True)
class GraphNode:
    node_id: str
    node_type: str
    attributes: dict[str, Any]


@dataclass(frozen=True)
class GraphEdge:
    source: str
    relation: str
    target: str
    attributes: dict[str, Any]


class EnterpriseKnowledgeGraph:
    def __init__(self, root: str | Path) -> None:
        root = Path(root)
        self.nodes = HashChainedJsonl(root / "nodes.jsonl")
        self.edges = HashChainedJsonl(root / "edges.jsonl")

    def upsert_node(self, node_id: str, node_type: str, **attributes: Any) -> GraphNode:
        node = GraphNode(node_id, node_type, attributes)
        self.nodes.append(asdict(node))
        return node

    def relate(self, source: str, relation: str, target: str, **attributes: Any) -> GraphEdge:
        known = {item["node_id"] for item in self.nodes.payloads()}
        if source not in known or target not in known:
            raise KeyError("both nodes must exist before creating a relationship")
        edge = GraphEdge(source, relation, target, attributes)
        self.edges.append(asdict(edge))
        return edge

    def neighbors(self, node_id: str, relation: str | None = None) -> list[GraphEdge]:
        results = []
        for payload in self.edges.payloads():
            if payload["source"] != node_id and payload["target"] != node_id:
                continue
            if relation and payload["relation"] != relation:
                continue
            results.append(GraphEdge(**payload))
        return results

    def lineage(self, node_id: str, max_depth: int = 8) -> list[str]:
        visited: set[str] = set()
        queue = [(node_id, 0)]
        while queue:
            current, depth = queue.pop(0)
            if current in visited or depth > max_depth:
                continue
            visited.add(current)
            for edge in self.neighbors(current):
                other = edge.target if edge.source == current else edge.source
                queue.append((other, depth + 1))
        visited.discard(node_id)
        return sorted(visited)

    def verify(self) -> bool:
        return self.nodes.verify() and self.edges.verify()
