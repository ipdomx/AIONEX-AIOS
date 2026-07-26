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
git clone https://github.com/aionex/aios.git
cd aionex-aios-dashboard

# Copy environment file
cp .env.example .env

# Start all services
docker-compose up -d

# Access the dashboard
open http://localhost:3000
```

### Local Development

```bash
# Backend
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python main.py

# Frontend (new terminal)
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

## Project Structure

```
aionex-aios-dashboard/
├── frontend/           # Next.js React Application
│   ├── src/
│   │   ├── app/       # Next.js App Router
│   │   ├── components/# React Components
│   │   ├── types/     # TypeScript Types
│   │   ├── store/     # Zustand Store
│   │   └── styles/    # Global Styles
│   ├── package.json
│   └── Dockerfile
├── backend/            # FastAPI Python Application
│   ├── app/
│   │   ├── api/       # API Endpoints
│   │   ├── core/      # Config, Logging, Events
│   │   ├── models/    # Database Models
│   │   ├── db/        # Database & Redis
│   │   └── websocket/ # WebSocket Manager
│   ├── main.py
│   ├── requirements.txt
│   └── Dockerfile
├── docker/            # Docker Configurations
├── docker-compose.yml
└── README.md
```

## API Documentation

- REST API: `http://localhost:8000/docs`
- GraphQL: `http://localhost:8000/graphql`
- Health Check: `http://localhost:8000/health`

## License

Proprietary — AIONEX Corp. All rights reserved.
