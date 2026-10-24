import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_TEST_DIRECTORY = tempfile.TemporaryDirectory(prefix="educare-phase6-tests-")
_TEST_ROOT = Path(_TEST_DIRECTORY.name)
os.environ["DATABASE_URL"] = f"sqlite:///{(_TEST_ROOT / 'phase6.db').as_posix()}"
os.environ["MODEL_CACHE_PATH"] = str(_TEST_ROOT / "model-cache" / "risk_model.joblib")
os.environ["SECRET_KEY"] = "phase-six-isolated-test-secret-not-production"
os.environ["CORS_ALLOWED_ORIGINS"] = "http://localhost:8000"

from app.auth import hash_password
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import (
    FacultyAssignment,
    InterventionAction,
    Student,
    StudentAccountRequest,
    StudentMentorMessage,
    StudentScore,
    UnifiedStudentMetrics,
    User,
)


@pytest.fixture
def isolated_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    admin = User(
        username="phase6-admin",
        hashed_password=hash_password("Admin-Secure-Password-1"),
        role="ADMIN",
    )
    faculty = User(
        username="phase6-faculty",
        hashed_password=hash_password("Faculty-Secure-Password-1"),
        role="FACULTY",
    )
    db.add_all([admin, faculty])
    db.flush()
    db.add_all([
        Student(student_id="P6-001", name="History Student", department="CSE", year=3, semester=5, mentor_id=faculty.id),
        Student(student_id="P6-002", name="No History Student", department="ECE", year=2, semester=3),
    ])
    db.flush()
    db.add_all([
        StudentScore(student_id="P6-001"),
        StudentScore(student_id="P6-002"),
        UnifiedStudentMetrics(student_id="P6-001", last_updated=datetime.now(timezone.utc) - timedelta(days=2)),
        UnifiedStudentMetrics(student_id="P6-002", last_updated=datetime.now(timezone.utc)),
        FacultyAssignment(faculty_id=faculty.id, student_id="P6-001"),
        InterventionAction(
            student_id="P6-001",
            mentor_id=faculty.id,
            action_type="advising",
            description="Schedule an academic check-in",
            status="done",
            created_at=datetime.now(timezone.utc) - timedelta(days=10),
            updated_at=datetime.now(timezone.utc) - timedelta(days=5),
            completed_at=datetime.now(timezone.utc) - timedelta(days=5),
        ),
        StudentMentorMessage(
            student_id="P6-001",
            mentor_id=faculty.id,
            message="I need help planning study time.",
            reply="Let's meet this week.",
            status="resolved",
            created_at=datetime.now(timezone.utc) - timedelta(days=3),
            updated_at=datetime.now(timezone.utc) - timedelta(days=2),
        ),
    ])
    db.commit()
    db.close()
    try:
        yield
    finally:
        app.dependency_overrides.clear()


@pytest.fixture(scope="session", autouse=True)
def cleanup_isolated_resources():
    yield
    app.dependency_overrides.clear()
    engine.dispose()
    _TEST_DIRECTORY.cleanup()


def _login(client, username, password):
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def test_student_registration_is_pending_and_rejects_invalid_or_duplicate_requests(isolated_database):
    with TestClient(app) as client:
        short_password = client.post(
            "/api/auth/student-account-requests",
            json={"student_id": "P6-001", "password": "short"},
        )
        missing_record = client.post(
            "/api/auth/student-account-requests",
            json={"student_id": "UNKNOWN", "password": "Long-Secure-Password-1"},
        )
        submitted = client.post(
            "/api/auth/student-account-requests",
            json={"student_id": "P6-001", "password": "Long-Secure-Password-1"},
        )
        duplicate = client.post(
            "/api/auth/student-account-requests",
            json={"student_id": "P6-001", "password": "Another-Secure-Password-2"},
        )

    assert short_password.status_code == 422
    assert missing_record.status_code == 404
    assert submitted.status_code == 202
    assert submitted.json()["status"] == "pending_approval"
    assert "access_token" not in submitted.json()
    assert duplicate.status_code == 409


def test_admin_approval_creates_student_only_account(isolated_database):
    with TestClient(app) as client:
        request_response = client.post(
            "/api/auth/student-account-requests",
            json={"student_id": "P6-001", "password": "Long-Secure-Password-1"},
        )
        assert request_response.status_code == 202
        admin_token = _login(client, "phase6-admin", "Admin-Secure-Password-1")
        headers = {"Authorization": f"Bearer {admin_token}"}
        requests_response = client.get("/api/admin/account-requests", headers=headers)
        request_id = requests_response.json()["requests"][0]["id"]
        approved = client.post(
            f"/api/admin/account-requests/{request_id}/approve",
            headers=headers,
        )
        student_token = _login(client, "P6-001", "Long-Secure-Password-1")
        student_headers = {"Authorization": f"Bearer {student_token}"}
        forbidden_directory = client.get("/api/students", headers=student_headers)
        forbidden_requests = client.get("/api/admin/account-requests", headers=student_headers)

    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert forbidden_directory.status_code == 403
    assert forbidden_requests.status_code == 403


def test_logout_revokes_access_to_protected_api(isolated_database):
    with TestClient(app) as client:
        token = _login(client, "phase6-admin", "Admin-Secure-Password-1")
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/admin/settings", headers=headers).status_code == 200
        logged_out = client.post("/api/auth/logout", headers=headers)
        after_logout = client.get("/api/admin/settings", headers=headers)

    assert logged_out.status_code == 204
    assert after_logout.status_code == 401


def test_profile_history_uses_recorded_dates_and_obeys_faculty_scope(isolated_database):
    with TestClient(app) as client:
        account_request = client.post(
            "/api/auth/student-account-requests",
            json={"student_id": "P6-001", "password": "Long-Secure-Password-1"},
        )
        admin_token = _login(client, "phase6-admin", "Admin-Secure-Password-1")
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        request_id = client.get(
            "/api/admin/account-requests",
            headers=admin_headers,
        ).json()["requests"][0]["id"]
        assert client.post(
            f"/api/admin/account-requests/{request_id}/approve",
            headers=admin_headers,
        ).status_code == 200

        faculty_token = _login(client, "phase6-faculty", "Faculty-Secure-Password-1")
        faculty_headers = {"Authorization": f"Bearer {faculty_token}"}
        profile = client.get("/api/students/P6-001", headers=faculty_headers)
        unavailable = client.get("/api/students/P6-002", headers=faculty_headers)
        other_token = _login(client, "phase6-admin", "Admin-Secure-Password-1")
        admin_profile = client.get(
            "/api/students/P6-002",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        student_token = _login(client, "P6-001", "Long-Secure-Password-1")
        student_profile = client.get(
            "/api/students/P6-001",
            headers={"Authorization": f"Bearer {student_token}"},
        )

    assert profile.status_code == 200
    history = profile.json()["activity_history"]
    assert [item["type"] for item in history] == [
        "Advisor support assigned",
        "Advisor support updated",
        "Advisor support completed",
        "Student message",
        "Advisor reply",
    ]
    assert profile.json()["last_activity_at"] == history[-1]["date"]
    assert profile.json()["days_since_last_activity"] is not None
    assert profile.json()["last_record_updated"] is not None
    assert unavailable.status_code == 403
    assert admin_profile.status_code == 200
    assert admin_profile.json()["activity_history"] == []
    assert admin_profile.json()["last_activity_at"] is None
    assert admin_profile.json()["days_since_last_activity"] is None
    assert student_profile.status_code == 200
    assert "activity_history" not in student_profile.json()
