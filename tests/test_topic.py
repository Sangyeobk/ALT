"""주제 구체화 (사용자 지시 2026-10-16): 확정한 이름이 결과물에 그대로 쓰이는지."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "alt"))

from common import display_names, report_title, scope_history, topic_line, write_json  # noqa: E402
from define_topic import FIELDS, add_scope_history, topic_record  # noqa: E402

TOPIC = {"input": "wave loads on offshore platform, data-driven, 2025-2027", "topic_ko": "해양플랫폼 파랑하중",
         "topic_en": "Wave loads on offshore platforms", "approach_ko": "데이터 기반 방법", "approach_en": "data-driven",
         "years": "2025-2027", "include": "고정식·부유식 플랫폼", "exclude": "교량·모노파일", "question": "어디까지 믿을 수 있나"}


def test_topic_record_keeps_input_verbatim_and_rejects_blank_fields():
    record = topic_record({**TOPIC, "input": "  wave loads on offshore platform  "})
    assert record["input"] == "wave loads on offshore platform" and set(FIELDS) <= set(record)
    with pytest.raises(SystemExit):
        topic_record({**TOPIC, "topic_ko": " "})


def test_confirmed_topic_wins_over_synthesis_names_and_input(tmp_path):
    s = {"title": "에이전트가 지은 제목", "names": {"topic": "해양구조물 파랑하중", "approach": "학습법"}}
    meta = {"topic": "Wave loads", "approach": "data-driven"}
    assert display_names(tmp_path, s, meta) == {"topic": "해양구조물 파랑하중", "approach": "학습법"}  # 확정 전: 요약 names
    assert display_names(tmp_path, {}, meta)["approach"] == "데이터 기반"  # 요약에도 없으면 입력 접근법 표시 이름
    assert report_title(tmp_path, s, {}) == "에이전트가 지은 제목" and topic_line(tmp_path) == ""
    write_json(tmp_path / "topic.json", topic_record(TOPIC))
    assert display_names(tmp_path, s, meta) == {"topic": "해양플랫폼 파랑하중", "approach": "데이터 기반 방법"}
    refs = {"A": {"year": 2025}, "B": {"year": 2026}}
    assert report_title(tmp_path, s, refs) == "해양플랫폼 파랑하중 — 데이터 기반 방법 연구 동향 (2025–2026)"
    assert topic_line(tmp_path).startswith("조사 주제: 해양플랫폼 파랑하중 (Wave loads on offshore platforms)")


def test_evaluator_inputs_carry_confirmed_topic_and_rubrics_assume_no_field(tmp_path):
    """두 번째 주제(선박 연료) 실행에서 리뷰 평가 기준에 시험 주제가 박혀 있던 결함 (2026-10-16)."""
    from common import PACKAGE_DIR, read_json
    from review_contribution import prepare
    write_json(tmp_path / "topic.json", topic_record(TOPIC))
    review = {"openalex_id": "W1", "title": "A review", "year": 2025, "venue": "J", "abstract": "x", "relevance": 5, "is_review": True}
    write_json(tmp_path / "scored.json", {"meta": {"queries": ["q"]}, "records": [review]})
    assert prepare(tmp_path) == 1
    data = read_json(tmp_path / "review_eval_input.json")
    assert data["topic"] == TOPIC["topic_en"] and data["scope"]["exclude"] == TOPIC["exclude"]
    for name in ("review_rubric.md", "relevance_rubric.md", "doc_review_prompt.md"):
        assert "파랑" not in (PACKAGE_DIR / name).read_text(encoding="utf-8"), name


def test_map_axis_defaults_to_structure_and_topic_axis_splits_title_abstract(tmp_path):
    """문헌지도 가로축 (사용자 결정 2026-10-16): 축을 정하지 않으면 구조물(첫 시험 주제와 같음), 정하면 제목·초록 낱말로."""
    from common import axis_group, candidate_distribution, load_config, map_axis
    from define_topic import parse_axis
    assert map_axis(tmp_path)["name"] == "구조물" and map_axis(tmp_path)["field"] == "structure_type"
    with pytest.raises(SystemExit):
        parse_axis("자료 종류", ["AIS ais"])  # ':' 없음
    write_json(tmp_path / "topic.json", {**topic_record(TOPIC), "axis": parse_axis("자료 종류", ["AIS: AIS", "기상: weather"])})
    axis = map_axis(tmp_path)
    other = load_config()["output"]["axis_unknown_label"]
    assert [g[0] for g in axis["groups"]] == ["AIS", "기상", other]
    assert axis_group({"title": "Fuel model from AIS data", "abstract": None}, axis) == "AIS"
    assert axis_group({"title": "On the basis of noon reports", "abstract": "Weather"}, axis) == "기상"  # 'basis'는 AIS 아님
    assert axis_group({"title": "x", "abstract": "", "structure_type": "vessel"}, axis) == other
    recs = [{"status": "selected", "relevance": 5, "exclude": False, "title": "AIS", "abstract": ""}]
    dist = candidate_distribution(recs, {"gap_matrix_min_relevance": 3}, axis)
    assert dist["선정"] == {"total": 1, "axis": "자료 종류", "by_group": {"AIS": 1}}


def test_axis_ai_assignment_wins_and_deeper_basis_revises_with_history(tmp_path):
    """AI 분류(사용자 결정 2026-10-16): 배정이 낱말보다 우선, 근거가 깊어지면 다시 나누고 이력 남김, 얕은 근거로는 안 덮음."""
    from classify_axis import merge, prepare
    from common import axis_group, load_config, map_axis, read_json
    from define_topic import parse_axis
    unknown = load_config()["output"]["axis_unknown_label"]
    write_json(tmp_path / "topic.json", {**topic_record(TOPIC), "axis": parse_axis("자료 종류", ["AIS: ais", "센서: sensor"])})
    recs = [{"openalex_id": f"W{i}", "title": "Fuel model", "abstract": "onboard monitoring data", "relevance": 4, "exclude": False}
            for i in (1, 2)]
    write_json(tmp_path / "scored.json", {"meta": {}, "records": recs})
    assert axis_group(recs[0], map_axis(tmp_path)) == unknown  # 낱말로는 못 나눔
    assert prepare(tmp_path, 2, fulltext_only=False) == 2
    files = read_json(tmp_path / "axis_batches.json")["outputs"]  # 읽을 글이 작으면 묶음 1개 (2026-10-16) — 묶음 수에 기대지 않음
    inputs = [read_json(tmp_path / f.replace("axis_", "axis_input_")) for f in files]
    assert inputs[0]["unknown_label"] == unknown and [g["name"] for g in inputs[0]["axis"]["groups"]] == ["AIS", "센서"]

    def answer(*per_paper):  # 논문 순서대로 (묶음, 근거 수준)
        by_id = dict(zip((r["openalex_id"] for r in recs), per_paper))
        for f, inp in zip(files, inputs):
            write_json(tmp_path / f, [{"openalex_id": p["openalex_id"], "axis_group": by_id[p["openalex_id"]][0],
                                       "basis": by_id[p["openalex_id"]][1], "reason": "r"} for p in inp["papers"]])
    answer(("센서", "초록"), (unknown, "초록"))
    merge(tmp_path)
    axis = map_axis(tmp_path)
    assert [axis_group(r, axis) for r in recs] == ["센서", unknown]
    answer(("AIS", "제목"), ("AIS", "전문"))
    merge(tmp_path)
    assign = read_json(tmp_path / "axis_assign.json")["assign"]
    assert assign["W1"]["group"] == "센서"  # 제목 근거로는 초록 근거를 덮지 않음
    assert assign["W2"]["group"] == "AIS" and assign["W2"]["history"][0]["group"] == unknown
    answer(("없는 묶음", "초록"), ("AIS", "초록"))
    with pytest.raises(SystemExit):
        merge(tmp_path)


def test_title_drops_repeated_approach_and_uses_scope_years(tmp_path):
    """사용자 결정 2026-10-16: 주제명에 접근법 말이 있으면 빼고, 연도는 조사 범위 (올해 뒤 연도 제외)."""
    write_json(tmp_path / "topic.json", topic_record({**TOPIC, "topic_ko": "데이터 기반 선박 연료 예측", "approach_ko": "데이터 기반",
                                                       "years": "2000-2001"}))
    assert report_title(tmp_path, {}, {"A": {"year": 2016}}) == "데이터 기반 선박 연료 예측 — 연구 동향 (2000–2001)"
    assert topic_line(tmp_path, {"A": {"year": 2000}, "B": {"year": 2001}}).endswith("기간 2000–2001")
    assert topic_line(tmp_path, {"A": {"year": 2001}}).endswith("(핵심논문 수록 2001)")


def test_scope_history_only_when_scope_changed_or_split(tmp_path):
    """사용자 피드백 2026-10-16: 입력(PINN)과 넓힌 범위·떼어 낸 세부 조사가 결과물 앞에 드러나야 함."""
    write_json(tmp_path / "topic.json", topic_record(TOPIC))
    assert scope_history(tmp_path) == []
    record = add_scope_history(topic_record(TOPIC), "PINN만으로는 적어 넓힘", ["PINN: 선정 2편뿐", "PINN: 검색 확대 필요"])
    assert len(record["split_out"]) == 1 and record["split_out"][0]["reason"] == "검색 확대 필요"  # 같은 분야는 새 이유로
    write_json(tmp_path / "topic.json", record)
    assert [label for label, _ in scope_history(tmp_path)] == ["입력 원문", "범위 결정", "세부 조사로 분리"]
    with pytest.raises(SystemExit):
        add_scope_history(topic_record(TOPIC), "", ["이유 없음"])


def test_clarifications_show_in_scope_history_and_confirmed_queries_are_kept(tmp_path):
    """사용자 결정 2026-10-21: 모호한 점을 묻고 답을 부록에 남김, 예상 검색어를 확인받아 그대로 씀."""
    from common import verbatim_strings
    from define_topic import add_clarifications
    record = add_clarifications(topic_record(TOPIC), ["platform 범위는? => 고정식·부유식만"], [" wave loads offshore platform ", ""])
    assert record["queries"] == ["wave loads offshore platform"]
    write_json(tmp_path / "topic.json", record)
    assert scope_history(tmp_path) == [("입력 원문", TOPIC["input"]), ("해석 확인", "platform 범위는? → 고정식·부유식만")]
    assert "platform 범위는? → 고정식·부유식만" in verbatim_strings(tmp_path)
    with pytest.raises(SystemExit):
        add_clarifications(topic_record(TOPIC), ["답 없는 질문"], [])


def test_sub_survey_links_parent_and_split_run(tmp_path):
    """세부 조사 ↔ 상위 조사 연결 (PINN 세부 조사 2026-10-16: 폴더 이름을 메모에만 적던 결함)."""
    parent = add_scope_history(topic_record(TOPIC), "", ["PINN: 핵심논문 2편뿐"], split_run="outputs/x_pinn")
    assert parent["split_out"][0]["run"] == "outputs/x_pinn"
    later = add_scope_history({**topic_record(TOPIC), "split_out": [{"field": "PINN", "reason": "r", "date": "d"}]}, "", [], split_run="outputs/y")
    assert later["split_out"][-1]["run"] == "outputs/y"
    child = add_scope_history(topic_record(TOPIC), "", [], parent="outputs/parent_run/")
    assert child["parent_run"] == "outputs/parent_run"
    write_json(tmp_path / "topic.json", child)
    assert [label for label, _ in scope_history(tmp_path)] == ["입력 원문", "상위 조사"]
    write_json(tmp_path / "topic.json", parent)
    assert scope_history(tmp_path)[-1][1].endswith("→ 결과 폴더 outputs/x_pinn")
