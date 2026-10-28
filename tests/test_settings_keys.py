import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "alt"))

import common  # noqa: E402
import settings  # noqa: E402

KEY = "TESTKEY0123456789abcdef"


def run_settings(monkeypatch, capsys, *args):
    monkeypatch.setattr(sys, "argv", ["settings.py", *args])
    settings.main()
    return capsys.readouterr().out


def test_openalex_key_from_clipboard_saved_and_hidden(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(common, "USER_SETTINGS_PATH", tmp_path / "settings.yaml")
    common.save_user_settings(email="me@example.com")
    assert "not set (optional)" in run_settings(monkeypatch, capsys, "--show")

    run_settings(monkeypatch, capsys, "--skip-openalex-key")
    assert "openalex_key: not set (declined " in run_settings(monkeypatch, capsys, "--show")

    monkeypatch.setattr(settings, "read_clipboard", lambda: f"  {KEY}\r\n")
    run_settings(monkeypatch, capsys, "--openalex-key", "--from-clipboard")
    saved = common.load_user_settings()
    assert saved["openalex_key"] == KEY and saved["email"] == "me@example.com"
    shown = run_settings(monkeypatch, capsys, "--show")
    assert "openalex_key: set" in shown and KEY not in shown
