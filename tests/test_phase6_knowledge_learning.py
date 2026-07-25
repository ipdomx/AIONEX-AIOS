from pathlib import Path

from aios.knowledge_learning import (
    DecisionOption, KnowledgeLearningPlatform, MemoryScope, Outcome,
    Provenance, ResearchClaim,
)


def test_memory_deduplicates_and_versions(tmp_path: Path):
    platform = KnowledgeLearningPlatform(tmp_path)
    first = platform.learn_fact(MemoryScope.PROJECT, "p", "architecture", "database", {"engine": "postgres"},
                                confidence=0.9, sources=("ADR-1",), verified=True)
    duplicate = platform.learn_fact(MemoryScope.PROJECT, "p", "architecture", "database", {"engine": "postgres"},
                                    confidence=0.9, sources=("ADR-1",), verified=True)
    updated = platform.learn_fact(MemoryScope.PROJECT, "p", "architecture", "database", {"engine": "cockroach"},
                                  confidence=0.82, sources=("ADR-2",), verified=True)
    assert duplicate.item_id == first.item_id
    assert updated.supersedes == first.item_id
    latest = platform.memory.recall(MemoryScope.PROJECT, "p", subject="database")
    assert [item.item_id for item in latest] == [updated.item_id]
    assert platform.memory.verify(MemoryScope.PROJECT, "p")


def test_graph_tracks_lineage(tmp_path: Path):
    platform = KnowledgeLearningPlatform(tmp_path)
    a = platform.graph.upsert_node("project:p", "project", name="p")
    b = platform.graph.upsert_node("decision:d", "decision", title="Use queue")
    c = platform.graph.upsert_node("evidence:e", "evidence", source="benchmark")
    platform.graph.relate(a.node_id, "has_decision", b.node_id)
    platform.graph.relate(b.node_id, "supported_by", c.node_id)
    assert platform.graph.lineage(a.node_id) == ["decision:d", "evidence:e"]
    assert platform.graph.verify()


def test_failure_guard_prevents_unchanged_retry(tmp_path: Path):
    platform = KnowledgeLearningPlatform(tmp_path)
    context = {"runtime": "python", "version": "3.13"}
    platform.record_outcome("deploy", context, Outcome.FAILURE, ("exit=1",),
                            error_fingerprint="ERR-1", lesson="Dependency is incompatible")
    assert platform.experience.guard("deploy", context) == ("Dependency is incompatible",)
    assert platform.experience.guard("deploy", {"runtime": "python", "version": "3.14"}) == ()


def test_strategy_reputation_is_evidence_based(tmp_path: Path):
    platform = KnowledgeLearningPlatform(tmp_path)
    for outcome in (Outcome.SUCCESS, Outcome.SUCCESS, Outcome.FAILURE):
        platform.record_outcome("repair", {"case": str(outcome)}, outcome, ("test",), strategy="A")
    platform.record_outcome("repair", {"case": "b"}, Outcome.SUCCESS, ("test",), strategy="B")
    reputation = platform.experience.strategy_reputation("repair")
    assert reputation["A"] == 2 / 3
    assert reputation["B"] == 1.0


def test_research_requires_diverse_corroboration(tmp_path: Path):
    platform = KnowledgeLearningPlatform(tmp_path)
    one = platform.verify_claim("claim", (ResearchClaim("claim", "source-a", 0.95, corroboration=3),))
    assert not one.accepted
    verified = platform.verify_claim("claim", (
        ResearchClaim("claim", "source-a", 0.95, corroboration=3),
        ResearchClaim("claim", "source-b", 0.9, corroboration=2),
    ))
    assert verified.accepted
    assert verified.confidence >= 0.72


def test_high_quality_conflict_blocks_claim(tmp_path: Path):
    platform = KnowledgeLearningPlatform(tmp_path)
    result = platform.verify_claim("claim", (
        ResearchClaim("claim", "source-a", 0.95, corroboration=3),
        ResearchClaim("claim", "source-b", 0.9, corroboration=3),
    ), (ResearchClaim("not claim", "source-c", 0.95),))
    assert not result.accepted
    assert result.conflicts == ("source-c",)


def test_wisdom_selects_durable_option_and_abstains_without_evidence(tmp_path: Path):
    platform = KnowledgeLearningPlatform(tmp_path)
    durable = DecisionOption("durable", "Durable", 0.92, 0.9, 0.9, 0.9, 0.85, 0.95, 0.75, 0.15)
    quick = DecisionOption("quick", "Quick", 0.8, 0.7, 0.65, 0.4, 0.3, 0.35, 0.95, 0.45)
    result = platform.decide((quick, durable))
    assert not result.abstained
    assert result.selected_option == "durable"
    weak = DecisionOption("weak", "Weak", 0.3, 0.8, 0.8, 0.8, 0.8, 0.9, 0.8, 0.1)
    abstained = platform.decide((weak,))
    assert abstained.abstained
    assert "stronger evidence" in abstained.conditions[0].lower()
