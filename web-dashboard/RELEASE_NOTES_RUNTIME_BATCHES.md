# AIONEX AIOS Consolidated Runtime Release

This release consolidates runtime batches 1 through 8 into one deployment line.

## Included

- Authentication, sessions, organizations, users, roles, permissions, and RBAC.
- Workspaces, projects, tasks, workflows, meetings, reports, and dashboard aggregates.
- AI providers, agents, jobs, notifications, and authenticated realtime delivery.
- Monitoring, logs, alerts, audit events, backups, restore operations, and disaster recovery controls.
- SQLAlchemy persistence infrastructure, Alembic migration baseline, and bootstrap seeding.
- Route validation, security tests, performance smoke tests, release verification, and production Docker orchestration.

## Deployment requirements

- Create `web-dashboard/.env.production` from `.env.production.example`.
- Replace every placeholder secret before startup.
- Run database migrations before serving traffic.
- Run `web-dashboard/scripts/release_verify.sh` before deployment.
- Use `docker-compose.production.yml` for the final production deployment.
