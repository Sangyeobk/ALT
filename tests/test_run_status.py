import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "alt"))

from run_status import CHECK, DONE, UNKNOWN, next_step, steps  # noqa: E402


def put(run, name, payload=None, age=0):
    """파일 쓰기. age초만큼 과거 시각으로 (오래된 결과 흉내)."""
    path = run / name
    path.write_text(json.dumps(payload if payload is not None else {}), encoding="utf-8")
    if age:
        t = path.stat().st_mtime - age
        os.utime(path, (t, t))


def state(rows, prefix):
    return next(r for r in rows if r["step"].startswith(prefix))


def test_next_step_follows_pipeline_order(tmp_path):
    assert next_step(steps(tmp_path, "초록"))["step"].startswith("②")
    for name in ("candidates.json", "venues.json", "integrity.json"):
        put(tmp_path, name, age=100)
    assert next_step(steps(tmp_path, "초록"))["step"].startswith("④")


def test_older_result_is_flagged_but_next_is_first_undone(tmp_path):
    put(tmp_path, "relevance_input_1.json")
    put(tmp_path, "relevance_1.json", [], age=100)  # 입력보다 오래된 채점 결과
    rows = steps(tmp_path, "초록")
    assert state(rows, "④")["state"] == CHECK and "오래됨" in state(rows, "④")["note"]
    assert next_step(rows)["step"].startswith("②")  # 경고는 경고로만, 다음은 안 한 첫 단계


def test_user_check_needs_a_record_newer_than_scoring(tmp_path):
    for name in ("candidates.json", "venues.json", "integrity.json", "relevance_input_1.json", "relevance_1.json",
                 "scored.json", "review_eval_input.json", "review_eval_claude.json", "review_eval_codex.json",
                 "references.json", "synthesis_input.json"):
        put(tmp_path, name)
    put(tmp_path, "verification_codex.json", {"verdict": "통과"})
    rows = steps(tmp_path, "초록")
    assert state(rows, "⑥")["state"] == UNKNOWN
    assert next_step(rows)["step"].startswith("⑥")  # 뒤 단계 파일이 있어도 확인 기록 없으면 사용자 확인부터
    put(tmp_path, "checkpoints.json", {"⑥": "2000-01-01T00:00:00"})  # 점수화보다 앞선 확인
    assert state(steps(tmp_path, "초록"), "⑥")["state"] == CHECK
    put(tmp_path, "checkpoints.json", {"⑥": "2999-01-01T00:00:00"})
    assert next_step(steps(tmp_path, "초록"))["step"].startswith("⑧")


def test_verification_counts_as_done_only_when_passed(tmp_path):
    put(tmp_path, "relevance_input_1.json", age=100)
    put(tmp_path, "relevance_1.json", age=50)
    put(tmp_path, "verification_codex.json", {"verdict": "조건부 통과"})
    assert state(steps(tmp_path, "초록"), "⑤-1")["state"] == CHECK
    put(tmp_path, "verification_codex.json", {"verdict": "통과"}, age=80)  # 재채점보다 오래된 검증
    assert "오래됨" in state(steps(tmp_path, "초록"), "⑤-1")["note"]

def test_references_compared_by_content_and_failed_citation_check(tmp_path):
    put(tmp_path, "scored.json", {"records": [{"openalex_id": "W1", "status": "selected"},
                                             {"openalex_id": "W2", "status": "below_threshold"}]})
    put(tmp_path, "references.json", {"Kim2025": {"openalex_id": "W9"}})
    put(tmp_path, "synthesis_input.json")
    assert "다름" in state(steps(tmp_path, "초록"), "⑦")["note"]
    put(tmp_path, "references.json", {"Kim2025": {"openalex_id": "W1"}}, age=100)  # 목록이 같아도 점수화보다 오래되면 경고 유지
    assert "오래됨" in state(steps(tmp_path, "초록"), "⑦")["note"]
    put(tmp_path, "references.json", {"Kim2025": {"openalex_id": "W1"}})
    put(tmp_path, "synthesis_input.json")
    assert state(steps(tmp_path, "초록"), "⑦")["state"] == DONE
    for name in ("synthesis.json", "00_summary.md", "01_background.pptx", "03_report.docx", "04_presentation.pptx",
                 "05_references.xlsx", "06_context.md", "02_literature_map.png"):
        put(tmp_path, name, age=100)
    put(tmp_path, "citation_check.json", {"passed": False})
    put(tmp_path, "terms_check.json", {"passed": False})
    rows = steps(tmp_path, "초록")
    assert state(rows, "⑩ 인용")["state"] == CHECK and state(rows, "⑩ 용어")["state"] == CHECK
    assert state(rows, "⑩ 문서")["state"] != DONE  # 문서 검토 기록이 없으면 끝이 아님


def test_list_runs_shows_topic_and_next_step(tmp_path):
    from run_status import list_runs
    (tmp_path / "20261020_a").mkdir()
    put(tmp_path / "20261020_a", "candidates.json", {"meta": {"queries": ["wave loads"]}, "records": []})
    put(tmp_path / "20261020_a", "scored.json", {"meta": {"topic": "Wave loads"}, "records": []})
    (tmp_path / "20261021_b").mkdir()
    (tmp_path / "_to_delete").mkdir()                         # 보관·삭제 폴더는 목록에서 뺌
    runs = {r["run"]: r for r in list_runs(tmp_path, "초록")}
    assert set(runs) == {"20261020_a", "20261021_b"}
    assert runs["20261020_a"]["topic"] == "Wave loads" and runs["20261021_b"]["topic"] == "-"
    assert runs["20261021_b"]["next"].startswith("②")


def test_adjacent_listed_papers_do_not_flag_reference_mismatch(tmp_path):
    """주목할 인접 문헌은 인용 목록에 있어도 ⑦ 경고가 아님 (PINN 세부 조사 2026-10-16: '30 / 35편' 거짓 경고)."""
    put(tmp_path, "scored.json", {"records": [{"openalex_id": "A", "status": "selected"},
                                              {"openalex_id": "B", "status": "below_relevance", "adjacent_listed": True}]})
    put(tmp_path, "references.json", {"A2025": {"openalex_id": "A"}, "B2025": {"openalex_id": "B"}})
    assert "다름" not in state(steps(tmp_path, "초록"), "⑦")["note"]


def test_claude_output_verification_counts_as_complete(tmp_path):
    from common import OUTPUT_NAMES
    for name in [*OUTPUT_NAMES, "02_literature_map.png"]:
        put(tmp_path, name, age=100)
    put(tmp_path, "verification_claude_outputs.json", {"verdict": "통과"})
    put(tmp_path, "doc_review_claude.md")
    rows = steps(tmp_path, "")
    assert state(rows, "⑩ 산출물 교차")["state"] == DONE
    assert state(rows, "⑩ 문서 검토")["state"] == DONE


def test_default_legacy_argument_still_checks_current_slide_plans(tmp_path, monkeypatch):
    import build_pptx
    import slides_plan
    monkeypatch.setattr(build_pptx, "pptx_style", lambda: {"path": tmp_path / "t.pptx"})  # 장 종류 목록이 있는 양식을 쓸 때 (개인 양식 없이도 시험)
    monkeypatch.setattr(slides_plan, "load_catalog", lambda style: {"types": {}})
    put(tmp_path, "slides.json", age=100)
    put(tmp_path, "slides_learn.json", age=100)
    put(tmp_path, "synthesis.json")
    row = state(steps(tmp_path, "초록"), "⑨ 산출물")
    assert row["state"] == CHECK and "구성안 갱신 필요" in row["note"]


def test_workspace_unset_for_home_or_unmarked_folder(tmp_path, monkeypatch):
    """처음 시작할 때 작업 폴더가 정해지지 않았으면 알림 (사용자 요청 2026-10-27)."""
    from run_status import WORKSPACE_MARK, workspace_problem
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    (tmp_path / "home").mkdir()
    assert "홈" in workspace_problem(tmp_path / "home")
    assert workspace_problem(Path(tmp_path.anchor))
    empty = tmp_path / "empty"
    empty.mkdir()
    assert "outputs" in workspace_problem(empty)
    (empty / WORKSPACE_MARK).write_text("x", encoding="utf-8")
    assert workspace_problem(empty) is None
    dev = tmp_path / "dev"
    (dev / "outputs").mkdir(parents=True)
    assert workspace_problem(dev) is None  # 결과 폴더가 이미 있는 곳은 그대로 통과

def test_finished_list_still_shows_remaining_checks():
    from run_status import CHECK, DONE, finished_label
    assert finished_label([{"step": "⑩ 검사", "state": DONE}]) == "없음 (끝)"
    assert "확인 필요 1건: ⑩ 검사" in finished_label([{"step": "⑨ 산출물", "state": DONE}, {"step": "⑩ 검사", "state": CHECK}])
