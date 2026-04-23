from fastapi import FastAPI, Depends, HTTPException, Request, Form, Response, UploadFile, File
from fastapi.responses import PlainTextResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session
from database import SessionLocal, engine
from models import Complaint as ComplaintModel
from schemas import ComplaintCreate, Complaint
import models
import os
import shutil
from pathlib import Path

models.Base.metadata.create_all(bind=engine)

app = FastAPI()

# Create uploads directory if it doesn't exist
UPLOAD_DIR = Path("static/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(SessionMiddleware, secret_key="your-secret-key-here-change-in-production")

templates = Jinja2Templates(directory="templates")

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    import traceback
    traceback.print_exc()
    return PlainTextResponse("Internal server error", status_code=500)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def classify_category(text: str) -> str:
    text_lower = text.lower()
    if "water" in text_lower:
        return "water"
    elif "electricity" in text_lower or "power" in text_lower:
        return "electricity"
    elif "internet" in text_lower or "wifi" in text_lower:
        return "internet"
    else:
        return "other"

def detect_urgency(text: str) -> str:
    text_lower = text.lower()
    if "urgent" in text_lower or "immediately" in text_lower:
        return "high"
    elif "soon" in text_lower:
        return "medium"
    else:
        return "low"

def assign_department(category: str) -> str:
    if category == "water":
        return "Water Department"
    elif category == "electricity":
        return "Electricity Department"
    elif category == "internet":
        return "IT Department"
    else:
        return "General Department"

def extract_entities(text: str) -> list:
    """Extract relevant entities from complaint text for AI display"""
    entities = []
    text_lower = text.lower()
    
    # Location-related entities
    locations = ["street", "road", "avenue", "lane", "block", "sector", "area", "neighborhood"]
    for loc in locations:
        if loc in text_lower:
            entities.append(loc.title())
            break
    
    # Time-related entities
    times = ["morning", "afternoon", "evening", "night", "week", "month", "day"]
    for time in times:
        if time in text_lower:
            entities.append(time.title())
            break
    
    # Issue severity indicators
    if "broken" in text_lower or "damaged" in text_lower:
        entities.append("Damage")
    if "leak" in text_lower or "leaking" in text_lower:
        entities.append("Leak")
    if "no power" in text_lower or "power outage" in text_lower:
        entities.append("Outage")
    if "slow" in text_lower or "intermittent" in text_lower:
        entities.append("Connectivity Issue")
    
    # Add some default entities if none found
    if not entities:
        entities = ["Infrastructure", "Public Service"]
    
    return entities[:4]  # Limit to 4 entities

@app.get("/")
def home(request: Request):
    return templates.TemplateResponse(request, "index.html", {"active_page": "home"})

@app.post("/submit")
def submit_complaint(request: Request, name: str = Form(...), text: str = Form(...), contact: str = Form(None), location: str = Form(None), image: UploadFile = File(None), db: Session = Depends(get_db)):
    # Combine contact, location, and text into the complaint text
    full_text = text
    if contact:
        full_text = f"Contact: {contact}\n\n{full_text}"
    if location:
        full_text = f"Location: {location}\n\n{full_text}"

    # Handle file upload
    image_path = None
    if image and image.filename:
        # Validate file type
        allowed_extensions = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
        file_extension = Path(image.filename).suffix.lower()

        if file_extension not in allowed_extensions:
            return templates.TemplateResponse(request, "index.html", {
                "error": "Invalid file type. Only image files are allowed.",
                "active_page": "home"
            })

        # Generate unique filename
        import uuid
        unique_filename = f"{uuid.uuid4()}{file_extension}"
        file_path = UPLOAD_DIR / unique_filename

        # Save file
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(image.file, buffer)

        image_path = f"uploads/{unique_filename}"

    complaint_data = ComplaintCreate(name=name, text=full_text)
    complaint = create_complaint(complaint_data, db)

    # Update complaint with image path if provided
    if image_path:
        complaint.image_path = image_path
        db.commit()

    # Extract entities for display
    entities = extract_entities(full_text)

    return templates.TemplateResponse(request, "success.html", {
        "complaint": complaint,
        "entities": entities
    })

@app.get("/track")
def track_form(request: Request, id: int = None, db: Session = Depends(get_db)):
    if id:
        complaint = db.query(ComplaintModel).filter(ComplaintModel.id == id).first()
        if complaint:
            entities = extract_entities(complaint.text)
            return templates.TemplateResponse(request, "track.html", {"complaint": complaint, "entities": entities, "active_page": "track"})
        else:
            return templates.TemplateResponse(request, "track.html", {"error": "Complaint not found", "active_page": "track"})
    return templates.TemplateResponse(request, "track.html", {"active_page": "track"})

@app.post("/track")
def track_complaint(request: Request, complaint_id: int = Form(...), db: Session = Depends(get_db)):
    complaint = db.query(ComplaintModel).filter(ComplaintModel.id == complaint_id).first()
    if complaint is None:
        return templates.TemplateResponse(request, "track.html", {"error": "Complaint not found", "active_page": "track"})
    entities = extract_entities(complaint.text)
    return templates.TemplateResponse(request, "track.html", {"complaint": complaint, "entities": entities, "active_page": "track"})

# Admin Authentication Routes
ADMIN_PASSWORD = "admin123"

@app.get("/admin/login")
def admin_login_page(request: Request):
    return templates.TemplateResponse(request, "login.html")

@app.post("/admin/login")
def admin_login(request: Request, password: str = Form(...)):
    if password == ADMIN_PASSWORD:
        request.session["admin_logged_in"] = True
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/admin", status_code=302)
    else:
        return templates.TemplateResponse(request, "login.html", {"error": "Invalid password"})

@app.get("/admin/logout")
def admin_logout(request: Request):
    request.session.clear()
    return templates.TemplateResponse(request, "login.html")

def require_admin_auth(request: Request):
    if not request.session.get("admin_logged_in", False):
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/admin/login", status_code=302)
    return None

@app.get("/admin")
def admin(request: Request, db: Session = Depends(get_db)):
    # Check authentication
    auth_check = require_admin_auth(request)
    if auth_check:
        return auth_check
    
    complaints = db.query(ComplaintModel).all()
    
    # Calculate category counts
    category_counts = {}
    for complaint in complaints:
        category = complaint.category
        category_counts[category] = category_counts.get(category, 0) + 1
    
    # Calculate urgency counts
    urgency_counts = {}
    for complaint in complaints:
        urgency = complaint.urgency
        urgency_counts[urgency] = urgency_counts.get(urgency, 0) + 1
    
    # Calculate status counts
    status_counts = {}
    for complaint in complaints:
        status = complaint.status
        status_counts[status] = status_counts.get(status, 0) + 1
    
    # Calculate daily intake for last 14 days
    from datetime import datetime, timedelta
    today = datetime.utcnow().date()
    daily_counts = []
    daily_labels = []
    
    for i in range(13, -1, -1):  # Last 14 days
        date = today - timedelta(days=i)
        count = sum(1 for c in complaints if c.timestamp.date() == date)
        daily_counts.append(count)
        daily_labels.append(date.strftime('%m/%d'))
    
    # Prepare chart data
    categories = list(category_counts.keys())
    counts = list(category_counts.values())
    urgencies = list(urgency_counts.keys())
    urgency_values = list(urgency_counts.values())
    
    complaint_entities = {complaint.id: extract_entities(complaint.text) for complaint in complaints}
    
    return templates.TemplateResponse(request, "admin.html", {
        "complaints": complaints,
        "active_page": "admin",
        "categories": categories,
        "counts": counts,
        "urgencies": urgencies,
        "urgency_values": urgency_values,
        "status_counts": status_counts,
        "daily_labels": daily_labels,
        "daily_counts": daily_counts,
        "complaint_entities": complaint_entities
    })

@app.post("/complaints/", response_model=Complaint)
def create_complaint(complaint: ComplaintCreate, db: Session = Depends(get_db)):
    category = classify_category(complaint.text)
    urgency = detect_urgency(complaint.text)
    department = assign_department(category)
    db_complaint = ComplaintModel(
        name=complaint.name,
        text=complaint.text,
        category=category,
        urgency=urgency,
        department=department
    )
    db.add(db_complaint)
    db.commit()
    db.refresh(db_complaint)
    return db_complaint

@app.post("/complaints", response_model=Complaint, include_in_schema=False)
def create_complaint_no_slash(complaint: ComplaintCreate, db: Session = Depends(get_db)):
    return create_complaint(complaint, db)

@app.get("/complaints/", response_model=list[Complaint])
def get_all_complaints(db: Session = Depends(get_db)):
    complaints = db.query(ComplaintModel).all()
    return complaints

@app.get("/complaints", response_model=list[Complaint], include_in_schema=False)
def get_all_complaints_no_slash(db: Session = Depends(get_db)):
    return get_all_complaints(db)

@app.get("/complaints/{complaint_id}", response_model=Complaint)
def get_complaint(complaint_id: int, db: Session = Depends(get_db)):
    complaint = db.query(ComplaintModel).filter(ComplaintModel.id == complaint_id).first()
    if complaint is None:
        raise HTTPException(status_code=404, detail="Complaint not found")
    return complaint

@app.put("/complaints/{complaint_id}/status")
def update_complaint_status(complaint_id: int, status: str, db: Session = Depends(get_db)):
    # Validate status
    allowed_statuses = ["pending", "in_progress", "resolved", "rejected"]
    if status not in allowed_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Allowed values: {', '.join(allowed_statuses)}")

    # Find complaint
    complaint = db.query(ComplaintModel).filter(ComplaintModel.id == complaint_id).first()
    if complaint is None:
        raise HTTPException(status_code=404, detail="Complaint not found")

    # Update status
    complaint.status = status
    db.commit()

    return {"message": "Status updated", "status": status}