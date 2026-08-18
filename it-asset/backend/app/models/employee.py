from sqlalchemy import Column, String, Date, TIMESTAMP
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID
import uuid

from app.db.base import Base


class Employee(Base):
    __tablename__ = "employees"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    emp_no = Column(String(20), unique=True, nullable=False)

    company = Column(String(100))
    location = Column(String(100))

    name = Column(String(100), nullable=False)

    department = Column(String(100))

    position = Column(String(100))
    rank = Column(String(100))

    email = Column(String(255))
    phone = Column(String(50))

    hire_date = Column(Date)
    resign_date = Column(Date)

    status = Column(String(20), default="ACTIVE")

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
