"""누적 갱신 (계획 docs/20261019_누적갱신_계획.md — 사용자 지정 방식 2026-10-13, NEW 뜻은 사용자 결정 2026-10-19)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "alt"))

from merge_runs import merge_new, snapshot  # noqa: E402
from score_papers import UPDATE_DROPPED, UPDATE_NEW, mark_update  # noqa: E402


def rec(oid, title, **extra):
    return {"openalex_id": oid, "title": title, "found_by": ["query:q"], "venue_type": "journal", "doi": None, **extra}


def test_merge_keeps_old_records_and_adds_only_new_papers():
    old = [rec("W1", "Old paper", fwci=1.0, cited_by_count=3, other_versions=["W1p"]), rec("W2", "Another old")]
    fresh = [rec("W1", "Old paper", fwci=2.5, cited_by_count=9),   # 같은 판 → 인용 값만 새로
             rec("W1p", "Old paper (preprint)"),                   # 다른 판 id → 이미 있음
             rec("W9", "ANOTHER OLD"),                             # 제목만 같음 → 이미 있음
             rec("W3", "Brand new"), rec("W3", "Brand new")]       # 새 논문 (검색 안 중복은 하나로)
    merged, added, refreshed = merge_new(old, fresh, "2026-10-19")
    assert [r["openalex_id"] for r in merged] == ["W1", "W2", "W3"] and added == 1 and refreshed == 1
    assert merged[0]["fwci"] == 2.5 and merged[0]["cited_by_count"] == 9
    assert merged[2]["first_seen"] == "2026-10-19" and "first_seen" not in merged[0]


def test_new_and_dropped_against_previous_selection():
    records = [{"openalex_id": "A", "status": "selected"},          # 계속 선정 → 표시 없음
               {"openalex_id": "B", "status": "selected"},          # 순위가 올라 새로 듦 → NEW
               {"openalex_id": "C", "status": "over_limit"},        # 밀려남 → 제외됨(이전 선정)
               {"openalex_id": "D", "status": "below_relevance", "update": UPDATE_NEW}]  # 지난 표시는 지움
    assert mark_update(records, {"A", "C"}) == (1, 1)
    assert [r.get("update") for r in records] == [None, UPDATE_NEW, UPDATE_DROPPED, None]


def test_snapshot_copies_results_without_overwriting(tmp_path):
    (tmp_path / "scored.json").write_text(json.dumps({"records": []}), encoding="utf-8")
    (tmp_path / "figures").mkdir()
    (tmp_path / "figures" / "prisma.png").write_bytes(b"png")
    first, second = snapshot(tmp_path, "20261013"), snapshot(tmp_path, "20261013")
    assert first.name == "run_20261013" and second.name == "run_20261013_2"
    assert (first / "scored.json").is_file() and (first / "figures" / "prisma.png").is_file()
