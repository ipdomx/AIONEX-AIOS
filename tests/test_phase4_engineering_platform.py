from pathlib import Path

from aios.engineering_platform import (
    DefinitionOfDoneEngine, EngineeringPlatform, EngineeringRequirement,
    ProjectAuditor, ProjectPlanner, ProjectSize,
)


def test_default_language_registry_is_multilingual():
    platform = EngineeringPlatform()
    for language in ("Python", "TypeScript", "Rust", "Go", "Java", "Kotlin", "Swift", "Dart", "C++"):
        assert platform.languages.supports(language)


def test_blueprint_has_valid_dependency_order():
    planner = ProjectPlanner()
    reqs = (
        EngineeringRequirement("Secure API", "Build API", ("tests_pass",), 90, ("security", "python")),
        EngineeringRequirement("Three scene", "Build scene", ("renders",), 70, ("three.js", "frontend")),
    )
    blueprint = planner.build_blueprint("p1", "complex platform", reqs, size=ProjectSize.LARGE,
                                        languages=("Python", "TypeScript"), services=("OpenAI", "GitHub"))
    assert len(planner.execution_order(blueprint)) == 2
    assert "coordination-complexity" in blueprint.risks
    assert {task.department for task in blueprint.tasks} == {"security", "frontend"}


def test_auditor_detects_secret_and_missing_tests(tmp_path: Path):
    (tmp_path / "app.py").write_text('API_KEY="abcdef123456"\n# TODO fix\n', encoding="utf-8")
    findings = ProjectAuditor().audit(tmp_path)
    titles = {finding.title for finding in findings}
    assert "Possible embedded secret" in titles
    assert "No automated tests detected" in titles
    assert "Missing README" in titles


def test_delivery_requires_every_gate():
    engine = DefinitionOfDoneEngine()
    evidence = {key: True for values in engine.DEFAULT_GATES.values() for key in values}
    evidence["security_reviewed"] = False
    rejected = engine.evaluate(evidence)
    assert not rejected.approved
    assert "security:security_reviewed" in rejected.blockers
    evidence["security_reviewed"] = True
    approved = engine.evaluate(evidence)
    assert approved.approved
    assert approved.readiness_score == 100.0
