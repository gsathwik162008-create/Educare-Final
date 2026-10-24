from typing import Tuple, List
from app.models import UnifiedStudentMetrics


def overall_risk_level(academic_level: str, placement_level: str) -> str:
    """Return the highest support level across academics and placement readiness."""
    levels = {"Low": 0, "Medium": 1, "High": 2}
    highest = max(
        levels.get(academic_level, 0),
        levels.get(placement_level, 0)
    )
    return {value: key for key, value in levels.items()}[highest]


def evaluate_academic_risk(
    metrics: UnifiedStudentMetrics,
    year: int = 3,
    trend: str = "stable"
) -> Tuple[str, List[str]]:
    """
    Evaluates rule-based Academic Risk (Low, Medium, High) and collects specific reasons.
    """
    cgpa = float(metrics.cgpa or 0.0)
    att = float(metrics.attendance_pct or 0.0)
    backlogs = int(metrics.total_backlogs or 0)

    reasons: List[str] = []

    if cgpa < 5.0:
        reasons.append(f"Critical CGPA {cgpa:.2f} (< 5.0 minimum requirement)")
    elif cgpa < 6.0:
        reasons.append(f"CGPA {cgpa:.2f} below benchmark threshold of 6.0")

    if att < 65.0:
        reasons.append(f"Critical attendance {att:.1f}% (< 65% exam condonation limit)")
    elif att < 75.0:
        reasons.append(f"Attendance {att:.1f}% below required 75% mandatory threshold")

    if backlogs >= 2:
        reasons.append(f"Multiple active backlogs ({backlogs}) pending clearance")
    elif backlogs == 1:
        reasons.append("1 active backlog pending clearance")

    if trend == "falling":
        reasons.append("Declining semester-over-semester GPA trajectory")

    if cgpa < 5.0 or att < 65.0 or backlogs >= 2:
        level = "High"
    elif cgpa < 6.0 or att < 75.0 or backlogs == 1:
        level = "Medium"
    else:
        level = "Low"

    return level, reasons


def evaluate_placement_risk(
    metrics: UnifiedStudentMetrics,
    year: int = 3
) -> Tuple[str, List[str]]:
    """
    Evaluates rule-based Placement Readiness Risk (Low, Medium, High).
    """
    code = float(metrics.coding_score or 0.0)
    apt = float(metrics.aptitude_score or 0.0)
    mocks = int(metrics.mock_interviews_completed or 0)
    tech = float(metrics.technical_skills_score or 0.0)

    reasons: List[str] = []

    if code < 40.0:
        reasons.append(f"Coding benchmark {code:.1f} below hiring cutoff (needs 40)")
    if apt < 50.0:
        reasons.append(f"Aptitude score {apt:.1f} below hiring benchmark (needs 50)")

    if year >= 3 and mocks == 0:
        reasons.append(f"0 mock interviews completed in Year {year}")
    elif year >= 3 and mocks == 1:
        reasons.append("Only 1 mock interview completed (recommended: 2+)")

    if tech < 50.0:
        reasons.append(f"Technical skills assessment low ({tech:.1f}/100)")

    if code < 35.0 or (year >= 3 and mocks == 0 and code < 45.0):
        level = "High"
    elif code < 40.0 or apt < 50.0 or (year >= 3 and mocks == 0) or tech < 50.0:
        level = "Medium"
    else:
        level = "Low"

    return level, reasons


def build_risk_summary(
    acad_level: str,
    acad_reasons: List[str],
    place_level: str,
    place_reasons: List[str]
) -> str:
    """Creates concise plain-English explanation for support needs."""
    clauses = []
    if acad_level in ["High", "Medium"] and acad_reasons:
        urg = "Urgent" if acad_level == "High" else "Soon"
        clauses.append(f"Studies need support ({urg}): {', '.join(acad_reasons[:2])}")
    if place_level in ["High", "Medium"] and place_reasons:
        urg = "Urgent" if place_level == "High" else "Soon"
        clauses.append(f"Job readiness needs support ({urg}): {', '.join(place_reasons[:2])}")

    if not clauses:
        return "Student is doing fine across studies and job readiness."
    return "; ".join(clauses) + "."
