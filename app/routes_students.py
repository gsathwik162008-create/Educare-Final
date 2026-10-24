import json
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import case, or_

from app.database import get_db
from app.models import (
    User,
    Student,
    InterventionAction,
    StudentMentorMessage,
    UnifiedStudentMetrics,
    StudentScore,
    FacultyAssignment,
    SemesterHistory,
    SubjectRecord,
    StudentMentorMessage
)
from app.auth import get_current_user, require_role, check_student_access
from app.ml import get_model_metrics
from app.risk import overall_risk_level

router = APIRouter(prefix="/api/students", tags=["students"])


def _current_ml_probability(score: Optional[StudentScore]) -> Optional[float]:
    if score is None or get_model_metrics().get("status") != "trained":
        return None
    return score.ml_risk_probability


class MessageCreate(BaseModel):
    message: str


class MessageReply(BaseModel):
    reply: str


@router.get("")
def list_students(
    search: Optional[str] = None,
    department: Optional[str] = None,
    year: Optional[int] = None,
    risk_level: Optional[str] = None,
    segment: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List students scoped to user role:
    - ADMIN: all students
    - FACULTY: only their assigned cohort
    - STUDENT: 403 Forbidden
    """
    if current_user.role == "STUDENT":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Students may not browse the cohort directory"
        )

    query = db.query(Student).join(StudentScore, Student.student_id == StudentScore.student_id)

    # Scope to faculty's assigned students
    if current_user.role == "FACULTY":
        query = query.filter(
            or_(
                Student.mentor_id == current_user.id,
                Student.student_id.in_(
                    db.query(FacultyAssignment.student_id).filter(FacultyAssignment.faculty_id == current_user.id)
                )
            )
        )

    # Filters
    if department and department != "All":
        query = query.filter(Student.department == department)
    if year and year != 0:
        query = query.filter(Student.year == year)
    if risk_level and risk_level != "All":
        overall_level = case(
            (
                or_(
                    StudentScore.academic_risk_level == "High",
                    StudentScore.placement_risk_level == "High"
                ),
                "High"
            ),
            (
                or_(
                    StudentScore.academic_risk_level == "Medium",
                    StudentScore.placement_risk_level == "Medium"
                ),
                "Medium"
            ),
            else_="Low"
        )
        query = query.filter(overall_level == risk_level)
    if segment and segment != "All":
        query = query.filter(
            or_(
                StudentScore.segment_rule == segment,
                StudentScore.segment_kmeans == segment
            )
        )
    if search:
        search_term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Student.student_id.ilike(search_term),
                Student.name.ilike(search_term),
                Student.department.ilike(search_term)
            )
        )

    total_count = query.count()
    records = query.order_by(StudentScore.total_success_score.asc()).offset((page - 1) * limit).limit(limit).all()

    items = []
    for s in records:
        sc = s.score
        items.append({
            "student_id": s.student_id,
            "name": s.name,
            "department": s.department,
            "year": s.year,
            "semester": s.semester,
            "total_success_score": sc.total_success_score if sc else 0.0,
            "academic_score": sc.academic_score if sc else 0.0,
            "attendance_score": sc.attendance_score if sc else 0.0,
            "placement_score": sc.placement_score if sc else 0.0,
            "lms_score": sc.lms_score if sc else 0.0,
            "skills_feedback_score": sc.skills_feedback_score if sc else 0.0,
            "academic_risk_level": sc.academic_risk_level if sc else "Low",
            "academic_risk_reasons": json.loads(sc.academic_risk_reasons or "[]") if sc else [],
            "placement_risk_level": sc.placement_risk_level if sc else "Low",
            "placement_risk_reasons": json.loads(sc.placement_risk_reasons or "[]") if sc else [],
            "overall_risk_level": overall_risk_level(
                sc.academic_risk_level if sc else "Low",
                sc.placement_risk_level if sc else "Low"
            ),
            "ml_risk_probability": _current_ml_probability(sc),
            "segment_rule": sc.segment_rule if sc else "Unassigned",
            "segment_kmeans": sc.segment_kmeans if sc else "Unassigned",
        })

    return {
        "total": total_count,
        "page": page,
        "limit": limit,
        "students": items
    }


@router.get("/messages/inbox")
def get_message_inbox(
    current_user: User = Depends(require_role(["ADMIN", "FACULTY"])),
    db: Session = Depends(get_db)
):
    """List open student messages visible to staff, newest first."""
    query = db.query(StudentMentorMessage).join(
        Student, Student.student_id == StudentMentorMessage.student_id
    ).filter(StudentMentorMessage.status == "open")

    if current_user.role == "FACULTY":
        query = query.filter(
            or_(
                Student.mentor_id == current_user.id,
                Student.student_id.in_(
                    db.query(FacultyAssignment.student_id).filter(
                        FacultyAssignment.faculty_id == current_user.id
                    )
                )
            )
        )

    messages = query.order_by(
        StudentMentorMessage.created_at.desc(),
        StudentMentorMessage.id.desc()
    ).all()

    for message in messages:
        check_student_access(message.student_id, current_user, db)

    return [
        {
            "id": message.id,
            "student_id": message.student_id,
            "student_name": message.student.name,
            "message": message.message,
            "reply": message.reply,
            "status": message.status,
            "created_at": message.created_at.isoformat() if message.created_at else None
        }
        for message in messages
    ]


@router.get("/{student_id}")
def get_student_profile(
    student_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Retrieve deep profile for student.
    Enforces strict access control:
    - ADMIN: all
    - FACULTY: assigned students only
    - STUDENT: only their own record; student receives supportive framing without risk labels or segments.
    """
    check_student_access(student_id, current_user, db)

    student = db.query(Student).filter(Student.student_id == student_id.strip().upper()).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    m = student.unified_metrics
    sc = student.score

    # Semester history
    semesters = [
        {
            "semester": h.semester,
            "gpa": h.gpa,
            "attendance_pct": h.attendance_pct,
            "credits_earned": h.credits_earned,
            "backlogs": h.backlogs
        }
        for h in sorted(student.semester_histories, key=lambda x: x.semester)
    ]

    # Subject records
    subjects = [
        {
            "semester": sr.semester,
            "subject_code": sr.subject_code,
            "subject_name": sr.subject_name,
            "marks": sr.marks,
            "attendance_pct": sr.attendance_pct,
            "is_backlog": sr.is_backlog
        }
        for sr in sorted(student.subject_records, key=lambda x: x.subject_code)
    ]

    # Mentor info
    mentor_info = {
        "name": student.mentor.faculty_name if student.mentor else "Assigned Faculty Advisor",
        "email": student.mentor.email if student.mentor else "advisor@campus.edu"
    }

    base_response = {
        "student_id": student.student_id,
        "name": student.name,
        "department": student.department,
        "year": student.year,
        "semester": student.semester,
        "email": student.email,
        "mentor": mentor_info,
        "total_success_score": sc.total_success_score if sc else 0.0,
        "academic_score": sc.academic_score if sc else 0.0,
        "attendance_score": sc.attendance_score if sc else 0.0,
        "placement_score": sc.placement_score if sc else 0.0,
        "lms_score": sc.lms_score if sc else 0.0,
        "skills_feedback_score": sc.skills_feedback_score if sc else 0.0,
        "semester_history": semesters,
        "subject_records": subjects,
        "metrics": {
            "cgpa": m.cgpa if m else 0.0,
            "total_backlogs": m.total_backlogs if m else 0,
            "attendance_pct": m.attendance_pct if m else 0.0,
            "aptitude_score": m.aptitude_score if m else 0.0,
            "coding_score": m.coding_score if m else 0.0,
            "mock_interviews_completed": m.mock_interviews_completed if m else 0,
            "assignments_submitted_pct": m.assignments_submitted_pct if m else 0.0,
            "lms_login_count": m.lms_login_count if m else 0,
            "lms_time_spent_hrs": m.lms_time_spent_hrs if m else 0.0,
            "forum_posts_count": m.forum_posts_count if m else 0,
            "event_participation_count": m.event_participation_count if m else 0,
            "library_visits": m.library_visits if m else 0,
            "technical_skills_score": m.technical_skills_score if m else 0.0,
            "soft_skills_score": m.soft_skills_score if m else 0.0,
            "faculty_feedback_score": m.faculty_feedback_score if m else 0.0,
            "peer_feedback_score": m.peer_feedback_score if m else 0.0,
        }
    }

    # STUDENT VIEW: Supportive phrasing without staff-only risk assessments or segments.
    if current_user.role == "STUDENT":
        focus_areas = []
        strengths = []
        if m:
            if m.attendance_pct < 80.0:
                focus_areas.append("Attendance Consistency: Boosting class participation to reach target 85%+")
            else:
                strengths.append(f"Strong attendance record ({m.attendance_pct:.1f}%)")

            if m.coding_score < 60.0:
                focus_areas.append("Coding Practice: Dedicated problem solving on core data structures")
            else:
                strengths.append(f"Solid coding assessment performance ({m.coding_score:.1f} pts)")

            if student.year >= 3 and m.mock_interviews_completed < 2:
                focus_areas.append("Placement Readiness: Completing your 2 recommended mock interview rounds")
            elif m.mock_interviews_completed >= 2:
                strengths.append("Completed recommended mock interview sessions")

            if m.assignments_submitted_pct < 85.0:
                focus_areas.append("Coursework Timeliness: Keeping all lab assignments and quizzes up to date")
            else:
                strengths.append(f"High coursework submission rate ({m.assignments_submitted_pct:.1f}%)")

        base_response["strengths"] = strengths if strengths else ["Consistent engagement with degree curriculum"]
        base_response["focus_areas"] = focus_areas if focus_areas else ["Keep maintaining your steady all-around performance!"]
        base_response["explanation"] = "Your success score is calculated across academics, attendance, practical readiness, coursework, and campus engagement."
        return base_response

    # STAFF VIEW (ADMIN & FACULTY): Full analytical depth, risk flags, ML probabilities, segments
    score_query = db.query(StudentScore)
    if current_user.role == "FACULTY":
        accessible_student_ids = db.query(Student.student_id).filter(
            or_(
                Student.mentor_id == current_user.id,
                Student.student_id.in_(
                    db.query(FacultyAssignment.student_id).filter(
                        FacultyAssignment.faculty_id == current_user.id
                    )
                )
            )
        )
        score_query = score_query.filter(StudentScore.student_id.in_(accessible_student_ids))
    all_scores = score_query.all()
    base_response["cohort_averages"] = {
        "total_success_score": round(sum(s.total_success_score for s in all_scores) / max(len(all_scores), 1), 1),
        "academic_score": round(sum(s.academic_score for s in all_scores) / max(len(all_scores), 1), 1),
        "attendance_score": round(sum(s.attendance_score for s in all_scores) / max(len(all_scores), 1), 1),
        "placement_score": round(sum(s.placement_score for s in all_scores) / max(len(all_scores), 1), 1),
        "lms_score": round(sum(s.lms_score for s in all_scores) / max(len(all_scores), 1), 1),
        "skills_feedback_score": round(sum(s.skills_feedback_score for s in all_scores) / max(len(all_scores), 1), 1),
    }
    base_response["academic_risk_level"] = sc.academic_risk_level if sc else "Low"
    base_response["academic_risk_reasons"] = json.loads(sc.academic_risk_reasons or "[]") if sc else []
    base_response["placement_risk_level"] = sc.placement_risk_level if sc else "Low"
    base_response["placement_risk_reasons"] = json.loads(sc.placement_risk_reasons or "[]") if sc else []
    base_response["ml_risk_probability"] = _current_ml_probability(sc)
    base_response["segment_rule"] = sc.segment_rule if sc else "Unassigned"
    base_response["segment_kmeans"] = sc.segment_kmeans if sc else "Unassigned"
    base_response["score_explanation"] = sc.score_explanation if sc else ""
    activity_history = []
    for action in db.query(InterventionAction).filter(
        InterventionAction.student_id == student.student_id
    ).all():
        action_details = action.description
        if action.notes:
            action_details = f"{action_details} — Notes: {action.notes}"
        if action.created_at:
            activity_history.append({
                "date": action.created_at.isoformat(),
                "type": "Advisor support assigned",
                "status": "created",
                "details": action_details,
            })
        if action.updated_at and action.updated_at != action.created_at:
            activity_history.append({
                "date": action.updated_at.isoformat(),
                "type": "Advisor support updated",
                "status": action.status,
                "details": action_details,
            })
        if action.completed_at:
            activity_history.append({
                "date": action.completed_at.isoformat(),
                "type": "Advisor support completed",
                "status": "done",
                "details": action.description,
            })

    for message in db.query(StudentMentorMessage).filter(
        StudentMentorMessage.student_id == student.student_id
    ).all():
        if message.created_at:
            activity_history.append({
                "date": message.created_at.isoformat(),
                "type": "Student message",
                "status": message.status,
                "details": message.message,
            })
        if (
            message.reply
            and message.updated_at
            and message.created_at
            and message.updated_at != message.created_at
        ):
            activity_history.append({
                "date": message.updated_at.isoformat(),
                "type": "Advisor reply",
                "status": message.status,
                "details": message.reply,
            })

    activity_history.sort(key=lambda item: item["date"])
    last_activity_at = activity_history[-1]["date"] if activity_history else None
    days_since_last_activity = None
    if last_activity_at:
        latest_activity = datetime.fromisoformat(last_activity_at)
        if latest_activity.tzinfo is None:
            latest_activity = latest_activity.replace(tzinfo=timezone.utc)
        days_since_last_activity = max(
            0,
            (datetime.now(timezone.utc) - latest_activity).days,
        )
    base_response["activity_history"] = activity_history
    base_response["last_activity_at"] = last_activity_at
    base_response["days_since_last_activity"] = days_since_last_activity
    base_response["last_record_updated"] = m.last_updated.isoformat() if m and m.last_updated else None

    return base_response


@router.post("/{student_id}/message")
def send_mentor_message(
    student_id: str,
    payload: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Student submits a message/question to their mentor ("Ask my mentor")."""
    if current_user.role != "STUDENT":
        raise HTTPException(status_code=403, detail="Only students may send mentor messages")

    check_student_access(student_id, current_user, db)

    student = db.query(Student).filter(Student.student_id == student_id.strip().upper()).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    msg = StudentMentorMessage(
        student_id=student.student_id,
        mentor_id=student.mentor_id,
        message=payload.message.strip(),
        status="open",
        created_at=datetime.now(timezone.utc)
    )
    db.add(msg)
    db.commit()
    return {"status": "success", "message_id": msg.id, "created_at": msg.created_at}


@router.get("/{student_id}/messages")
def get_student_messages(
    student_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Retrieve message thread between student and mentor."""
    check_student_access(student_id, current_user, db)

    msgs = db.query(StudentMentorMessage).filter(
        StudentMentorMessage.student_id == student_id.strip().upper()
    ).order_by(StudentMentorMessage.created_at.desc()).all()

    return [
        {
            "id": m.id,
            "student_id": m.student_id,
            "message": m.message,
            "reply": m.reply,
            "status": m.status,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "updated_at": m.updated_at.isoformat() if m.updated_at else None
        }
        for m in msgs
    ]


@router.patch("/messages/{message_id}/reply")
def reply_mentor_message(
    message_id: int,
    payload: MessageReply,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Faculty or Admin replies to student message."""
    if current_user.role not in ["ADMIN", "FACULTY"]:
        raise HTTPException(status_code=403, detail="Only faculty and admin may post replies")

    msg = db.query(StudentMentorMessage).filter(StudentMentorMessage.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    check_student_access(msg.student_id, current_user, db)

    msg.reply = payload.reply.strip()
    msg.status = "resolved"
    msg.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "success", "message_id": msg.id}
