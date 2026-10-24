import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

_TEST_DIRECTORY = tempfile.TemporaryDirectory(prefix="educare-phase5-tests-")
_TEST_ROOT = Path(_TEST_DIRECTORY.name)
os.environ["DATABASE_URL"] = f"sqlite:///{(_TEST_ROOT / 'phase5.db').as_posix()}"
os.environ["MODEL_CACHE_PATH"] = str(_TEST_ROOT / "model-cache" / "risk_model.joblib")
os.environ["SECRET_KEY"] = "phase-five-isolated-test-secret-not-production"

from app.auth import get_current_user
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import Student, StudentScore


def _get_students(client, **params):
    response = client.get("/api/students", params=params)
    assert response.status_code == 200
    return response.json()["students"]


def test_overall_status_filters_use_highest_domain_risk(isolated_student_filter_data):
    with TestClient(app) as client:
        urgent = _get_students(client, risk_level="High")
        soon = _get_students(client, risk_level="Medium")
        doing_fine = _get_students(client, risk_level="Low")

    assert {student["student_id"] for student in urgent} == {"S-HIGH-ACADEMIC", "S-HIGH-PLACEMENT"}
    assert {student["student_id"] for student in soon} == {"S-MEDIUM-ACADEMIC", "S-MEDIUM-PLACEMENT"}
    assert {student["student_id"] for student in doing_fine} == {"S-LOW-CSE", "S-LOW-ECE"}
    assert all(student["overall_risk_level"] == "High" for student in urgent)
    assert all(student["overall_risk_level"] == "Medium" for student in soon)
    assert all(student["overall_risk_level"] == "Low" for student in doing_fine)


def test_status_filters_combine_with_department_and_search(isolated_student_filter_data):
    with TestClient(app) as client:
        cse_fine = _get_students(
            client,
            risk_level="Low",
            department="CSE",
        )
        searched_urgent = _get_students(
            client,
            risk_level="High",
            department="ECE",
            search="Placement urgent",
        )

    assert [student["student_id"] for student in cse_fine] == ["S-LOW-CSE"]
    assert [student["student_id"] for student in searched_urgent] == ["S-HIGH-PLACEMENT"]
    assert searched_urgent[0]["overall_risk_level"] == "High"


def test_support_list_uses_api_canonical_status_for_badges_and_sends_filter():
    app_source = (Path(__file__).resolve().parents[1] / "static" / "js" / "app.js").read_text(
        encoding="utf-8"
    )

    assert "risk_level: riskSelect.value" in app_source
    assert "getAttentionBadgeHtml(s.overall_risk_level)" in app_source

@pytest.fixture
def isolated_student_filter_data():
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    db.add_all([
        Student(
            student_id="S-HIGH-ACADEMIC",
            name="Academic urgent student",
            department="CSE",
            year=3,
            semester=5,
        ),
        Student(
            student_id="S-HIGH-PLACEMENT",
            name="Placement urgent student",
            department="ECE",
            year=3,
            semester=5,
        ),
        Student(
            student_id="S-MEDIUM-ACADEMIC",
            name="Academic soon student",
            department="CSE",
            year=2,
            semester=3,
        ),
        Student(
            student_id="S-MEDIUM-PLACEMENT",
            name="Placement soon student",
            department="ECE",
            year=2,
            semester=3,
        ),
        Student(
            student_id="S-LOW-CSE",
            name="CSE fine student",
            department="CSE",
            year=1,
            semester=1,
        ),
        Student(
            student_id="S-LOW-ECE",
            name="ECE fine student",
            department="ECE",
            year=1,
            semester=1,
        ),
    ])
    db.flush()
    db.add_all([
        StudentScore(student_id="S-HIGH-ACADEMIC", academic_risk_level="High", placement_risk_level="Low"),
        StudentScore(student_id="S-HIGH-PLACEMENT", academic_risk_level="Low", placement_risk_level="High"),
        StudentScore(student_id="S-MEDIUM-ACADEMIC", academic_risk_level="Medium", placement_risk_level="Low"),
        StudentScore(student_id="S-MEDIUM-PLACEMENT", academic_risk_level="Low", placement_risk_level="Medium"),
        StudentScore(student_id="S-LOW-CSE", academic_risk_level="Low", placement_risk_level="Low"),
        StudentScore(student_id="S-LOW-ECE", academic_risk_level="Low", placement_risk_level="Low"),
    ])
    db.commit()
    db.close()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=1,
        role="ADMIN",
        student_id=None,
    )

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
