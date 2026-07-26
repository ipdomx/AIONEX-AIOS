"""Container model."""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Text, Integer, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.database import Base


class Container(Base):
    __tablename__ = "containers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    container_id = Column(String(255), nullable=False, unique=True)
    image = Column(String(500), nullable=False)
    status = Column(String(20), default="stopped")  # running, stopped, restarting, error
    server_id = Column(UUID(as_uuid=True), ForeignKey("servers.id"), nullable=False)
    cpu_usage = Column(Numeric(5, 2), default=0)
    memory_usage_mb = Column(Integer, default=0)
    memory_limit_mb = Column(Integer, default=0)
    ports = Column(Text, nullable=True)  # JSON
    volumes = Column(Text, nullable=True)  # JSON
    env_vars = Column(Text, nullable=True)  # JSON
    restart_count = Column(Integer, default=0)
    health_status = Column(String(20), default="unknown")  # healthy, unhealthy, unknown
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Container {self.name}>"
