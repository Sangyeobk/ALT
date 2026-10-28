import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "alt"))

import common  # noqa: E402
import prepare_relevance_batches  # noqa: E402
import review_contribution  # noqa: E402
from test_revise_synthesis import make_run  # noqa: E402
from revise_synthesis import extract  # noqa: E402

PREF = "SECRET_PREF 부유식 해상풍력은 늘 포함"


def use_tmp_profile(monkeypatch, tmp_path):
    monkeypatch.setattr(common, "USER_STYLE_PATH", tmp_path / "profile" / "report_style.md")
    monkeypatch.setattr(common, "USER_SEARCH_PREFS_PATH", tmp_path / "profile" / "search_prefs.md")


def test_add_preference_keeps_date_and_run_with_one_header(tmp_path, monkeypatch):
    use_tmp_profile(monkeypatch, tmp_path)
    common.add_preference("search", PREF, run="20261013_test")
    path = common.add_preference("search", "두 번째", run=None)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("# 검색 취향") and sum(line.startswith("#") for line in lines) == 1
    assert "(20261013_test): SECRET_PREF" in lines[2] and lines[3].endswith(": 두 번째")
    assert common.load_search_prefs().count("- ") == 2


def test_search_prefs_never_reach_scoring_inputs(tmp_path, monkeypatch):
    use_tmp_profile(monkeypatch, tmp_path)
    common.add_preference("search", PREF)
    candidates = tmp_path / "candidates.json"
    record = {"openalex_id": "W1", "title": "t", "year": 2025, "venue": "v", "abstract": "a"}
    candidates.write_text(json.dumps({"meta": {"search_prefs": common.load_search_prefs()}, "records": [record]}),
                          encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["x", str(candidates), "--topic", "t", "--approach", "a", "--batches", "1"])
    prepare_relevance_batches.main()
    (tmp_path / "scored.json").write_text(json.dumps({"meta": {"queries": ["q"], "search_prefs": PREF},
                                                      "records": [{**record, "is_review": True, "relevance": 5}]}),
                                          encoding="utf-8")
    review_contribution.prepare(tmp_path)
    for name in ("relevance_input_1.json", "review_eval_input.json"):  # 관련성 채점 · 문헌조사논문 평가 입력
        assert "SECRET_PREF" not in (tmp_path / name).read_text(encoding="utf-8")


def test_style_edits_and_deletion_reach_the_next_run(tmp_path, monkeypatch):
    use_tmp_profile(monkeypatch, tmp_path)
    run = make_run(tmp_path)
    style = common.add_preference("style", "결론은 세 줄")
    assert "결론은 세 줄" in extract(run, "초록", ["conclusion"], "f")["user_style"]
    style.write_text("# 개인 스타일\n- 결론은 두 줄\n", encoding="utf-8")  # 사용자가 직접 고침
    assert "두 줄" in extract(run, "초록", ["conclusion"], "f")["user_style"]
    style.unlink()  # 지움
    assert extract(run, "초록", ["conclusion"], "f")["user_style"] == "" == common.load_user_style()
