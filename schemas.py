from pydantic import BaseModel, ConfigDict
from datetime import datetime

class ComplaintBase(BaseModel):
    name: str
    email: str | None = None
    text: str
    category: str
    urgency: str
    department: str

class ComplaintCreate(BaseModel):
    name: str
    text: str
    email: str | None = None

class Complaint(ComplaintBase):
    id: int
    status: str
    timestamp: datetime
    resolved_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
