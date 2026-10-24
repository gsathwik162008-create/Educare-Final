import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

_TEST_DIRECTORY = tempfile.TemporaryDirectory(prefix="educare-phase4-tests-")
_TEST_ROOT = Path(_TEST_DIRECTORY.name)
os.environ["DATABASE_URL"] = f"sqlite:///{(_TEST_ROOT / 'phase4.db').as_posix()}"
os.environ["MODEL_CACHE_PATH"] = str(_TEST_ROOT / "model-cache" / "risk_model.joblib")
os.environ["SECRET_KEY"] = "phase-four-isolated-test-secret-not-production"
os.environ["CORS_ALLOWED_ORIGINS"] = "http://localhost:8000"

from app.auth import get_current_user
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import (
    FacultyAssignment,
    InterventionAction,
    Student,
    StudentScore,
    UnifiedStudentMetrics,
    User,
)
from app import routes_admin
from app import ml


@pytest.fixture
def isolated_app():
    app.dependency_overrides.clear()
    ml._TRAINED_MODEL = None
    ml._MODEL_METRICS = {}
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    faculty = User(username="faculty-test", hashed_password="unused", role="FACULTY")
    admin = User(username="admin-test", hashed_password="unused", role="ADMIN")
    student_user = User(
        username="TEST-001",
        hashed_password="unused",
        role="STUDENT",
        student_id="TEST-001",
    )
    db.add_all([faculty, admin, student_user])
    db.flush()
    db.add_all([
        Student(
            student_id="TEST-001",
            name="Test Student",
            department="CSE",
            year=3,
            semester=5,
            mentor_id=faculty.id,
        ),
        Student(
            student_id="TEST-002",
            name="Other Student",
            department="ECE",
            year=2,
            semester=3,
        ),
    ])
    db.add(StudentScore(student_id="TEST-001", ml_risk_probability=0.0))
    db.flush()
    db.add(FacultyAssignment(faculty_id=faculty.id, student_id="TEST-001"))
    db.add_all([
        UnifiedStudentMetrics(
            student_id="TEST-001",
            cgpa=4.5,
            total_backlogs=2,
            attendance_pct=55.0,
            lms_login_count=4,
            lms_time_spent_hrs=2.0,
            assignments_submitted_pct=45.0,
            forum_posts_count=0,
            event_participation_count=0,
            library_visits=0,
            aptitude_score=30.0,
            coding_score=20.0,
            mock_interviews_completed=0,
            technical_skills_score=30.0,
            soft_skills_score=35.0,
            faculty_feedback_score=40.0,
            peer_feedback_score=45.0,
        ),
        UnifiedStudentMetrics(
            student_id="TEST-002",
            cgpa=7.0,
            total_backlogs=0,
            attendance_pct=80.0,
            coding_score=65.0,
        ),
    ])
    db.commit()
    users = {
        "admin": SimpleNamespace(id=admin.id, role=admin.role, student_id=None),
        "faculty": SimpleNamespace(id=faculty.id, role=faculty.role, student_id=None),
        "student": SimpleNamespace(
            id=student_user.id,
            role=student_user.role,
            student_id=student_user.student_id,
        ),
    }
    db.close()
    try:
        yield users
    finally:
        app.dependency_overrides.clear()


@pytest.fixture(scope="session", autouse=True)
def cleanup_isolated_resources():
    yield
    app.dependency_overrides.clear()
    engine.dispose()
    _TEST_DIRECTORY.cleanup()


def _set_user(user):
    app.dependency_overrides[get_current_user] = lambda: user


def _staff_client(user):
    _set_user(user)
    return TestClient(app)


def _full_import_files(student_id="NEW-001"):
    rows = {
        "academic": (
            "student_id,name,department,year,semester,cgpa,backlogs\n"
            f"{student_id},New Student,CSE,3,5,4.5,2\n"
        ),
        "attendance": f"student_id,attendance_pct\n{student_id},55\n",
        "lms": (
            "student_id,lms_login_count,lms_time_spent_hrs,assignments_submitted_pct\n"
            f"{student_id},4,2,45\n"
        ),
        "engagement": (
            "student_id,event_participation_count,library_visits\n"
            f"{student_id},0,0\n"
        ),
        "placement": (
            "student_id,aptitude_score,coding_score,mock_interviews_completed\n"
            f"{student_id},30,20,0\n"
        ),
        "skills": (
            "student_id,technical_skills_score,soft_skills_score\n"
            f"{student_id},30,35\n"
        ),
        "feedback": (
            "student_id,faculty_feedback_score,peer_feedback_score\n"
            f"{student_id},40,45\n"
        ),
    }
    return {
        source: (f"{source}.csv", content, "text/csv")
        for source, content in rows.items()
    }


def test_startup_and_ui_routes_work_without_seed_data():
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/").status_code == 200
        assert client.get("/static/js/app.js").status_code == 200

    db = SessionLocal()
    try:
        assert db.query(Student).count() == 0
        assert db.query(User).count() == 0
    finally:
        db.close()


def test_cors_and_frontend_auth_error_contracts():
    with TestClient(app) as client:
        allowed = client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:8000",
                "Access-Control-Request-Method": "GET",
            },
        )
        denied = client.options(
            "/api/health",
            headers={
                "Origin": "https://untrusted.example",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert allowed.headers.get("access-control-allow-origin") == "http://localhost:8000"
        assert "access-control-allow-origin" not in denied.headers

    project_root = Path(__file__).resolve().parents[1]
    api_source = (project_root / "static" / "js" / "api.js").read_text(encoding="utf-8")
    app_source = (project_root / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert 'response.status === 401' in api_source
    assert "logout({ revoke: false });" in api_source
    assert "if (!response.ok)" in api_source
    assert 'mlMetrics.status === "trained"' in app_source
    assert '"N/A"' in app_source
    assert "cv_precision" not in app_source


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/analytics/overview"),
        ("get", "/api/students"),
        ("get", "/api/students/TEST-001"),
        ("get", "/api/interventions"),
        ("get", "/api/admin/settings"),
        ("get", "/api/admin/model-metrics"),
        ("post", "/api/admin/recompute"),
    ],
)
def test_protected_endpoints_reject_unauthenticated_requests(isolated_app, method, path):
    with TestClient(app) as client:
        response = getattr(client, method)(path)

    assert response.status_code == 401


def test_student_and_faculty_role_boundaries_across_integrated_routes(isolated_app):
    with _staff_client(isolated_app["student"]) as client:
        assert client.get("/api/analytics/overview").status_code == 403
        assert client.get("/api/admin/model-metrics").status_code == 403
        own_profile = client.get("/api/students/TEST-001")
        other_profile = client.get("/api/students/TEST-002")
        assert own_profile.status_code == 200
        assert not {
            "academic_risk_level",
            "academic_risk_reasons",
            "placement_risk_level",
            "placement_risk_reasons",
            "ml_risk_probability",
            "segment_rule",
            "segment_kmeans",
        }.intersection(own_profile.json())
        assert other_profile.status_code == 403

    with _staff_client(isolated_app["faculty"]) as client:
        assert client.get("/api/admin/settings").status_code == 403
        assigned_profile = client.get("/api/students/TEST-001")
        assert assigned_profile.status_code == 200
        assert assigned_profile.json()["ml_risk_probability"] is None
        assert client.get("/api/students/TEST-002").status_code == 403
        faculty_list = client.get("/api/students").json()
        assert faculty_list["students"][0]["ml_risk_probability"] is None


def test_full_import_recomputes_analytics_and_interventions_with_unavailable_ml(
    isolated_app,
):
    with _staff_client(isolated_app["admin"]) as client:
        response = client.post(
            "/api/admin/upload",
            data={"import_mode": "full"},
            files=_full_import_files(),
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["ingestion_summary"]["import_mode"] == "full"
        assert payload["pipeline_summary"]["status"] == "success"
        assert payload["pipeline_summary"]["students_evaluated"] == 3

        profile = client.get("/api/students/NEW-001")
        metrics = client.get("/api/admin/model-metrics")

    assert profile.status_code == 200
    assert profile.json()["ml_risk_probability"] is None
    assert metrics.status_code == 200
    assert metrics.json()["status"] == "insufficient_data"

    db = SessionLocal()
    try:
        assert db.query(Student).filter_by(student_id="NEW-001").count() == 1
        assert db.query(StudentScore).filter_by(student_id="NEW-001").one().ml_risk_probability is None
        assert db.query(InterventionAction).filter_by(student_id="NEW-001").count() > 0
    finally:
        db.close()


def test_partial_import_preserves_other_sources_and_refreshes_score(isolated_app):
    with _staff_client(isolated_app["admin"]) as client:
        response = client.post(
            "/api/admin/upload",
            data={"import_mode": "partial"},
            files={
                "attendance": (
                    "attendance.csv",
                    "student_id,attendance_pct\nTEST-001,90\n",
                    "text/csv",
                )
            },
        )

    assert response.status_code == 200, response.text
    assert response.json()["pipeline_summary"]["status"] == "success"
    db = SessionLocal()
    try:
        metrics = db.query(UnifiedStudentMetrics).filter_by(student_id="TEST-001").one()
        score = db.query(StudentScore).filter_by(student_id="TEST-001").one()
        assert metrics.attendance_pct == 90.0
        assert metrics.cgpa == 4.5
        assert metrics.coding_score == 20.0
        assert score.total_success_score is not None
        assert db.query(InterventionAction).filter_by(student_id="TEST-001").count() > 0
    finally:
        db.close()


def test_successful_import_refreshes_pending_actions_without_losing_notes(
    isolated_app,
):
    db = SessionLocal()
    db.add(InterventionAction(
        student_id="TEST-001",
        action_type="academic_remediation",
        description="Old recommendation from previous metrics.",
        potential_gain=14.0,
        urgency=5.0,
        priority=70.0,
        status="pending",
        notes="Advisor already discussed tutoring.",
        score_at_creation=20.0,
    ))
    db.commit()
    db.close()

    with _staff_client(isolated_app["admin"]) as client:
        response = client.post(
            "/api/admin/upload",
            data={"import_mode": "partial"},
            files={
                "academic": (
                    "academic.csv",
                    "student_id,name,department,year,semester,cgpa,backlogs\n"
                    "TEST-001,Test Student,CSE,3,5,5.0,2\n",
                    "text/csv",
                )
            },
        )

    assert response.status_code == 200, response.text
    db = SessionLocal()
    try:
        updated_action = db.query(InterventionAction).filter_by(
            student_id="TEST-001",
            action_type="academic_remediation",
            status="pending",
        ).one()
        assert updated_action.description != "Old recommendation from previous metrics."
        assert updated_action.potential_gain == 13.5
        assert updated_action.priority == 67.5
        assert updated_action.notes == "Advisor already discussed tutoring."
        assert updated_action.score_at_creation == 20.0
    finally:
        db.close()


def test_obsolete_pending_recommendation_with_notes_is_demoted_not_discarded(
    isolated_app,
):
    db = SessionLocal()
    db.add(InterventionAction(
        student_id="TEST-001",
        action_type="attendance_alert",
        description="Old attendance recommendation.",
        potential_gain=12.0,
        urgency=5.0,
        priority=60.0,
        status="pending",
        notes="Advisor has already scheduled a check-in.",
        score_at_creation=20.0,
    ))
    db.commit()
    db.close()

    with _staff_client(isolated_app["admin"]) as client:
        response = client.post(
            "/api/admin/upload",
            data={"import_mode": "partial"},
            files={
                "attendance": (
                    "attendance.csv",
                    "student_id,attendance_pct\nTEST-001,90\n",
                    "text/csv",
                )
            },
        )

    assert response.status_code == 200, response.text
    db = SessionLocal()
    try:
        action = db.query(InterventionAction).filter_by(
            student_id="TEST-001",
            action_type="attendance_alert",
            status="pending",
        ).one()
        assert "no longer among the current top recommendations" in action.description
        assert action.priority == 0.0
        assert action.notes == "Advisor has already scheduled a check-in."
    finally:
        db.close()


def test_invalid_upload_neither_writes_metrics_nor_runs_analytics(
    isolated_app, monkeypatch
):
    called = {"pipeline": False}

    def unexpected_pipeline(*args, **kwargs):
        called["pipeline"] = True
        raise AssertionError("analytics must not run after validation failure")

    monkeypatch.setattr(routes_admin, "run_full_analytics_pipeline", unexpected_pipeline)
    with _staff_client(isolated_app["admin"]) as client:
        response = client.post(
            "/api/admin/upload",
            data={"import_mode": "partial"},
            files={
                "attendance": (
                    "attendance.csv",
                    "student_id,attendance_pct\nTEST-001,invalid\n",
                    "text/csv",
                )
            },
        )

    assert response.status_code == 400
    assert called["pipeline"] is False
    db = SessionLocal()
    try:
        assert db.query(UnifiedStudentMetrics).filter_by(student_id="TEST-001").one().attendance_pct == 55.0
    finally:
        db.close()


def test_pipeline_failure_rolls_back_imported_metrics(isolated_app, monkeypatch):
    def fail_pipeline(*args, **kwargs):
        raise RuntimeError("simulated integration failure")

    monkeypatch.setattr(routes_admin, "run_full_analytics_pipeline", fail_pipeline)
    _set_user(isolated_app["admin"])
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/admin/upload",
            data={"import_mode": "partial"},
            files={
                "attendance": (
                    "attendance.csv",
                    "student_id,attendance_pct\nTEST-001,90\n",
                    "text/csv",
                )
            },
        )

    assert response.status_code == 500
    db = SessionLocal()
    try:
        assert db.query(UnifiedStudentMetrics).filter_by(student_id="TEST-001").one().attendance_pct == 55.0
    finally:
        db.close()
