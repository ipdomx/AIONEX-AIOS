from pathlib import Path
import os
from aios.kernel import AIOSKernel
from aios.orchestration import DefinitionOfDoneEngine, IntegrationJudge
from aios.languages import ProgrammingLanguageRegistry, HumanLanguageRegistry
from aios.interactions import InteractionNormalizer, PersonaRegistry
from aios.access import SessionAccessController


def test_definition_of_done_blocks_missing_evidence():
    result=DefinitionOfDoneEngine().evaluate({'tests_passed':True})
    assert not result.approved and 'security_reviewed' in result.missing_evidence


def test_integration_judge_rejects_conflicts():
    result=IntegrationJudge().evaluate({'frontend':{'tests_passed':True,'interface_conflicts':True}})
    assert not result.approved


def test_language_and_persona_registries():
    assert ProgrammingLanguageRegistry().get('Rust').name=='Rust'
    assert HumanLanguageRegistry().resolve('ar').direction=='rtl'
    assert PersonaRegistry().get('chief-engineer').paid is True


def test_voice_text_normalization():
    e=InteractionNormalizer().normalize('اختبار',modality='voice',dialect='Egyptian')
    assert e.modality=='voice' and e.dialect=='Egyptian'


def test_owner_only_session_approval(tmp_path, monkeypatch):
    monkeypatch.setenv('AIOS_HOME',str(tmp_path/'home'))
    k=AIOSKernel()
    s=k.sessions.request('u1','p1','project-staff','small',15,free_used=0,free_limit=2)
    assert s.price==0
    try:
        k.sessions.approve(s.session_id,'other')
        assert False
    except PermissionError:
        pass
    approved=k.sessions.approve(s.session_id,'owner')
    assert approved['status']=='approved'


def test_master_orchestrator_delivery_gate(tmp_path, monkeypatch):
    monkeypatch.setenv('AIOS_HOME',str(tmp_path/'home2'))
    k=AIOSKernel()
    tasks=k.master_orchestrator.decompose('p','build system',departments=('Backend','Quality'))
    assert len(tasks)==2
    bad=k.master_orchestrator.delivery_review({'Backend':{'tests_passed':False}})
    assert bad['approved'] is False
