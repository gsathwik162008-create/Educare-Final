import atexit
import os
import tempfile
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

_TEST_DIRECTORY = tempfile.TemporaryDirectory(prefix="educare-ingestion-tests-")
_TEST_ROOT = Path(_TEST_DIRECTORY.name)
os.environ["DATABASE_URL"] = f"sqlite:///{(_TEST_ROOT / 'ingestion-test.db').as_posix()}"
os.environ["MODEL_CACHE_PATH"] = str(_TEST_ROOT / "model-cache" / "risk_model.joblib")
os.environ["SECRET_KEY"] = "isolated-ingestion-test-key-not-for-production"
os.environ["CORS_ALLOWED_ORIGINS"] = "http://localhost:8000"

from app.auth import get_current_user
from app.analytics_pipeline import run_full_analytics_pipeline
from app import ml
from app.database import Base, SessionLocal, engine
from app.ingestion import SOURCE_REQUIRED_COLUMNS, ingest_seven_sources
from app.main import app
from app.models import Student, StudentScore, UnifiedStudentMetrics, User
from app import routes_admin

_CLEANED_UP = False


def _cleanup_isolated_resources():
    global _CLEANED_UP
    if _CLEANED_UP:
        return
    _CLEANED_UP = True
    app.dependency_overrides.clear()
    engine.dispose()
    _TEST_DIRECTORY.cleanup()


atexit.register(_cleanup_isolated_resources)


BASE_METRICS = {
    "cgpa": 7.2,
    "total_backlogs": 1,
    "attendance_pct": 81.0,
    "lms_login_count": 40,
    "lms_time_spent_hrs": 32.0,
    "assignments_submitted_pct": 79.0,
    "forum_posts_count": 4,
    "event_participation_count": 2,
    "library_visits": 8,
    "aptitude_score": 65.0,
    "coding_score": 61.0,
    "mock_interviews_completed": 1,
    "technical_skills_score": 70.0,
    "soft_skills_score": 72.0,
    "faculty_feedback_score": 75.0,
    "peer_feedback_score": 76.0,
}

SOURCE_ROWS = {
    "academic": {
        "student_id": "STU-001", "name": "Changed Name", "department": "ECE",
        "year": "4", "semester": "7", "cgpa": "8.3", "backlogs": "0",
    },
    "attendance": {"student_id": "STU-001", "attendance_pct": "91"},
    "lms": {
        "student_id": "STU-001", "lms_login_count": "90",
        "lms_time_spent_hrs": "42.5", "assignments_submitted_pct": "95",
    },
    "engagement": {
        "student_id": "STU-001", "event_participation_count": "5", "library_visits": "17",
    },
    "placement": {
        "student_id": "STU-001", "aptitude_score": "80", "coding_score": "78",
        "mock_interviews_completed": "3",
    },
    "skills": {
        "student_id": "STU-001", "technical_skills_score": "88", "soft_skills_score": "83",
    },
    "feedback": {
        "student_id": "STU-001", "faculty_feedback_score": "90", "peer_feedback_score": "85",
    },
}


@pytest.fixture(autouse=True)
def isolated_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    student = Student(
        student_id="STU-001",
        name="Original Name",
        department="CSE",
        year=3,
        semester=5,
    )
    db.add(student)
    db.add(UnifiedStudentMetrics(student_id="STU-001", **BASE_METRICS))
    db.commit()
    try:
        yield db
    finally:
        app.dependency_overrides.clear()
        db.close()


@pytest.fixture(scope="session", autouse=True)
def cleanup_isolated_resources():
    yield
    _cleanup_isolated_resources()


def _frame(source: str, values=None) -> pd.DataFrame:
    return pd.DataFrame([values or SOURCE_ROWS[source]])


@pytest.mark.parametrize(
    ("source", "field", "expected"),
    [
        ("academic", "cgpa", 8.3),
        ("attendance", "attendance_pct", 91.0),
        ("lms", "lms_login_count", 90),
        ("engagement", "library_visits", 17),
        ("placement", "coding_score", 78.0),
        ("skills", "technical_skills_score", 88.0),
        ("feedback", "faculty_feedback_score", 90.0),
    ],
)
def test_single_source_partial_updates_preserve_absent_fields(
    isolated_database, source, field, expected
):
    db = isolated_database
    before = db.query(UnifiedStudentMetrics).filter_by(student_id="STU-001").one()
    previous_values = {name: getattr(before, name) for name in BASE_METRICS}

    result = ingest_seven_sources({source: _frame(source)}, db)

    assert result["status"] == "success"
    assert result["import_mode"] == "partial"
    assert result["accepted_rows"] == 1
    assert result["updated_rows"] == 1
    after = db.query(UnifiedStudentMetrics).filter_by(student_id="STU-001").one()
    target_field = "total_backlogs" if field == "backlogs" else field
    assert getattr(after, target_field) == expected
    changed_fields = {"cgpa", "total_backlogs"} if source == "academic" else {
        "lms_login_count", "lms_time_spent_hrs", "assignments_submitted_pct"
    } if source == "lms" else {
        "event_participation_count", "library_visits"
    } if source == "engagement" else {
        "aptitude_score", "coding_score", "mock_interviews_completed"
    } if source == "placement" else {
        "technical_skills_score", "soft_skills_score"
    } if source == "skills" else {
        "faculty_feedback_score", "peer_feedback_score"
    } if source == "feedback" else {"attendance_pct"}
    for metric_name, old_value in previous_values.items():
        if metric_name not in changed_fields:
            assert getattr(after, metric_name) == old_value

    student = db.query(Student).filter_by(student_id="STU-001").one()
    if source == "academic":
        assert student.name == "Changed Name"
        assert student.department == "ECE"
    else:
        assert student.name == "Original Name"


def test_missing_required_column_rejects_before_any_update(isolated_database):
    db = isolated_database
    result = ingest_seven_sources(
        {"attendance": pd.DataFrame([{"student_id": "STU-001"}])},
        db,
    )

    assert result["status"] == "error"
    assert result["rejected_rows"] == 1
    assert "attendance_pct" in result["errors"]["attendance"][0]
    assert db.query(UnifiedStudentMetrics).one().attendance_pct == 81.0


@pytest.mark.parametrize("value", ["not-a-number", "101"])
def test_invalid_numeric_values_reject_whole_upload(isolated_database, value):
    db = isolated_database
    result = ingest_seven_sources(
        {"attendance": _frame("attendance", {"student_id": "STU-001", "attendance_pct": value})},
        db,
    )

    assert result["status"] == "error"
    assert result["rejected_rows"] == 1
    assert result["updated_rows"] == 0
    assert db.query(UnifiedStudentMetrics).one().attendance_pct == 81.0


def test_exact_duplicate_rows_are_counted_and_conflicting_duplicates_rejected(isolated_database):
    db = isolated_database
    row = SOURCE_ROWS["attendance"]
    exact_duplicates = pd.DataFrame([row, row])
    result = ingest_seven_sources({"attendance": exact_duplicates}, db)

    assert result["status"] == "success"
    assert result["accepted_rows"] == 1
    assert result["duplicate_rows"] == 1

    conflicting = pd.DataFrame([
        row,
        {"student_id": "STU-001", "attendance_pct": "90"},
    ])
    failed = ingest_seven_sources({"attendance": conflicting}, db)
    assert failed["status"] == "error"
    assert failed["rejected_rows"] == 2
    assert db.query(UnifiedStudentMetrics).one().attendance_pct == 91.0


def test_invalid_student_identifier_rejects_upload(isolated_database):
    db = isolated_database
    result = ingest_seven_sources(
        {"attendance": _frame("attendance", {"student_id": "BAD ID!", "attendance_pct": "90"})},
        db,
    )

    assert result["status"] == "error"
    assert result["accepted_rows"] == 0
    assert result["rejected_rows"] == 1
    assert db.query(UnifiedStudentMetrics).one().attendance_pct == 81.0


def test_partial_blank_cell_keeps_existing_metric(isolated_database):
    db = isolated_database
    result = ingest_seven_sources(
        {"attendance": _frame("attendance", {"student_id": "STU-001", "attendance_pct": ""})},
        db,
    )

    assert result["status"] == "success"
    assert result["updated_rows"] == 0
    assert db.query(UnifiedStudentMetrics).one().attendance_pct == 81.0


def test_template_only_columns_are_reported_as_not_persisted(isolated_database):
    db = isolated_database
    result = ingest_seven_sources(
        {
            "attendance": _frame(
                "attendance",
                {
                    "student_id": "STU-001",
                    "attendance_pct": "91",
                    "lab_attendance_pct": "95",
                },
            )
        },
        db,
    )

    assert result["status"] == "success"
    assert result["not_persisted_columns"] == ["lab_attendance_pct"]
    assert db.query(UnifiedStudentMetrics).one().attendance_pct == 91.0


def test_full_import_requires_all_sources_and_matching_student_ids(isolated_database):
    db = isolated_database
    incomplete = ingest_seven_sources(
        {"academic": _frame("academic")},
        db,
        import_mode="full",
    )
    assert incomplete["status"] == "error"
    assert "all seven source files" in incomplete["errors"]["sources"][0]
    assert db.query(Student).count() == 1

    complete = {
        source: _frame(source, {**SOURCE_ROWS[source], "student_id": "STU-002"})
        for source in SOURCE_REQUIRED_COLUMNS
    }
    mismatched = dict(complete)
    mismatched["attendance"] = _frame(
        "attendance",
        {"student_id": "STU-003", "attendance_pct": "91"},
    )
    mismatch_result = ingest_seven_sources(mismatched, db, import_mode="full")
    assert mismatch_result["status"] == "error"
    assert db.query(Student).count() == 1

    result = ingest_seven_sources(complete, db, import_mode="full")

    assert result["status"] == "success"
    assert result["accepted_rows"] == 7
    assert db.query(Student).count() == 2
    assert db.query(UnifiedStudentMetrics).filter_by(student_id="STU-002").one().attendance_pct == 91.0
    assert db.query(Student).filter_by(student_id="STU-001").one().name == "Original Name"


def test_database_flush_failure_rolls_back_all_ingestion_changes(isolated_database, monkeypatch):
    db = isolated_database
    original_flush = db.flush

    def fail_flush(*args, **kwargs):
        raise RuntimeError("simulated write failure")

    monkeypatch.setattr(db, "flush", fail_flush)
    with pytest.raises(RuntimeError, match="simulated write failure"):
        ingest_seven_sources({"attendance": _frame("attendance")}, db)
    monkeypatch.setattr(db, "flush", original_flush)

    fresh_db = SessionLocal()
    try:
        assert fresh_db.query(UnifiedStudentMetrics).one().attendance_pct == 81.0
    finally:
        fresh_db.close()


def test_analytics_pipeline_changes_remain_in_caller_transaction(isolated_database):
    db = isolated_database
    previous_model_state = ml.snapshot_model_state()
    try:
        result = run_full_analytics_pipeline(db, persist_model_cache=False)
        assert result["status"] == "success"

        fresh_db = SessionLocal()
        try:
            assert fresh_db.query(StudentScore).count() == 0
        finally:
            fresh_db.close()
    finally:
        db.rollback()
        ml.restore_model_state(previous_model_state)


def test_failed_analytics_rolls_back_uploaded_rows(isolated_database, monkeypatch):
    admin = User(username="ingestion-admin", hashed_password="unused", role="ADMIN")
    isolated_database.add(admin)
    isolated_database.commit()
    app.dependency_overrides[get_current_user] = lambda: admin

    def fail_pipeline(*args, **kwargs):
        raise RuntimeError("simulated analytics failure")

    monkeypatch.setattr(routes_admin, "run_full_analytics_pipeline", fail_pipeline)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/admin/upload",
            files={"attendance": ("attendance.csv", "student_id,attendance_pct\nSTU-001,91\n", "text/csv")},
        )

    assert response.status_code == 500
    fresh_db = SessionLocal()
    try:
        assert fresh_db.query(UnifiedStudentMetrics).one().attendance_pct == 81.0
    finally:
        fresh_db.close()


def test_upload_endpoint_commits_only_after_pipeline_succeeds(isolated_database, monkeypatch):
    admin = User(username="successful-ingestion-admin", hashed_password="unused", role="ADMIN")
    isolated_database.add(admin)
    isolated_database.commit()
    app.dependency_overrides[get_current_user] = lambda: admin
    monkeypatch.setattr(
        routes_admin,
        "run_full_analytics_pipeline",
        lambda *args, **kwargs: {"status": "success", "students_evaluated": 1},
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/admin/upload",
            data={"import_mode": "partial"},
            files={"attendance": ("attendance.csv", "student_id,attendance_pct\nSTU-001,91\n", "text/csv")},
        )

    assert response.status_code == 200
    assert response.json()["ingestion_summary"]["updated_rows"] == 1
    fresh_db = SessionLocal()
    try:
        assert fresh_db.query(UnifiedStudentMetrics).one().attendance_pct == 91.0
    finally:
        fresh_db.close()


def test_upload_endpoint_rejects_oversized_csv(isolated_database):
    admin = User(username="oversized-ingestion-admin", hashed_password="unused", role="ADMIN")
    isolated_database.add(admin)
    isolated_database.commit()
    app.dependency_overrides[get_current_user] = lambda: admin

    oversized_content = b"x" * (routes_admin.MAX_CSV_FILE_BYTES + 1)
    with TestClient(app) as client:
        response = client.post(
            "/api/admin/upload",
            files={"attendance": ("attendance.csv", oversized_content, "text/csv")},
        )

    assert response.status_code == 413
    fresh_db = SessionLocal()
    try:
        assert fresh_db.query(UnifiedStudentMetrics).one().attendance_pct == 81.0
    finally:
        fresh_db.close()
