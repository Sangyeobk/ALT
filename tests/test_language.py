"""결과물 언어 (사용자 결정 2026-10-29): 한국어는 그대로, 영어는 alt/lang/en.yaml — 빠진 번역이 없는지."""
import ast
import re
import string
import sys
from pathlib import Path

import pytest
import yaml

ALT = Path(__file__).resolve().parents[1] / "alt"
sys.path.insert(0, str(ALT))

import common  # noqa: E402
from common import report_title, scope_years, topic_line, tr, use_language, write_json  # noqa: E402

EN = yaml.safe_load((ALT / "lang" / "en.yaml").read_text(encoding="utf-8"))
HANGUL = re.compile("[가-힣]")
TOPIC = {"input": "x", "topic_ko": "선박 연료 소모량", "topic_en": "Ship fuel consumption", "approach_ko": "데이터 기반",
         "approach_en": "data-driven", "years": "2025-2026", "include": "a", "exclude": "b", "question": "c"}


@pytest.fixture
def english():
    common._output_language["code"] = "en"
    yield
    common._output_language["code"] = "ko"


def marked_literals() -> list[tuple[str, str]]:
    """alt/*.py의 tr("…")·tr_later("…") 원문 (파일, 원문)."""
    found = []
    for path in ALT.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and getattr(node.func, "id", None) in ("tr", "tr_later") and node.args
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                found.append((path.name, node.args[0].value))
    return found


def fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_every_marked_korean_literal_has_an_english_entry_with_same_placeholders():
    missing, mismatched = [], []
    for name, text in marked_literals():
        if not HANGUL.search(text):
            continue
        entry = EN.get(text)
        if entry is None:
            missing.append(f"{name}: {text}")
            continue
        for value in ([entry] if isinstance(entry, str) else [entry["one"], entry["other"]]):
            if fields(value) != fields(text) or HANGUL.search(value):
                mismatched.append(f"{name}: {text} -> {value}")
    assert not missing, "영어 대응 없음:\n" + "\n".join(sorted(set(missing)))
    assert not mismatched, "자리표시가 다르거나 한글이 남음:\n" + "\n".join(sorted(set(mismatched)))


def test_config_display_labels_have_english_entries():
    output = common.load_config()["output"]
    labels = [*output["role_labels"].values(), *output["approach_labels"].values(), *output["data_source_labels"],
              output["axis_unknown_label"], output["structure_axis_name"], *(g[0] for g in output["structure_groups"])]
    assert not [x for x in labels if HANGUL.search(x) and x not in EN]


def test_korean_is_unchanged_and_english_uses_the_table(english):
    assert tr(" 외 {n}편", n=1) == " and 1 more paper" and tr(" 외 {n}편", n=3) == " and 3 more papers"
    assert tr("AI가 쓴 글은 그대로") == "AI가 쓴 글은 그대로"  # 대응표에 없는 글(요약 등)은 바꾸지 않음
    common._output_language["code"] = "ko"
    assert tr(" 외 {n}편", n=3) == " 외 3편"


def test_run_language_comes_from_topic_record(tmp_path, english):
    write_json(tmp_path / "topic.json", {**TOPIC, "language": "en"})
    assert use_language(tmp_path) == "en"
    assert report_title(tmp_path, {}, {}) == f"Ship fuel consumption — Research Trends (data-driven, {scope_years(TOPIC)})"
    assert topic_line(tmp_path).startswith("Survey topic: Ship fuel consumption · Approach: data-driven")
    write_json(tmp_path / "topic.json", TOPIC)  # 언어 기록 없는 예전 조사 → 한국어
    assert use_language(tmp_path) == "ko"
    assert report_title(tmp_path, {}, {}) == f"선박 연료 소모량 — 데이터 기반 연구 동향 ({scope_years(TOPIC)})"


def test_stored_flags_with_filled_values_are_translated(english):
    from common import tr_stored
    assert tr_stored("공지: retraction") == "Notice: retraction"
    assert tr_stored("초록 없음 → 관련성 5점을 상한 3점으로") == "No abstract → relevance 5 capped at 3"
    assert tr_stored("철회됨") == "Retracted" and tr_stored("모르는 표시") == "모르는 표시"


def test_language_option_is_kept_with_other_update_options(tmp_path, monkeypatch):
    import define_topic
    write_json(tmp_path / "topic.json", TOPIC)
    monkeypatch.setattr(sys, "argv", ["define_topic.py", str(tmp_path), "--language", "en", "--scope-reason", "이유"])
    define_topic.main()
    record = common.read_json(tmp_path / "topic.json")
    assert record["language"] == "en" and record["scope_reason"] == "이유"


def test_korean_title_keeps_case_sensitive_approach_check(tmp_path):
    write_json(tmp_path / "topic.json", {**TOPIC, "topic_ko": "pinn 기반 파랑하중", "approach_ko": "PINN"})
    use_language(tmp_path)
    assert report_title(tmp_path, {}, {}).startswith("pinn 기반 파랑하중 — PINN 연구 동향")
