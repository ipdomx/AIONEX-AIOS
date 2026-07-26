"""AI Agent model."""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Text, Integer, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.database import Base


class AIAgent(Base):
    __tablename__ = "ai_agents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    slug = Column(String(255), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    avatar = Column(String(500), nullable=True)
    status = Column(String(20), default="idle")  # idle, running, learning, error, paused
    role = Column(String(100), nullable=False)
    department = Column(String(100), nullable=True)
    provider_id = Column(UUID(as_uuid=True), ForeignKey("ai_providers.id"), nullable=False)
    model = Column(String(100), nullable=False)
    system_prompt = Column(Text, nullable=True)
    temperature = Column(Numeric(3, 2), default=0.7)
    max_tokens = Column(Integer, default=2048)
    tasks_completed = Column(Integer, default=0)
    tasks_failed = Column(Integer, default=0)
    knowledge_count = Column(Integer, default=0)
    memory_usage_mb = Column(Integer, default=0)
    performance_score = Column(Numeric(5, 2), default=0)
    avg_latency_ms = Column(Integer, default=0)
    total_cost = Column(Numeric(15, 4), default=0)
    tokens_used = Column(Integer, default=0)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=True)
    is_public = Column(String(20), default="private")  # private, team, public
    config = Column(Text, nullable=True)  # JSON
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    provider = relationship("AIProvider", back_populates="agents")

    def __repr__(self):
        return f"<AIAgent {self.name}>"
