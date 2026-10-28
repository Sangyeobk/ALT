import json

from extract_fulltext import make_batches, next_batch_number, noted_keys, trim_sections


def test_already_noted_papers_are_skipped_and_numbering_continues(tmp_path):
    assert noted_keys(tmp_path) == set() and next_batch_number(tmp_path) == 1
    (tmp_path / "fulltext_notes_1.json").write_text(json.dumps({"notes": {"A": {}}}), encoding="utf-8")
    (tmp_path / "fulltext_notes_8.json").write_text(json.dumps({"notes": {"B": {"unreadable": True}}}), encoding="utf-8")
    assert noted_keys(tmp_path) == {"A", "B"}  # 못 읽은 것도 시도했으니 다시 읽지 않음
    assert next_batch_number(tmp_path) == 9    # 기존 정리 파일을 덮어쓰지 않음

WORDS = ["introduction", "literature review"]
PAPER = """[[p.1]]
Abstract
We predict loads.
1. Introduction
Long motivation text.
[[p.2]]
More background.
1.1 Previous studies
Many studies.
2. Literature review
Review text.
[[p.3]]
3. Methodology
Our model.
4 Results
R2 = 0.98
"""


def test_trim_sections_drops_intro_and_review_but_keeps_page_marks():
    text, removed = trim_sections(PAPER, WORDS, max_ratio=0.9)
    assert "motivation" not in text and "Many studies" not in text and "Review text" not in text
    assert "Abstract" in text and "3. Methodology" in text and "R2 = 0.98" in text
    assert text.index("[[p.2]]") < text.index("[[p.3]]") < text.index("3. Methodology")  # 쪽 번호가 그대로 맞음
    assert removed > 0


def test_trim_sections_skips_when_too_much_would_go():
    assert trim_sections(PAPER, WORDS, max_ratio=0.1) == (PAPER, 0)


def test_trim_sections_needs_numbered_heading():
    plain = "INTRODUCTION\nText\nMETHODS\nModel\n"
    assert trim_sections(plain, WORDS, max_ratio=0.9) == (plain, 0)


def test_make_batches_one_paper_each_and_balanced():
    assert sorted(map(len, make_batches({"a": 5, "b": 3, "c": 1}, 1))) == [1, 1, 1]
    batches = make_batches({"a": 9, "b": 5, "c": 4, "d": 1}, 2)
    assert len(batches) == 2 and sorted(map(sorted, batches)) == [["a", "d"], ["b", "c"]]


def test_context_targets_are_all_cited_papers_but_not_institution_docs():
    """맥락 정리 대상 (사용자 결정 2026-10-16): 핵심논문·문헌조사논문 전부, 기관·선급 문서와 그 밖 후보는 제외."""
    from extract_fulltext import context_keys
    refs = {"A": {"status": "selected"}, "B": {"status": "review_listed"}, "C": {"status": "below_threshold"},
            "KR2024": {"status": "institution_listed", "category": "institution"},
            "D": {"status": "selected", "category": "institution"}}
    assert context_keys(refs, ["selected", "review_listed"]) == ["A", "B"]


def test_figure_targets_fall_back_to_noted_papers_when_priority_has_no_fulltext(tmp_path):
    """fulltext_priority는 '다음에 읽을 논문'이라 본문이 없을 수 있음 (PINN 세부 조사 2026-10-16: 그림 대상 0편)."""
    from common import write_json
    from extract_fulltext import target_keys
    refs = {"A": {}, "B": {}, "C": {}}
    write_json(tmp_path / "fulltext_notes_1.json", {"notes": {"A": {}, "B": {}}})
    write_json(tmp_path / "synthesis.json", {"conclusion": {"fulltext_priority": [{"key": "C"}]}})
    assert target_keys(tmp_path, refs, "priority", "초록") == ["A", "B"]
    write_json(tmp_path / "synthesis.json", {"conclusion": {"fulltext_priority": [{"key": "B"}, {"key": "C"}]}})
    assert target_keys(tmp_path, refs, "priority", "초록") == ["B"]
