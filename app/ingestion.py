import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import pandas as pd
from sqlalchemy.orm import Session

from app.models import CleaningLog, Student, UnifiedStudentMetrics

DEPT_MAPPING = {
    "cse": "CSE",
    "c.s.e": "CSE",
    "cs": "CSE",
    "computer science": "CSE",
    "comp sci": "CSE",
    "ece": "ECE",
    "e.c.e": "ECE",
    "electronics": "ECE",
    "electronics & comm": "ECE",
    "electronics and communication": "ECE",
    "ece dept": "ECE",
    "eee": "EEE",
    "e.e.e": "EEE",
    "electrical": "EEE",
    "electrical & electronics": "EEE",
    "electrical and electronics": "EEE",
    "mech": "Mech",
    "mechanical": "Mech",
    "mech engg": "Mech",
    "mechanical engineering": "Mech",
    "m.e.": "Mech",
    "civil": "Civil",
    "civil engg": "Civil",
    "civil engineering": "Civil",
    "c.e.": "Civil",
}


def normalize_department(value: str) -> str:
    cleaned = value.strip()
    return DEPT_MAPPING.get(cleaned.casefold(), cleaned)


SOURCE_REQUIRED_COLUMNS = {
    "academic": ["student_id", "name", "department", "year", "semester", "cgpa", "backlogs"],
    "attendance": ["student_id", "attendance_pct"],
    "lms": ["student_id", "lms_login_count", "lms_time_spent_hrs", "assignments_submitted_pct"],
    "engagement": ["student_id", "event_participation_count", "library_visits"],
    "placement": ["student_id", "aptitude_score", "coding_score", "mock_interviews_completed"],
    "skills": ["student_id", "technical_skills_score", "soft_skills_score"],
    "feedback": ["student_id", "faculty_feedback_score", "peer_feedback_score"],
}

SOURCE_ALLOWED_COLUMNS = {
    "academic": set(SOURCE_REQUIRED_COLUMNS["academic"]),
    "attendance": set(SOURCE_REQUIRED_COLUMNS["attendance"]) | {
        "lab_attendance_pct", "lecture_attendance_pct",
    },
    "lms": set(SOURCE_REQUIRED_COLUMNS["lms"]) | {"forum_posts_count"},
    "engagement": set(SOURCE_REQUIRED_COLUMNS["engagement"]) | {"hackathons_attended"},
    "placement": set(SOURCE_REQUIRED_COLUMNS["placement"]) | {"resume_score"},
    "skills": set(SOURCE_REQUIRED_COLUMNS["skills"]) | {"certifications_count"},
    "feedback": set(SOURCE_REQUIRED_COLUMNS["feedback"]) | {"mentor_feedback_score"},
}

CSV_TEMPLATES = {
    "academic": "student_id,name,department,year,semester,cgpa,backlogs\n22CSE001,Aarav Sharma,CSE,3,5,8.45,0\n22ECE012,Diya Patel,ECE,3,5,7.20,1\n",
    "attendance": "student_id,attendance_pct,lab_attendance_pct,lecture_attendance_pct\n22CSE001,88.5,92.0,86.0\n22ECE012,71.2,75.0,68.5\n",
    "lms": "student_id,lms_login_count,lms_time_spent_hrs,assignments_submitted_pct,forum_posts_count\n22CSE001,142,65.5,95.0,12\n22ECE012,68,28.0,72.0,3\n",
    "engagement": "student_id,event_participation_count,library_visits,hackathons_attended\n22CSE001,4,18,2\n22ECE012,1,6,0\n",
    "placement": "student_id,aptitude_score,coding_score,mock_interviews_completed,resume_score\n22CSE001,78.5,82.0,2,85.0\n22ECE012,55.0,38.0,0,60.0\n",
    "skills": "student_id,technical_skills_score,soft_skills_score,certifications_count\n22CSE001,84.0,80.0,3\n22ECE012,62.0,65.0,1\n",
    "feedback": "student_id,faculty_feedback_score,peer_feedback_score,mentor_feedback_score\n22CSE001,86.0,82.0,85.0\n22ECE012,65.0,70.0,68.0\n",
}

NUMERIC_RULES: Dict[str, Tuple[float, float, bool]] = {
    "year": (1, 4, True),
    "semester": (1, 8, True),
    "cgpa": (0, 10, False),
    "backlogs": (0, 20, True),
    "attendance_pct": (0, 100, False),
    "lab_attendance_pct": (0, 100, False),
    "lecture_attendance_pct": (0, 100, False),
    "lms_login_count": (0, 1000, True),
    "lms_time_spent_hrs": (0, 500, False),
    "assignments_submitted_pct": (0, 100, False),
    "forum_posts_count": (0, 200, True),
    "event_participation_count": (0, 50, True),
    "library_visits": (0, 200, True),
    "hackathons_attended": (0, 50, True),
    "aptitude_score": (0, 100, False),
    "coding_score": (0, 100, False),
    "mock_interviews_completed": (0, 20, True),
    "resume_score": (0, 100, False),
    "technical_skills_score": (0, 100, False),
    "soft_skills_score": (0, 100, False),
    "certifications_count": (0, 100, True),
    "faculty_feedback_score": (0, 100, False),
    "peer_feedback_score": (0, 100, False),
    "mentor_feedback_score": (0, 100, False),
}

METRIC_FIELDS = {
    "cgpa": "cgpa",
    "backlogs": "total_backlogs",
    "attendance_pct": "attendance_pct",
    "lms_login_count": "lms_login_count",
    "lms_time_spent_hrs": "lms_time_spent_hrs",
    "assignments_submitted_pct": "assignments_submitted_pct",
    "forum_posts_count": "forum_posts_count",
    "event_participation_count": "event_participation_count",
    "library_visits": "library_visits",
    "aptitude_score": "aptitude_score",
    "coding_score": "coding_score",
    "mock_interviews_completed": "mock_interviews_completed",
    "technical_skills_score": "technical_skills_score",
    "soft_skills_score": "soft_skills_score",
    "faculty_feedback_score": "faculty_feedback_score",
    "peer_feedback_score": "peer_feedback_score",
}

STUDENT_ID_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]{1,49}$")


def clean_student_id(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip().upper()


def validate_source_columns(source_name: str, df: pd.DataFrame) -> List[str]:
    required = SOURCE_REQUIRED_COLUMNS.get(source_name, ["student_id"])
    columns = [str(column).strip().lower() for column in df.columns]
    return [column for column in required if column not in columns]


def _cleaning_log(
    source: str,
    row_number: int,
    student_id: str,
    field: str,
    issue: str,
    original: Any,
    cleaned: Any,
    rule: str,
) -> CleaningLog:
    return CleaningLog(
        source_file=source,
        row_number=row_number,
        student_id=student_id or None,
        field_name=field,
        issue_type=issue,
        original_value=str(original)[:255],
        cleaned_value=str(cleaned)[:255],
        rule_applied=rule,
    )


def _prepare_sources(
    sources_data: Dict[str, pd.DataFrame],
    import_mode: str,
) -> Tuple[Dict[str, List[Tuple[str, Dict[str, Any]]]], List[CleaningLog], Dict[str, List[str]], Dict[str, int]]:
    errors: Dict[str, List[str]] = {}
    logs: List[CleaningLog] = []
    prepared: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {}
    counts = {"accepted_rows": 0, "rejected_rows": 0, "duplicate_rows": 0}

    unknown_sources = sorted(set(sources_data) - set(SOURCE_REQUIRED_COLUMNS))
    if unknown_sources:
        errors["sources"] = [f"Unknown source name(s): {', '.join(unknown_sources)}."]
    if not sources_data:
        errors["sources"] = ["Upload at least one CSV file."]
    if import_mode == "full":
        missing_sources = sorted(set(SOURCE_REQUIRED_COLUMNS) - set(sources_data))
        if missing_sources:
            errors["sources"] = [
                f"Full imports require all seven source files; missing: {', '.join(missing_sources)}."
            ]

    for source, dataframe in sources_data.items():
        if source not in SOURCE_REQUIRED_COLUMNS:
            continue
        source_errors: List[str] = []
        df = dataframe.copy()
        normalized_columns = [str(column).strip().lower() for column in df.columns]
        if len(set(normalized_columns)) != len(normalized_columns):
            errors[source] = ["Column names must be unique after trimming and case normalization."]
            counts["rejected_rows"] += len(df)
            continue
        df.columns = normalized_columns
        missing_columns = validate_source_columns(source, df)
        if missing_columns:
            errors[source] = [f"Missing required columns: {', '.join(missing_columns)}."]
            counts["rejected_rows"] += len(df)
            continue
        unexpected_columns = sorted(set(normalized_columns) - SOURCE_ALLOWED_COLUMNS[source])
        if unexpected_columns:
            errors[source] = [
                f"Unsupported column(s): {', '.join(unexpected_columns)}."
            ]
            counts["rejected_rows"] += len(df)
            continue
        if df.empty:
            errors[source] = ["CSV must contain at least one data row."]
            continue

        unique_rows: Dict[str, Dict[str, Any]] = {}
        for index, row in df.iterrows():
            row_number = int(index) + 2 if isinstance(index, int) else len(unique_rows) + 2
            original_id = row.get("student_id")
            student_id = clean_student_id(original_id)
            if not student_id or not STUDENT_ID_PATTERN.fullmatch(student_id):
                source_errors.append(f"Row {row_number}: student_id is missing or invalid.")
                counts["rejected_rows"] += 1
                continue

            values: Dict[str, Any] = {"student_id": student_id}
            row_invalid = False
            if str(original_id).strip() != student_id:
                logs.append(_cleaning_log(
                    source, row_number, student_id, "student_id", "id_normalization",
                    original_id, student_id, "Trim whitespace and uppercase student ID.",
                ))

            for column in normalized_columns:
                if column == "student_id" or column not in (
                    set(NUMERIC_RULES) | {"name", "department"}
                ):
                    continue
                raw_value = row[column]
                if raw_value is None or pd.isna(raw_value) or str(raw_value).strip() == "":
                    if import_mode == "full":
                        source_errors.append(f"Row {row_number}: {column} is required and cannot be blank.")
                        row_invalid = True
                    else:
                        logs.append(_cleaning_log(
                            source, row_number, student_id, column, "missing_value",
                            raw_value, "", "Blank partial-update values leave existing data unchanged.",
                        ))
                    continue

                if column == "department":
                    raw_department = str(raw_value).strip()
                    department = DEPT_MAPPING.get(raw_department.lower())
                    if department is None:
                        source_errors.append(
                            f"Row {row_number}: department '{raw_department}' is not recognized."
                        )
                        row_invalid = True
                        continue
                    values[column] = department
                    if raw_department != department:
                        logs.append(_cleaning_log(
                            source, row_number, student_id, column, "spelling_normalization",
                            raw_department, department, "Map recognized department aliases to canonical names.",
                        ))
                    continue

                if column == "name":
                    name = str(raw_value).strip()
                    if not name or len(name) > 100:
                        source_errors.append(f"Row {row_number}: name must contain 1 to 100 characters.")
                        row_invalid = True
                    else:
                        values[column] = name
                    continue

                minimum, maximum, integer_value = NUMERIC_RULES[column]
                try:
                    numeric_value = float(str(raw_value).strip())
                except (TypeError, ValueError):
                    source_errors.append(f"Row {row_number}: {column} must be numeric.")
                    row_invalid = True
                    continue
                if not pd.notna(numeric_value):
                    source_errors.append(f"Row {row_number}: {column} must be a finite number.")
                    row_invalid = True
                    continue
                if column == "cgpa" and 10 < numeric_value <= 100:
                    logs.append(_cleaning_log(
                        source, row_number, student_id, column, "out_of_range",
                        raw_value, round(numeric_value / 10, 2),
                        "Convert a CGPA expressed on the 100-point scale to a 10-point scale.",
                    ))
                    numeric_value = round(numeric_value / 10, 2)
                if numeric_value < minimum or numeric_value > maximum:
                    source_errors.append(
                        f"Row {row_number}: {column} must be between {minimum:g} and {maximum:g}."
                    )
                    row_invalid = True
                    continue
                if integer_value and not numeric_value.is_integer():
                    source_errors.append(f"Row {row_number}: {column} must be a whole number.")
                    row_invalid = True
                    continue
                values[column] = int(numeric_value) if integer_value else numeric_value

            if row_invalid:
                counts["rejected_rows"] += 1
                continue

            previous = unique_rows.get(student_id)
            if previous is not None:
                if previous == values:
                    counts["duplicate_rows"] += 1
                    logs.append(_cleaning_log(
                        source, row_number, student_id, "student_id", "duplicate_id",
                        student_id, student_id, "Ignore an exact duplicate student row.",
                    ))
                else:
                    source_errors.append(
                        f"Row {row_number}: conflicting duplicate record for student_id {student_id}."
                    )
                    counts["rejected_rows"] += 1
                continue
            unique_rows[student_id] = values

        if source_errors:
            errors[source] = source_errors
        prepared[source] = list(unique_rows.items())

    counts["accepted_rows"] = sum(len(rows) for rows in prepared.values())
    return prepared, logs, errors, counts


def ingest_seven_sources(
    sources_data: Dict[str, pd.DataFrame],
    db: Session,
    import_mode: str = "partial",
) -> Dict[str, Any]:
    """Validate all source data, then apply an atomic upsert without committing the caller's transaction."""
    if import_mode not in {"partial", "full"}:
        return {
            "status": "error",
            "message": "import_mode must be 'partial' or 'full'.",
            "errors": {"import_mode": ["Choose 'partial' or 'full'."]},
            "accepted_rows": 0,
            "rejected_rows": 0,
            "duplicate_rows": 0,
            "updated_rows": 0,
        }

    prepared, logs, errors, counts = _prepare_sources(sources_data, import_mode)
    existing_students = {
        student.student_id: student for student in db.query(Student).all()
    }
    incoming_ids = {
        source: {student_id for student_id, _ in rows}
        for source, rows in prepared.items()
    }

    if import_mode == "partial":
        unknown_ids = sorted({
            student_id
            for ids in incoming_ids.values()
            for student_id in ids
            if student_id not in existing_students
        })
        if unknown_ids:
            errors["student_id"] = [
                f"Partial imports can update existing students only; {len(unknown_ids)} unknown student ID(s) found."
            ]
    elif incoming_ids:
        academic_ids = incoming_ids.get("academic", set())
        for source, ids in incoming_ids.items():
            if ids != academic_ids:
                errors[source] = [
                    "Full-import student IDs must match the academic file exactly."
                ]

    if errors:
        counts["rejected_rows"] += counts["accepted_rows"]
        counts["accepted_rows"] = 0
        return {
            "status": "error",
            "message": "CSV validation failed; no records were changed.",
            "errors": errors,
            **counts,
            "updated_rows": 0,
        }

    persisted_columns = {"student_id", "name", "department", "year", "semester"} | set(METRIC_FIELDS)
    not_persisted_columns = sorted({
        str(column).strip().lower()
        for dataframe in sources_data.values()
        for column in dataframe.columns
        if str(column).strip().lower() not in persisted_columns
    })

    source_order = ["academic", "attendance", "lms", "engagement", "placement", "skills", "feedback"]
    updated_rows = 0
    metrics_by_id = {
        metric.student_id: metric for metric in db.query(UnifiedStudentMetrics).all()
    }

    try:
        for source in source_order:
            for student_id, values in prepared.get(source, []):
                student = existing_students.get(student_id)
                if student is None:
                    student = Student(
                        student_id=student_id,
                        name=values["name"],
                        department=values["department"],
                        year=values["year"],
                        semester=values["semester"],
                    )
                    db.add(student)
                    existing_students[student_id] = student
                    row_changed = True
                else:
                    row_changed = False
                    for field in ("name", "department", "year", "semester"):
                        if field in values and getattr(student, field) != values[field]:
                            setattr(student, field, values[field])
                            row_changed = True

                metric_fields = {
                    field: METRIC_FIELDS[field]
                    for field in values
                    if field in METRIC_FIELDS
                }
                if metric_fields:
                    metric = metrics_by_id.get(student_id)
                    if metric is None:
                        metric = UnifiedStudentMetrics(student_id=student_id)
                        db.add(metric)
                        metrics_by_id[student_id] = metric
                    metric_changed = False
                    for field, model_field in metric_fields.items():
                        if getattr(metric, model_field) != values[field]:
                            setattr(metric, model_field, values[field])
                            row_changed = True
                            metric_changed = True
                    if metric_changed:
                        metric.last_updated = datetime.now(timezone.utc)

                if row_changed:
                    updated_rows += 1

        db.add_all(logs)
        db.flush()
    except Exception:
        db.rollback()
        raise

    return {
        "status": "success",
        "import_mode": import_mode,
        "students_count": len(existing_students),
        "cleaning_logs_count": len(logs),
        "sources_merged": list(prepared),
        "not_persisted_columns": not_persisted_columns,
        **counts,
        "updated_rows": updated_rows,
    }
