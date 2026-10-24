import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

_TEST_DIRECTORY = tempfile.TemporaryDirectory(prefix="educare-ml-tests-")
_TEST_ROOT = Path(_TEST_DIRECTORY.name)
os.environ["DATABASE_URL"] = f"sqlite:///{(_TEST_ROOT / 'ml-test.db').as_posix()}"
os.environ["MODEL_CACHE_PATH"] = str(_TEST_ROOT / "model-cache" / "risk_model.joblib")
os.environ["SECRET_KEY"] = "isolated-ml-test-key-not-for-production"
os.environ["CORS_ALLOWED_ORIGINS"] = "http://localhost:8000"

from app import ml
from app.database import Base, engine


@pytest.fixture(scope="session", autouse=True)
def isolated_database_and_cache():
    Base.metadata.create_all(bind=engine)
    yield
    engine.dispose()
    _TEST_DIRECTORY.cleanup()


def _history(semester, gpa=7.0, attendance=80.0, credits=20, backlogs=0):
    return SimpleNamespace(
        student_id="TEST-ONLY",
        semester=semester,
        gpa=gpa,
        attendance_pct=attendance,
        credits_earned=credits,
        backlogs=backlogs,
    )


def _balanced_test_data():
    features = [[float(index + offset) for offset in range(5)] for index in range(24)]
    labels = [int(index in (0, 1, 20)) for index in range(24)]
    semesters = [index % 5 + 1 for index in range(20)] + [6, 7, 6, 7]
    return features, labels, semesters


def test_target_uses_next_semester_outcome_but_features_do_not():
    history = [_history(1, gpa=7.5), _history(2, gpa=6.8)]

    features, labels, semesters = ml._transition_examples(history)

    assert features == [ml._features_at_semester(history, 0)]
    assert labels == [1]
    assert semesters == [1]
    changed_future = [_history(1, gpa=7.5), _history(2, gpa=9.0)]
    assert ml._features_at_semester(changed_future, 0) == features[0]
    assert ml._transition_examples(changed_future)[1] == [0]


def test_missing_or_invalid_feature_values_are_not_replaced_with_zero():
    assert ml._features_at_semester([_history(1, attendance=None)], 0) is None
    assert ml._features_at_semester([_history(1, gpa=float("nan"))], 0) is None


def test_metrics_report_confusion_matrix_and_class_counts():
    actual = np.asarray([0, 0, 0, 1, 1])
    predicted = np.asarray([0, 0, 1, 1, 0])
    probabilities = np.asarray([0.1, 0.2, 0.8, 0.7, 0.4])

    result = ml._classification_metrics(actual, predicted, probabilities)

    assert result["precision"] == 0.5
    assert result["recall"] == 0.5
    assert result["f1"] == 0.5
    assert result["confusion_matrix"] == [[2, 1], [1, 1]]
    assert result["actual_class_counts"] == {"negative": 3, "positive": 2}
    assert result["roc_auc"] is not None


def test_training_uses_time_separated_metrics_and_reports_imbalance(monkeypatch):
    monkeypatch.setattr(ml, "_transition_examples", lambda _: _balanced_test_data())
    monkeypatch.setattr(ml, "MODEL_PATH", _TEST_ROOT / "unused-cache.joblib")

    metrics = ml.train_gradient_boosting_model([], persist=False)

    assert metrics["status"] == "trained"
    assert metrics["training_samples"] == 20
    assert metrics["test_samples"] == 4
    assert metrics["training_class_counts"] == {"negative": 18, "positive": 2}
    assert metrics["test_class_counts"] == {"negative": 3, "positive": 1}
    assert metrics["model_metrics"]["confusion_matrix"]
    assert "scarce" in metrics["honest_note"]
    assert "cv_precision" not in metrics
    assert "backlog count increases" in metrics["target_definition"]


def test_single_class_training_data_does_not_create_a_model(monkeypatch):
    monkeypatch.setattr(
        ml,
        "_transition_examples",
        lambda _: ([[1.0] * 5 for _ in range(4)], [0, 0, 0, 0], [1, 2, 6, 7]),
    )
    ml._TRAINED_MODEL = None

    metrics = ml.train_gradient_boosting_model([], persist=False)

    assert metrics["status"] == "insufficient_class_variation"
    assert ml.predict_student_risk_probability([_history(1)]) is None


def test_missing_corrupt_and_incompatible_model_cache_never_predict_low_risk(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(ml, "MODEL_PATH", tmp_path / "risk_model.joblib")
    ml._TRAINED_MODEL = None
    ml._MODEL_METRICS = {}
    ml._load_cached_model()
    assert ml.predict_student_risk_probability([_history(1)]) is None

    ml.MODEL_PATH.write_bytes(b"not a valid joblib artifact")
    ml._load_cached_model()
    assert ml.get_model_metrics()["status"] == "invalid_model_artifact"
    assert ml.predict_student_risk_probability([_history(1)]) is None

    ml.joblib.dump(
        {"artifact_version": -1, "model": None, "metrics": {"status": "trained"}},
        ml.MODEL_PATH,
    )
    ml._load_cached_model()
    assert ml.get_model_metrics()["status"] == "invalid_model_artifact"
    assert ml.predict_student_risk_probability([_history(1)]) is None


def test_persisted_unavailable_model_stays_unavailable_after_reload(monkeypatch, tmp_path):
    monkeypatch.setattr(ml, "MODEL_PATH", tmp_path / "risk_model.joblib")
    ml._TRAINED_MODEL = None
    ml._MODEL_METRICS = ml._empty_metrics("insufficient_data")

    ml.persist_trained_model()
    ml._MODEL_METRICS = {}
    ml._load_cached_model()

    assert ml._TRAINED_MODEL is None
    assert ml.get_model_metrics()["status"] == "insufficient_data"
    assert ml.predict_student_risk_probability([_history(1)]) is None


def test_prediction_requires_contiguous_valid_features():
    ml._TRAINED_MODEL = None
    assert ml.predict_student_risk_probability([]) is None
    assert ml.predict_student_risk_probability([_history(2)]) is None
