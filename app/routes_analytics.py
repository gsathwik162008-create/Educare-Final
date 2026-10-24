from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, func

from app.database import get_db
from app.models import (
    User,
    Student,
    UnifiedStudentMetrics,
    StudentScore,
    FacultyAssignment,
    SemesterHistory,
    SubjectRecord
)
from app.auth import get_current_user, require_role
from app.ingestion import DEPT_MAPPING, normalize_department
from app.risk import overall_risk_level

router = APIRouter(
    prefix="/api/analytics",
    tags=["analytics"],
    dependencies=[Depends(require_role(["ADMIN", "FACULTY"]))]
)


def get_scoped_student_ids(current_user: User, db: Session) -> Optional[List[str]]:
    """Helper to get student IDs accessible to current user."""
    if current_user.role == "ADMIN":
        return None  # All students
    if current_user.role == "FACULTY":
        sids = [
            r[0] for r in db.query(FacultyAssignment.student_id).filter(
                FacultyAssignment.faculty_id == current_user.id
            ).all()
        ]
        # Include any students where mentor_id matches
        mentor_sids = [
            r[0] for r in db.query(Student.student_id).filter(
                Student.mentor_id == current_user.id
            ).all()
        ]
        return list(set(sids + mentor_sids))
    if current_user.role == "STUDENT":
        return [current_user.student_id] if current_user.student_id else []
    return []


@router.get("/overview")
def get_cohort_overview(
    department: Optional[str] = None,
    year: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Screen 1: Cohort Overview with KPIs, score distribution, and department heatmap."""
    scoped_sids = get_scoped_student_ids(current_user, db)

    query = db.query(Student, StudentScore, UnifiedStudentMetrics).join(
        StudentScore, Student.student_id == StudentScore.student_id
    ).join(
        UnifiedStudentMetrics, Student.student_id == UnifiedStudentMetrics.student_id
    )

    if scoped_sids is not None:
        query = query.filter(Student.student_id.in_(scoped_sids))
    if department and department != "All":
        canonical_department = normalize_department(department)
        department_values = {
            alias.casefold()
            for alias, canonical in DEPT_MAPPING.items()
            if canonical.casefold() == canonical_department.casefold()
        }
        department_values.add(canonical_department.casefold())
        query = query.filter(
            func.lower(func.trim(Student.department)).in_(department_values)
        )
    if year and year != 0:
        query = query.filter(Student.year == year)

    records = query.all()
    total_count = len(records)
    if total_count == 0:
        return {
            "total_students": 0,
            "avg_score": 0.0,
            "at_risk_count": 0,
            "placement_ready_count": 0,
            "avg_attendance": 0.0,
            "risk_distribution": {"High": 0, "Medium": 0, "Low": 0},
            "score_distribution": [],
            "department_heatmap": []
        }

    total_score_sum = sum(sc.total_success_score for _, sc, _ in records)
    avg_score = round(total_score_sum / total_count, 1)

    risk_distribution = {"High": 0, "Medium": 0, "Low": 0}
    for _, score, _ in records:
        risk_distribution[overall_risk_level(
            score.academic_risk_level,
            score.placement_risk_level,
        )] += 1
    at_risk_count = risk_distribution["High"]

    placement_ready_count = sum(
        1 for _, sc, _ in records
        if sc.placement_score >= 70.0
    )

    avg_attendance = round(
        sum(m.attendance_pct for _, _, m in records) / total_count, 1
    )

    # Score Distribution Bins
    bins = {
        "< 50": 0,
        "50 - 59": 0,
        "60 - 69": 0,
        "70 - 79": 0,
        "80 - 89": 0,
        "90 - 100": 0
    }
    for _, sc, _ in records:
        s = sc.total_success_score
        if s < 50: bins["< 50"] += 1
        elif s < 60: bins["50 - 59"] += 1
        elif s < 70: bins["60 - 69"] += 1
        elif s < 80: bins["70 - 79"] += 1
        elif s < 90: bins["80 - 89"] += 1
        else: bins["90 - 100"] += 1

    score_distribution = [{"range": k, "count": v} for k, v in bins.items()]

    # Department Heatmap
    dept_groups: Dict[str, List] = {}
    for st, sc, m in records:
        department_name = normalize_department(st.department)
        dept_groups.setdefault(department_name, []).append((st, sc, m))

    dept_heatmap = []
    for d_name in sorted(dept_groups, key=str.casefold):
        d_recs = dept_groups[d_name]
        cnt = len(d_recs)
        d_avg_score = round(sum(sc.total_success_score for _, sc, _ in d_recs) / cnt, 1)
        d_avg_att = round(sum(m.attendance_pct for _, _, m in d_recs) / cnt, 1)
        d_avg_place = round(sum(sc.placement_score for _, sc, _ in d_recs) / cnt, 1)
        d_risk_counts = {"High": 0, "Medium": 0, "Low": 0}
        for _, score, _ in d_recs:
            d_risk_counts[overall_risk_level(
                score.academic_risk_level,
                score.placement_risk_level,
            )] += 1
        d_high_risk = d_risk_counts["High"]
        dept_heatmap.append({
            "department": d_name,
            "student_count": cnt,
            "avg_score": d_avg_score,
            "avg_attendance": d_avg_att,
            "avg_placement": d_avg_place,
            "risk_counts": d_risk_counts,
            "high_risk_count": d_high_risk,
            "risk_rate_pct": round((d_high_risk / cnt) * 100, 1)
        })

    return {
        "total_students": total_count,
        "avg_score": avg_score,
        "at_risk_count": at_risk_count,
        "at_risk_pct": round((at_risk_count / total_count) * 100, 1),
        "placement_ready_count": placement_ready_count,
        "placement_ready_pct": round((placement_ready_count / total_count) * 100, 1),
        "avg_attendance": avg_attendance,
        "risk_distribution": risk_distribution,
        "score_distribution": score_distribution,
        "department_heatmap": dept_heatmap
    }


@router.get("/trends")
def get_trends(
    department: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Screen 2: Trends across semesters, departments, and academic years."""
    scoped_sids = get_scoped_student_ids(current_user, db)

    # 1. Semester-wise trends (1 to 8)
    sem_query = db.query(SemesterHistory)
    if scoped_sids is not None:
        sem_query = sem_query.filter(SemesterHistory.student_id.in_(scoped_sids))

    all_sem_records = sem_query.all()
    sem_buckets = {}
    for r in all_sem_records:
        sem_buckets.setdefault(r.semester, []).append(r)

    semester_trends = []
    for s_num in range(1, 9):
        items = sem_buckets.get(s_num, [])
        if items:
            avg_gpa = round(sum(i.gpa for i in items) / len(items), 2)
            avg_att = round(sum(i.attendance_pct for i in items) / len(items), 1)
            backlog_cnt = sum(i.backlogs for i in items)
            semester_trends.append({
                "semester": f"Sem {s_num}",
                "avg_gpa": avg_gpa,
                "avg_attendance": avg_att,
                "total_backlogs": backlog_cnt
            })

    # 2. Year comparison
    st_query = db.query(Student, StudentScore).join(StudentScore, Student.student_id == StudentScore.student_id)
    if scoped_sids is not None:
        st_query = st_query.filter(Student.student_id.in_(scoped_sids))

    all_students = st_query.all()
    year_buckets = {}
    dept_buckets = {}

    for st, sc in all_students:
        year_buckets.setdefault(st.year, []).append(sc)
        dept_buckets.setdefault(st.department, []).append(sc)

    year_comparison = []
    for y_num in sorted(year_buckets.keys()):
        scs = year_buckets[y_num]
        year_comparison.append({
            "year": f"Year {y_num}",
            "student_count": len(scs),
            "avg_score": round(sum(s.total_success_score for s in scs) / len(scs), 1),
            "avg_academic": round(sum(s.academic_score for s in scs) / len(scs), 1),
            "avg_placement": round(sum(s.placement_score for s in scs) / len(scs), 1),
            "avg_attendance": round(sum(s.attendance_score for s in scs) / len(scs), 1)
        })

    # 3. Department multi-dimension comparison
    dept_comparison = []
    for d_name, scs in sorted(dept_buckets.items()):
        dept_comparison.append({
            "department": d_name,
            "avg_score": round(sum(s.total_success_score for s in scs) / len(scs), 1),
            "avg_academic": round(sum(s.academic_score for s in scs) / len(scs), 1),
            "avg_placement": round(sum(s.placement_score for s in scs) / len(scs), 1),
            "avg_attendance": round(sum(s.attendance_score for s in scs) / len(scs), 1),
            "avg_lms": round(sum(s.lms_score for s in scs) / len(scs), 1),
            "avg_skills": round(sum(s.skills_feedback_score for s in scs) / len(scs), 1)
        })

    return {
        "semester_trends": semester_trends,
        "year_comparison": year_comparison,
        "department_comparison": dept_comparison
    }


@router.get("/segments")
def get_segments_distribution(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Screen 6: Student Segments (Rule-based and K-Means clusters)."""
    scoped_sids = get_scoped_student_ids(current_user, db)

    query = db.query(StudentScore)
    if scoped_sids is not None:
        query = query.filter(StudentScore.student_id.in_(scoped_sids))

    scores = query.all()
    total = len(scores)

    rule_counts = {}
    kmeans_counts = {}

    for s in scores:
        r_name = s.segment_rule or "Unassigned"
        k_name = s.segment_kmeans or "Unassigned"
        rule_counts[r_name] = rule_counts.get(r_name, 0) + 1
        kmeans_counts[k_name] = kmeans_counts.get(k_name, 0) + 1

    rule_segments = [
        {"segment": k, "count": v, "percentage": round((v / max(total, 1)) * 100, 1)}
        for k, v in sorted(rule_counts.items(), key=lambda x: x[1], reverse=True)
    ]

    kmeans_clusters = [
        {"cluster": k, "count": v, "percentage": round((v / max(total, 1)) * 100, 1)}
        for k, v in sorted(kmeans_counts.items(), key=lambda x: x[1], reverse=True)
    ]

    return {
        "total_students": total,
        "rule_segments": rule_segments,
        "kmeans_clusters": kmeans_clusters
    }


@router.get("/insights")
def get_insights(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Screen 7: Auto-generated analytical insights, department satisfaction, and subject failure heatmap."""
    scoped_sids = get_scoped_student_ids(current_user, db)

    # 1. Subject failure heatmap
    subj_query = db.query(SubjectRecord)
    if scoped_sids is not None:
        subj_query = subj_query.filter(SubjectRecord.student_id.in_(scoped_sids))

    subject_records = subj_query.all()
    subj_groups = {}
    for r in subject_records:
        subj_groups.setdefault((r.subject_code, r.subject_name), []).append(r)

    subject_heatmap = []
    for (code, name), recs in subj_groups.items():
        total_enrolled = len(recs)
        failures = sum(1 for r in recs if r.is_backlog or r.marks < 40.0)
        avg_marks = round(sum(r.marks for r in recs) / total_enrolled, 1)
        avg_att = round(sum(r.attendance_pct for r in recs) / total_enrolled, 1)
        failure_rate = round((failures / total_enrolled) * 100, 1)
        subject_heatmap.append({
            "code": code,
            "name": name,
            "total_enrolled": total_enrolled,
            "failures": failures,
            "failure_rate": failure_rate,
            "avg_marks": avg_marks,
            "avg_attendance": avg_att
        })

    subject_heatmap.sort(key=lambda x: x["failure_rate"], reverse=True)

    # 2. Automated findings computed from dataset
    students_query = db.query(Student, StudentScore, UnifiedStudentMetrics).join(
        StudentScore, Student.student_id == StudentScore.student_id
    ).join(
        UnifiedStudentMetrics, Student.student_id == UnifiedStudentMetrics.student_id
    )
    if scoped_sids is not None:
        students_query = students_query.filter(Student.student_id.in_(scoped_sids))

    data = students_query.all()
    auto_findings = []

    if data:
        # Finding 1: Department leader in placement readiness
        dept_place = {}
        for st, sc, _ in data:
            dept_place.setdefault(st.department, []).append(sc.placement_score)
        best_dept = max(dept_place.items(), key=lambda x: sum(x[1])/len(x[1]))
        auto_findings.append({
            "category": "Job Readiness",
            "title": f"Department {best_dept[0]} leads in job readiness",
            "description": f"{best_dept[0]} has the highest average job readiness score ({round(sum(best_dept[1])/len(best_dept[1]))} out of 100), with regular coding practice and mock interviews."
        })

        # Finding 2: Mock interview deficit in upperclassmen
        yr34_no_mocks = sum(1 for st, _, m in data if st.year >= 3 and m.mock_interviews_completed == 0)
        total_yr34 = sum(1 for st, _, _ in data if st.year >= 3)
        if total_yr34 > 0:
            mock_deficit_pct = round((yr34_no_mocks / total_yr34) * 100)
            auto_findings.append({
                "category": "Support Alert",
                "title": f"{mock_deficit_pct}% of Year 3 and Year 4 students need mock interview practice",
                "description": f"{yr34_no_mocks} upper-year students have not yet practiced a mock interview before campus placements."
            })

        # Finding 3: Attendance link with course backlogs
        low_att_backlogs = sum(1 for _, _, m in data if m.attendance_pct < 75.0 and m.total_backlogs > 0)
        auto_findings.append({
            "category": "Studies Need Support",
            "title": "Clear link between attendance under 75% and course backlogs",
            "description": f"{low_att_backlogs} students with attendance below the 75% minimum needed hold at least 1 course backlog."
        })

    # 3. Department Satisfaction Ratings
    dept_fb = {}
    for st, _, m in data:
        dept_fb.setdefault(st.department, []).append(m.faculty_feedback_score)

    department_satisfaction = [
        {"department": d, "avg_satisfaction": round(sum(vals)/len(vals), 1)}
        for d, vals in sorted(dept_fb.items())
    ]

    return {
        "auto_findings": auto_findings,
        "subject_heatmap": subject_heatmap[:10],
        "department_satisfaction": department_satisfaction
    }


@router.get("/search")
def search_analytics(
    q: str = Query(..., min_length=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Keyword search for students, risk factors, branches, or academic topics."""
    scoped_sids = get_scoped_student_ids(current_user, db)
    term = f"%{q.strip()}%"

    query = db.query(Student, StudentScore).join(
        StudentScore, Student.student_id == StudentScore.student_id
    ).filter(
        or_(
            Student.student_id.ilike(term),
            Student.name.ilike(term),
            Student.department.ilike(term),
            StudentScore.segment_rule.ilike(term),
            StudentScore.academic_risk_level.ilike(term),
            StudentScore.placement_risk_level.ilike(term)
        )
    )

    if scoped_sids is not None:
        query = query.filter(Student.student_id.in_(scoped_sids))

    results = []
    for st, sc in query.limit(20).all():
        results.append({
            "student_id": st.student_id,
            "name": st.name,
            "department": st.department,
            "year": st.year,
            "total_score": sc.total_success_score,
            "academic_risk": sc.academic_risk_level,
            "placement_risk": sc.placement_risk_level,
            "segment": sc.segment_rule
        })

    return {"query": q, "count": len(results), "results": results}
