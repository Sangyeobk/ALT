"""갱신 전 점검 — 새 전문은 맥락 정리 대상만 (10-19 거짓 경고: 인접 문헌 PDF를 '새 전문'으로 셈)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "alt"))

from refresh_check import new_fulltexts  # noqa: E402


def test_stale_slide_plans_are_reported_separately(tmp_path, monkeypatch):
    import os
    import build_pptx
    import slides_plan
    from refresh_check import slide_plan_status

    monkeypatch.setattr(build_pptx, "pptx_style", lambda: {"path": tmp_path / "t.pptx"})
    monkeypatch.setattr(slides_plan, "load_catalog", lambda style: {"types": {}})  # 장 종류 목록이 있는 양식
    for name in ("synthesis.json", "slides.json", "slides_learn.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    os.utime(tmp_path / "synthesis.json", (200, 200))
    os.utime(tmp_path / "slides.json", (100, 100))
    os.utime(tmp_path / "slides_learn.json", (300, 300))
    assert slide_plan_status(tmp_path) == {"slides.json": "오래됨", "slides_learn.json": "최신"}
    (tmp_path / "slides_learn.json").unlink()
    assert slide_plan_status(tmp_path)["slides_learn.json"] == "없음"
    monkeypatch.setattr(build_pptx, "pptx_style", lambda: {"path": None})  # 양식 없음(plain) → 구성안 없이 만듦, 점검 안 함
    assert slide_plan_status(tmp_path) == {}


def test_only_context_targets_count_as_new_fulltext(tmp_path):
    refs = {"Sel2025": {"status": "selected"}, "Adj2025": {"status": "below_relevance", "adjacent_listed": True},
            "Done2025": {"status": "selected"}}
    (tmp_path / "references.json").write_text(json.dumps(refs), encoding="utf-8")
    (tmp_path / "papers").mkdir()
    for key in refs:
        (tmp_path / "papers" / f"{key}.pdf").write_bytes(b"%PDF")
    assert new_fulltexts(tmp_path, {"Done2025": "전문"}) == ["Sel2025"]
