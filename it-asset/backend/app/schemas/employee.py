from pydantic import BaseModel
from datetime import date
from uuid import UUID


class EmployeeCreate(BaseModel):
    emp_no: str

    company: str | None = None
    location: str | None = None

    name: str

    department: str | None = None

    position: str | None = None
    rank: str | None = None

    email: str | None = None
    phone: str | None = None

    hire_date: date | None = None
    resign_date: date | None = None

    status: str = "ACTIVE"


class EmployeeResponse(BaseModel):
    id: UUID

    emp_no: str

    company: str | None = None
    location: str | None = None

    name: str

    department: str | None = None

    position: str | None = None
    rank: str | None = None

    email: str | None = None
    phone: str | None = None

    hire_date: date | None = None
    resign_date: date | None = None

    status: str

    class Config:
        from_attributes = True

class EmployeeUpdate(BaseModel):
    company: str | None = None
    location: str | None = None

    name: str | None = None
    department: str | None = None

    position: str | None = None
    rank: str | None = None

    email: str | None = None
    phone: str | None = None

    hire_date: date | None = None
    resign_date: date | None = None

    status: str | None = None
