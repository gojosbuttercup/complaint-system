from pathlib import Path
from contextlib import asynccontextmanager

from dotenv import load_dotenv

# Load .env from project root before app reads os.environ (SMTP, SESSION_SECRET, etc.)
load_dotenv(Path(__file__).resolve().parent / ".env")

from datetime import datetime
import io
import traceback
from fastapi import FastAPI, Depends, HTTPException, Request, Form, UploadFile, File
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session
from database import SessionLocal, engine
from models import AdminUser, Complaint as ComplaintModel
from schemas import ComplaintCreate, Complaint
from services.ai_service import DEPARTMENT_BY_CATEGORY, ai_classifier, classify_category_keywords, detect_urgency_keywords
from services.analytics_service import build_dashboard_data
from services.email_service import send_complaint_email
from services.report_service import PDFReportError, build_complaints_pdf
from utils.security import hash_password, verify_password
from utils.validators import is_valid_email
import models
import os
import shutil

models.Base.metadata.create_all(bind=engine)


def ensure_database_columns():
    # Lightweight SQLite migrations for existing local installs.
    with engine.begin() as connection:
        complaint_columns = {row[1] for row in connection.execute(sql_text("PRAGMA table_info(complaints)"))}
        if "email" not in complaint_columns:
            connection.execute(sql_text("ALTER TABLE complaints ADD COLUMN email VARCHAR"))
        if "resolved_at" not in complaint_columns:
            connection.execute(sql_text("ALTER TABLE complaints ADD COLUMN resolved_at DATETIME"))


ensure_database_columns()


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    from services.email_service import log_smtp_configuration

    log_smtp_configuration()
    yield


app = FastAPI(lifespan=app_lifespan)

SUPER_ADMIN = "super_admin"
DEPARTMENT_ADMIN = "department_admin"

DEPARTMENTS = [
    "Water Department",
    "Electricity Department",
    "Internet Department",
    "Roads Department",
    "Sanitation Department",
    "Public Safety Department",
    "Waste Management Department",
]

DEFAULT_ADMIN_ACCOUNTS = [
    {"username": "superadmin", "password": "admin123", "role": SUPER_ADMIN, "department": None},
    {"username": "wateradmin", "password": "water123", "role": DEPARTMENT_ADMIN, "department": "Water Department"},
    {"username": "electricadmin", "password": "electric123", "role": DEPARTMENT_ADMIN, "department": "Electricity Department"},
    {"username": "internetadmin", "password": "internet123", "role": DEPARTMENT_ADMIN, "department": "Internet Department"},
    {"username": "roadsadmin", "password": "roads123", "role": DEPARTMENT_ADMIN, "department": "Roads Department"},
    {"username": "sanitationadmin", "password": "sanitation123", "role": DEPARTMENT_ADMIN, "department": "Sanitation Department"},
    {"username": "safetyadmin", "password": "safety123", "role": DEPARTMENT_ADMIN, "department": "Public Safety Department"},
    {"username": "wasteadmin", "password": "waste123", "role": DEPARTMENT_ADMIN, "department": "Waste Management Department"},
]

# Create uploads directories if they do not exist.
UPLOAD_DIR = Path("static/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
PUBLIC_UPLOAD_DIR = Path("uploads")
PUBLIC_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", "your-secret-key-here-change-in-production"),
    max_age=60 * 60 * 8,
)

templates = Jinja2Templates(directory="templates")

def seed_default_admins():
    db = SessionLocal()
    try:
        for account in DEFAULT_ADMIN_ACCOUNTS:
            user = db.query(AdminUser).filter(AdminUser.username == account["username"]).first()
            if user is None:
                db.add(AdminUser(
                    username=account["username"],
                    password=hash_password(account["password"]),
                    role=account["role"],
                    department=account["department"],
                ))
            elif not user.password.startswith("pbkdf2_sha256$") and verify_password(account["password"], user.password):
                user.password = hash_password(account["password"])

        legacy_department_map = {
            "IT Department": "Internet Department",
            "General Department": "Roads Department",
        }
        for old_department, new_department in legacy_department_map.items():
            db.query(ComplaintModel).filter(
                ComplaintModel.department == old_department
            ).update({ComplaintModel.department: new_department})

        db.commit()
    finally:
        db.close()

seed_default_admins()

def get_current_admin(request: Request, db: Session):
    login_at = request.session.get("login_at")
    if login_at and datetime.utcnow().timestamp() - login_at > 60 * 60 * 8:
        request.session.clear()
        return None

    username = request.session.get("username")
    if not username:
        return None
    return db.query(AdminUser).filter(AdminUser.username == username).first()

def is_super_admin(user: AdminUser) -> bool:
    return user.role == SUPER_ADMIN

def complaint_query_for_user(db: Session, user: AdminUser):
    query = db.query(ComplaintModel)
    if is_super_admin(user):
        return query
    return query.filter(ComplaintModel.department == user.department)

def require_admin_user(request: Request, db: Session):
    user = get_current_admin(request, db)
    if user is None:
        return None, RedirectResponse(url="/login", status_code=302)
    return user, None

def require_complaint_access(complaint: ComplaintModel, user: AdminUser):
    if complaint is None:
        raise HTTPException(status_code=404, detail="Complaint not found")
    if not is_super_admin(user) and complaint.department != user.department:
        raise HTTPException(status_code=403, detail="You cannot access complaints from another department")

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    traceback.print_exc()
    return PlainTextResponse(f"Internal server error:\n{exc}", status_code=500)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def classify_category(text: str) -> str:
    return classify_category_keywords(text)

def detect_urgency(text: str) -> str:
    return detect_urgency_keywords(text)

def assign_department(category: str) -> str:
    return DEPARTMENT_BY_CATEGORY.get(category, "Public Safety Department")

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
def submit_complaint(request: Request, name: str = Form(...), text: str = Form(...), email: str = Form(...), location: str = Form(None), image: UploadFile = File(None), db: Session = Depends(get_db)):
    email = email.strip()
    if not is_valid_email(email):
        return templates.TemplateResponse(request, "index.html", {
            "error": "Please enter a valid email address.",
            "active_page": "home"
        })

    # Combine contact, location, and text into the complaint text
    full_text = text
    if email:
        full_text = f"Contact: {email}\n\n{full_text}"
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
        shutil.copyfile(file_path, PUBLIC_UPLOAD_DIR / unique_filename)

        image_path = f"uploads/{unique_filename}"

    complaint_data = ComplaintCreate(name=name, text=full_text, email=email)
    complaint = create_complaint(complaint_data, db)

    # Update complaint with image path if provided
    if image_path:
        complaint.image_path = image_path
        db.commit()

    try:
        send_complaint_email(email, "CIVITAS complaint submitted", complaint, request)
    except Exception:
        traceback.print_exc()

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
@app.get("/login")
def login_page(request: Request):
    if request.session.get("username"):
        return RedirectResponse(url="/admin", status_code=302)
    return templates.TemplateResponse(request, "login.html")

@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(AdminUser).filter(AdminUser.username == username.strip()).first()
    if user and verify_password(password, user.password):
        if not user.password.startswith("pbkdf2_sha256$"):
            user.password = hash_password(password)
            db.commit()
        request.session.clear()
        request.session["user_id"] = user.id
        request.session["username"] = user.username
        request.session["role"] = user.role
        request.session["department"] = user.department
        request.session["login_at"] = datetime.utcnow().timestamp()
        return RedirectResponse(url="/admin", status_code=302)

    return templates.TemplateResponse(request, "login.html", {"error": "Invalid username or password"})

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)

@app.get("/admin/login")
def admin_login_page(request: Request):
    return RedirectResponse(url="/login", status_code=302)

@app.post("/admin/login")
def admin_login_alias(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    return login(request, username, password, db)

@app.get("/admin/logout")
def admin_logout(request: Request):
    return logout(request)

@app.get("/admin")
def admin(request: Request, db: Session = Depends(get_db)):
    current_user, auth_redirect = require_admin_user(request, db)
    if auth_redirect:
        return auth_redirect
    
    complaints = complaint_query_for_user(db, current_user).order_by(ComplaintModel.timestamp.desc()).all()
    analytics = build_dashboard_data(complaints, DEPARTMENTS)
    
    complaint_entities = {complaint.id: extract_entities(complaint.text) for complaint in complaints}
    
    return templates.TemplateResponse(request, "admin.html", {
        "complaints": complaints,
        "active_page": "admin",
        "categories": list(analytics["category_counts"].keys()),
        "counts": list(analytics["category_counts"].values()),
        "urgencies": list(analytics["urgency_counts"].keys()),
        "urgency_values": list(analytics["urgency_counts"].values()),
        "status_counts": analytics["status_counts"],
        "daily_labels": analytics["daily_labels"],
        "daily_counts": analytics["daily_counts"],
        "avg_resolution_hours": analytics["avg_resolution_hours"],
        "department_chart_labels": list(analytics["department_counts"].keys()),
        "department_chart_values": list(analytics["department_counts"].values()),
        "resolved_vs_pending": analytics["resolved_vs_pending"],
        "complaint_entities": complaint_entities,
        "current_user": current_user,
        "is_super_admin": is_super_admin(current_user),
        "departments": DEPARTMENTS,
        "department_counts": analytics["department_counts"]
    })


def serialize_complaint(complaint: ComplaintModel):
    return {
        "id": complaint.id,
        "name": complaint.name,
        "email": complaint.email or "",
        "category": complaint.category,
        "urgency": complaint.urgency,
        "status": complaint.status,
        "department": complaint.department,
        "filedDate": complaint.timestamp.strftime("%B %d, %Y at %I:%M %p"),
        "filedShort": complaint.timestamp.strftime("%m/%d/%y"),
        "description": complaint.text,
        "imagePath": complaint.image_path or "",
        "entities": extract_entities(complaint.text),
    }


def dashboard_payload(complaints):
    analytics = build_dashboard_data(complaints, DEPARTMENTS)
    return {
        "complaints": [serialize_complaint(complaint) for complaint in complaints],
        "stats": {
            "total": len(complaints),
            "pending": analytics["status_counts"].get("pending", 0),
            "in_progress": analytics["status_counts"].get("in_progress", 0),
            "resolved": analytics["status_counts"].get("resolved", 0),
            "rejected": analytics["status_counts"].get("rejected", 0),
            "avg_resolution_hours": analytics["avg_resolution_hours"],
        },
        "charts": {
            "categories": list(analytics["category_counts"].keys()),
            "category_counts": list(analytics["category_counts"].values()),
            "urgencies": list(analytics["urgency_counts"].keys()),
            "urgency_values": list(analytics["urgency_counts"].values()),
            "daily_labels": analytics["daily_labels"],
            "daily_counts": analytics["daily_counts"],
            "department_labels": list(analytics["department_counts"].keys()),
            "department_values": list(analytics["department_counts"].values()),
            "status_labels": ["Resolved", "Open"],
            "status_values": [analytics["resolved_vs_pending"]["resolved"], analytics["resolved_vs_pending"]["pending"]],
        },
        "department_counts": analytics["department_counts"],
    }


@app.get("/admin/data")
def admin_data(request: Request, db: Session = Depends(get_db)):
    current_user, auth_redirect = require_admin_user(request, db)
    if auth_redirect:
        raise HTTPException(status_code=401, detail="Authentication required")
    complaints = complaint_query_for_user(db, current_user).order_by(ComplaintModel.timestamp.desc()).all()
    return JSONResponse(dashboard_payload(complaints))


@app.get("/admin/report.pdf")
def admin_report_pdf(
    request: Request,
    category: str = "",
    urgency: str = "",
    status: str = "",
    department: str = "",
    search: str = "",
    db: Session = Depends(get_db),
):
    current_user, auth_redirect = require_admin_user(request, db)
    if auth_redirect:
        return auth_redirect

    complaints = complaint_query_for_user(db, current_user).order_by(ComplaintModel.timestamp.desc()).all()
    filtered = []
    for complaint in complaints:
        row_text = f"{complaint.id} {complaint.name} {complaint.email or ''} {complaint.text} {complaint.department}".lower()
        if category and complaint.category != category:
            continue
        if urgency and complaint.urgency != urgency:
            continue
        if status and complaint.status != status:
            continue
        if department and is_super_admin(current_user) and complaint.department != department:
            continue
        if search and search.lower() not in row_text:
            continue
        filtered.append(complaint)

    try:
        pdf_buffer = build_complaints_pdf(filtered, DEPARTMENTS)
        pdf_buffer.seek(0, io.SEEK_END)
        content_length = pdf_buffer.tell()
        pdf_buffer.seek(0)
    except PDFReportError as exc:
        traceback.print_exc()
        return PlainTextResponse(f"PDF export failed:\n{exc}", status_code=500)
    except Exception as exc:
        tb = traceback.format_exc()
        traceback.print_exc()
        return PlainTextResponse(
            f"PDF export failed with an unexpected error:\n{exc}\n\nTraceback:\n{tb}",
            status_code=500,
        )

    def pdf_chunks():
        while True:
            chunk = pdf_buffer.read(65536)
            if not chunk:
                break
            yield chunk

    return StreamingResponse(
        pdf_chunks(),
        media_type="application/pdf",
        headers={
            "Content-Disposition": "attachment; filename=civitas-complaints-report.pdf",
            "Content-Length": str(content_length),
        },
    )

@app.post("/complaints/", response_model=Complaint)
def create_complaint(complaint: ComplaintCreate, db: Session = Depends(get_db)):
    classification = ai_classifier.classify(complaint.text)
    db_complaint = ComplaintModel(
        name=complaint.name,
        email=complaint.email,
        text=complaint.text,
        category=classification.category,
        urgency=classification.urgency,
        department=classification.department
    )
    db.add(db_complaint)
    db.commit()
    db.refresh(db_complaint)
    return db_complaint

@app.post("/complaints", response_model=Complaint, include_in_schema=False)
def create_complaint_no_slash(complaint: ComplaintCreate, db: Session = Depends(get_db)):
    return create_complaint(complaint, db)

@app.get("/complaints/", response_model=list[Complaint])
def get_all_complaints(request: Request, db: Session = Depends(get_db)):
    current_user, auth_redirect = require_admin_user(request, db)
    if auth_redirect:
        raise HTTPException(status_code=401, detail="Authentication required")
    complaints = complaint_query_for_user(db, current_user).all()
    return complaints

@app.get("/complaints", response_model=list[Complaint], include_in_schema=False)
def get_all_complaints_no_slash(request: Request, db: Session = Depends(get_db)):
    return get_all_complaints(request, db)

@app.get("/complaints/{complaint_id}", response_model=Complaint)
def get_complaint(request: Request, complaint_id: int, db: Session = Depends(get_db)):
    complaint = db.query(ComplaintModel).filter(ComplaintModel.id == complaint_id).first()
    if complaint is None:
        raise HTTPException(status_code=404, detail="Complaint not found")
    current_user = get_current_admin(request, db)
    if current_user is not None:
        require_complaint_access(complaint, current_user)
    return complaint

@app.put("/complaints/{complaint_id}/status")
def update_complaint_status(request: Request, complaint_id: int, status: str, db: Session = Depends(get_db)):
    current_user, auth_redirect = require_admin_user(request, db)
    if auth_redirect:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Validate status
    allowed_statuses = ["pending", "in_progress", "resolved", "rejected"]
    if status not in allowed_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Allowed values: {', '.join(allowed_statuses)}")

    # Find complaint
    complaint = db.query(ComplaintModel).filter(ComplaintModel.id == complaint_id).first()
    require_complaint_access(complaint, current_user)

    # Update status
    complaint.status = status
    complaint.resolved_at = datetime.utcnow() if status == "resolved" else None
    db.commit()
    db.refresh(complaint)  # Ensure we have the latest data in memory

    try:
        send_complaint_email(
            complaint.email,
            "CIVITAS complaint resolved" if status == "resolved" else "CIVITAS complaint status updated",
            complaint,
            request,
        )
    except Exception:
        traceback.print_exc()

    return {"message": "Status updated", "status": status, "id": complaint.id}
