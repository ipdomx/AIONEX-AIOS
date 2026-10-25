"""Project list counting must remain tenant-scoped and index-compatible."""
from __future__ import annotations

import unittest

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.api.v1.endpoints.projects import _tenant_scoped_active_task_count
from app.db.models import Project


class ProjectCountSQLTests(unittest.TestCase):
    def test_task_count_uses_tenant_composite_index_prefix(self):
        statement = select(Project.id, _tenant_scoped_active_task_count())
        sql = str(statement.compile(dialect=postgresql.dialect())).upper()
        self.assertIn("COUNT(*)", sql)
        self.assertIn("TASKS.ORGANIZATION_ID = PROJECTS.ORGANIZATION_ID", sql)
        self.assertIn("TASKS.PROJECT_ID = PROJECTS.ID", sql)
        self.assertIn("TASKS.STATUS !=", sql)

    def test_count_preserves_independent_org_and_project_filters(self):
        statement = select(Project.id, _tenant_scoped_active_task_count()).where(
            Project.organization_id == "synthetic-tenant-a"
        )
        sql = str(statement.compile(dialect=postgresql.dialect())).upper()
        self.assertIn("PROJECTS.ORGANIZATION_ID =", sql)
        self.assertIn("TASKS.ORGANIZATION_ID = PROJECTS.ORGANIZATION_ID", sql)


if __name__ == "__main__":
    unittest.main()
