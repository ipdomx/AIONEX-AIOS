"""AI Provider model."""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Text, Integer, Numeric, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.database import Base


class AIProvider(Base):
    __tablename__ = "ai_providers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    slug = Column(String(100), nullable=False, unique=True)
    type = Column(String(50), nullable=False)  # openai, anthropic, google, openrouter, ollama, custom
    status = Column(String(20), default="disconnected")  # connected, disconnected, error, rate_limited
    api_key_encrypted = Column(Text, nullable=True)
    base_url = Column(String(500), nullable=True)
    org_id = Column(String(100), nullable=True)
    latency_ms = Column(Integer, default=0)
    cost_per_1k_input = Column(Numeric(10, 6), default=0)
    cost_per_1k_output = Column(Numeric(10, 6), default=0)
    usage_today = Column(Integer, default=0)
    usage_limit = Column(Integer, default=1000000)
    last_used = Column(DateTime, nullable=True)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    is_default = Column(Boolean, default=False)
    config = Column(Text, nullable=True)  # JSON
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    agents = relationship("AIAgent", back_populates="provider")

    def __repr__(self):
        return f"<AIProvider {self.name}>"
