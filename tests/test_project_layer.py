"""이 조사 맞춤 층(결과 폴더 project/): 우선순위 기본 < 개인 < 이 조사, 선정 기준 덮어쓰기, 맞춤 결과물 (사용자 결정 2026-10-16)."""
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "alt"))

import common  # noqa: E402


@pytest.fixture
def personal(tmp_path, monkeypatch):
    """개인 설정 파일을 임시 위치로 (사용자 PC 설정을 건드리지 않음)."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(common, "USER_SETTINGS_PATH", home / "settings.yaml")
    monkeypatch.setattr(common, "USER_STYLE_PATH", home / "report_style.md")
    return home


def project_settings(run, data):
    (run / "project").mkdir(parents=True, exist_ok=True)
    (run / "project" / "settings.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def test_sections_project_beats_personal_beats_config(tmp_path, personal):
    run = tmp_path / "run"
    run.mkdir()
    default = common.load_config()["output"]["report_sections"]
    assert common.sections("report", run) == default                      # 맞춤 없음 → 기존과 같음
    (personal / "settings.yaml").write_text(yaml.safe_dump({"report_sections": ["summary"]}), encoding="utf-8")
    assert common.sections("report", run) == ["summary"]
    project_settings(run, {"report_sections": ["conclusion"]})
    assert common.sections("report", run) == ["conclusion"]
    assert common.sections("report") == ["summary"]                       # 결과 폴더 없이 부르면 개인 설정까지만


def test_style_adds_project_after_personal(tmp_path, personal):
    run = tmp_path / "run"
    (personal / "report_style.md").write_text("- 개인: 짧게", encoding="utf-8")
    assert common.load_user_style(run) == "- 개인: 짧게"
    (run / "project").mkdir(parents=True)
    (run / "project" / "style.md").write_text("- 이 조사: 표 먼저", encoding="utf-8")
    text = common.load_user_style(run)
    assert text.index("개인") < text.index("이 조사 맞춤") < text.index("표 먼저")


def test_scoring_overrides_are_layered_and_listed(tmp_path, personal):
    run = tmp_path / "run"
    run.mkdir()
    default = common.load_config()["scoring"]
    rules, overrides = common.scoring_config(run)
    assert rules == default and overrides == []
    common.set_scoring("max_selected=20")                                 # 개인 설정
    common.set_scoring("review.max_listed=2", run)                        # 이 조사만
    common.set_scoring(f"max_selected={default['max_selected']}", run)    # 이 조사에서 기본값으로 되돌림 → 목록에 안 나옴
    rules, overrides = common.scoring_config(run)
    assert rules["max_selected"] == default["max_selected"] and rules["review"]["max_listed"] == 2
    assert rules["weights"] == default["weights"]                         # 안 바꾼 항목은 그대로
    assert overrides == [{"key": "review.max_listed", "default": default["review"]["max_listed"], "value": 2, "source": "이 조사 맞춤"}]
    assert common.scoring_config()[0]["max_selected"] == 20               # 다른 조사는 개인 설정을 따름


def test_scoring_rejects_unknown_key(tmp_path, personal):
    with pytest.raises(SystemExit):
        common.set_scoring("max_selcted=20")
    project_settings(tmp_path, {"scoring": {"typo_key": 1}})
    with pytest.raises(SystemExit):
        common.scoring_config(tmp_path)


def test_extra_outputs_are_citation_checked(tmp_path):
    import check_citations
    (tmp_path / "project").mkdir()
    (tmp_path / "project" / "extras.yaml").write_text(yaml.safe_dump([
        {"name": "비교", "script": "a.py", "outputs": ["07_비교.md"]},
        {"name": "그림", "script": "b.py", "outputs": ["08_그림.png"], "cite_check": False}], allow_unicode=True), encoding="utf-8")
    assert common.extra_files(tmp_path, "초록") == ["07_비교.md", "08_그림.png"]
    (tmp_path / "07_비교.md").write_text("[Kim2025] 비교", encoding="utf-8")
    texts, unreadable = check_citations.output_texts(tmp_path, "초록")
    assert "07_비교.md" in texts and not unreadable
    assert common.extra_outputs(tmp_path / "없음") == []
