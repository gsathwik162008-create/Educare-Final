import os
from sqlalchemy import inspect, text
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.database import engine, Base
from app.routes_auth import router as auth_router
from app.routes_students import router as students_router
from app.routes_analytics import router as analytics_router
from app.routes_interventions import router as interventions_router
from app.routes_admin import router as admin_router
from app.llm import router as llm_router


DEFAULT_CORS_ORIGINS = "http://localhost:8000,http://127.0.0.1:8000"
cors_origins = [
    origin.strip().rstrip("/")
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", DEFAULT_CORS_ORIGINS).split(",")
    if origin.strip()
]
if not cors_origins:
    cors_origins = DEFAULT_CORS_ORIGINS.split(",")
if "*" in cors_origins:
    raise RuntimeError("CORS_ALLOWED_ORIGINS must not contain the wildcard origin.")

# Ensure tables exist
Base.metadata.create_all(bind=engine)

intervention_columns = {
    column["name"] for column in inspect(engine).get_columns("intervention_actions")
}
with engine.begin() as connection:
    for column_name, column_type in (
        ("score_at_creation", "FLOAT"),
        ("score_at_completion", "FLOAT"),
        ("completed_at", "DATETIME")
    ):
        if column_name not in intervention_columns:
            connection.execute(text(
                f"ALTER TABLE intervention_actions ADD COLUMN {column_name} {column_type}"
            ))

app = FastAPI(
    title="EduCare - Student Success Platform",
    description="Student Success Platform for faculty, administrators and students",
    version="1.0.0"
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API Routers
app.include_router(auth_router)
app.include_router(students_router)
app.include_router(analytics_router)
app.include_router(interventions_router)
app.include_router(admin_router)
app.include_router(llm_router)

# Static directory setup
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(os.path.join(STATIC_DIR, "css"), exist_ok=True)
os.makedirs(os.path.join(STATIC_DIR, "js"), exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def serve_index():
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "Smart Campus Analytics API is running. Access /docs for API documentation."}


@app.get("/health")
def health_check():
    return {"status": "ok", "timestamp": "2026-10-10"}
