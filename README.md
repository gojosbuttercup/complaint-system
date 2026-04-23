# Complaint Management System

A FastAPI backend for managing complaints with AI-powered processing and modern web frontend.

## Features

- Submit a complaint (AI automatically classifies category, detects urgency, and assigns department)
- Get all complaints (admin)
- Track complaint by ID
- Modern, professional web interface with responsive design

## AI Processing

- **Category Classification**: Based on keywords in complaint text
  - water: mentions "water"
  - electricity: mentions "electricity" or "power"
  - internet: mentions "internet" or "wifi"
  - other: default

- **Urgency Detection**:
  - high: mentions "urgent" or "immediately"
  - medium: mentions "soon"
  - low: default

- **Department Assignment**:
  - water → Water Department
  - electricity → Electricity Department
  - internet → IT Department
  - other → General Department

## Setup

1. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

2. Run the server:
   ```
   uvicorn main:app --reload
   ```

3. Open http://127.0.0.1:8000 for the web interface.

## Web Interface

- **/** - Modern SaaS civic complaint filing page with:
  - Live ticker bar showing system status
  - Two-column layout (left: description & image, right: form)
  - Responsive form with name, contact, location, and description fields
  - AI-powered visual design language
- **/track** - Track complaint by ID (with colored status and urgency indicators)
- **/admin** - Admin dashboard with:
  - Statistics cards (Total, High Urgency, Resolved, Pending)
  - Bar chart showing complaints per category
  - Detailed complaints table

## UI Features

- Clean blue/white/gray color palette
- **Fixed top navigation bar** with dark background (#1e293b), white text, and active page highlighting
- **Professional dashboard layout** with centered content (max-width 900px), generous padding, and card-based design
- Card-style layouts with rounded corners and subtle box shadows
- Responsive design for different screen sizes
- Hover effects on buttons and navigation
- Colored badges for categories, urgency, and status:
  - **Categories**: Water (blue), Electricity (yellow), Internet (green), Other (gray)
  - **Urgency**: High (red), Medium (orange), Low (green)
  - **Status**: Pending (yellow), Resolved (green), In-progress (blue)
- Dashboard-style admin page with statistics cards
- Modern sans-serif fonts (Segoe UI) with improved typography and spacing

## API Endpoints

- POST /complaints/ - Submit a complaint (JSON API)
- GET /complaints/ - Get all complaints
- GET /complaints/{id} - Get complaint by ID
- POST /submit - Submit via web form
- GET /track - Track form
- POST /track - Track complaint
- GET /admin - Admin view