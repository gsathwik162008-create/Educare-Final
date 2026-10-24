from datetime import datetime, timezone
from sqlalchemy import Column, Index, Integer, String, Float, Boolean, DateTime, ForeignKey, Text, text
from sqlalchemy.orm import relationship
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False)  # ADMIN, FACULTY, STUDENT
    faculty_name = Column(String(100), nullable=True)
    student_id = Column(String(50), nullable=True, index=True)
    email = Column(String(120), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    assignments = relationship("FacultyAssignment", back_populates="faculty", cascade="all, delete-orphan")


class StudentAccountRequest(Base):
    __tablename__ = "student_account_requests"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(String(50), ForeignKey("students.student_id"), nullable=False, unique=True, index=True)
    hashed_password = Column(String(255), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    reviewed_at = Column(DateTime, nullable=True)


class AccountRequest(Base):
    __tablename__ = "account_requests"
    __table_args__ = (
        Index(
            "uq_account_requests_pending_username",
            text("lower(requested_username)"),
            unique=True,
            sqlite_where=text("status = 'pending'"),
            postgresql_where=text("status = 'pending'"),
        ),
        Index(
            "uq_account_requests_pending_faculty_email",
            text("lower(email)"),
            unique=True,
            sqlite_where=text("status = 'pending' AND role = 'FACULTY' AND email IS NOT NULL"),
            postgresql_where=text("status = 'pending' AND role = 'FACULTY' AND email IS NOT NULL"),
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    legacy_request_id = Column(Integer, unique=True, nullable=True, index=True)
    role = Column(String(20), nullable=False, default="STUDENT", index=True)
    student_id = Column(String(50), nullable=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(120), nullable=True, index=True)
    department = Column(String(50), nullable=False)
    requested_username = Column(String(50), nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    status = Column(String(20), nullable=False, default="pending", index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    reviewed_at = Column(DateTime, nullable=True)
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reject_reason = Column(Text, nullable=True)


class RevokedToken(Base):
    __tablename__ = "revoked_tokens"

    jti = Column(String(64), primary_key=True)
    expires_at = Column(DateTime, nullable=False)


class Student(Base):
    __tablename__ = "students"

    student_id = Column(String(50), primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    department = Column(String(50), nullable=False, index=True)  # CSE, ECE, EEE, Mech, Civil
    year = Column(Integer, nullable=False, index=True)  # 1, 2, 3, 4
    semester = Column(Integer, nullable=False)  # 1 to 8
    email = Column(String(120), nullable=True)
    mentor_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    # Relationships
    mentor = relationship("User", foreign_keys=[mentor_id])
    semester_histories = relationship("SemesterHistory", back_populates="student", cascade="all, delete-orphan")
    subject_records = relationship("SubjectRecord", back_populates="student", cascade="all, delete-orphan")
    unified_metrics = relationship("UnifiedStudentMetrics", back_populates="student", uselist=False, cascade="all, delete-orphan")
    score = relationship("StudentScore", back_populates="student", uselist=False, cascade="all, delete-orphan")
    interventions = relationship("InterventionAction", back_populates="student", cascade="all, delete-orphan")
    messages = relationship("StudentMentorMessage", back_populates="student", cascade="all, delete-orphan")


class FacultyAssignment(Base):
    __tablename__ = "faculty_assignments"

    id = Column(Integer, primary_key=True, index=True)
    faculty_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    student_id = Column(String(50), ForeignKey("students.student_id"), nullable=False, index=True)

    faculty = relationship("User", back_populates="assignments")
    student = relationship("Student")


class SemesterHistory(Base):
    __tablename__ = "semester_history"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(String(50), ForeignKey("students.student_id"), nullable=False, index=True)
    semester = Column(Integer, nullable=False)
    gpa = Column(Float, nullable=False)
    attendance_pct = Column(Float, nullable=False)
    credits_earned = Column(Integer, default=20)
    backlogs = Column(Integer, default=0)

    student = relationship("Student", back_populates="semester_histories")


class SubjectRecord(Base):
    __tablename__ = "subject_records"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(String(50), ForeignKey("students.student_id"), nullable=False, index=True)
    semester = Column(Integer, nullable=False)
    subject_code = Column(String(20), nullable=False)
    subject_name = Column(String(100), nullable=False)
    marks = Column(Float, nullable=False)
    max_marks = Column(Float, default=100.0)
    attendance_pct = Column(Float, nullable=False)
    is_backlog = Column(Boolean, default=False)

    student = relationship("Student", back_populates="subject_records")


class UnifiedStudentMetrics(Base):
    __tablename__ = "unified_student_metrics"

    student_id = Column(String(50), ForeignKey("students.student_id"), primary_key=True, index=True)
    cgpa = Column(Float, default=0.0)
    total_backlogs = Column(Integer, default=0)
    attendance_pct = Column(Float, default=0.0)
    lms_login_count = Column(Integer, default=0)
    lms_time_spent_hrs = Column(Float, default=0.0)
    assignments_submitted_pct = Column(Float, default=0.0)
    forum_posts_count = Column(Integer, default=0)
    event_participation_count = Column(Integer, default=0)
    library_visits = Column(Integer, default=0)
    aptitude_score = Column(Float, default=0.0)
    coding_score = Column(Float, default=0.0)
    mock_interviews_completed = Column(Integer, default=0)
    technical_skills_score = Column(Float, default=0.0)
    soft_skills_score = Column(Float, default=0.0)
    faculty_feedback_score = Column(Float, default=0.0)
    peer_feedback_score = Column(Float, default=0.0)
    last_updated = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    student = relationship("Student", back_populates="unified_metrics")


class StudentScore(Base):
    __tablename__ = "student_scores"

    student_id = Column(String(50), ForeignKey("students.student_id"), primary_key=True, index=True)
    academic_score = Column(Float, default=0.0)
    attendance_score = Column(Float, default=0.0)
    placement_score = Column(Float, default=0.0)
    lms_score = Column(Float, default=0.0)
    skills_feedback_score = Column(Float, default=0.0)
    total_success_score = Column(Float, default=0.0)
    academic_risk_level = Column(String(20), default="Low")  # Low, Medium, High
    academic_risk_reasons = Column(Text, default="[]")  # JSON encoded list of strings
    placement_risk_level = Column(String(20), default="Low")  # Low, Medium, High
    placement_risk_reasons = Column(Text, default="[]")  # JSON encoded list of strings
    ml_risk_probability = Column(Float, nullable=True, default=None)
    segment_rule = Column(String(100), default="Unassigned")
    segment_kmeans = Column(String(100), default="Cluster 0")
    score_explanation = Column(Text, default="")
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    student = relationship("Student", back_populates="score")


class CleaningLog(Base):
    __tablename__ = "cleaning_log"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    source_file = Column(String(100), nullable=False)
    row_number = Column(Integer, nullable=True)
    student_id = Column(String(50), nullable=True)
    field_name = Column(String(50), nullable=False)
    issue_type = Column(String(50), nullable=False)  # duplicate_id, missing_value, spelling_normalization, out_of_range, invalid_format
    original_value = Column(String(255), nullable=True)
    cleaned_value = Column(String(255), nullable=True)
    rule_applied = Column(String(255), nullable=False)


class ScoreSettings(Base):
    __tablename__ = "score_settings"

    key = Column(String(50), primary_key=True, default="default")
    weight_academic = Column(Float, default=35.0)
    weight_attendance = Column(Float, default=20.0)
    weight_placement = Column(Float, default=20.0)
    weight_lms = Column(Float, default=15.0)
    weight_skills = Column(Float, default=10.0)
    threshold_academic_cgpa = Column(Float, default=6.0)
    threshold_attendance_pct = Column(Float, default=75.0)
    threshold_coding_score = Column(Float, default=40.0)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class InterventionAction(Base):
    __tablename__ = "intervention_actions"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(String(50), ForeignKey("students.student_id"), nullable=False, index=True)
    mentor_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    action_type = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    potential_gain = Column(Float, default=0.0)
    urgency = Column(Float, default=0.0)
    priority = Column(Float, default=0.0)
    status = Column(String(30), default="pending")  # pending, in_progress, done
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    score_at_creation = Column(Float, nullable=True, default=None)
    score_at_completion = Column(Float, nullable=True, default=None)
    completed_at = Column(DateTime, nullable=True, default=None)

    student = relationship("Student", back_populates="interventions")
    mentor = relationship("User")


class StudentMentorMessage(Base):
    __tablename__ = "student_mentor_messages"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(String(50), ForeignKey("students.student_id"), nullable=False, index=True)
    mentor_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    message = Column(Text, nullable=False)
    reply = Column(Text, nullable=True)
    status = Column(String(30), default="open")  # open, resolved
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    student = relationship("Student", back_populates="messages")
    mentor = relationship("User")
