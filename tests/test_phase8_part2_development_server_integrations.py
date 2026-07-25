import asyncio

import pytest

from aios.infrastructure import (CommandRejected, ConnectionProfile, Credential, DockerProvider,
                                 GitHubProvider, GitLabProvider, GitProvider, InfrastructurePlatform,
                                 RemoteExecutionManager, RemoteJobState, SSHProvider)


def make_platform():
    return InfrastructurePlatform(b"0123456789abcdef")


def test_ssh_execute_and_command_policy():
    platform = make_platform()
    ssh = SSHProvider()
    platform.registry.register(ssh)
    platform.credentials.register("root", Credential(username="root", private_key="key"))
    platform.connections.register_profile(ConnectionProfile(
        name="server", integration="ssh", endpoint="server.example", credential_ref="root"))
    asyncio.run(platform.connections.connect("server"))
    result = asyncio.run(platform.connections.execute("server", "execute", {"command": "uptime"}))
    assert result["exit_code"] == 0
    with pytest.raises(CommandRejected):
        asyncio.run(platform.connections.execute("server", "execute", {"command": "rm -rf /"}))


def test_git_builds_safe_argument_vector():
    platform = make_platform()
    git = GitProvider()
    platform.registry.register(git)
    platform.connections.register_profile(ConnectionProfile(
        name="repo", integration="git", options={"repository": "/srv/project"}))
    asyncio.run(platform.connections.connect("repo"))
    result = asyncio.run(platform.connections.execute("repo", "commit", {"message": "phase 8"}))
    assert result["args"] == ("git", "commit", "-m", "phase 8")
    assert result["cwd"] == "/srv/project"


def test_github_and_gitlab_api_integrations():
    platform = make_platform()
    platform.registry.register(GitHubProvider())
    platform.registry.register(GitLabProvider())
    platform.credentials.register("scm", Credential(token="secret"))
    platform.connections.register_profile(ConnectionProfile(name="gh", integration="github", credential_ref="scm"))
    platform.connections.register_profile(ConnectionProfile(name="gl", integration="gitlab", credential_ref="scm"))
    asyncio.run(platform.connections.connect("gh"))
    asyncio.run(platform.connections.connect("gl"))
    gh = asyncio.run(platform.connections.execute("gh", "pull_requests", {"repository": "a/b"}))
    gl = asyncio.run(platform.connections.execute("gl", "pipelines", {"project": "a/b"}))
    assert gh["provider"] == "github"
    assert gl["provider"] == "gitlab"


def test_docker_requires_approval_for_remove():
    platform = make_platform()
    platform.registry.register(DockerProvider())
    platform.connections.register_profile(ConnectionProfile(name="local-docker", integration="docker"))
    asyncio.run(platform.connections.connect("local-docker"))
    with pytest.raises(CommandRejected):
        asyncio.run(platform.connections.execute("local-docker", "remove", {"container": "x"}))
    result = asyncio.run(platform.connections.execute("local-docker", "remove", {"container": "x", "approved": True}))
    assert result["operation"] == "remove"


def test_remote_execution_job_lifecycle():
    async def scenario():
        platform = make_platform()
        platform.registry.register(SSHProvider())
        platform.connections.register_profile(ConnectionProfile(name="server", integration="ssh", endpoint="host"))
        await platform.connections.connect("server")
        manager = RemoteExecutionManager(platform.connections, concurrency=1)
        job = await manager.submit("server", "execute", {"command": "echo ready"})
        assert job.state == RemoteJobState.SUCCEEDED
        assert job.result["exit_code"] == 0
        await manager.close()
    asyncio.run(scenario())
