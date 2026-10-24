import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

_TEST_DIRECTORY = tempfile.TemporaryDirectory(prefix="educare-phase7-tests-")
_TEST_ROOT = Path(_TEST_DIRECTORY.name)
os.environ["DATABASE_URL"] = f"sqlite:///{(_TEST_ROOT / 'phase7.db').as_posix()}"
os.environ["MODEL_CACHE_PATH"] = str(_TEST_ROOT / "model-cache" / "risk_model.joblib")
os.environ["SECRET_KEY"] = "phase-seven-isolated-test-secret-not-production"

from app.auth import get_current_user
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import Student, StudentScore, UnifiedStudentMetrics


@pytest.fixture(scope="session", autouse=True)
def cleanup_isolated_resources():
    yield
    app.dependency_overrides.clear()
    engine.dispose()
    _TEST_DIRECTORY.cleanup()


@pytest.fixture
def isolated_department_data():
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    students = [
        ("CSE-1", "CSE", 1, "High", "Low"),
        ("CS-2", "computer science", 2, "Low", "Low"),
        ("ECE-1", "ECE", 1, "Low", "Medium"),
        ("CIVIL-2", "Civil Engineering", 2, "Low", "Low"),
    ]
    for index, (student_id, department, year, academic_risk, placement_risk) in enumerate(students):
        db.add(Student(
            student_id=student_id,
            name=f"Chart Student {index + 1}",
            department=department,
            year=year,
            semester=year * 2,
        ))
        db.add(UnifiedStudentMetrics(
            student_id=student_id,
            attendance_pct=75.0 + index,
        ))
        db.add(StudentScore(
            student_id=student_id,
            total_success_score=60.0 + index,
            academic_score=65.0,
            attendance_score=75.0,
            placement_score=60.0,
            academic_risk_level=academic_risk,
            placement_risk_level=placement_risk,
        ))
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


def _department_rows(client, **params):
    response = client.get("/api/analytics/overview", params=params)
    assert response.status_code == 200
    return response.json()["department_heatmap"]


def test_overview_includes_all_departments_and_normalizes_aliases(isolated_department_data):
    with TestClient(app) as client:
        rows = _department_rows(client)

    assert [row["department"] for row in rows] == ["Civil", "CSE", "ECE"]
    assert {row["department"]: row["student_count"] for row in rows} == {
        "Civil": 1,
        "CSE": 2,
        "ECE": 1,
    }
    assert next(row for row in rows if row["department"] == "CSE")["risk_counts"] == {
        "High": 1,
        "Medium": 0,
        "Low": 1,
    }


def test_overview_returns_one_department_when_selected(isolated_department_data):
    with TestClient(app) as client:
        rows = _department_rows(client, department="CSE")

    assert len(rows) == 1
    assert rows[0]["department"] == "CSE"
    assert rows[0]["student_count"] == 2


def test_overview_department_and_year_filters_limit_chart_data(isolated_department_data):
    with TestClient(app) as client:
        rows = _department_rows(client, department="computer science", year=2)

    assert len(rows) == 1
    assert rows[0]["department"] == "CSE"
    assert rows[0]["student_count"] == 1


def test_overview_year_filter_updates_all_matching_departments(isolated_department_data):
    with TestClient(app) as client:
        rows = _department_rows(client, year=2)

    assert [row["department"] for row in rows] == ["Civil", "CSE"]
    assert all(row["student_count"] == 1 for row in rows)


def test_overview_returns_no_department_rows_for_empty_filter(isolated_department_data):
    with TestClient(app) as client:
        rows = _department_rows(client, department="EEE", year=4)

    assert rows == []


def test_department_chart_has_empty_state_and_bounded_stacked_bars():
    root = Path(__file__).resolve().parents[1]
    app_source = (root / "static" / "js" / "app.js").read_text(encoding="utf-8")
    css_source = (root / "static" / "css" / "style.css").read_text(encoding="utf-8")

    assert "No department data matches the selected filters." in app_source
    assert "updateDepartmentChart(filteredData.department_heatmap)" in app_source
    assert "comparison is limited." in app_source
    assert "maxBarThickness: 68" in app_source
    assert 'chart.canvas.id === "chart-dept-overview"' in app_source
    assert "value <= 0" in app_source
    assert "const segmentBottom = Math.max(element.y, element.base)" in app_source
    assert "x: rightFits ? rightEdge + 5 : leftEdge - 5" in app_source
    assert "context.textAlign = item.direction > 0 ? \"left\" : \"right\"" in app_source
    assert 'grace: "20%"' in app_source
    assert "strokeText(item.label, x, y)" in app_source
    assert ".chart-box-department" in css_source
