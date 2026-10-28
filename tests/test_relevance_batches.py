"""관련성 채점 묶음: 크기로 나누기·한 줄에 한 편·묶음 검사 (토큰 절감, 사용자 승인 2026-10-27)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "alt"))

from prepare_relevance_batches import check_batches, size_batches, write_compact  # noqa: E402


def test_size_batches_keep_each_file_under_limit_and_order():
    papers = [{"openalex_id": f"W{i}", "abstract": "x" * 400} for i in range(10)]
    batches = size_batches(papers, max_bytes=1500, overhead=300)
    assert [p["openalex_id"] for b in batches for p in b] == [f"W{i}" for i in range(10)]
    assert all(300 + sum(len(json.dumps(p)) + 2 for p in b) <= 1500 for b in batches) and len(batches) > 1
    assert len(size_batches([{"openalex_id": "W1", "abstract": "x" * 5000}], 1500, 300)) == 1  # 한 편이 커도 빠뜨리지 않음


def test_compact_input_is_valid_json_one_paper_per_line_and_check(tmp_path):
    papers = [{"openalex_id": "W1", "title": "a"}, {"openalex_id": "W2", "title": "b"}]
    path = tmp_path / "relevance_input_1.json"
    write_compact(path, {"topic": "t", "rubric": "r", "output_file": "relevance_1.json"}, papers)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["papers"] == papers and data["output_file"] == "relevance_1.json"
    assert sum('"openalex_id"' in line for line in path.read_text(encoding="utf-8").splitlines()) == 2
    assert "없음" in check_batches(tmp_path)[0]
    (tmp_path / "relevance_1.json").write_text(json.dumps([{"openalex_id": "W1", "relevance": 4, "reason": "r"}]), encoding="utf-8")
    assert "불일치" in check_batches(tmp_path)[0]
    (tmp_path / "relevance_1.json").write_text(json.dumps([{"openalex_id": "W1", "relevance": 4, "reason": "r"}, {"openalex_id": "W2", "relevance": 0, "reason": "r"}]),
                                               encoding="utf-8")
    assert check_batches(tmp_path) == []
