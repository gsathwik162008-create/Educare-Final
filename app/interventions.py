from typing import List, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session

from app.models import Student, UnifiedStudentMetrics, StudentScore, InterventionAction


def generate_candidate_actions(
    student: Student,
    m: UnifiedStudentMetrics,
    score: StudentScore
) -> List[Dict[str, Any]]:
    """
    Evaluates fixable performance gaps and generates targeted action recommendations
    with potential score gains, urgency, and composite priority.
    """
    candidates = []

    cgpa = float(m.cgpa or 0.0)
    backlogs = int(m.total_backlogs or 0)
    att = float(m.attendance_pct or 0.0)
    code = float(m.coding_score or 0.0)
    assigns = float(m.assignments_submitted_pct or 0.0)
    mocks = int(m.mock_interviews_completed or 0)
    soft = float(m.soft_skills_score or 0.0)
    total_score = float(score.total_success_score or 50.0)
    year = int(student.year or 3)

    # Urgency metric: scales from 1.0 to 5.0
    # Higher urgency for lower overall score, upperclassmen (Years 3 & 4), and active backlogs
    urgency_raw = 1.0 + ((100.0 - total_score) / 28.0)
    if year >= 3:
        urgency_raw += 1.2
    if backlogs > 0:
        urgency_raw += 0.8
    if att < 75.0:
        urgency_raw += 0.6
    urgency = round(min(5.0, max(1.0, urgency_raw)), 2)

    # 1. Attendance Gap
    if att < 80.0:
        gain = round(min(12.0, max(3.0, (85.0 - att) * 0.4)), 1)
        candidates.append({
            "action_type": "attendance_alert",
            "description": f"Schedule a 1-on-1 check-in with {student.name} about class attendance (current: {round(att)}%).",
            "potential_gain": gain,
            "urgency": urgency,
            "priority": round(gain * urgency, 1)
        })

    # 2. Coding Readiness Gap
    if code < 60.0:
        gain = round(min(15.0, max(4.0, (75.0 - code) * 0.35)), 1)
        candidates.append({
            "action_type": "coding_bootcamp",
            "description": f"Invite {student.name} to hands-on coding practice sessions (current: {round(code)} out of 100).",
            "potential_gain": gain,
            "urgency": urgency,
            "priority": round(gain * urgency, 1)
        })

    # 3. Placement Mock Interview Gap
    if year >= 3 and mocks < 2:
        needed = 2 - mocks
        gain = round(float(needed * 5.5), 1)
        candidates.append({
            "action_type": "mock_interview_prep",
            "description": f"Schedule {needed} mock job interview session(s) with campus advisors.",
            "potential_gain": gain,
            "urgency": urgency,
            "priority": round(gain * urgency, 1)
        })

    # 4. Academic Tutoring & Backlog Remediation
    if backlogs > 0 or cgpa < 6.2:
        gain = round(min(14.0, max(4.0, backlogs * 4.5 + max(0.0, (6.5 - cgpa) * 3.0))), 1)
        candidates.append({
            "action_type": "academic_remediation",
            "description": f"Pair {student.name} with a peer tutor to clear {backlogs} course backlog(s).",
            "potential_gain": gain,
            "urgency": urgency,
            "priority": round(gain * urgency, 1)
        })

    # 5. Coursework & LMS Submission Catch-up
    if assigns < 80.0:
        gain = round(min(8.0, max(2.5, (85.0 - assigns) * 0.25)), 1)
        candidates.append({
            "action_type": "lms_catchup",
            "description": f"Support {student.name} in submitting overdue homework on the online portal.",
            "potential_gain": gain,
            "urgency": urgency,
            "priority": round(gain * urgency, 1)
        })

    # 6. Soft Skills & Career Counseling Check-in
    if soft < 65.0:
        gain = round(min(6.0, max(2.0, (75.0 - soft) * 0.2)), 1)
        candidates.append({
            "action_type": "counselor_checkin",
            "description": f"Refer {student.name} to Department Career Counselor for soft-skills workshop and communication confidence building.",
            "potential_gain": gain,
            "urgency": urgency,
            "priority": round(gain * urgency, 1)
        })

    # Sort descending by priority (gain * urgency)
    candidates.sort(key=lambda x: x["priority"], reverse=True)
    # Pick top 2 most impactful fixable gaps
    return candidates[:2]


def refresh_interventions_for_all(db: Session) -> int:
    """
    Populates intervention actions for students needing support.
    Preserves in-progress and completed actions while updating pending recommendations.
    """
    students = db.query(Student).all()
    metrics_map = {m.student_id: m for m in db.query(UnifiedStudentMetrics).all()}
    scores_map = {s.student_id: s for s in db.query(StudentScore).all()}

    existing_actions = db.query(InterventionAction).all()
    actions_by_student: Dict[str, List[InterventionAction]] = {}
    for action in existing_actions:
        actions_by_student.setdefault(action.student_id, []).append(action)

    created_count = 0
    for s in students:
        m = metrics_map.get(s.student_id)
        score = scores_map.get(s.student_id)
        if not m or not score:
            continue

        recs = generate_candidate_actions(s, m, score)
        pending_by_type = {
            action.action_type: action
            for action in actions_by_student.get(s.student_id, [])
            if action.status == "pending"
        }
        for rec in recs:
            action = pending_by_type.pop(rec["action_type"], None)
            if action is None:
                action = InterventionAction(
                    student_id=s.student_id,
                    mentor_id=s.mentor_id,
                    action_type=rec["action_type"],
                    description=rec["description"],
                    potential_gain=rec["potential_gain"],
                    urgency=rec["urgency"],
                    priority=rec["priority"],
                    status="pending",
                    notes="",
                    score_at_creation=float(score.total_success_score)
                )
                db.add(action)
                created_count += 1
                continue

            action.mentor_id = s.mentor_id
            action.description = rec["description"]
            action.potential_gain = rec["potential_gain"]
            action.urgency = rec["urgency"]
            action.priority = rec["priority"]
            action.updated_at = datetime.now()

        for obsolete_action in pending_by_type.values():
            if (obsolete_action.notes or "").strip():
                obsolete_action.description = (
                    "This action is no longer among the current top recommendations. "
                    "Review the advisor notes before closing it."
                )
                obsolete_action.potential_gain = 0.0
                obsolete_action.urgency = 0.0
                obsolete_action.priority = 0.0
                obsolete_action.updated_at = datetime.now()
            else:
                db.delete(obsolete_action)

    db.flush()
    return created_count
