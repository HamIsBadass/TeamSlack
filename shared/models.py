"""
Database models using SQLAlchemy 2.0.

Defines all tables for request lifecycle, steps, approvals, audit logs, and user profiles.
"""

from datetime import datetime
from enum import Enum
from uuid import uuid4

from sqlalchemy import Column, DateTime, Enum as SQLEnum, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


# ============ Enums ============

class RequestStatus(str, Enum):
    """Defines request lifecycle states."""
    RECEIVED = "RECEIVED"
    PARSING = "PARSING"
    MEETING_DONE = "MEETING_DONE"
    JIRA_DRAFTED = "JIRA_DRAFTED"
    REVIEW_DONE = "REVIEW_DONE"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    APPROVED = "APPROVED"
    CANCELED = "CANCELED"
    DONE = "DONE"
    FAILED = "FAILED"


class StepStatus(str, Enum):
    """Defines step execution states."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class StepName(str, Enum):
    """Defines available step names."""
    PARSING = "PARSING"
    MEETING_DONE = "MEETING_DONE"
    JIRA_DRAFTED = "JIRA_DRAFTED"
    REVIEW_DONE = "REVIEW_DONE"


class LogLevel(str, Enum):
    """Defines audit log levels."""
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    APPROVAL = "APPROVAL"
    DONE = "DONE"


class ApprovalAction(str, Enum):
    """Defines approval actions."""
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELED = "CANCELED"


class PersonaStyle(str, Enum):
    """Defines user persona styles."""
    PM = "pm"
    DEVELOPER = "developer"
    DESIGNER = "designer"
    CONCISE = "concise"


class OutputFormat(str, Enum):
    """Defines output formats."""
    MARKDOWN = "markdown"
    BULLET_LIST = "bullet_list"
    JSON = "json"


class KeyMode(str, Enum):
    """Defines LLM key management modes."""
    SHARED = "shared"
    BYOK = "byok"


# ============ Models ============

class Request(Base):
    """Main request record."""
    __tablename__ = "requests"

    request_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(String(20), nullable=False, index=True)
    tenant_id = Column(String(100), nullable=False)
    trace_id = Column(UUID(as_uuid=True), nullable=False)
    status = Column(SQLEnum(RequestStatus), nullable=False, default=RequestStatus.RECEIVED, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)

    # Relationships
    steps = relationship("RequestStep", back_populates="request", cascade="all, delete-orphan")
    approvals = relationship("Approval", back_populates="request", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="request", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Request {self.request_id} user={self.user_id} status={self.status}>"


class RequestStep(Base):
    """Per-step execution log."""
    __tablename__ = "request_steps"

    step_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    request_id = Column(UUID(as_uuid=True), ForeignKey("requests.request_id"), nullable=False, index=True)
    step_name = Column(SQLEnum(StepName), nullable=False)
    status = Column(SQLEnum(StepStatus), nullable=False, default=StepStatus.PENDING)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)

    # Relationships
    request = relationship("Request", back_populates="steps")

    def __repr__(self):
        return f"<RequestStep {self.step_name} status={self.status}>"


class Approval(Base):
    """Approval records."""
    __tablename__ = "approvals"

    approval_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    request_id = Column(UUID(as_uuid=True), ForeignKey("requests.request_id"), nullable=False, index=True)
    requested_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    approved_by = Column(String(20), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    action = Column(SQLEnum(ApprovalAction), nullable=False)

    # Relationships
    request = relationship("Request", back_populates="approvals")

    def __repr__(self):
        return f"<Approval request_id={self.request_id} action={self.action}>"


class AuditLog(Base):
    """Audit trail for all events."""
    __tablename__ = "audit_logs"

    log_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    request_id = Column(UUID(as_uuid=True), ForeignKey("requests.request_id"), nullable=False, index=True)
    step_id = Column(UUID(as_uuid=True), ForeignKey("request_steps.step_id"), nullable=True)
    level = Column(SQLEnum(LogLevel), nullable=False, index=True)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    # Relationships
    request = relationship("Request", back_populates="audit_logs")

    def __repr__(self):
        return f"<AuditLog {self.level} {self.message[:30]}...>"


class UserProfile(Base):
    """User personalization and key management."""
    __tablename__ = "user_profiles"

    user_id = Column(String(20), primary_key=True)
    tenant_id = Column(String(100), nullable=False)
    display_name = Column(String(100), nullable=False)
    persona_style = Column(SQLEnum(PersonaStyle), nullable=False, default=PersonaStyle.CONCISE)
    output_format = Column(SQLEnum(OutputFormat), nullable=False, default=OutputFormat.MARKDOWN)
    job_role = Column(String(50), nullable=True)
    key_mode = Column(SQLEnum(KeyMode), nullable=False, default=KeyMode.SHARED)
    secret_ref = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<UserProfile {self.user_id} style={self.persona_style}>"


# ============ Database initialization ============

def init_db(database_url: str):
    """
    Initialize database and create all tables.
    
    Args:
        database_url: PostgreSQL URL (e.g., postgresql://user:pass@localhost/db)
    """
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    print(f"Database initialized at {database_url}")
    return engine
    _engine = None
    _SessionLocal = None


def init_db(database_url: str):
    """
    Initialize database and create all tables.
    
    Args:
        database_url: PostgreSQL URL (e.g., postgresql://user:pass@localhost/db)
    
    Returns:
        SQLAlchemy engine instance
    """
    global _engine, _SessionLocal
    
    from sqlalchemy.orm import sessionmaker
    
    _engine = create_engine(database_url, echo=False)
    Base.metadata.create_all(_engine)
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    
    print(f"✓ Database initialized: {database_url}")
    return _engine


def get_db_session():
    """
    Get a database session (for manual usage).
    
    Returns:
        SQLAlchemy session
    """
    if _SessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_db() first")
    return _SessionLocal()


if __name__ == "__main__":
    # Example usage (requires DATABASE_URL env var or hard-coded URL)
    import os
    
    db_url = os.getenv("DATABASE_URL", "postgresql://user:password@localhost/teamslack")
    init_db(db_url)
    
    # Test session
    session = get_db_session()
    print("✓ Database session created successfully")
    session.close()
