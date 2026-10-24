import os
import sqlite3
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_TEST_DIRECTORY = tempfile.TemporaryDirectory(prefix="educare-demo-data-tests-")
_TEST_ROOT = Path(_TEST_DIRECTORY.name)
_DEMO_DATABASE = _TEST_ROOT / "campus_demo.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_DEMO_DATABASE.as_posix()}"
os.environ["MODEL_CACHE_PATH"] = str(_TEST_ROOT / "model-cache" / "risk_model.joblib")
os.environ["SECRET_KEY"] = "isolated-demo-data-test-secret-not-production"
os.environ["CORS_ALLOWED_ORIGINS"] = "http://localhost:8000"
os.environ["PYTHON_DOTENV_DISABLED"] = "1"

from app.database import SessionLocal, engine
from app.main import app
from app.models import (
    FacultyAssignment,
    SemesterHistory,
    Student,
    StudentScore,
    SubjectRecord,
    UnifiedStudentMetrics,
    User,
)
from seed_demo import DEMO_ACCOUNTS, DEMO_STUDENTS

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _seed_environment():
    environment = os.environ.copy()
    environment["EDUCARE_ENABLE_DEMO_SEED"] = "1"
    return environment


def _run_demo_seed(database_url: str):
    return subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "seed_demo.py"),
            "--database-url",
            database_url,
        ],
        cwd=PROJECT_ROOT,
        env=_seed_environment(),
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="session", autouse=True)
def initialize_isolated_demo_database():
    database_url = f"sqlite:///{_DEMO_DATABASE.as_posix()}"
    first_run = _run_demo_seed(database_url)
    assert first_run.returncode == 0, first_run.stderr
    assert "Created 7 local demo accounts" in first_run.stdout

    second_run = _run_demo_seed(database_url)
    assert second_run.returncode == 0, second_run.stderr
    assert "already initialized" in second_run.stdout

    yield

    app.dependency_overrides.clear()
    engine.dispose()
    _TEST_DIRECTORY.cleanup()


@pytest.fixture
def client(initialize_isolated_demo_database):
    with TestClient(app) as test_client:
        yield test_client


def _login(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_seeding_creates_exactly_seven_role_specific_accounts_and_records():
    with SessionLocal() as db:
        users = db.query(User).all()
        students = db.query(Student).all()

        assert len(users) == 7
        assert Counter(user.role for user in users) == {
            "ADMIN": 1,
            "FACULTY": 2,
            "STUDENT": 4,
        }
        assert {student.student_id for student in students} == {
            student["student_id"] for student in DEMO_STUDENTS
        }
        assert db.query(FacultyAssignment).count() == 4
        assert db.query(UnifiedStudentMetrics).count() == 4
        assert db.query(StudentScore).count() == 4
        assert db.query(SemesterHistory).count() == sum(
            len(student["gpa_history"]) for student in DEMO_STUDENTS
        )
        assert db.query(SubjectRecord).count() == 8

        student_metrics = db.query(UnifiedStudentMetrics).all()
        assert len({
            (metric.cgpa, metric.attendance_pct, metric.coding_score)
            for metric in student_metrics
        }) == 4
        assert {student.department for student in students} == {"CSE", "ECE"}


def test_all_seven_accounts_authenticate_with_separate_credentials(client):
    for account in DEMO_ACCOUNTS:
        headers = _login(client, account["username"], account["password"])
        current_user = client.get("/api/auth/me", headers=headers)
        assert current_user.status_code == 200
        assert current_user.json()["username"] == account["username"]
        assert current_user.json()["role"] == account["role"]


def test_admin_and_faculty_permissions_are_role_and_cohort_scoped(client):
    admin_account = next(account for account in DEMO_ACCOUNTS if account["role"] == "ADMIN")
    admin_headers = _login(client, admin_account["username"], admin_account["password"])
    admin_students = client.get("/api/students", headers=admin_headers).json()["students"]
    admin_overview = client.get("/api/analytics/overview", headers=admin_headers)
    assert len(admin_students) == 4
    assert admin_overview.status_code == 200
    assert admin_overview.json()["total_students"] == 4
    assert client.get("/api/admin/settings", headers=admin_headers).status_code == 200

    faculty_accounts = [account for account in DEMO_ACCOUNTS if account["role"] == "FACULTY"]
    expected_cohorts = {
        "demo_faculty_cse": {"DEMO-CSE-001", "DEMO-CSE-002"},
        "demo_faculty_ece": {"DEMO-ECE-001", "DEMO-ECE-002"},
    }
    for account in faculty_accounts:
        headers = _login(client, account["username"], account["password"])
        listed = client.get("/api/students", headers=headers).json()["students"]
        listed_ids = {student["student_id"] for student in listed}
        assert listed_ids == expected_cohorts[account["username"]]
        assert client.get("/api/analytics/overview", headers=headers).status_code == 200
        assert client.get("/api/admin/settings", headers=headers).status_code == 403

        outside_student_id = (
            "DEMO-ECE-001"
            if account["username"] == "demo_faculty_cse"
            else "DEMO-CSE-001"
        )
        assert client.get(
            f"/api/students/{outside_student_id}",
            headers=headers,
        ).status_code == 403


def test_students_only_access_their_own_profiles_and_no_staff_analytics(client):
    students = [account for account in DEMO_ACCOUNTS if account["role"] == "STUDENT"]
    for account in students:
        headers = _login(client, account["username"], account["password"])
        student_id = account["student_id"]
        own_profile = client.get(f"/api/students/{student_id}", headers=headers)
        assert own_profile.status_code == 200
        assert own_profile.json()["student_id"] == student_id
        assert "academic_risk_level" not in own_profile.json()
        assert client.get("/api/students", headers=headers).status_code == 403
        assert client.get("/api/analytics/overview", headers=headers).status_code == 403
        assert client.get("/api/admin/settings", headers=headers).status_code == 403

        other_student_id = next(
            other["student_id"]
            for other in students
            if other["student_id"] != student_id
        )
        assert client.get(
            f"/api/students/{other_student_id}",
            headers=headers,
        ).status_code == 403


def test_seed_script_refuses_campus_db_without_modifying_it():
    protected_database = _TEST_ROOT / "campus.db"
    connection = sqlite3.connect(protected_database)
    try:
        connection.execute("CREATE TABLE sentinel (value TEXT NOT NULL)")
        connection.execute("INSERT INTO sentinel (value) VALUES ('preserve-me')")
        connection.commit()
    finally:
        connection.close()

    refused = _run_demo_seed(f"sqlite:///{protected_database.as_posix()}")
    assert refused.returncode != 0
    assert "dedicated file named campus_demo.db" in refused.stderr

    connection = sqlite3.connect(protected_database)
    try:
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        sentinel = connection.execute("SELECT value FROM sentinel").fetchone()
    finally:
        connection.close()
    assert tables == [("sentinel",)]
    assert sentinel == ("preserve-me",)
