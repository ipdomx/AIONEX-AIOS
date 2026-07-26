"""Project model."""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Text, Integer, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import relationship

from app.db.database import Base


class Project(Base):
    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    slug = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(20), default="planning")  # planning, active, paused, completed, archived
    priority = Column(String(20), default="medium")  # low, medium, high, critical
    progress = Column(Integer, default=0)  # 0-100
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    budget = Column(Numeric(15, 2), nullable=True)
    tags = Column(ARRAY(String), default=list)
    settings = Column(Text, nullable=True)  # JSON
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)

    workspace = relationship("Workspace", back_populates="projects")
    organization = relationship("Organization", back_populates="projects")
    owner = relationship("User")
    tasks = relationship("Task", back_populates="project")

    def __repr__(self):
        return f"<Project {self.name}>"
