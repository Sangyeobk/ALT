import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "alt"))

from revise_synthesis import extract, get_part, merge, shape_errors  # noqa: E402

SYNTHESIS = {
    "keywords": [{"id": "K1", "term": "검증 기준"}],
    "terms": [],
    "subtopics": [{"id": "T1", "name": "하중", "synthesis": "요지 [Tan2025]", "papers": ["Tan2025"]},
                  {"id": "T2", "name": "응답", "synthesis": "요지 [Hilo2026]", "papers": ["Hilo2026"]}],
    "method_comparison": [{"key": "Tan2025", "method": "CNN"}],
    "conclusion": {"points": [{"text": "결론", "cites": ["Tan2025"]}], "closing": "끝"},
}
REFERENCES = {"Tan2025": {"title": "A"}, "Hilo2026": {"title": "B"}, "Luo2026": {"title": "C"}}
PAPERS = [{"key": "Tan2025", "abstract": "a"}, {"key": "Hilo2026", "abstract": "b"}, {"key": "Luo2026", "abstract": "c"}]


def make_run(tmp_path):
    for name, payload in {"synthesis.json": SYNTHESIS, "references.json": REFERENCES,
                          "synthesis_input.json": {"meta": {}, "papers": PAPERS}}.items():
        (tmp_path / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def answer(run, changes, affected=(), **override):
    request_id = json.loads((run / "revision_input.json").read_text(encoding="utf-8"))["request_id"]
    payload = {"request_id": request_id, "changes": changes, "summary": "s", **override,
               "affected": None if affected is None else list(affected)}  # None = 작성자가 affected를 빠뜨린 경우
    (run / "revision_output.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def synthesis(run):
    return json.loads((run / "synthesis.json").read_text(encoding="utf-8"))


def test_get_part_finds_items_by_id_key_and_dict_key():
    assert get_part(SYNTHESIS, "subtopics#T2")["name"] == "응답"
    assert get_part(SYNTHESIS, "method_comparison#Tan2025")["method"] == "CNN"
    assert get_part(SYNTHESIS, "conclusion#closing") == "끝"


def test_extract_gives_only_cited_papers_but_all_citable_keys(tmp_path):
    run = make_run(tmp_path)
    payload = extract(run, "초록", ["subtopics#T1"], "더 쉽게")
    assert [p["key"] for p in payload["papers"]] == ["Tan2025"]
    assert {c["key"] for c in payload["citable"]} == set(REFERENCES)  # 새 근거도 붙일 수 있게
    assert "subtopics" in payload["outline"] and payload["attempt"] == 1
    assert (run / "feedback_log.jsonl").is_file()


def test_merge_replaces_only_the_target_and_keeps_backup(tmp_path):
    run = make_run(tmp_path)
    extract(run, "초록", ["subtopics#T1"], "더 쉽게")
    new = dict(SYNTHESIS["subtopics"][0], synthesis="쉬운 요지 [Tan2025; Luo2026]")
    answer(run, {"subtopics#T1": new})
    result = merge(run, "초록")
    assert result["merged"] and result["cross_verify"]  # 인용이 붙은 글이 바뀜
    after = synthesis(run)
    assert after["subtopics"][0]["synthesis"].startswith("쉬운") and after["subtopics"][1] == SYNTHESIS["subtopics"][1]
    assert len(list(run.glob("synthesis_before_revise_*.json"))) == 1


def test_merge_refuses_when_other_parts_are_affected_and_second_time_asks_user(tmp_path):
    run = make_run(tmp_path)
    for attempt in (1, 2):
        payload = extract(run, "초록", ["subtopics#T1"], "편수 고쳐")
        assert payload["attempt"] == attempt
        answer(run, {"subtopics#T1": SYNTHESIS["subtopics"][0]}, affected=[{"target": "conclusion", "why": "편수"}])
        result = merge(run, "초록")
        assert not result["merged"] and result["attempt"] == attempt
    assert synthesis(run) == SYNTHESIS  # 아무것도 안 바뀜


def test_merge_refuses_shape_change_and_unknown_citation(tmp_path):
    run = make_run(tmp_path)
    extract(run, "초록", ["conclusion"], "x")
    answer(run, {"conclusion": {"points": [{"text": "새 [Kim2024]", "cites": ["Kim2024"]}], "closing": "끝"}})
    assert any("Kim2024" in e for e in merge(run, "초록")["errors"])
    answer(run, {"conclusion": {"points": "글"}})
    errors = merge(run, "초록")["errors"]
    assert any("빠진 항목" in e for e in errors) and any("자료형" in e for e in errors)
    answer(run, {})
    assert any("대상 불일치" in e for e in merge(run, "초록")["errors"])
    assert synthesis(run) == SYNTHESIS


def test_shape_errors_for_lists_of_items():
    old = [{"text": "a", "cites": ["Tan2025"]}, {"text": "b", "cites": [], "source": "x"}]
    assert shape_errors(old, [{"text": "c", "cites": []}], "p") == []
    assert shape_errors(old, [{"text": "c"}], "p") == ["p[0]: 빠진 항목 ['cites']"]
    assert shape_errors(old, [{"text": "c", "cites": [], "new": 1}], "p") == ["p[0]: 새 항목 ['new']"]
    assert shape_errors(old, [{"text": "c", "cites": [123]}], "p") == ["p[0].cites[0]: 자료형이 바뀜 (str → int)"]
    assert shape_errors([[1]], [["문자"]], "n") == ["n[0][0]: 자료형이 바뀜 (int → str)"]  # 목록 안의 목록도 끝까지
    assert shape_errors(old, [{"text": None, "cites": []}], "p") == ["p[0].text: 값이 비었음 (이 항목의 기존 값 있음)"]
    assert shape_errors({"a": [1]}, None, "q") == ["q: 값이 비었음 (기존 dict)"]  # 절 전체 지우기 금지


def test_shape_errors_allow_data_keyed_dicts_and_optional_fields():
    old = [{"text": "a", "cites": ["Tan2025"], "pages": {"Tan2025": 3}}]
    new = [{"text": "b", "cites": ["Hilo2026"], "pages": {"Hilo2026": 7}}]  # pages의 키는 논문 키(데이터)
    assert shape_errors(old, new, "p") == []
    # 쪽 번호는 정수 또는 쪽 범위 글자만 (config optional_fields.pages) — 그 밖의 자료형은 거부
    assert shape_errors(old, [{"text": "b", "cites": [], "pages": {"Hilo2026": [7]}}], "p") == ["p[0].pages.Hilo2026: 자료형이 바뀜 (int/str → list)"]
    datasets = [{"name": "a", "link": None}]  # 실제 파일: 링크 없으면 null → 채우기는 허용, 엉뚱한 자료형은 거부
    assert shape_errors(datasets, [{"name": "a", "link": "https://x.org"}], "d") == []
    assert shape_errors(datasets, datasets, "d") == []  # 비어 있던 링크를 그대로 두는 것은 허용
    mixed_links = [{"name": "A", "link": "https://a.org"}, {"name": "B", "link": None}]
    cleared = [{"name": "A", "link": None}, {"name": "B", "link": None}]  # B가 비어 있어도 A의 링크는 지우지 못함
    assert shape_errors(mixed_links, cleared, "d") == ["d[0].link: 값이 비었음 (이 항목의 기존 값 있음)"]
    assert shape_errors(mixed_links, [{"name": "A"}, {"name": "B", "link": None}], "d") == ["d[0]: 빠진 항목 ['link']"]
    assert shape_errors(datasets, [{"name": "a", "link": {}}], "d") == ["d[0].link: 자료형이 바뀜 (str → dict)"]
    plain = [{"text": "a", "cites": []}]  # 선택 칸(source·pages)이 한 번도 없던 목록 → config 예시가 기준
    assert shape_errors(plain, [{"text": "b", "cites": [], "source": "일반 개념"}], "p") == []
    assert shape_errors(plain, [{"text": "b", "cites": [], "pages": {"A": 7, "B": "10–11"}}], "p") == []
    assert shape_errors(plain, [{"text": "b", "cites": [], "source": 123}], "p") == ["p[0].source: 자료형이 바뀜 (str → int)"]
    assert shape_errors(plain, [{"text": "b", "cites": [], "pages": 123}], "p") == ["p[0].pages: 자료형이 바뀜 (dict → int)"]
    assert shape_errors({"AI": "x"}, {"AI": "x", "CFD": "y"}, "abbreviations", free=True) == []
    mixed = [{"text": "a", "cites": [], "pages": {"A": 3}}, {"text": "b", "cites": [], "pages": {"B": "10–11"}}]
    assert shape_errors(mixed, [{"text": "c", "cites": [], "pages": {"C": "4–5"}}], "p") == []  # 실제 파일에 쪽 범위가 섞여 있음


def test_merge_requires_matching_request_unchanged_source_and_affected_list(tmp_path):
    run = make_run(tmp_path)
    extract(run, "초록", ["conclusion"], "x")
    answer(run, {"conclusion": SYNTHESIS["conclusion"]}, request_id="old-request")  # 이전 요청의 결과
    assert any("요청 번호" in e for e in merge(run, "초록")["errors"])
    answer(run, {"conclusion": SYNTHESIS["conclusion"]}, affected=None)
    assert any("affected" in e for e in merge(run, "초록")["errors"])
    answer(run, {"conclusion": SYNTHESIS["conclusion"]})
    (run / "synthesis.json").write_text(json.dumps({**SYNTHESIS, "terms": [{"term": "x", "variants": []}]},
                                                      ensure_ascii=False), encoding="utf-8")  # 뽑은 뒤 다른 수정
    assert any("바뀜" in e for e in merge(run, "초록")["errors"])


def test_removing_citations_still_needs_cross_verification(tmp_path):
    run = make_run(tmp_path)
    extract(run, "초록", ["conclusion"], "근거 빼고 단정")
    answer(run, {"conclusion": {"points": [{"text": "새 주장", "cites": []}], "closing": "끝"}})
    assert merge(run, "초록")["cross_verify"]


def test_each_merge_keeps_its_own_backup_and_lock_blocks_parallel_merge(tmp_path):
    run = make_run(tmp_path)
    for text in ("하나", "둘"):
        extract(run, "초록", ["conclusion#closing"], text)
        answer(run, {"conclusion#closing": text})
        assert merge(run, "초록")["merged"]
    assert len(list(run.glob("synthesis_before_revise_*.json"))) == 2
    extract(run, "초록", ["conclusion#closing"], "셋")
    answer(run, {"conclusion#closing": "셋"})
    (run / "synthesis.json.lock").write_text("", encoding="utf-8")  # 다른 합치기 진행 중
    assert any("진행 중" in e for e in merge(run, "초록")["errors"])
    assert synthesis(run)["conclusion"]["closing"] == "둘"
