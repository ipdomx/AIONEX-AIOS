from app.core.runtime_store import RuntimeStore


def test_runtime_store_bootstraps_consistent_entities():
    store = RuntimeStore()
    assert store.workspaces
    assert store.projects
    assert store.tasks
    assert store.workflows
    assert store.meetings
    assert store.reports

    project = next(iter(store.projects.values()))
    tasks = [item for item in store.tasks.values() if item.get("project_id") == project["id"]]
    assert project["task_count"] == len(tasks)


def test_runtime_store_activity_is_latest_first():
    store = RuntimeStore()
    first = store.add_activity("test", "First", "first", "owner-1")
    second = store.add_activity("test", "Second", "second", "owner-1")
    assert store.activities[0]["id"] == second["id"]
    assert store.activities[1]["id"] == first["id"]
