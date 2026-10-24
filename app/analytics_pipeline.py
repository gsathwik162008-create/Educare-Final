import json
from datetime import datetime, timezone
from typing import Dict, Any, List
import numpy as np
from sqlalchemy.orm import Session

from app.models import (
    Student,
    UnifiedStudentMetrics,
    StudentScore,
    ScoreSettings,
    SemesterHistory
)
from app.scoring import (
    compute_indicator_scores,
    compute_success_score,
    generate_score_explanation
)
from app.risk import (
    evaluate_academic_risk,
    evaluate_placement_risk,
    build_risk_summary
)
from app.segments import (
    assign_rule_segment,
    compute_kmeans_segments
)
from app.ml import (
    train_gradient_boosting_model,
    predict_student_risk_probability
)
from app.interventions import refresh_interventions_for_all


def run_full_analytics_pipeline(
    db: Session,
    persist_model_cache: bool = True,
) -> Dict[str, Any]:
    """
    Executes complete analytics pipeline:
    1. Reads score settings & metrics
    2. Computes indicator sub-scores & Success Scores
    3. Calculates cohort averages & score explanations
    4. Evaluates rule-based Academic & Placement risks with stored reasons
    5. Computes rule-based and K-Means segments
    6. Trains Gradient Boosting Risk Model & infers ML risk probabilities
    7. Updates intervention recommendations
    """
    # 1. Fetch settings
    settings = db.query(ScoreSettings).filter(ScoreSettings.key == "default").first()
    if not settings:
        settings = ScoreSettings(
            key="default",
            weight_academic=35.0,
            weight_attendance=20.0,
            weight_placement=20.0,
            weight_lms=15.0,
            weight_skills=10.0,
            threshold_academic_cgpa=6.0,
            threshold_attendance_pct=75.0,
            threshold_coding_score=40.0
        )
        db.add(settings)

    weights = {
        "academic_score": settings.weight_academic,
        "attendance_score": settings.weight_attendance,
        "placement_score": settings.weight_placement,
        "lms_score": settings.weight_lms,
        "skills_feedback_score": settings.weight_skills
    }

    students = db.query(Student).all()
    metrics_list = db.query(UnifiedStudentMetrics).all()
    metrics_map = {m.student_id: m for m in metrics_list}

    if not students or not metrics_list:
        return {"status": "empty", "message": "No students found to evaluate."}

    # 2. Compute sub-scores & raw metrics for all students
    student_year_map = {s.student_id: s.year for s in students}
    sub_scores_map = {}
    for m in metrics_list:
        sub_scores_map[m.student_id] = compute_indicator_scores(m, settings, year=student_year_map.get(m.student_id, 3))

    # 3. Calculate cohort averages
    cohort_averages = {
        "academic_score": float(np.mean([s["academic_score"] for s in sub_scores_map.values()])),
        "attendance_score": float(np.mean([s["attendance_score"] for s in sub_scores_map.values()])),
        "placement_score": float(np.mean([s["placement_score"] for s in sub_scores_map.values()])),
        "lms_score": float(np.mean([s["lms_score"] for s in sub_scores_map.values()])),
        "skills_feedback_score": float(np.mean([s["skills_feedback_score"] for s in sub_scores_map.values()]))
    }

    # 4. Evaluate semester history for the next-semester predictor
    sem_histories = db.query(SemesterHistory).all()
    history_by_student = {}
    for h in sem_histories:
        history_by_student.setdefault(h.student_id, []).append(h)

    # 5. Train and use the time-based next-semester GPA-drop model
    ml_metrics = train_gradient_boosting_model(
        sem_histories,
        persist=persist_model_cache,
    )

    # 6. Compute K-Means clusters
    kmeans_clusters = compute_kmeans_segments(metrics_list)

    # 7. Evaluate GPA trends
    trend_map = {}

    for sid, hist in history_by_student.items():
        hist.sort(key=lambda x: x.semester)
        if len(hist) >= 2:
            last_two = [h.gpa for h in hist[-2:]]
            if last_two[1] < last_two[0] - 0.5:
                trend_map[sid] = "falling"
            elif last_two[1] > last_two[0] + 0.5:
                trend_map[sid] = "improving"
            else:
                trend_map[sid] = "stable"
        else:
            trend_map[sid] = "stable"

    # 8. Update StudentScore table
    existing_scores = {s.student_id: s for s in db.query(StudentScore).all()}

    for s in students:
        sid = s.student_id
        m = metrics_map.get(sid)
        if not m:
            continue

        sub = sub_scores_map[sid]
        total_score = compute_success_score(
            sub,
            w_acad=settings.weight_academic,
            w_att=settings.weight_attendance,
            w_place=settings.weight_placement,
            w_lms=settings.weight_lms,
            w_skills=settings.weight_skills
        )

        # Risks
        trend = trend_map.get(sid, "stable")
        acad_level, acad_reasons = evaluate_academic_risk(m, year=s.year, trend=trend)
        place_level, place_reasons = evaluate_placement_risk(m, year=s.year)

        # Explanation
        explanation = generate_score_explanation(sub, cohort_averages, weights)

        # ML Risk Probability
        ml_prob = predict_student_risk_probability(history_by_student.get(sid, []))

        # Segments
        rule_seg = assign_rule_segment(m)
        kmeans_seg = kmeans_clusters.get(sid, "Core Performers")

        score_rec = existing_scores.get(sid)
        if not score_rec:
            score_rec = StudentScore(student_id=sid)
            db.add(score_rec)
            existing_scores[sid] = score_rec

        score_rec.academic_score = sub["academic_score"]
        score_rec.attendance_score = sub["attendance_score"]
        score_rec.placement_score = sub["placement_score"]
        score_rec.lms_score = sub["lms_score"]
        score_rec.skills_feedback_score = sub["skills_feedback_score"]
        score_rec.total_success_score = total_score
        score_rec.academic_risk_level = acad_level
        score_rec.academic_risk_reasons = json.dumps(acad_reasons)
        score_rec.placement_risk_level = place_level
        score_rec.placement_risk_reasons = json.dumps(place_reasons)
        score_rec.ml_risk_probability = ml_prob
        score_rec.segment_rule = rule_seg
        score_rec.segment_kmeans = kmeans_seg
        score_rec.score_explanation = explanation
        score_rec.updated_at = datetime.now(timezone.utc)

    db.flush()

    # 9. Refresh and rank intervention actions
    created_interventions = refresh_interventions_for_all(db)

    return {
        "status": "success",
        "students_evaluated": len(students),
        "cohort_averages": cohort_averages,
        "ml_model_metrics": ml_metrics,
        "new_interventions_created": created_interventions
    }
