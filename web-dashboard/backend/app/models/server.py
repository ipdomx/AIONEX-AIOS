"""Server model."""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Text, Integer, Numeric, BigInteger
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import relationship

from app.db.database import Base


class Server(Base):
    __tablename__ = "servers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    hostname = Column(String(255), nullable=False)
    ip = Column(String(45), nullable=False)
    status = Column(String(20), default="offline")  # online, offline, maintenance, warning
    os = Column(String(100), nullable=True)
    cpu_cores = Column(Integer, default=0)
    cpu_usage = Column(Numeric(5, 2), default=0)
    memory_total_gb = Column(Numeric(10, 2), default=0)
    memory_used_gb = Column(Numeric(10, 2), default=0)
    disk_total_gb = Column(Numeric(10, 2), default=0)
    disk_used_gb = Column(Numeric(10, 2), default=0)
    network_rx_mbps = Column(Numeric(10, 2), default=0)
    network_tx_mbps = Column(Numeric(10, 2), default=0)
    uptime_seconds = Column(BigInteger, default=0)
    location = Column(String(100), nullable=True)
    provider = Column(String(100), nullable=True)
    instance_type = Column(String(100), nullable=True)
    cost_per_hour = Column(Numeric(10, 4), default=0)
    tags = Column(ARRAY(String), default=list)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    ssh_key = Column(Text, nullable=True)
    monitoring_enabled = Column(String(20), default="yes")
    config = Column(Text, nullable=True)  # JSON
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Server {self.name}>"
