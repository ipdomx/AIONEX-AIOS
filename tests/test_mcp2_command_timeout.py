"""Owned, self-expiring child processes only; no installed MCP or host services."""
from __future__ import annotations
import json
import subprocess
import sys
import time
from pathlib import Path
import pytest
from test_mcp2_operator_repair import operator


@pytest.mark.parametrize('parent_exits', [False, True])
def test_timeout_stops_same_group_child_before_its_late_write(operator, tmp_path, parent_exits):
    marker = tmp_path / 'owned-child-marker'
    child = ('import sys,time;from pathlib import Path;'
             'time.sleep(1.8);Path(sys.argv[1]).write_text("owned synthetic effect")')
    parent = ('import subprocess,sys,time;'
              'subprocess.Popen([sys.executable,"-c",'+repr(child)+',sys.argv[1]]);'
              'print("child-started",flush=True);' + ('' if parent_exits else 'time.sleep(5)'))
    started = time.monotonic()
    result = operator._run([sys.executable, '-c', parent, str(marker)], cwd=tmp_path, timeout_seconds=1)
    assert result['exit_code'] == 124
    # The baseline child exits by itself. Never signal the caller's process group.
    time.sleep(max(0, 2.2 - (time.monotonic() - started)))
    assert not marker.exists(), 'owned child performed an effect after the timeout response'


def test_timeout_keeps_effects_already_performed_and_reports_unknown(operator, tmp_path):
    marker = tmp_path / 'before-timeout'
    code = 'import sys,time;from pathlib import Path;Path(sys.argv[1]).write_text("retained");time.sleep(5)'
    result = operator._run([sys.executable, '-c', code, str(marker)], cwd=tmp_path, timeout_seconds=1)
    assert marker.read_text() == 'retained'
    assert result['outcome'] == 'unknown' and result['automatic_retry'] is False
    assert result['cleanup']['process_group_signal_sent'] is True
    assert result['cleanup']['direct_child_reaped'] is True
    assert 'do not replay' in result['stderr']


def test_unrelated_detached_session_is_not_signaled_or_claimed_stopped(operator, tmp_path):
    marker = tmp_path / 'separate-owned-session'
    child = 'import sys,time;from pathlib import Path;time.sleep(1.8);Path(sys.argv[1]).write_text("alive")'
    parent = ('import subprocess,sys,time;subprocess.Popen([sys.executable,"-c",'+repr(child)+
              ',sys.argv[1]],start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);time.sleep(5)')
    start = time.monotonic()
    result = operator._run([sys.executable, '-c', parent, str(marker)], cwd=tmp_path, timeout_seconds=1)
    time.sleep(max(0, 2.2 - (time.monotonic() - start)))
    assert marker.read_text() == 'alive'
    assert result['outcome'] == 'unknown'
    assert set(result['cleanup']) == {'process_group_signal_sent','direct_child_reaped','output_collection_complete'}


@pytest.mark.parametrize('exit_code', [0, 7])
def test_normal_command_semantics_and_new_group(operator, tmp_path, exit_code):
    import os
    code='import os,sys,json;print(json.dumps([os.getpid(),os.getpgrp(),os.getsid(0)]));print("ordinary-error",file=sys.stderr);sys.exit('+str(exit_code)+')'
    result=operator._run([sys.executable,'-c',code],cwd=tmp_path,timeout_seconds=3)
    pid,group,session=json.loads(result['stdout'])
    assert pid == group == session and group != os.getpgrp()
    assert result['exit_code'] == exit_code and result['stderr'] == 'ordinary-error\n'
    assert set(result) == {'exit_code','stdout','stderr'}


def test_explicit_empty_environment_does_not_reintroduce_inherited_values(operator, tmp_path, monkeypatch):
    monkeypatch.setenv('MCP_SYNTHETIC_SHOULD_NOT_INHERIT','synthetic-only')
    result=operator._run([sys.executable,'-c','import os;print(os.getenv("MCP_SYNTHETIC_SHOULD_NOT_INHERIT", "absent"))'],cwd=tmp_path,env={})
    assert result['exit_code']==0 and result['stdout']=='absent\n'


def test_timeout_preserves_unicode_output_once(operator,tmp_path):
    code='import time;print("اختبار-🧪",flush=True);time.sleep(5)'
    result=operator._run([sys.executable,'-c',code],cwd=tmp_path,timeout_seconds=1)
    assert result['exit_code']==124 and result['stdout']=='اختبار-🧪\n'


def test_shell_route_uses_the_same_timeout_supervision(operator,tmp_path):
    import shlex
    code='import time;print("owned-shell",flush=True);time.sleep(5)'
    result=operator._shell(shlex.join([sys.executable,'-c',code]),cwd=tmp_path,timeout_seconds=1)
    assert result['exit_code']==124 and result['stdout']=='owned-shell\n'
    assert result['cleanup']['process_group_signal_sent'] is True


@pytest.mark.parametrize('fault',['platform','child_handler'])
def test_unsupported_supervision_rejects_before_launch(operator,tmp_path,monkeypatch,fault):
    from types import SimpleNamespace
    from unittest.mock import Mock
    launch=Mock(side_effect=AssertionError('must not launch'))
    monkeypatch.setattr(operator.subprocess,'Popen',launch)
    if fault=='platform':monkeypatch.setattr(operator,'sys',SimpleNamespace(platform='win32'))
    else:monkeypatch.setattr(operator,'signal',SimpleNamespace(SIGCHLD=17,SIG_DFL=0,getsignal=lambda _:1))
    result=operator._run(['must-not-execute'],cwd=tmp_path)
    assert result['exit_code']==125 and 'not started' in result['stderr']
    launch.assert_not_called()


@pytest.mark.parametrize('budget,expected',[(0,1),(-9,1),(5,5),(9999,1800)])
def test_timeout_bounds_and_session_are_not_caller_overrideable(operator,tmp_path,monkeypatch,budget,expected):
    from types import SimpleNamespace
    called={}
    def launch(args,**kw):
        called.update(kw)
        return SimpleNamespace(returncode=0,communicate=lambda *,timeout:(called.update(timeout=timeout) or ('ok','')))
    monkeypatch.setattr(operator.subprocess,'Popen',launch)
    assert operator._run(['fixture-only'],cwd=tmp_path,timeout_seconds=budget)['exit_code']==0
    assert called['timeout']==expected and called['start_new_session'] is True
    assert called['stdin']==subprocess.DEVNULL


class Stream:
    def __init__(self):self.closed=False
    def close(self):self.closed=True


@pytest.mark.parametrize('already_reaped',[False,True])
def test_unknown_leader_ownership_never_signals_a_reusable_pid(operator,monkeypatch,already_reaped):
    from types import SimpleNamespace
    from unittest.mock import Mock
    wait=Mock(side_effect=ChildProcessError('synthetic ownership loss'))
    kill=Mock(side_effect=AssertionError('must not signal'))
    monkeypatch.setattr(operator,'os',SimpleNamespace(P_PID=1,WEXITED=4,WNOWAIT=8,WNOHANG=16,waitid=wait,killpg=kill))
    p=SimpleNamespace(pid=987654,returncode=0 if already_reaped else None,stdout=Stream(),stderr=Stream())
    out,state=operator._stop_owned_command(p,b'partial')
    assert out==b'partial' and not any(state.values())
    assert p.stdout.closed and p.stderr.closed
    kill.assert_not_called()
    assert wait.call_count==(0 if already_reaped else 1)


@pytest.mark.parametrize('kill_error',[False,True])
def test_leader_identity_is_observed_without_reaping_before_single_group_signal(operator,monkeypatch,kill_error):
    from types import SimpleNamespace
    calls=[]
    def waitid(*args):calls.append(('observe',args));return None
    def killpg(*args):
        calls.append(('signal',args))
        if kill_error:raise PermissionError('synthetic')
    monkeypatch.setattr(operator,'os',SimpleNamespace(P_PID=1,WEXITED=4,WNOWAIT=8,WNOHANG=16,waitid=waitid,killpg=killpg))
    p=SimpleNamespace(pid=987654,returncode=None,stdout=Stream(),stderr=Stream())
    def communicate(*,timeout):calls.append(('join',timeout));p.returncode=-9;return ('whole-output','')
    p.communicate=communicate
    out,state=operator._stop_owned_command(p,b'partial')
    assert [x[0] for x in calls]==['observe','signal','join']
    assert calls[0][1]==(1,p.pid,4|8|16) and calls[1][1]==(p.pid,operator.signal.SIGKILL)
    assert out=='whole-output' and state['process_group_signal_sent'] is (not kill_error)
    assert state['direct_child_reaped'] is True


@pytest.mark.parametrize('wait_finishes',[False,True])
def test_detached_pipe_cleanup_has_a_second_bounded_wait(operator,monkeypatch,wait_finishes):
    from types import SimpleNamespace
    called=[]
    monkeypatch.setattr(operator,'os',SimpleNamespace(P_PID=1,WEXITED=4,WNOWAIT=8,WNOHANG=16,waitid=lambda *a:None,killpg=lambda *a:None))
    p=SimpleNamespace(pid=987654,returncode=None,stdout=Stream(),stderr=Stream())
    def communicate(*,timeout):called.append(timeout);raise subprocess.TimeoutExpired(['fixture'],timeout,output=b'new-partial')
    def wait(*,timeout):
        called.append(timeout)
        if not wait_finishes:raise subprocess.TimeoutExpired(['fixture'],timeout)
        p.returncode=-9
    p.communicate=communicate;p.wait=wait
    out,state=operator._stop_owned_command(p,b'old')
    assert called==[3,1] and out==b'new-partial'
    assert p.stdout.closed and p.stderr.closed
    assert state['direct_child_reaped'] is wait_finishes and state['output_collection_complete'] is False


def test_missing_executable_is_not_reported_as_a_completed_command(operator,tmp_path):
    with pytest.raises(FileNotFoundError):operator._run([str(tmp_path/'not-created')],cwd=tmp_path)
