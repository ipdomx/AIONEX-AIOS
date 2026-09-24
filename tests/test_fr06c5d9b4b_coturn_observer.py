"""Executable tests for private Coturn observation; no Docker or network needed."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from scripts.security import fr06c5d9_coturn_observer as observer

TYPE = '# TYPE turn_total_allocations gauge\n'
CONFIG = 'prometheus\nprometheus-address=127.0.0.1\nprometheus-port=9641\nno-tcp-relay\n'


@pytest.mark.parametrize('number, expected', [('0',0),('3',3),('0.0',0),('2e1',20)])
def test_real_exporter_udp_gauge_shape(number, expected):
    assert observer.parse_allocations(TYPE+'turn_total_allocations{type="UDP"} '+number) == expected


@pytest.mark.parametrize('family', [
    '', TYPE, '# TYPE turn_total_allocations counter\nturn_total_allocations{type="UDP"} 0',
    'turn_total_allocations{type="UDP"} 0',
    TYPE+'turn_total_allocations{type="TCP"} 0',
    TYPE+'turn_total_allocations{type="UDP",username="private"} 0',
    TYPE+'turn_total_allocations 0',
    TYPE+'turn_total_allocations{type="UDP"} 0\nturn_total_allocations{type="UDP"} 0',
    TYPE+TYPE+'turn_total_allocations{type="UDP"} 0',
    TYPE+'turn_total_allocations{type="UDP"} 0 123456',
    TYPE+'turn_total_allocations{type="UDP"} NaN',
    TYPE+'turn_total_allocations{type="UDP"} +Inf',
    TYPE+'turn_total_allocations{type="UDP"} -1',
    TYPE+'turn_total_allocations{type="UDP"} 1.5',
    TYPE+'turn_total_allocations{type="UDP"} 9999999999999999999999',
    TYPE+'turn_total_allocations{type="UDP"} bad',
    TYPE+'turn_total_allocations{type="UDP"} 0\nturn_total_allocations{type="TCP"} 1',
    None, True,
])
def test_missing_malformed_or_incomplete_metric_never_means_zero(family):
    with pytest.raises(observer.ObservationBlocked):
        observer.parse_allocations(family)


def test_private_udp_profile_is_accepted_without_reading_credentials():
    observer.validate_config(CONFIG+'realm=example.invalid\nstatic-auth-secret=not-used-test-value\n')


@pytest.mark.parametrize('body', [
    '', CONFIG.replace('prometheus\n',''), CONFIG.replace('127.0.0.1','0.0.0.0'),
    CONFIG.replace('9641','9642'), CONFIG.replace('no-tcp-relay\n',''),
    CONFIG+'no-udp-relay\n', CONFIG+'prometheus-username-labels\n',
    CONFIG+'include=some-file\n', CONFIG+'config=some-file\n',
    CONFIG+'prometheus-port=9641\n',CONFIG+'prometheus-path=/elsewhere\n',
    CONFIG.replace('prometheus\n','prometheus=false\n'),
])
def test_unconfigured_public_or_uncovered_profile_is_rejected(body):
    with pytest.raises(observer.ObservationBlocked):
        observer.validate_config(body)


class FakeObserver:
    project='aionex-disposable-unit-test'

    def __init__(self):
        self.operation=str(uuid4())
        self.authority_state={'schema_version':8,'scope':observer.SCOPE,
            'generation':17,'status':'closed','enabled':False,'operation_id':self.operation,
            'changed_at':datetime.now(UTC).isoformat(),'full_host_closure':False}
        self.baseline=observer.Epoch('a'*64,observer.IMAGE,123,'2026-09-01T00:00:00Z',0,str(uuid4()),100,200)
        self.epoch_calls={}
        self.authority_calls=0
        self.sample_calls=0
        self.config_calls=0
        self.mode='ok'
        self.values=[0,0]
        self.closed_namespace=False

    def epoch(self, service):
        self.epoch_calls[service]=self.epoch_calls.get(service,0)+1
        count=self.epoch_calls[service]
        if self.mode=='turn-restart' and service=='realtime-turn' and count>=2:
            return replace(self.baseline,restart_count=1)
        if self.mode=='backend-final-restart' and service=='backend' and count>=3:
            return replace(self.baseline,pid=456)
        return self.baseline

    def authority(self, epoch):
        self.authority_calls+=1
        result=dict(self.authority_state)
        if self.mode=='open-before':
            result.update(status='open',enabled=True)
        if self.authority_calls>1:
            if self.mode=='reopen':result.update(status='open',enabled=True)
            if self.mode=='generation':result['generation']+=2
            if self.mode=='operation':result['operation_id']=str(uuid4())
            if self.mode=='timestamp':result['changed_at']='2026-09-02T00:00:00Z'
        return result

    def config_digest(self, epoch):
        self.config_calls+=1
        if self.mode=='config' and self.config_calls>1:return 'b'*64
        return 'a'*64

    @contextmanager
    def network_namespace(self, epoch):
        try:yield 123
        finally:self.closed_namespace=True

    def sample(self, fd):
        self.sample_calls+=1
        if self.mode=='missing':raise observer.ObservationBlocked('allocation metric missing')
        return {'udp_allocations':self.values[self.sample_calls-1],'body_sha256':'c'*64,'body_bytes':500}


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(observer.time,'sleep',lambda _:None)
    return FakeObserver()


@pytest.mark.parametrize('counts,zero', [([0,0],True),([1,0],False),([0,1],False),([3,3],False)])
def test_observation_keeps_live_counts_and_never_authorizes_rollout(fake, counts, zero):
    fake.values=counts
    result=observer.collect_observation(operation_id=fake.operation,generation=17,observer=fake)
    assert result['allocation_zero_observed'] is zero
    assert [r['udp_allocations'] for r in result['samples']]==counts
    assert fake.authority_calls==2 and fake.closed_namespace
    assert result['generation']==17 and result['operation_id']==fake.operation
    for key in ['missing_metric_is_zero','credential_expiry_verified','production_deployment_performed',
                'turn_allocation_drain_verified','provider_drain_verified','full_host_closure','migration_0064_rollout_allowed']:
        assert result[key] is False


@pytest.mark.parametrize('mode', ['open-before','reopen','generation','operation','timestamp',
                                  'turn-restart','backend-final-restart','config','missing'])
def test_any_changed_authority_epoch_or_missing_metric_blocks_observation(fake, mode):
    fake.mode=mode
    with pytest.raises(observer.ObservationBlocked):
        observer.collect_observation(operation_id=fake.operation,generation=17,observer=fake)
    if mode=='open-before':assert fake.sample_calls==0
    else:assert fake.closed_namespace


@pytest.mark.parametrize('generation', [True,False,0,7,17.0,'17'])
def test_generation_is_strict_before_any_observer_io(fake,generation):
    with pytest.raises(observer.ObservationBlocked):
        observer.collect_observation(operation_id=fake.operation,generation=generation,observer=fake)
    assert fake.epoch_calls=={}


def test_interval_deadline_includes_final_epoch_reads(fake,monkeypatch):
    readings=iter([0,31])
    monkeypatch.setattr(observer.time,'monotonic',lambda:next(readings))
    with pytest.raises(observer.ObservationBlocked,match='interval'):
        observer.collect_observation(operation_id=fake.operation,generation=17,observer=fake)


def test_other_project_cannot_be_selected():
    with pytest.raises(observer.ObservationBlocked):
        observer.DockerObserver('other-production-server')


def test_reader_commands_are_fixed_private_and_have_process_deadlines():
    assert 'http://127.0.0.1:9641/metrics' in observer.METRICS_READER
    assert 'ProxyHandler({})' in observer.METRICS_READER
    assert 'NoRedirect' in observer.METRICS_READER
    assert 'signal.alarm(5)' in observer.METRICS_READER
    assert 'signal.alarm(8)' in observer.AUTHORITY_READER
    assert 'read_admission_snapshot' in observer.AUTHORITY_READER
    assert 'commit(' not in observer.AUTHORITY_READER


def test_observer_plan_tracks_real_source_without_granting_production_acceptance():
    import json
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    plan=json.loads((root/'docs/project/PLAN.json').read_text())
    part=next(x for x in plan['batches'] if x['id']=='FR-06')['host_state_cutover_admission']
    assert part['source_part']=='FR-06C5D9B4'
    item=part['realtime_private_coturn_observer_source']
    assert item['source_part']=='FR-06C5D9B4B'
    assert item['closed_authority_before_after_required'] and item['pinned_network_namespace_descriptor']
    assert (root/item['observer']).is_file()
    assert all((root/x).is_file() for x in item['evidence'])
    for flag in ['missing_metric_is_zero','production_observer_activated','production_database_migrated',
                 'turn_allocation_drain_verified','provider_drain_verified','full_host_closure','migration_0064_rollout_allowed']:
        assert item[flag] is False
