"""결과는 판 구분 없이 한 벌 (사용자 결정 2026-10-19) — 기본 초록, 전문을 한 번이라도 쓴 조사는 계속 전문."""

import json

from common import run_reading_mode, variant_name
from cross_verify import relevance_rounds


def test_output_names_have_no_variant():
    assert variant_name("03_report.docx", "초록") == "03_report.docx"
    assert variant_name("synthesis.json", "전문활용") == "synthesis.json"


def test_reading_mode_stays_full_once_fulltext_was_used(tmp_path):
    assert run_reading_mode(tmp_path) == "abstract"  # 기본 (config fulltext.reading_mode)
    (tmp_path / "synthesis_input.json").write_text(json.dumps({"meta": {"reading_mode": "full"}}), encoding="utf-8")
    assert run_reading_mode(tmp_path) == "full"  # 지난 요약이 전문 모드
    (tmp_path / "synthesis_input.json").unlink()
    (tmp_path / "fulltext_notes_1.json").write_text("{}", encoding="utf-8")
    assert run_reading_mode(tmp_path) == "full"  # 전문 정리 기록이 있음


def test_relevance_rounds_skip_output_reports(tmp_path):
    for name in ("verification_codex.md", "verification_codex_2.md", "verification_codex_outputs_초록.md",
                 "verification_codex_outputs_전문활용.md"):
        (tmp_path / name).write_text("", encoding="utf-8")
    assert sorted(p.name for p in relevance_rounds(tmp_path, "codex")) == ["verification_codex.md", "verification_codex_2.md"]
