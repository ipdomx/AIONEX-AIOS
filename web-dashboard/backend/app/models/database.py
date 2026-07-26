"""Database model."""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Text, Integer, Numeric, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.database import Base


class Database(Base):
    __tablename__ = "databases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    type = Column(String(50), nullable=False)  # postgresql, mysql, mongodb, redis, elasticsearch, clickhouse
    host = Column(String(255), nullable=False)
    port = Column(Integer, nullable=False)
    database_name = Column(String(255), nullable=True)
    username = Column(String(255), nullable=True)
    password_encrypted = Column(Text, nullable=True)
    status = Column(String(20), default="disconnected")  # connected, disconnected, error
    size_mb = Column(Numeric(15, 2), default=0)
    connections = Column(Integer, default=0)
    queries_per_second = Column(Integer, default=0)
    slow_queries = Column(Integer, default=0)
    replication_lag_ms = Column(Integer, default=0)
    backup_status = Column(String(20), default="ok")  # ok, warning, error
    last_backup = Column(DateTime, nullable=True)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    server_id = Column(UUID(as_uuid=True), ForeignKey("servers.id"), nullable=True)
    ssl_enabled = Column(Boolean, default=True)
    config = Column(Text, nullable=True)  # JSON
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Database {self.name}>"
