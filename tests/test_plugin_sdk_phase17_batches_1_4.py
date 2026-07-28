from aios.plugin_sdk.models import PluginManifest, PluginPackage, PluginState
from aios.plugin_sdk.permissions import PluginPermissionEvaluator, PluginPermissionPolicy
from aios.plugin_sdk.registry import PluginRegistry
from aios.plugin_sdk.runtime import PluginExecutionContext, PluginRuntime


def test_plugin_registry_lifecycle() -> None:
    registry = PluginRegistry()
    package = PluginPackage(
        manifest=PluginManifest(
            plugin_id="plugin-1",
            owner_id="owner-1",
            name="GitHub Helper",
            version="1.0.0",
            description="Project automation plugin",
            entrypoint="plugin:run",
            permissions={"projects:read"},
        ),
        checksum="sha256:abc",
        artifact_uri="s3://plugins/plugin-1.zip",
    )
    registry.register(package)
    registry.submit("plugin-1", "owner-1")
    registry.approve("plugin-1")
    published = registry.publish("plugin-1")

    assert published.manifest.state is PluginState.PUBLISHED
    assert registry.list_published()[0].manifest.plugin_id == "plugin-1"


def test_plugin_owner_scope_is_enforced() -> None:
    registry = PluginRegistry()
    registry.register(
        PluginPackage(
            manifest=PluginManifest(
                plugin_id="plugin-2",
                owner_id="owner-1",
                name="Private Plugin",
                version="1.0.0",
                description="Owner isolated",
                entrypoint="plugin:run",
            ),
            checksum="sha256:def",
            artifact_uri="s3://plugins/plugin-2.zip",
        )
    )

    try:
        registry.submit("plugin-2", "owner-2")
    except PermissionError:
        pass
    else:
        raise AssertionError("another owner must not submit the plugin")


def test_permission_evaluator_requires_owner_approval() -> None:
    evaluator = PluginPermissionEvaluator(
        PluginPermissionPolicy(
            allowed_permissions={"projects:read", "projects:write"},
            owner_approval_required={"projects:write"},
        )
    )

    try:
        evaluator.validate({"projects:write"})
    except PermissionError:
        pass
    else:
        raise AssertionError("owner approval must be required")

    evaluator.validate({"projects:write"}, owner_approved=True)


def test_plugin_runtime_executes_registered_handler() -> None:
    runtime = PluginRuntime()
    runtime.register_handler(
        "plugin-1",
        lambda context, payload: {
            "owner": context.owner_id,
            "value": payload["value"],
        },
    )

    result = runtime.execute(
        PluginExecutionContext(
            plugin_id="plugin-1",
            owner_id="owner-1",
            project_id="project-1",
        ),
        {"value": 7},
    )

    assert result.success is True
    assert result.output == {"owner": "owner-1", "value": 7}
