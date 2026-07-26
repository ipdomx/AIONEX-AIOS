"""Role model."""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, Boolean, DateTime, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.database import Base


class Role(Base):
    __tablename__ = "roles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False, unique=True)
    slug = Column(String(100), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    level = Column(Integer, default=0)  # Higher = more permissions
    is_custom = Column(Boolean, default=False)
    is_system = Column(Boolean, default=False)
    permissions = relationship("Permission", secondary="role_permissions", back_populates="roles")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    users = relationship("User", back_populates="role")

    def __repr__(self):
        return f"<Role {self.name}>"
