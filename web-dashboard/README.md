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

The bundled Compose stack uses the `POSTGRES_*` values for both PostgreSQL and
the backend. Leave `DATABASE_URL` empty to let the backend construct a safely
encoded asyncpg URL. Set `DATABASE_URL` only when connecting to an external
database.

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

The script waits for PostgreSQL, updates the existing role to the configured
password, verifies password authentication over TCP, recreates the backend, and
waits for its health check. It never deletes the database volume.

### Local Development

```bash
# Backend
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp ../.env.example .env
# Change POSTGRES_HOST to localhost when PostgreSQL runs on the host.
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
