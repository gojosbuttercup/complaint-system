from sqlalchemy import Column, Integer, String, DateTime
from database import Base
import datetime

class Complaint(Base):
    __tablename__ = "complaints"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    text = Column(String)
    category = Column(String)
    urgency = Column(String)
    department = Column(String)
    status = Column(String, default="pending")
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    image_path = Column(String, nullable=True)
    image_path = Column(String, nullable=True)