import io
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models import (
    User,
    ScoreSettings,
    CleaningLog,
    Student,
    StudentAccountRequest,
    StudentScore,
)
from app.auth import get_current_user, require_role
from app.ingestion import ingest_seven_sources, CSV_TEMPLATES
from app.analytics_pipeline import run_full_analytics_pipeline
from app import ml
from app.ml import get_model_metrics

router = APIRouter(prefix="/api/admin", tags=["admin"])
MAX_CSV_FILE_BYTES = 8 * 1024 * 1024
MAX_CSV_REQUEST_BYTES = 20 * 1024 * 1024


async def _read_upload_limited(upload: UploadFile, remaining_bytes: int) -> bytes:
    content = bytearray()
    while True:
        chunk = await upload.read(min(64 * 1024, remaining_bytes - len(content) + 1))
        if not chunk:
            return bytes(content)
        content.extend(chunk)
        if len(content) > min(MAX_CSV_FILE_BYTES, remaining_bytes):
            raise HTTPException(
                status_code=413,
                detail="CSV uploads are limited to 8 MB per file and 20 MB per request.",
            )


def _run_pipeline_and_commit(db: Session) -> Dict[str, Any]:
    previous_model_state = ml.snapshot_model_state()
    try:
        result = run_full_analytics_pipeline(db, persist_model_cache=False)
        db.commit()
    except Exception:
        db.rollback()
        ml.restore_model_state(previous_model_state)
        raise

    try:
        ml.persist_trained_model()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Analytics were saved, but the model cache could not be updated.",
        ) from exc
    return result


class SettingsUpdate(BaseModel):
    weight_academic: float = Field(..., ge=0, le=100)
    weight_attendance: float = Field(..., ge=0, le=100)
    weight_placement: float = Field(..., ge=0, le=100)
    weight_lms: float = Field(..., ge=0, le=100)
    weight_skills: float = Field(..., ge=0, le=100)
    threshold_academic_cgpa: float = Field(..., ge=0, le=10)
    threshold_attendance_pct: float = Field(..., ge=0, le=100)
    threshold_coding_score: float = Field(..., ge=0, le=100)


@router.get("/account-requests")
def list_student_account_requests(
    current_user: User = Depends(require_role(["ADMIN"])),
    db: Session = Depends(get_db),
):
    requests = db.query(StudentAccountRequest).filter(
        StudentAccountRequest.status == "pending"
    ).order_by(StudentAccountRequest.created_at.asc()).all()
    students = {
        student.student_id: student
        for student in db.query(Student).filter(
            Student.student_id.in_([request.student_id for request in requests])
        ).all()
    }
    return {
        "requests": [
            {
                "id": request.id,
                "student_id": request.student_id,
                "student_name": students[request.student_id].name,
                "department": students[request.student_id].department,
                "created_at": request.created_at.isoformat() if request.created_at else None,
            }
            for request in requests
            if request.student_id in students
        ]
    }


@router.post("/account-requests/{request_id}/approve")
def approve_student_account_request(
    request_id: int,
    current_user: User = Depends(require_role(["ADMIN"])),
    db: Session = Depends(get_db),
):
    account_request = db.query(StudentAccountRequest).filter(
        StudentAccountRequest.id == request_id,
        StudentAccountRequest.status == "pending",
    ).first()
    if not account_request:
        raise HTTPException(status_code=404, detail="Pending account request not found.")
    if db.query(User.id).filter(
        (User.username == account_request.student_id)
        | (User.student_id == account_request.student_id)
    ).first():
        raise HTTPException(status_code=409, detail="An account already exists for this student.")

    db.add(User(
        username=account_request.student_id,
        hashed_password=account_request.hashed_password,
        role="STUDENT",
        student_id=account_request.student_id,
    ))
    account_request.status = "approved"
    account_request.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "approved", "student_id": account_request.student_id}


@router.post("/account-requests/{request_id}/reject")
def reject_student_account_request(
    request_id: int,
    current_user: User = Depends(require_role(["ADMIN"])),
    db: Session = Depends(get_db),
):
    account_request = db.query(StudentAccountRequest).filter(
        StudentAccountRequest.id == request_id,
        StudentAccountRequest.status == "pending",
    ).first()
    if not account_request:
        raise HTTPException(status_code=404, detail="Pending account request not found.")
    account_request.status = "rejected"
    account_request.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "rejected"}


@router.get("/settings")
def get_score_settings(
    current_user: User = Depends(require_role(["ADMIN"])),
    db: Session = Depends(get_db)
):
    """Retrieve scoring weights and risk thresholds."""
    settings = db.query(ScoreSettings).filter(ScoreSettings.key == "default").first()
    if not settings:
        settings = ScoreSettings(key="default")
        db.add(settings)
        db.commit()

    return {
        "weight_academic": settings.weight_academic,
        "weight_attendance": settings.weight_attendance,
        "weight_placement": settings.weight_placement,
        "weight_lms": settings.weight_lms,
        "weight_skills": settings.weight_skills,
        "threshold_academic_cgpa": settings.threshold_academic_cgpa,
        "threshold_attendance_pct": settings.threshold_attendance_pct,
        "threshold_coding_score": settings.threshold_coding_score,
        "updated_at": settings.updated_at.isoformat() if settings.updated_at else None
    }


@router.post("/settings")
def update_score_settings(
    payload: SettingsUpdate,
    current_user: User = Depends(require_role(["ADMIN"])),
    db: Session = Depends(get_db)
):
    """Update weights and thresholds; validates that weights sum to 100% and recomputes all scores."""
    total_weights = (
        payload.weight_academic +
        payload.weight_attendance +
        payload.weight_placement +
        payload.weight_lms +
        payload.weight_skills
    )
    if abs(total_weights - 100.0) > 0.05:
        raise HTTPException(
            status_code=400,
            detail=f"Score weights must sum to exactly 100%. Current sum: {total_weights:.1f}%"
        )

    settings = db.query(ScoreSettings).filter(ScoreSettings.key == "default").first()
    if not settings:
        settings = ScoreSettings(key="default")
        db.add(settings)

    settings.weight_academic = payload.weight_academic
    settings.weight_attendance = payload.weight_attendance
    settings.weight_placement = payload.weight_placement
    settings.weight_lms = payload.weight_lms
    settings.weight_skills = payload.weight_skills
    settings.threshold_academic_cgpa = payload.threshold_academic_cgpa
    settings.threshold_attendance_pct = payload.threshold_attendance_pct
    settings.threshold_coding_score = payload.threshold_coding_score
    settings.updated_at = datetime.now(timezone.utc)
    # Recompute analytics pipeline with new weights
    pipeline_res = _run_pipeline_and_commit(db)

    return {
        "status": "success",
        "message": "Weights updated and pipeline successfully recomputed",
        "pipeline_result": pipeline_res
    }


@router.post("/recompute")
def trigger_recompute(
    current_user: User = Depends(require_role(["ADMIN"])),
    db: Session = Depends(get_db)
):
    """Admin trigger to recompute all scoring, risk flags, ML predictions, and interventions."""
    result = _run_pipeline_and_commit(db)
    return {"status": "success", "result": result}


@router.post("/upload")
async def upload_csv_files(
    academic: Optional[UploadFile] = File(None),
    attendance: Optional[UploadFile] = File(None),
    lms: Optional[UploadFile] = File(None),
    engagement: Optional[UploadFile] = File(None),
    placement: Optional[UploadFile] = File(None),
    skills: Optional[UploadFile] = File(None),
    feedback: Optional[UploadFile] = File(None),
    import_mode: str = Form("partial"),
    current_user: User = Depends(require_role(["ADMIN"])),
    db: Session = Depends(get_db)
):
    """
    Screen 8: Ingestion upload endpoint for any combination of the 7 CSV files.
    Performs validation, cleaning, deduplication, logging, and pipeline recompute.
    """
    file_map = {
        "academic": academic,
        "attendance": attendance,
        "lms": lms,
        "engagement": engagement,
        "placement": placement,
        "skills": skills,
        "feedback": feedback
    }

    uploaded_dfs = {}
    total_bytes = 0
    for name, f in file_map.items():
        if f is not None and f.filename:
            content = await _read_upload_limited(f, MAX_CSV_REQUEST_BYTES - total_bytes)
            total_bytes += len(content)
            if content:
                try:
                    df = pd.read_csv(
                        io.BytesIO(content),
                        dtype=str,
                        keep_default_na=False,
                        encoding="utf-8-sig",
                        on_bad_lines="error",
                    )
                    uploaded_dfs[name] = df
                except (pd.errors.ParserError, UnicodeDecodeError, ValueError) as exc:
                    raise HTTPException(
                        status_code=400,
                        detail=f"CSV file for '{name}' is malformed: {exc}",
                    ) from exc

    if not uploaded_dfs:
        raise HTTPException(status_code=400, detail="Please upload at least one valid CSV file.")

    res = ingest_seven_sources(uploaded_dfs, db, import_mode=import_mode)
    if res.get("status") == "error":
        raise HTTPException(
            status_code=400,
            detail={"message": res.get("message"), "errors": res.get("errors"), "counts": {
                "accepted_rows": res.get("accepted_rows", 0),
                "rejected_rows": res.get("rejected_rows", 0),
                "duplicate_rows": res.get("duplicate_rows", 0),
                "updated_rows": 0,
            }},
        )

    # Automatically recompute analytics
    pipeline_res = _run_pipeline_and_commit(db)

    return {
        "status": "success",
        "ingestion_summary": res,
        "pipeline_summary": pipeline_res
    }


@router.get("/quality-log")
def get_data_quality_log(
    current_user: User = Depends(require_role(["ADMIN"])),
    db: Session = Depends(get_db)
):
    """Screen 8: Data Quality Screen showing issues grouped by type, before/after counts, and detailed log."""
    logs = db.query(CleaningLog).order_by(CleaningLog.timestamp.desc()).all()

    issue_counts = {}
    source_counts = {}
    for l in logs:
        issue_counts[l.issue_type] = issue_counts.get(l.issue_type, 0) + 1
        source_counts[l.source_file] = source_counts.get(l.source_file, 0) + 1

    issue_breakdown = [
        {"issue_type": k, "count": v}
        for k, v in sorted(issue_counts.items(), key=lambda x: x[1], reverse=True)
    ]

    source_breakdown = [
        {"source_file": k, "count": v}
        for k, v in sorted(source_counts.items(), key=lambda x: x[1], reverse=True)
    ]

    recent_entries = [
        {
            "id": l.id,
            "timestamp": l.timestamp.isoformat() if l.timestamp else None,
            "source_file": l.source_file,
            "row_number": l.row_number,
            "student_id": l.student_id,
            "field_name": l.field_name,
            "issue_type": l.issue_type,
            "original_value": l.original_value,
            "cleaned_value": l.cleaned_value,
            "rule_applied": l.rule_applied
        }
        for l in logs[:100]
    ]

    return {
        "total_anomalies_cleaned": len(logs),
        "issue_breakdown": issue_breakdown,
        "source_breakdown": source_breakdown,
        "recent_logs": recent_entries
    }


@router.get("/templates/{source_name}")
def download_csv_template(
    source_name: str,
    current_user: User = Depends(require_role(["ADMIN"]))
):
    """Download standardized CSV template for any of the 7 sources."""
    src = source_name.lower().strip()
    if src not in CSV_TEMPLATES:
        raise HTTPException(status_code=404, detail=f"Template '{source_name}' not found. Available: {list(CSV_TEMPLATES.keys())}")

    content = CSV_TEMPLATES[src]
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=template_{src}.csv"}
    )


@router.get("/model-metrics")
def get_ml_model_metrics(
    current_user: User = Depends(require_role(["ADMIN"])),
    db: Session = Depends(get_db)
):
    """Screen 9: time-based held-out model metrics and feature importance."""
    metrics = get_model_metrics()
    return metrics
