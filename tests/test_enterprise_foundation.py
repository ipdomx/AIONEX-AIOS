from pathlib import Path
import pytest
from aios.enterprise import (
    Contract, ContractRegistry, Event, ServiceBus, Capability, CapabilityRegistry,
    TenantContext, PolicyEngine, APIGateway, WorkflowStep, DurableWorkflowEngine,
    Observability, PluginManifest, PluginRuntime,
)
from aios.kernel import AIOSKernel


def test_contract_bus_is_versioned_and_idempotent():
    registry=ContractRegistry()
    registry.register(Contract('ProjectCreated','1.0',('project_id',),'projects',('audit',)))
    bus=ServiceBus(registry); seen=[]
    bus.subscribe('ProjectCreated','audit',lambda e: seen.append(e.payload['project_id']))
    event=Event('ProjectCreated',{'project_id':'p1'},'tenant-a','projects',correlation_id='same')
    assert bus.publish(event)==1
    assert bus.publish(event)==0
    assert seen==['p1']


def test_contract_rejects_wrong_producer_and_missing_fields():
    registry=ContractRegistry(); registry.register(Contract('X','1.0',('id',),'a',('b',)))
    bus=ServiceBus(registry)
    with pytest.raises(PermissionError): bus.publish(Event('X',{'id':'1'},'t','wrong'))
    with pytest.raises(ValueError): bus.publish(Event('X',{},'t','a'))


def test_capability_selection_prefers_trust():
    r=CapabilityRegistry()
    r.register(Capability('c1','worker-a',('security','python'),('Python',),0.7))
    r.register(Capability('c2','worker-b',('security','python'),('Python',),0.95))
    assert r.select(('security',),'python')[0].capability_id=='c2'


def test_tenant_isolation_and_owner_policy():
    tenants=TenantContext(); tenants.add_member('t1','u1')
    gateway=APIGateway(PolicyEngine(),tenants,limit_per_minute=2)
    gateway.authorize(tenant_id='t1',subject_id='u1',role='member',action='project.read')
    with pytest.raises(PermissionError): gateway.authorize(tenant_id='t2',subject_id='u1',role='member',action='project.read')
    with pytest.raises(PermissionError): gateway.authorize(tenant_id='t1',subject_id='u1',role='member',action='meeting.approve')


def test_durable_workflow_resumes_after_failure(tmp_path):
    engine=DurableWorkflowEngine(tmp_path/'wf')
    attempts={'n':0}
    def first(ctx): return {'a':1}
    def unstable(ctx):
        attempts['n']+=1
        if attempts['n']==1: raise RuntimeError('temporary')
        return {'b':ctx['a']+1}
    wid='wf1'
    result=engine.run('t','build',[WorkflowStep('one',first),WorkflowStep('two',unstable)],{},wid)
    assert result.state=='failed' and result.current_step==1
    result=engine.run('t','build',[WorkflowStep('one',first),WorkflowStep('two',unstable)],{},wid)
    assert result.state=='complete' and result.context['b']==2


def test_immutable_audit_chain(tmp_path):
    obs=Observability(tmp_path/'audit.jsonl')
    obs.record('event','t',{'x':1}); obs.record('event','t',{'x':2})
    assert obs.verify()


def test_plugin_runtime_requires_signature_and_api_version():
    runtime=PluginRuntime()
    with pytest.raises(PermissionError): runtime.install(PluginManifest('p','1','2.0',('x',),False))
    runtime.install(PluginManifest('p','1','2.0',('x',),True))
    assert len(runtime.list())==1


def test_kernel_exposes_enterprise_foundation(tmp_path,monkeypatch):
    monkeypatch.setenv('AIOS_HOME',str(tmp_path/'home'))
    k=AIOSKernel(); status=k.status()
    assert status['enterprise_foundation'].startswith('service-bus')
    assert status['version']=='2.3.0-beta.5'
