from pathlib import Path
import os
import logging
import pickle
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Tuple

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sqlalchemy.orm import Session

from app.models import SemesterHistory

logger = logging.getLogger(__name__)
ARTIFACT_VERSION = 1

FEATURE_NAMES = [
    "last_gpa",
    "gpa_change",
    "mean_attendance",
    "total_backlogs_so_far",
    "credits_earned_k"
]

DISPLAY_FEATURE_NAMES = [
    "Latest GPA",
    "GPA Change",
    "Mean Attendance",
    "Backlogs So Far",
    "Credits Earned"
]

MODEL_PATH = Path(os.getenv(
    "MODEL_CACHE_PATH",
    str(Path(__file__).resolve().parent.parent / "model_cache" / "risk_model.joblib")
))
_TRAINED_MODEL: Optional[GradientBoostingClassifier] = None
_MODEL_METRICS: Dict[str, Any] = {}


def _features_at_semester(
    history: Sequence[SemesterHistory],
    index: int
) -> Optional[List[float]]:
    current = history[index]
    try:
        current_gpa = float(current.gpa)
        current_credits = float(current.credits_earned)
        backlog_values = [float(row.backlogs) for row in history[:index + 1]]
        attendance_values = [float(row.attendance_pct) for row in history[:index + 1]]
    except (AttributeError, TypeError, ValueError):
        return None

    values = [current_gpa, current_credits, *backlog_values, *attendance_values]
    if not all(np.isfinite(value) for value in values):
        return None

    previous_gpa = 0.0
    if current.semester > 1:
        if index == 0:
            return None
        previous = history[index - 1]
        if previous.semester != current.semester - 1:
            return None
        try:
            previous_gpa = float(previous.gpa)
        except (AttributeError, TypeError, ValueError):
            return None
        if not np.isfinite(previous_gpa):
            return None

    rows_to_date = history[:index + 1]
    return [
        current_gpa,
        current_gpa - previous_gpa if current.semester > 1 else 0.0,
        float(np.mean(attendance_values)),
        float(sum(int(row.backlogs) for row in rows_to_date)),
        current_credits
    ]


def _transition_examples(
    histories: Sequence[SemesterHistory]
) -> Tuple[List[List[float]], List[int], List[int]]:
    histories_by_student: Dict[str, List[SemesterHistory]] = {}
    for history in histories:
        histories_by_student.setdefault(history.student_id, []).append(history)

    features: List[List[float]] = []
    labels: List[int] = []
    transition_semesters: List[int] = []

    for student_history in histories_by_student.values():
        student_history.sort(key=lambda row: row.semester)
        for index in range(len(student_history) - 1):
            current = student_history[index]
            following = student_history[index + 1]
            if following.semester != current.semester + 1:
                continue

            feature_row = _features_at_semester(student_history, index)
            try:
                current_gpa = float(current.gpa)
                following_gpa = float(following.gpa)
                current_backlogs = int(current.backlogs)
                following_backlogs = int(following.backlogs)
            except (AttributeError, TypeError, ValueError):
                continue
            if feature_row is None or not all(np.isfinite(value) for value in (
                current_gpa, following_gpa, current_backlogs, following_backlogs
            )):
                continue

            features.append(feature_row)
            labels.append(int(
                following_gpa < current_gpa - 0.5
                or following_backlogs > current_backlogs
            ))
            transition_semesters.append(current.semester)

    return features, labels, transition_semesters


def _classification_metrics(
    actual: np.ndarray,
    predicted: np.ndarray,
    probabilities: np.ndarray
) -> Dict[str, Any]:
    try:
        roc_auc: Optional[float] = round(float(roc_auc_score(actual, probabilities)), 4)
    except ValueError:
        roc_auc = None

    return {
        "accuracy": round(float(accuracy_score(actual, predicted)), 4),
        "precision": round(float(precision_score(actual, predicted, zero_division=0)), 4),
        "recall": round(float(recall_score(actual, predicted, zero_division=0)), 4),
        "f1": round(float(f1_score(actual, predicted, zero_division=0)), 4),
        "roc_auc": roc_auc,
        "actual_class_counts": {
            "negative": int(np.sum(actual == 0)),
            "positive": int(np.sum(actual == 1)),
        },
        "confusion_matrix": confusion_matrix(actual, predicted, labels=[0, 1]).tolist(),
    }


def _empty_metrics(status: str) -> Dict[str, Any]:
    empty_evaluation = {
        "accuracy": 0.0,
        "precision": 0.0,
        "recall": 0.0,
        "f1": 0.0,
        "roc_auc": None,
        "actual_class_counts": {"negative": 0, "positive": 0},
        "confusion_matrix": [[0, 0], [0, 0]],
    }
    return {
        "status": status,
        "training_samples": 0,
        "test_samples": 0,
        "training_class_counts": {"negative": 0, "positive": 0},
        "test_class_counts": {"negative": 0, "positive": 0},
        **empty_evaluation,
        "model_metrics": dict(empty_evaluation),
        "baseline_majority_metrics": dict(empty_evaluation),
        "baseline_gpa_rule_metrics": dict(empty_evaluation),
        "model_beats_baseline": False,
        "target_definition": (
            "Positive when the following semester's GPA drops by more than 0.5 "
            "or its backlog count increases."
        ),
        "feature_names": list(DISPLAY_FEATURE_NAMES),
        "honest_note": "Model is unavailable; no validated prediction or evaluation is available.",
        "feature_importances": [],
        "model_type": "GradientBoostingClassifier (scikit-learn)"
    }


def snapshot_model_state() -> Tuple[Optional[GradientBoostingClassifier], Dict[str, Any]]:
    return _TRAINED_MODEL, dict(_MODEL_METRICS)


def restore_model_state(
    state: Tuple[Optional[GradientBoostingClassifier], Dict[str, Any]]
) -> None:
    global _TRAINED_MODEL, _MODEL_METRICS
    _TRAINED_MODEL, _MODEL_METRICS = state


def persist_trained_model() -> None:
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{MODEL_PATH.name}.",
            suffix=".tmp",
            dir=MODEL_PATH.parent,
            delete=False,
        ) as temporary_file:
            temporary_path = temporary_file.name
        joblib.dump({
            "artifact_version": ARTIFACT_VERSION,
            "sklearn_version": sklearn.__version__,
            "feature_names": FEATURE_NAMES,
            "model": _TRAINED_MODEL,
            "metrics": _MODEL_METRICS,
        }, temporary_path)
        os.replace(temporary_path, MODEL_PATH)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)


def train_gradient_boosting_model(
    histories: List[SemesterHistory],
    persist: bool = True,
) -> Dict[str, Any]:
    """Train on early semester transitions and evaluate only on semesters 6->7 and 7->8."""
    global _TRAINED_MODEL, _MODEL_METRICS

    features, labels, semesters = _transition_examples(histories)
    train_indices = [i for i, semester in enumerate(semesters) if semester <= 5]
    test_indices = [i for i, semester in enumerate(semesters) if semester in (6, 7)]

    if not train_indices or not test_indices:
        _TRAINED_MODEL = None
        _MODEL_METRICS = _empty_metrics("insufficient_data")
        _MODEL_METRICS["honest_note"] = (
            "Model is unavailable: insufficient time-separated semester transitions for evaluation."
        )
        return _MODEL_METRICS

    X = np.asarray(features, dtype=float)
    y = np.asarray(labels, dtype=int)
    X_train, y_train = X[train_indices], y[train_indices]
    X_test, y_test = X[test_indices], y[test_indices]

    if len(np.unique(y_train)) < 2:
        _TRAINED_MODEL = None
        _MODEL_METRICS = _empty_metrics("insufficient_class_variation")
        _MODEL_METRICS["training_samples"] = len(train_indices)
        _MODEL_METRICS["test_samples"] = len(test_indices)
        _MODEL_METRICS["training_class_counts"] = {
            "negative": int(np.sum(y_train == 0)),
            "positive": int(np.sum(y_train == 1)),
        }
        _MODEL_METRICS["test_class_counts"] = {
            "negative": int(np.sum(y_test == 0)),
            "positive": int(np.sum(y_test == 1)),
        }
        _MODEL_METRICS["honest_note"] = (
            "Model is not trained: the time-based training transitions contain only one target class."
        )
        return _MODEL_METRICS

    class_counts = np.bincount(y_train, minlength=2)
    sample_weights = np.asarray([
        len(y_train) / (2.0 * class_counts[label]) for label in y_train
    ])
    model = GradientBoostingClassifier(
        n_estimators=100,
        max_depth=2,
        learning_rate=0.05,
        random_state=42
    )
    model.fit(X_train, y_train, sample_weight=sample_weights)

    model_predictions = model.predict(X_test)
    model_probabilities = model.predict_proba(X_test)[:, 1]
    model_metrics = _classification_metrics(y_test, model_predictions, model_probabilities)

    majority_class = int(np.bincount(y_train).argmax())
    majority_predictions = np.full(len(y_test), majority_class)
    majority_probabilities = np.full(len(y_test), float(majority_class))
    majority_metrics = _classification_metrics(y_test, majority_predictions, majority_probabilities)

    gpa_rule_predictions = (X_test[:, 0] < 6.5).astype(int)
    gpa_rule_metrics = _classification_metrics(
        y_test,
        gpa_rule_predictions,
        gpa_rule_predictions.astype(float)
    )

    model_beats_baseline = (
        model_metrics["f1"] > majority_metrics["f1"]
        and model_metrics["f1"] > gpa_rule_metrics["f1"]
    )
    if model_beats_baseline:
        honest_note = (
            "Predicts next-semester GPA drop or backlog increase using a time-based held-out split. "
            "The held-out F1 exceeds both baselines, but this imbalanced dataset is too small to "
            "support a reliable performance claim."
        )
    else:
        honest_note = (
            "Predicts next-semester GPA drop or backlog increase using a time-based held-out split. "
            "The model does not beat both baselines on held-out F1; results are not reliable enough "
            "for a performance claim."
        )
    if int(np.sum(y_train == 1)) < 20 or int(np.sum(y_test == 1)) < 20:
        honest_note += (
            f" Positive examples are scarce (training: {int(np.sum(y_train == 1))}; "
            f"held-out: {int(np.sum(y_test == 1))}). Interpret all metrics cautiously."
        )

    feature_importances = [
        {
            "feature": display_name,
            "raw_key": feature_name,
            "importance": round(float(importance), 4),
            "percentage": round(float(importance) * 100, 1)
        }
        for feature_name, display_name, importance in zip(
            FEATURE_NAMES,
            DISPLAY_FEATURE_NAMES,
            model.feature_importances_
        )
    ]

    _MODEL_METRICS = {
        "status": "trained",
        "training_samples": len(train_indices),
        "test_samples": len(test_indices),
        "training_class_counts": {
            "negative": int(np.sum(y_train == 0)),
            "positive": int(np.sum(y_train == 1)),
        },
        "test_class_counts": {
            "negative": int(np.sum(y_test == 0)),
            "positive": int(np.sum(y_test == 1)),
        },
        "accuracy": model_metrics["accuracy"],
        "precision": model_metrics["precision"],
        "recall": model_metrics["recall"],
        "f1": model_metrics["f1"],
        "roc_auc": model_metrics["roc_auc"],
        "model_metrics": model_metrics,
        "baseline_majority_metrics": majority_metrics,
        "baseline_gpa_rule_metrics": gpa_rule_metrics,
        "model_beats_baseline": model_beats_baseline,
        "honest_note": honest_note,
        "target_definition": (
            "Positive when the following semester's GPA drops by more than 0.5 "
            "or its backlog count increases."
        ),
        "feature_names": list(DISPLAY_FEATURE_NAMES),
        "feature_importance_note": (
            "Feature importance describes this fitted model's split usage; it is not causal "
            "and does not explain an individual prediction."
        ),
        "feature_importances": feature_importances,
        "model_type": "GradientBoostingClassifier (scikit-learn)"
    }
    _TRAINED_MODEL = model

    if persist:
        persist_trained_model()
    return _MODEL_METRICS


def get_model_metrics() -> Dict[str, Any]:
    """Return cached test metrics, including a clear note before training."""
    return _MODEL_METRICS if _MODEL_METRICS else _empty_metrics("not_trained")


def _load_cached_model() -> None:
    global _TRAINED_MODEL, _MODEL_METRICS
    if not MODEL_PATH.is_file():
        return

    try:
        cached = joblib.load(MODEL_PATH)
        model = cached.get("model") if isinstance(cached, dict) else None
        if (
            not isinstance(cached, dict)
            or cached.get("artifact_version") != ARTIFACT_VERSION
            or cached.get("sklearn_version") != sklearn.__version__
            or cached.get("feature_names") != FEATURE_NAMES
            or not isinstance(cached.get("metrics"), dict)
            or (
                model is not None
                and (
                    not callable(getattr(model, "predict_proba", None))
                    or getattr(model, "n_features_in_", None) != len(FEATURE_NAMES)
                    or list(getattr(model, "classes_", [])) != [0, 1]
                )
            )
        ):
            raise ValueError("incompatible model artifact")
    except (
        OSError,
        EOFError,
        ValueError,
        TypeError,
        AttributeError,
        ImportError,
        IndexError,
        KeyError,
        pickle.UnpicklingError,
    ) as exc:
        _TRAINED_MODEL = None
        _MODEL_METRICS = _empty_metrics("invalid_model_artifact")
        _MODEL_METRICS["honest_note"] = (
            "Cached model is missing, corrupt, or incompatible; predictions are unavailable "
            "until the model is retrained."
        )
        logger.warning("Risk model cache could not be loaded (%s).", type(exc).__name__)
        return

    if model is None and cached["metrics"].get("status") == "trained":
        _TRAINED_MODEL = None
        _MODEL_METRICS = _empty_metrics("invalid_model_artifact")
        _MODEL_METRICS["honest_note"] = (
            "Cached model is missing, corrupt, or incompatible; predictions are unavailable "
            "until the model is retrained."
        )
        logger.warning("Risk model cache contains metrics without a trained model.")
        return

    _TRAINED_MODEL = model
    _MODEL_METRICS = cached["metrics"]


def predict_student_risk_probability(
    history: Sequence[SemesterHistory]
) -> Optional[float]:
    """Return a validated probability, or None when the model/input is unavailable."""
    if _TRAINED_MODEL is None or not history:
        return None

    ordered_history = sorted(history, key=lambda row: row.semester)
    feature_row = _features_at_semester(ordered_history, len(ordered_history) - 1)
    if feature_row is None:
        return None
    features = np.asarray(
        [feature_row],
        dtype=float
    )
    try:
        probability = float(_TRAINED_MODEL.predict_proba(features)[0][1])
    except (AttributeError, IndexError, TypeError, ValueError) as exc:
        logger.warning("Risk model prediction failed (%s).", type(exc).__name__)
        return None
    if not np.isfinite(probability) or not 0.0 <= probability <= 1.0:
        logger.warning("Risk model returned an invalid probability.")
        return None
    return round(probability, 3)


_load_cached_model()
