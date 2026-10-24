from pathlib import Path
import re


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_login_backdrop_uses_a_soft_teal_gradient():
    stylesheet = (PROJECT_ROOT / "static" / "css" / "style.css").read_text(
        encoding="utf-8"
    )
    backdrop_rule = re.search(
        r"\.login-backdrop\s*\{([^}]+)\}", stylesheet, re.DOTALL
    )

    assert backdrop_rule is not None
    assert "linear-gradient" in backdrop_rule.group(1)
    assert "radial-gradient" in backdrop_rule.group(1)
    assert "rgba(15, 92, 92" in backdrop_rule.group(1)


def test_visible_registration_panel_has_a_teal_highlight():
    stylesheet = (PROJECT_ROOT / "static" / "css" / "style.css").read_text(
        encoding="utf-8"
    )

    assert "#registration-panel:not([hidden])" in stylesheet
    registration_rule = re.search(
        r"#registration-panel:not\(\[hidden\]\)\s*\{([^}]+)\}",
        stylesheet,
        re.DOTALL,
    )

    assert registration_rule is not None
    assert "linear-gradient" in registration_rule.group(1)
    assert "#0A4343" in registration_rule.group(1)
    assert "#0F5C5C" in registration_rule.group(1)
    assert "#registration-panel p" in stylesheet
    assert "color: #F2F7F5;" in stylesheet
