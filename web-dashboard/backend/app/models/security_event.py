"""Security event model."""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Text, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.db.database import Base


class SecurityEvent(Base):
    __tablename__ = "security_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    type = Column(String(50), nullable=False)  # login, logout, failed_login, permission_change, data_access, api_call, suspicious, breach
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    ip_address = Column(String(45), nullable=False)
    user_agent = Column(String(500), nullable=True)
    resource = Column(String(255), nullable=False)
    action = Column(String(100), nullable=False)
    result = Column(String(20), nullable=False)  # success, failure, blocked
    risk_score = Column(Numeric(5, 2), default=0)
    details = Column(JSONB, nullable=True)
    geo_country = Column(String(100), nullable=True)
    geo_city = Column(String(100), nullable=True)
    geo_lat = Column(Numeric(10, 6), nullable=True)
    geo_lng = Column(Numeric(10, 6), nullable=True)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="security_events")

    def __repr__(self):
        return f"<SecurityEvent {self.type}>"
