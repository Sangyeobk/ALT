"""공통 인용 보강 (사용자 승인 2026-10-19, docs/20261016_놓친고전_계획.md 방안 A)."""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "alt"))

from add_cocited import child_classics, cocited_targets, in_years  # noqa: E402
from run_status import CHECK, steps  # noqa: E402
from score_papers import capped_relevance, mark_cocited, percentile_ranks, select  # noqa: E402

RULES = {"min_relevance": 4, "min_share": 0.10, "min_count": 2}


def test_targets_are_shared_references_outside_candidates():
    refs = ["X", "Y", "Z"]
    records = [{"openalex_id": f"P{i}", "referenced_works": refs if i < 3 else ["X"], "other_versions": []} for i in range(5)]
    records[0]["other_versions"] = ["Z"]  # 후보의 다른 판이면 이미 있는 것
    relevance = {"P0": 5, "P1": 4, "P2": 4, "P3": 3, "P4": 4}
    targets, threshold, base = cocited_targets(records, relevance, RULES)
    assert base == 4 and threshold == 2  # 4편의 10% → 1편이지만 최소 2편
    assert targets == {"X": 4, "Y": 3}   # 3점 논문(P3)의 참고문헌은 세지 않음, Z는 후보 판
    assert in_years(2016, "2000-2026") and not in_years(1999, "2000-2026") and not in_years(None, "2000-2026")


def test_only_unscored_batches_continue_numbering(tmp_path):
    recs = [{"openalex_id": f"W{i}", "title": "t", "year": 2020, "venue": "v", "abstract": None} for i in range(3)]
    (tmp_path / "candidates.json").write_text(json.dumps({"meta": {}, "records": recs}), encoding="utf-8")
    (tmp_path / "relevance_input_1.json").write_text("{}", encoding="utf-8")
    (tmp_path / "relevance_input_2.json").write_text("{}", encoding="utf-8")
    (tmp_path / "relevance_1.json").write_text(json.dumps([{"openalex_id": "W0", "relevance": 4}]), encoding="utf-8")
    script = Path(__file__).resolve().parents[1] / "alt" / "prepare_relevance_batches.py"
    subprocess.run([sys.executable, str(script), str(tmp_path / "candidates.json"), "--only-unscored", "--batches", "4",
                    "--topic", "t", "--approach", "a"], check=True, capture_output=True)
    new = json.loads((tmp_path / "relevance_input_3.json").read_text(encoding="utf-8"))
    others = sorted(tmp_path.glob("relevance_input_*.json"))
    assert [p["openalex_id"] for p in new["papers"]] in (["W1"], ["W2"]) and len(others) == 4  # 2편 → 묶음 2개(3·4번)
    assert new["output_file"] == "relevance_3.json"


def paper(key, total, citation, abstract="a", found_by=("query:q",), relevance=5):
    return {"openalex_id": key, "total_score": total, "exclude": False, "relevance": relevance, "abstract": abstract,
            "score_parts": {"citation": citation}, "found_by": list(found_by)}


def test_no_abstract_low_citation_excluded_and_classics_listed_apart():
    records = [paper("keep", 0.9, 0.2), paper("title_only_high", 0.8, 0.9, abstract=None),
               paper("title_only_low", 0.85, 0.3, abstract=None), paper("no_citation", 0.7, None, abstract=None),
               paper("c_many", 0.5, 0.9, found_by=("cocited:30",)), paper("c_few", 0.95, 0.9, found_by=("cocited:20",)),
               paper("c_low_rel", 0.9, 0.9, found_by=("cocited:40",), relevance=3)]
    select(records, min_total=0.5, max_selected=30, min_relevance=4, no_abstract_min_citation=0.5)
    mark_cocited(records, {"min_relevance": 4, "max_listed": 1})
    status = {r["openalex_id"]: r["status"] for r in records}
    assert status["keep"] == status["title_only_high"] == status["no_citation"] == "selected"  # 인용 높거나 정보 없으면 남김
    assert status["title_only_low"] == "excluded_no_abstract"
    assert status["c_many"] == "cocited_listed"  # 총점이 낮아도 공통 인용 많은 순, 핵심논문 선정에는 안 들어감
    assert status["c_few"] == status["c_low_rel"] == "cocited_not_listed"


def test_title_only_relevance_capped_at_four():
    assert capped_relevance(5, has_text=False, cap=4) == 4  # 제목만으로 5점 → 4점 (사용자 2026-10-19)
    assert capped_relevance(3, has_text=False, cap=4) == 3
    assert capped_relevance(5, has_text=True, cap=4) == 5   # 초록이나 본문 정리가 있으면 그대로


def test_relevance_file_with_wrong_field_name_is_rejected(tmp_path):
    from score_papers import relevance_format_errors
    good, bad = tmp_path / "relevance_1.json", tmp_path / "relevance_2.json"
    good.write_text(json.dumps([{"openalex_id": "W1", "relevance": 4, "reason": "r"}]), encoding="utf-8")
    bad.write_text(json.dumps([{"openalex_id": "W2", "score": 4}]), encoding="utf-8")  # 10-16 실제 결함
    assert relevance_format_errors([good]) == []
    assert len(relevance_format_errors([good, bad])) == 1


def test_percentiles_use_searched_candidates_only():
    values = {"a": 1.0, "b": 2.0, "classic": 9.0}
    assert percentile_ranks(values, {"a", "b"}) == {"a": 0.25, "b": 0.75, "classic": 1.0}
    assert percentile_ranks(values)["b"] == 0.5  # 고전을 넣으면 검색 후보 점수가 바뀜 → 모집단에서 뺌


def test_parent_takes_classics_found_by_sub_survey(tmp_path):
    parent, child, other = tmp_path / "20261016_fuel", tmp_path / "20261016_fuel__pinn", tmp_path / "20261016_fuelx"
    rec = lambda i, year, found: {"openalex_id": f"https://openalex.org/{i}", "title": f"title {i}", "year": year, "found_by": [found]}
    for run, records in ((child, [rec("W1", 2015, "cocited:12"), rec("W2", 1990, "cocited:9"), rec("W3", 2015, "query:q"),
                                  rec("W4", 2016, "cocited:7")]),
                         (other, [rec("W5", 2015, "cocited:30")])):  # 이름이 '__'로 이어지지 않으면 세부 조사 아님
        run.mkdir()
        (run / "candidates.json").write_text(json.dumps({"meta": {}, "records": records}), encoding="utf-8")
    parent.mkdir()
    found = child_classics(parent, [rec("W4", 2016, "query:q")], "2000-2026")
    assert [r["openalex_id"].rsplit("/", 1)[-1] for r in found] == ["W1"]  # 기간 밖 W2, 고전 아님 W3, 이미 있는 W4 제외
    assert found[0]["found_by"] == ["cocited:12:20261016_fuel__pinn"]


def test_run_status_flags_candidates_without_relevance(tmp_path):
    (tmp_path / "relevance_input_1.json").write_text("{}", encoding="utf-8")
    (tmp_path / "relevance_1.json").write_text(json.dumps([{"openalex_id": "W1", "relevance": 4}]), encoding="utf-8")
    (tmp_path / "candidates.json").write_text(json.dumps({"records": [{"openalex_id": "W1"}, {"openalex_id": "W2"}]}), encoding="utf-8")
    row = next(r for r in steps(tmp_path, "초록") if r["step"].startswith("④"))
    assert row["state"] == CHECK and "채점 안 된 후보 1편" in row["note"]


def test_run_status_compares_each_relevance_file_with_its_own_input(tmp_path):
    import os
    for name, age in (("relevance_input_1.json", 300), ("relevance_1.json", 200), ("relevance_input_2.json", 100), ("relevance_2.json", 0)):
        (tmp_path / name).write_text("[]", encoding="utf-8")
        t = (tmp_path / name).stat().st_mtime - age
        os.utime(tmp_path / name, (t, t))
    row = next(r for r in steps(tmp_path, "초록") if r["step"].startswith("④"))
    assert row["state"] == "끝"  # 보강 묶음(2번) 입력이 1번 결과보다 새로워도 오래됨이 아님
