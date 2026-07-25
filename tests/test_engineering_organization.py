from aios.organization import EngineeringOrganization, WorkStatus
from aios.kernel import AIOSKernel


def passing_evidence(item):
    return {
        'passed_criteria': list(item.acceptance_criteria),
        'tests_passed': True,
        'security_reviewed': True,
    }


def test_every_department_has_specialist_engineer_manager():
    org = EngineeringOrganization()
    blueprint = org.plan('hard-project', 'Build a complex distributed 3D platform')
    chart = org.workforce.organization_chart()
    for department in blueprint.departments:
        roles = {row['role'] for row in chart[department]}
        assert {'specialist', 'engineer', 'manager'} <= roles


def test_chief_engineer_rejects_incomplete_project():
    org = EngineeringOrganization()
    blueprint = org.plan('incomplete', 'Build platform')
    review = org.chief_review(blueprint)
    assert review.approved is False
    assert review.rework_plan
    assert all(item.status == WorkStatus.REWORK for item in blueprint.deliverables)


def test_chief_engineer_approves_only_fully_proven_project():
    org = EngineeringOrganization()
    blueprint = org.plan('complete', 'Build platform')
    for item in blueprint.deliverables:
        item.evidence.update(passing_evidence(item))
    review = org.chief_review(blueprint)
    assert review.approved is True
    assert review.readiness_score == 1.0
    assert not review.blocking_findings


def test_kernel_persists_engineering_review(tmp_path, monkeypatch):
    monkeypatch.setenv('AIOS_HOME', str(tmp_path / 'home'))
    kernel = AIOSKernel()
    blueprint = kernel.engineering.plan('p', 'objective', departments=('Architecture',))
    evidence = {'Architecture': passing_evidence(blueprint.deliverables[0])}
    result = kernel.engineer_project('p', 'objective', departments=('Architecture',), evidence=evidence)
    assert result['approved'] is True
    with kernel.db.connect() as conn:
        row = conn.execute('SELECT approved FROM engineering_reviews WHERE project=?', ('p',)).fetchone()
    assert row['approved'] == 1
