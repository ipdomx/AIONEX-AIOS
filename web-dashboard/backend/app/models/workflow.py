"""Workflow model."""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Text, Integer, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.database import Base


class Workflow(Base):
    __tablename__ = "workflows"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    slug = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(20), default="draft")  # draft, active, paused, archived
    nodes = Column(Text, nullable=True)  # JSON - workflow nodes
    edges = Column(Text, nullable=True)  # JSON - workflow edges
    execution_count = Column(Integer, default=0)
    success_rate = Column(Numeric(5, 2), default=100)
    avg_execution_time_ms = Column(Integer, default=0)
    last_executed = Column(DateTime, nullable=True)
    schedule = Column(String(100), nullable=True)  # cron expression
    is_template = Column(String(20), default="no")  # no, system, custom
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    config = Column(Text, nullable=True)  # JSON
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Workflow {self.name}>"
