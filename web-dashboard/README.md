# AIONEX AIOS — Enterprise AI Operating System

The most premium Enterprise AI Operating System dashboard ever created.

## Features

- **AI Management**: Multi-provider AI agents (OpenAI, Anthropic, Google, OpenRouter, Ollama)
- **Workflow Engine**: Visual node editor for building automation pipelines
- **Infrastructure**: Server, container, Kubernetes, and database monitoring
- **Security**: Threat detection, audit logs, session management
- **Knowledge Base**: AI-powered document management with embeddings
- **Project Management**: Kanban, Gantt, and timeline views
- **Real-time Monitoring**: Live metrics, logs, and alerts
- **RBAC**: 26+ dynamic roles with permission matrix
- **Global Search**: Universal search across all resources
- **Command Palette**: Keyboard-driven command interface

## Tech Stack

### Frontend
- Next.js 14 + React 18 + TypeScript
- TailwindCSS + Framer Motion
- Apache ECharts + Recharts
- Zustand + React Query
- Radix UI + Lucide Icons

### Backend
- FastAPI (Python)
- SQLAlchemy + Alembic
- PostgreSQL + Redis
- WebSocket + Socket.io
- JWT + MFA

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Node.js 20+ (for local development)
- Python 3.11+ (for local development)

### Using Docker (Recommended)

```bash
# Clone the repository
git clone https://github.com/ipdomx/AIONEX-AIOS.git
cd AIONEX-AIOS/web-dashboard

# Create and secure the environment file
cp .env.example .env

# Start all services
docker compose up -d

# Access the dashboard
open http://localhost:3000
```

New bundled Compose installations use the `POSTGRES_*` values for PostgreSQL
and leave `DATABASE_URL` empty so the backend constructs a safely encoded
asyncpg URL. Existing installations may keep an explicit `DATABASE_URL`;
the backend and backup worker continue to honor it without requiring a manual
environment-file migration. When that URL targets the bundled `postgres`
service, its complete user, password, and database identity takes precedence.

### Existing PostgreSQL volume recovery

PostgreSQL applies `POSTGRES_PASSWORD` only when it initializes an empty data
directory. Editing `.env` later does not change the role password stored in an
existing `postgres_data` volume. If the backend reports `password
authentication failed`, synchronize the existing role without deleting data:

```bash
cd /opt/AIOS/web-dashboard
chmod +x scripts/reconcile-postgres-credentials.sh
./scripts/reconcile-postgres-credentials.sh
```

For the production stack, pass the same Compose and environment files used to
start it so every reconciliation command targets one project consistently:

```bash
AIOS_ENV_FILE="$PWD/.env.production" \
docker compose --env-file .env.production \
  -f docker-compose.production.yml up -d

COMPOSE_FILE=docker-compose.production.yml \
ENV_FILE=.env.production \
./scripts/reconcile-postgres-credentials.sh
```

This `web-dashboard` production stack exposes HTTP on port 80 for an external
TLS terminator. Use `deploy/production` when Caddy-managed public TLS is
required. The two stacks use separate Compose projects and must not be run
interchangeably against a server's existing data.

Compose automatically runs a one-shot credential reconciler before the backend.
It accepts `POSTGRES_*` alone or a legacy `postgresql+asyncpg` `DATABASE_URL`.
A URL targeting the bundled `postgres` service becomes the compatibility
credential source, including its user and database, so stale `POSTGRES_*`
initialization values do not break an existing volume. A valid external URL
skips local reconciliation. Malformed bundled values fail before changing the
local role. The same gate is used by this recovery script, which stops the
backup worker, updates only the existing role password through the private
PostgreSQL socket, verifies password-authenticated TCP access, recreates the
backend and backup worker, and waits for their health checks. It never deletes
or recreates the database volume, never writes the environment file, and never
places plaintext credentials in SQL or command arguments.

On first startup the backend creates the configured Super Owner after Alembic
finishes. Later restarts never reset that password. To perform an intentional
reset, set both `AIOS_BOOTSTRAP_OWNER_PASSWORD` and
`AIOS_BOOTSTRAP_RESET_OWNER_PASSWORD=true` for one controlled restart, then
clear the password and disable the reset flag again.

### Local Development

```bash
# Backend
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp ../.env.example .env
# Change POSTGRES_HOST to localhost when PostgreSQL runs on the host.
alembic upgrade head
python -m app.db.seed
python main.py

# Frontend (new terminal)
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

## Project Structure

```
AIONEX-AIOS/
├── web-dashboard/
│   ├── frontend/           # Next.js React application
│   ├── backend/            # FastAPI application
│   ├── docker/             # Docker configuration
│   ├── scripts/            # Operational recovery scripts
│   └── docker-compose.yml
└── README.md
```

## API Documentation

- REST API: `http://localhost:8000/docs`
- GraphQL: `http://localhost:8000/graphql`
- Health Check: `http://localhost:8000/health`

## License

Proprietary — AIONEX Corp. All rights reserved.
