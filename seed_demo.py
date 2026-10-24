"""Initialize isolated local-only EduCare demo data."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


DEMO_ACCOUNTS = (
    {
        "username": "demo_admin",
        "password": "EduCare-Admin-Demo-2026!",
        "role": "ADMIN",
        "faculty_name": "Demo Administrator",
        "student_id": None,
        "email": "demo.admin@example.edu",
    },
    {
        "username": "demo_faculty_cse",
        "password": "EduCare-Faculty-CSE-2026!",
        "role": "FACULTY",
        "faculty_name": "Asha Mehta",
        "student_id": None,
        "email": "asha.mehta@example.edu",
    },
    {
        "username": "demo_faculty_ece",
        "password": "EduCare-Faculty-ECE-2026!",
        "role": "FACULTY",
        "faculty_name": "Rohan Iyer",
        "student_id": None,
        "email": "rohan.iyer@example.edu",
    },
    {
        "username": "DEMO-CSE-001",
        "password": "EduCare-Student-01-2026!",
        "role": "STUDENT",
        "faculty_name": None,
        "student_id": "DEMO-CSE-001",
        "email": "demo.cse001@example.edu",
    },
    {
        "username": "DEMO-CSE-002",
        "password": "EduCare-Student-02-2026!",
        "role": "STUDENT",
        "faculty_name": None,
        "student_id": "DEMO-CSE-002",
        "email": "demo.cse002@example.edu",
    },
    {
        "username": "DEMO-ECE-001",
        "password": "EduCare-Student-03-2026!",
        "role": "STUDENT",
        "faculty_name": None,
        "student_id": "DEMO-ECE-001",
        "email": "demo.ece001@example.edu",
    },
    {
        "username": "DEMO-ECE-002",
        "password": "EduCare-Student-04-2026!",
        "role": "STUDENT",
        "faculty_name": None,
        "student_id": "DEMO-ECE-002",
        "email": "demo.ece002@example.edu",
    },
)

DEMO_STUDENTS = (
    {
        "student_id": "DEMO-CSE-001",
        "name": "Nisha Kapoor",
        "department": "CSE",
        "year": 3,
        "semester": 5,
        "email": "demo.cse001@example.edu",
        "faculty_username": "demo_faculty_cse",
        "metrics": {
            "cgpa": 8.7,
            "total_backlogs": 0,
            "attendance_pct": 92.0,
            "lms_login_count": 142,
            "lms_time_spent_hrs": 63.5,
            "assignments_submitted_pct": 96.0,
            "forum_posts_count": 12,
            "event_participation_count": 4,
            "library_visits": 18,
            "aptitude_score": 82.0,
            "coding_score": 86.0,
            "mock_interviews_completed": 3,
            "technical_skills_score": 88.0,
            "soft_skills_score": 84.0,
            "faculty_feedback_score": 87.0,
            "peer_feedback_score": 85.0,
        },
        "gpa_history": (7.4, 7.7, 8.0, 8.4, 8.7),
        "attendance_history": (84.0, 86.0, 88.0, 90.0, 92.0),
        "backlog_history": (0, 0, 0, 0, 0),
        "subjects": (
            ("CS301", "Data Structures", 88.0, 92.0, False),
            ("CS305", "Database Systems", 91.0, 95.0, False),
        ),
    },
    {
        "student_id": "DEMO-CSE-002",
        "name": "Arjun Rao",
        "department": "CSE",
        "year": 3,
        "semester": 5,
        "email": "demo.cse002@example.edu",
        "faculty_username": "demo_faculty_cse",
        "metrics": {
            "cgpa": 6.8,
            "total_backlogs": 1,
            "attendance_pct": 73.0,
            "lms_login_count": 78,
            "lms_time_spent_hrs": 34.0,
            "assignments_submitted_pct": 76.0,
            "forum_posts_count": 4,
            "event_participation_count": 1,
            "library_visits": 8,
            "aptitude_score": 58.0,
            "coding_score": 54.0,
            "mock_interviews_completed": 1,
            "technical_skills_score": 62.0,
            "soft_skills_score": 68.0,
            "faculty_feedback_score": 72.0,
            "peer_feedback_score": 70.0,
        },
        "gpa_history": (6.4, 6.5, 6.6, 6.7, 6.8),
        "attendance_history": (78.0, 77.0, 76.0, 74.0, 73.0),
        "backlog_history": (0, 0, 0, 1, 1),
        "subjects": (
            ("CS301", "Data Structures", 67.0, 74.0, False),
            ("CS305", "Database Systems", 58.0, 69.0, True),
        ),
    },
    {
        "student_id": "DEMO-ECE-001",
        "name": "Meera Nair",
        "department": "ECE",
        "year": 4,
        "semester": 7,
        "email": "demo.ece001@example.edu",
        "faculty_username": "demo_faculty_ece",
        "metrics": {
            "cgpa": 5.2,
            "total_backlogs": 2,
            "attendance_pct": 67.0,
            "lms_login_count": 41,
            "lms_time_spent_hrs": 17.5,
            "assignments_submitted_pct": 58.0,
            "forum_posts_count": 1,
            "event_participation_count": 0,
            "library_visits": 4,
            "aptitude_score": 44.0,
            "coding_score": 33.0,
            "mock_interviews_completed": 0,
            "technical_skills_score": 46.0,
            "soft_skills_score": 55.0,
            "faculty_feedback_score": 58.0,
            "peer_feedback_score": 60.0,
        },
        "gpa_history": (6.7, 6.4, 6.1, 5.9, 5.7, 5.5, 5.2),
        "attendance_history": (76.0, 74.0, 72.0, 71.0, 69.0, 68.0, 67.0),
        "backlog_history": (0, 0, 0, 1, 1, 2, 2),
        "subjects": (
            ("EC701", "Digital Signal Processing", 52.0, 66.0, False),
            ("EC705", "Wireless Communications", 41.0, 58.0, True),
        ),
    },
    {
        "student_id": "DEMO-ECE-002",
        "name": "Kabir Shah",
        "department": "ECE",
        "year": 2,
        "semester": 3,
        "email": "demo.ece002@example.edu",
        "faculty_username": "demo_faculty_ece",
        "metrics": {
            "cgpa": 7.6,
            "total_backlogs": 0,
            "attendance_pct": 85.0,
            "lms_login_count": 109,
            "lms_time_spent_hrs": 46.0,
            "assignments_submitted_pct": 88.0,
            "forum_posts_count": 7,
            "event_participation_count": 2,
            "library_visits": 12,
            "aptitude_score": 72.0,
            "coding_score": 69.0,
            "mock_interviews_completed": 0,
            "technical_skills_score": 76.0,
            "soft_skills_score": 73.0,
            "faculty_feedback_score": 78.0,
            "peer_feedback_score": 75.0,
        },
        "gpa_history": (7.1, 7.3, 7.6),
        "attendance_history": (81.0, 83.0, 85.0),
        "backlog_history": (0, 0, 0),
        "subjects": (
            ("EC201", "Circuit Analysis", 79.0, 86.0, False),
            ("EC203", "Electronic Devices", 82.0, 88.0, False),
        ),
    },
)


def _validate_database_url(database_url: str):
    url = make_url(database_url)
    if url.drivername != "sqlite" or not url.database or url.database == ":memory:":
        raise ValueError("Demo initialization requires a file-backed SQLite demo database.")

    database_path = Path(url.database).expanduser().resolve()
    if database_path.name.casefold() != "campus_demo.db":
        raise ValueError(
            "Refusing to seed this path. Use a dedicated file named campus_demo.db; "
            "the existing campus.db is never a demo target."
        )
    if database_path.name.casefold() == "campus.db":
        raise ValueError("Refusing to seed the existing campus.db.")
    return url, database_path


def _validate_already_seeded(db: Session, expected_users: dict[str, dict[str, Any]]) -> None:
    from app.auth import verify_password
    from app.models import (
        FacultyAssignment,
        SemesterHistory,
        Student,
        StudentScore,
        SubjectRecord,
        UnifiedStudentMetrics,
        User,
    )

    users = db.query(User).all()
    if {user.username for user in users} != set(expected_users):
        raise RuntimeError(
            "The demo database contains a partial or non-demo account set; "
            "no existing accounts were changed."
        )
    for user in users:
        expected = expected_users[user.username]
        if (
            user.role != expected["role"]
            or user.student_id != expected["student_id"]
            or user.faculty_name != expected["faculty_name"]
            or user.email != expected["email"]
            or not verify_password(expected["password"], user.hashed_password)
        ):
            raise RuntimeError(
                f"Existing account {user.username!r} differs from the local demo definition; "
                "no existing accounts were changed."
            )

    student_ids = {student["student_id"] for student in DEMO_STUDENTS}
    if {student.student_id for student in db.query(Student).all()} != student_ids:
        raise RuntimeError("The demo database student set is incomplete or contains extra records.")
    if db.query(FacultyAssignment).count() != 4:
        raise RuntimeError("The demo faculty assignments are incomplete or contain extra records.")
    if db.query(UnifiedStudentMetrics).count() != 4 or db.query(StudentScore).count() != 4:
        raise RuntimeError("The demo analytics records are incomplete or contain extra records.")
    expected_history_count = sum(len(student["gpa_history"]) for student in DEMO_STUDENTS)
    if db.query(SemesterHistory).count() != expected_history_count:
        raise RuntimeError("The demo semester history is incomplete or contains extra records.")
    if db.query(SubjectRecord).count() != sum(len(s["subjects"]) for s in DEMO_STUDENTS):
        raise RuntimeError("The demo subject records are incomplete or contain extra records.")


def initialize_demo_database(database_url: str) -> str:
    if os.getenv("EDUCARE_ENABLE_DEMO_SEED") != "1":
        raise RuntimeError(
            "Demo initialization is disabled. Set EDUCARE_ENABLE_DEMO_SEED=1 explicitly "
            "for local development before running this script."
        )

    url, database_path = _validate_database_url(database_url)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    from app.database import Base
    from app.models import (
        FacultyAssignment,
        SemesterHistory,
        Student,
        StudentScore,
        SubjectRecord,
        UnifiedStudentMetrics,
        User,
    )
    from app.auth import hash_password
    from app.analytics_pipeline import run_full_analytics_pipeline

    engine = create_engine(
        url,
        connect_args={"check_same_thread": False},
    )
    try:
        Base.metadata.create_all(bind=engine)
        expected_users = {account["username"]: account for account in DEMO_ACCOUNTS}
        with Session(engine) as db, db.begin():
            existing_users = db.query(User).count()
            existing_students = db.query(Student).count()
            if existing_users or existing_students:
                if existing_users == len(DEMO_ACCOUNTS):
                    _validate_already_seeded(db, expected_users)
                    return "already_initialized"
                raise RuntimeError(
                    "The demo database is not empty. Existing records were preserved; "
                    "use a dedicated empty campus_demo.db."
                )

            user_by_name: dict[str, User] = {}
            for account in DEMO_ACCOUNTS:
                user = User(
                    username=account["username"],
                    hashed_password=hash_password(account["password"]),
                    role=account["role"],
                    faculty_name=account["faculty_name"],
                    student_id=account["student_id"],
                    email=account["email"],
                )
                db.add(user)
                user_by_name[user.username] = user
            db.flush()

            for record in DEMO_STUDENTS:
                mentor = user_by_name[record["faculty_username"]]
                student = Student(
                    student_id=record["student_id"],
                    name=record["name"],
                    department=record["department"],
                    year=record["year"],
                    semester=record["semester"],
                    email=record["email"],
                    mentor_id=mentor.id,
                )
                db.add(student)
                db.add(FacultyAssignment(
                    faculty_id=mentor.id,
                    student_id=student.student_id,
                ))
                db.add(UnifiedStudentMetrics(
                    student_id=student.student_id,
                    **record["metrics"],
                ))

                for semester, (gpa, attendance, backlogs) in enumerate(
                    zip(
                        record["gpa_history"],
                        record["attendance_history"],
                        record["backlog_history"],
                    ),
                    start=1,
                ):
                    db.add(SemesterHistory(
                        student_id=student.student_id,
                        semester=semester,
                        gpa=gpa,
                        attendance_pct=attendance,
                        credits_earned=20 if semester < record["semester"] else 18,
                        backlogs=backlogs,
                    ))

                for code, name, marks, attendance, is_backlog in record["subjects"]:
                    db.add(SubjectRecord(
                        student_id=student.student_id,
                        semester=record["semester"],
                        subject_code=code,
                        subject_name=name,
                        marks=marks,
                        attendance_pct=attendance,
                        is_backlog=is_backlog,
                    ))

            db.flush()
            run_full_analytics_pipeline(db, persist_model_cache=False)
        return "created"
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create local EduCare demo accounts and synthetic student records."
    )
    parser.add_argument(
        "--database-url",
        required=True,
        help="Dedicated file-backed SQLite URL, e.g. sqlite:///./campus_demo.db",
    )
    args = parser.parse_args()
    result = initialize_demo_database(args.database_url)
    if result == "created":
        print("Created 7 local demo accounts and their synthetic student records.")
    else:
        print("The 7 local demo accounts and records are already initialized; no changes made.")


if __name__ == "__main__":
    main()
