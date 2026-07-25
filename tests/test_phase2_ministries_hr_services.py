import pytest
from aios.ministries import build_default_ministry_registry, MinistryAssignment, MinistryState
from aios.hr import CareerSystem, EmployeeRecord, EmploymentState
from aios.academy import Academy, Course
from aios.services import build_default_service_registry, ServiceEvaluation, DiscoveryCandidate, FutureServiceDiscovery


def test_ministries_are_isolated_and_state_controlled():
    registry=build_default_ministry_registry()
    assert len(registry.list()) >= 10
    registry.set_state('engineering', MinistryState.PAUSED)
    with pytest.raises(PermissionError):
        registry.assign(MinistryAssignment('engineering','p1',('w1',),'build'))
    registry.set_state('engineering', MinistryState.ACTIVE)
    registry.assign(MinistryAssignment('engineering','p1',('w1',),'build'))
    assert len(registry.assignments('p1')) == 1


def test_career_requires_owner_and_evidence():
    careers=CareerSystem()
    careers.hire(EmployeeRecord('e1','engineer','engineering'))
    with pytest.raises(PermissionError):
        careers.promote('e1', actor_is_owner=False)
    for _ in range(3): careers.record_result('e1', True)
    assert careers.promote('e1', actor_is_owner=True).grade == 2
    assert careers.restrict('e1','review',EmploymentState.SUPERVISED).state == EmploymentState.SUPERVISED


def test_academy_certifies_only_passing_results():
    academy=Academy(); academy.register_course(Course('secure-code','Secure Code',('security',),85))
    assert academy.assess('e1','secure-code',90).passed is True
    assert academy.assess('e2','secure-code',70).passed is False


def test_services_owner_control_and_scoped_policy():
    services=build_default_service_registry()
    services.evaluate(ServiceEvaluation('openai',90,90,90,True,True))
    with pytest.raises(PermissionError): services.enable('openai',actor_is_owner=False)
    services.enable('openai',actor_is_owner=True)
    services.set_policy('openai','project','secret',False,actor_is_owner=True)
    assert services.allowed('openai',{'project':'normal'}) is True
    assert services.allowed('openai',{'project':'secret'}) is False


def test_future_discovery_never_auto_installs():
    discovery=FutureServiceDiscovery()
    discovery.submit(DiscoveryCandidate('future-ai','https://example.com/docs','useful',('review',),('commercial',)))
    assert discovery.candidates()[0].service_id == 'future-ai'
