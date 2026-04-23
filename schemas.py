from pydantic import BaseModel, ConfigDict
from datetime import datetime

class ComplaintBase(BaseModel):
    name: str
    text: str
    category: str
    urgency: str
    department: str

class ComplaintCreate(BaseModel):
    name: str
    text: str

class Complaint(ComplaintBase):
    id: int
    status: str
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)