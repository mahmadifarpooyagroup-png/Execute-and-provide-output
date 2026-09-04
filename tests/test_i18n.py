import json
from pathlib import Path


def test_english_and_persian_locales_have_required_keys():
    project_root = Path(__file__).parents[1]
    english = json.loads(
        (project_root / "frontend/src/locales/en/translation.json").read_text(encoding="utf-8")
    )
    persian = json.loads(
        (project_root / "frontend/src/locales/fa/translation.json").read_text(encoding="utf-8")
    )
    required = {
        "app_title",
        "dashboard",
        "workflows",
        "recovery",
        "settings",
        "language_toggle",
        "welcome_message",
        "loading",
        "error",
    }
    assert required <= english.keys()
    assert required <= persian.keys()