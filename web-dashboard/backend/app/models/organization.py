"""Organization model."""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, Boolean, DateTime, Text, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.database import Base


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    slug = Column(String(255), nullable=False, unique=True, index=True)
    logo = Column(String(500), nullable=True)
    description = Column(Text, nullable=True)
    plan = Column(String(20), default="free")  # free, starter, pro, enterprise, custom
    status = Column(String(20), default="active")  # active, suspended, pending
    settings = Column(Text, nullable=True)  # JSON
    billing_email = Column(String(255), nullable=True)
    billing_address = Column(Text, nullable=True)
    tax_id = Column(String(100), nullable=True)
    member_count = Column(Integer, default=0)
    project_count = Column(Integer, default=0)
    agent_count = Column(Integer, default=0)
    max_users = Column(Integer, default=5)
    max_agents = Column(Integer, default=3)
    max_projects = Column(Integer, default=10)
    storage_limit_gb = Column(Integer, default=10)
    api_rate_limit = Column(Integer, default=1000)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)

    users = relationship("User", back_populates="organization")
    workspaces = relationship("Workspace", back_populates="organization")
    projects = relationship("Project", back_populates="organization")
    invoices = relationship("Invoice", back_populates="organization")

    def __repr__(self):
        return f"<Organization {self.name}>"
