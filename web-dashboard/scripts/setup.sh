#!/bin/bash
# AIONEX AIOS — Setup Script

set -e

echo "🚀 AIONEX AIOS — Setup"
echo "======================"

# Check prerequisites
command -v docker >/dev/null 2>&1 || { echo "❌ Docker is required but not installed. Aborting." >&2; exit 1; }
command -v docker-compose >/dev/null 2>&1 || { echo "❌ Docker Compose is required but not installed. Aborting." >&2; exit 1; }

# Copy env file if not exists
if [ ! -f .env ]; then
    cp .env.example .env
    echo "✅ Created .env file from example"
fi

# Build and start
echo "🏗️  Building and starting services..."
docker-compose up -d --build

echo ""
echo "✅ AIONEX AIOS is running!"
echo ""
echo "🌐 Dashboard: http://localhost:3000"
echo "📡 API: http://localhost:8000"
echo "📚 API Docs: http://localhost:8000/docs"
echo ""
echo "To view logs: docker-compose logs -f"
echo "To stop: docker-compose down"
