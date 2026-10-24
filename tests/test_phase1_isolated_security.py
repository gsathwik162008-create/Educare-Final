import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_TEST_DIRECTORY = tempfile.TemporaryDirectory(prefix="educare-security-tests-")
_TEST_ROOT = Path(_TEST_DIRECTORY.name)
os.environ["DATABASE_URL"] = f"sqlite:///{(_TEST_ROOT / 'test.db').as_posix()}"
os.environ["MODEL_CACHE_PATH"] = str(_TEST_ROOT / "model-cache" / "risk_model.joblib")
os.environ["SECRET_KEY"] = "isolated-test-key-that-is-not-a-real-secret"
os.environ["CORS_ALLOWED_ORIGINS"] = "https://dashboard.example,https://staff.example"

from app import ml
from app.auth import get_current_user
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import (
    FacultyAssignment,
    SemesterHistory,
    Student,
    StudentMentorMessage,
    StudentScore,
    SubjectRecord,
    UnifiedStudentMetrics,
    User,
)


@pytest.fixture(scope="session", autouse=True)
def cleanup_isolated_resources():
    yield
    app.dependency_overrides.clear()
    engine.dispose()
    _TEST_DIRECTORY.cleanup()


@pytest.fixture
def isolated_client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    admin = User(username="test-admin", hashed_password="unused", role="ADMIN")
    faculty = User(username="test-faculty", hashed_password="unused", role="FACULTY")
    student_user = User(
        username="TEST-STUDENT-1",
        hashed_password="unused",
        role="STUDENT",
        student_id="TEST-STUDENT-1",
    )
    db.add_all([admin, faculty, student_user])
    db.flush()

    students = [
        Student(
            student_id="TEST-STUDENT-1",
            name="Test Student One",
            department="CSE",
            year=3,
            semester=5,
            mentor_id=faculty.id,
        ),
        Student(
            student_id="TEST-STUDENT-2",
            name="Test Student Two",
            department="ECE",
            year=3,
            semester=5,
        ),
    ]
    db.add_all(students)
    db.flush()
    db.add(FacultyAssignment(faculty_id=faculty.id, student_id=students[0].student_id))

    for index, student in enumerate(students):
        db.add_all([
            UnifiedStudentMetrics(
                student_id=student.student_id,
                cgpa=7.0 + index,
                attendance_pct=80.0,
                coding_score=60.0,
            ),
            StudentScore(
                student_id=student.student_id,
                total_success_score=65.0 + index,
                academic_score=70.0,
                attendance_score=80.0,
                placement_score=60.0,
                lms_score=70.0,
                skills_feedback_score=75.0,
                academic_risk_level="Medium",
                academic_risk_reasons='["test-only risk reason"]',
                placement_risk_level="Low",
                placement_risk_reasons="[]",
                segment_rule="Test Segment",
                segment_kmeans="Test Cluster",
            ),
            SemesterHistory(
                student_id=student.student_id,
                semester=5,
                gpa=7.0 + index,
                attendance_pct=80.0,
                credits_earned=20,
                backlogs=0,
            ),
            SubjectRecord(
                student_id=student.student_id,
                semester=5,
                subject_code=f"TEST{index}",
                subject_name=f"Test Subject {index}",
                marks=75.0,
                attendance_pct=80.0,
                is_backlog=False,
            ),
        ])
    db.commit()

    active_user = {"value": student_user}
    app.dependency_overrides[get_current_user] = lambda: active_user["value"]

    try:
        with TestClient(app) as client:
            yield client, active_user, {
                "admin": admin,
                "faculty": faculty,
                "student": student_user,
            }
    finally:
        app.dependency_overrides.clear()
        db.close()


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("get", "/api/analytics/overview", {}),
        ("get", "/api/analytics/trends", {}),
        ("get", "/api/analytics/segments", {}),
        ("get", "/api/analytics/insights", {}),
        ("get", "/api/analytics/search?q=Test", {}),
        ("post", "/api/ask", {"json": {"query": "How many students need support?"}}),
    ],
)
def test_student_is_denied_staff_analytics(isolated_client, method, path, kwargs):
    client, _, _ = isolated_client

    response = getattr(client, method)(path, **kwargs)

    assert response.status_code == 403


def test_student_profile_only_returns_own_non_sensitive_profile(isolated_client):
    client, _, _ = isolated_client

    own_response = client.get("/api/students/TEST-STUDENT-1")
    other_response = client.get("/api/students/TEST-STUDENT-2")
    directory_response = client.get("/api/students")

    assert own_response.status_code == 200
    own_profile = own_response.json()
    assert "cohort_averages" not in own_profile
    assert "strengths" in own_profile
    assert "focus_areas" in own_profile
    assert not {
        "academic_risk_level",
        "academic_risk_reasons",
        "placement_risk_level",
        "placement_risk_reasons",
        "ml_risk_probability",
        "segment_rule",
        "segment_kmeans",
        "score_explanation",
    }.intersection(own_profile)
    assert other_response.status_code == 403
    assert directory_response.status_code == 403


def test_student_explanation_is_supportive_and_own_profile_only(isolated_client):
    client, _, _ = isolated_client

    own_response = client.post(
        "/api/explain",
        json={"student_id": "TEST-STUDENT-1"},
    )
    other_response = client.post(
        "/api/explain",
        json={"student_id": "TEST-STUDENT-2"},
    )

    assert own_response.status_code == 200
    assert "Your strengths:" in own_response.json()["explanation"]
    assert other_response.status_code == 403


def test_staff_analytics_remain_available_and_faculty_scoped(isolated_client):
    client, active_user, users = isolated_client

    active_user["value"] = users["faculty"]
    faculty_overview = client.get("/api/analytics/overview").json()
    faculty_trends = client.get("/api/analytics/trends").json()
    faculty_segments = client.get("/api/analytics/segments").json()
    faculty_insights = client.get("/api/analytics/insights").json()
    faculty_search = client.get("/api/analytics/search?q=Test%20Student%20Two").json()
    faculty_profile = client.get("/api/students/TEST-STUDENT-1")
    outside_profile = client.get("/api/students/TEST-STUDENT-2")

    assert faculty_overview["total_students"] == 1
    assert sum(item["student_count"] for item in faculty_trends["year_comparison"]) == 1
    assert faculty_segments["total_students"] == 1
    assert faculty_insights["subject_heatmap"][0]["total_enrolled"] == 1
    assert faculty_search["count"] == 0
    assert faculty_profile.status_code == 200
    assert faculty_profile.json()["cohort_averages"]["total_success_score"] == 65.0
    assert "academic_risk_level" in faculty_profile.json()
    assert outside_profile.status_code == 403

    active_user["value"] = users["admin"]
    admin_overview = client.get("/api/analytics/overview")
    assert admin_overview.status_code == 200
    assert admin_overview.json()["total_students"] == 2


def test_only_student_can_create_their_own_mentor_message(isolated_client):
    client, active_user, users = isolated_client
    active_user["value"] = users["faculty"]

    faculty_response = client.post(
        "/api/students/TEST-STUDENT-1/message",
        json={"message": "Should not be accepted as a student message"},
    )
    assert faculty_response.status_code == 403

    active_user["value"] = users["student"]
    own_response = client.post(
        "/api/students/TEST-STUDENT-1/message",
        json={"message": "I would like help with coursework."},
    )
    other_response = client.post(
        "/api/students/TEST-STUDENT-2/message",
        json={"message": "This must not be sent for another student."},
    )
    other_thread_response = client.get("/api/students/TEST-STUDENT-2/messages")

    assert own_response.status_code == 200
    assert other_response.status_code == 403
    assert other_thread_response.status_code == 403

    db = SessionLocal()
    try:
        assert db.query(StudentMentorMessage).count() == 1
    finally:
        db.close()


def test_cors_uses_explicit_trusted_origins(isolated_client):
    client, _, _ = isolated_client

    trusted_response = client.options(
        "/",
        headers={
            "Origin": "https://dashboard.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    untrusted_response = client.options(
        "/",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert trusted_response.headers["access-control-allow-origin"] == "https://dashboard.example"
    assert "access-control-allow-origin" not in untrusted_response.headers
    assert "*" not in trusted_response.headers["access-control-allow-origin"]


def test_frontend_escapes_untrusted_text_before_insertion():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to run the frontend escaping check.")

    helper_path = Path(__file__).resolve().parents[1] / "static" / "js" / "security.js"
    payload = '<img src=x onerror="alert(1)"> &'
    script = (
        f"import {{ escapeHtml }} from {json.dumps(helper_path.as_uri())};"
        f"console.log(JSON.stringify(escapeHtml({json.dumps(payload)})));"
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout) == (
        "&lt;img src=x onerror=&quot;alert(1)&quot;&gt; &amp;"
    )

    app_source = (helper_path.parent / "app.js").read_text(encoding="utf-8")
    for unescaped_interpolation in (
        "${student.name}",
        "${student.student_id}",
        "${student.department}",
        "${sub.subject_name}",
        "${s.name}",
        "${a.description}",
        "${m.message}",
        "${m.reply}",
        "${res.answer}",
        "${err.message}",
    ):
        assert unescaped_interpolation not in app_source


def test_model_cache_path_is_isolated_from_project_cache():
    project_cache = Path(__file__).resolve().parents[1] / "model_cache" / "risk_model.joblib"

    assert ml.MODEL_PATH == Path(os.environ["MODEL_CACHE_PATH"])
    assert ml.MODEL_PATH != project_cache
