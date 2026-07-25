from pathlib import Path
import pytest
from aios.runtime import ClusterManager, Worker, DistributedRuntime, TaskState
from aios.notifications import NotificationCenter, Notification, Audience, Severity, Channel
from aios.mission_control import MissionControl


def test_distributed_task_checkpoint_requeue_and_resume(tmp_path:Path):
    cluster=ClusterManager()
    cluster.register(Worker('w1','tenant-a',('security',),trust_score=.9))
    cluster.register(Worker('w2','tenant-a',('security',),trust_score=.8))
    runtime=DistributedRuntime(cluster,tmp_path/'runtime')
    task=runtime.submit('tenant-a','project-a','security',{'scan':'authorized'})
    assert runtime.assign(task.task_id)=='w1'
    runtime.checkpoint(task.task_id,{'files_scanned':42})
    fingerprint=runtime.fail_and_requeue(task.task_id,'worker connection lost')
    assert fingerprint and task.checkpoint=={'files_scanned':42}
    cluster.heartbeat('w1',state='offline')
    resumed=runtime.resume(task.task_id)
    assert resumed.worker_id=='w2'
    assert resumed.checkpoint['files_scanned']==42
    runtime.complete(task.task_id,{'status':'ok'})
    assert task.state==TaskState.COMPLETED


def test_notification_consent_owner_whatsapp_and_workforce_visibility(tmp_path:Path):
    center=NotificationCenter('owner-1',tmp_path/'notifications.jsonl')
    center.configure('user-1',{Channel.IN_APP,Channel.PUSH,Channel.EMAIL},push_consent=False)
    user_channels=center.project_question('tenant-a','user-1','p1','Choose database')
    assert Channel.PUSH not in user_channels and Channel.EMAIL in user_channels
    center.configure('owner-1',{Channel.IN_APP,Channel.EMAIL,Channel.WHATSAPP},push_consent=True)
    owner_channels=center.owner_event('tenant-a','Production incident','Service unavailable',Severity.EMERGENCY,'p1')
    assert Channel.WHATSAPP in owner_channels
    center.configure('engineer-1',{Channel.IN_APP,Channel.WHATSAPP},push_consent=True)
    workforce_channels=center.workforce_event('tenant-a','engineer-1','Review requested','Review API contract','p1')
    assert Channel.WHATSAPP not in workforce_channels
    assert any(n.recipient_id=='owner-1' for items in center.router.outbox.values() for n in items)


def test_owner_command_center_is_owner_only(tmp_path:Path):
    cluster=ClusterManager(); runtime=DistributedRuntime(cluster,tmp_path/'runtime')
    center=NotificationCenter('owner-1',tmp_path/'notifications.jsonl')
    mission=MissionControl('owner-1',cluster,runtime,center)
    mission.request_approval('a1','Release project','chief-engineer')
    with pytest.raises(PermissionError): mission.decide('a1','manager-1',True)
    mission.decide('a1','owner-1',True)
    assert mission.approvals['a1']['status']=='approved'
