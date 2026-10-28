import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "alt"))

from search_papers import merge_records, to_record  # noqa: E402


def fake_work(work_id, title="t"):
    return {
        "id": f"https://openalex.org/{work_id}",
        "title": title,
        "publication_year": 2025,
        "primary_location": {"source": {"display_name": "Marine Structures", "id": "S1", "type": "journal"}},
        "open_access": {"is_oa": True, "oa_url": "https://x/pdf"},
        "citation_normalized_percentile": {"value": 0.9},
        "authorships": [{"author": {"display_name": "Kim"}}, {"author": {}}],
    }


def test_to_record_flattens_nested_fields():
    record = to_record(fake_work("W1"), "query:a")
    assert record["venue"] == "Marine Structures"
    assert record["citation_percentile"] == 0.9
    assert record["oa_url"] == "https://x/pdf"
    assert record["authors"] == ["Kim"]
    assert record["abstract"] is None
    assert record["found_by"] == ["query:a"]


def test_to_record_handles_missing_location():
    work = fake_work("W2")
    work["primary_location"] = None
    work["citation_normalized_percentile"] = None
    record = to_record(work, "query:a")
    assert record["venue"] is None and record["citation_percentile"] is None


def test_merge_records_dedupes_and_unions_found_by():
    records = [to_record(fake_work("W1"), "query:a"),
               to_record(fake_work("W1"), "query:b"),
               to_record(fake_work("W1"), "query:a"),
               to_record(fake_work("W2", "another paper"), "query:b")]
    unique, duplicates = merge_records(records)
    assert duplicates == 2
    assert len(unique) == 2
    w1 = next(r for r in unique if r["openalex_id"].endswith("W1"))
    assert w1["found_by"] == ["query:a", "query:b"]


def test_merge_records_does_not_mutate_input():
    first = to_record(fake_work("W1"), "query:a")
    merge_records([first, to_record(fake_work("W1"), "query:b")])
    assert first["found_by"] == ["query:a"]


def test_to_record_rebuilds_abstract_keeping_repeated_words():
    work = fake_work("W3")
    work["abstract_inverted_index"] = {"wave": [0, 2], "loads": [1]}
    assert to_record(work, "query:a")["abstract"] == "wave loads wave"


def test_merge_records_folds_preprint_into_journal_version():
    preprint = to_record({**fake_work("W10", "Same Title: X"), "doi": "10.1/pre"}, "query:a")
    preprint["venue_type"] = "repository"
    journal = to_record({**fake_work("W11", "Same title - X"), "doi": "10.1/j"}, "query:b")
    unique, duplicates = merge_records([preprint, journal])
    assert duplicates == 1 and len(unique) == 1
    assert unique[0]["openalex_id"].endswith("W11")
    assert unique[0]["other_versions"] == ["https://openalex.org/W10"]
    assert unique[0]["found_by"] == ["query:a", "query:b"]
def test_count_queries_does_not_download_candidate_records(monkeypatch):
    import search_papers

    class Query:
        def search(self, text):
            self.text = text
            return self

        def filter(self, **filters):
            assert filters == {"publication_year": "2025-2026"}
            return self

        def count(self):
            return {"wave loads": 12, "ship fuel": 34}[self.text]

    monkeypatch.setattr(search_papers, "Works", Query)
    monkeypatch.setattr(search_papers, "load_user_settings", lambda: {})
    assert search_papers.count_queries(["wave loads", "ship fuel"], "2025-2026") == [
        {"query": "wave loads", "expected_total": 12}, {"query": "ship fuel", "expected_total": 34}]


def test_count_preview_cannot_overwrite_candidate_file_with_different_case(monkeypatch, tmp_path):
    import pytest
    import search_papers
    candidate = tmp_path / "Candidates.json"
    candidate.write_text('{"records": ["preserve"]}', encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["search_papers.py", "--query", "wave", "--years", "2026",
                                     "--count-only", "--out", str(candidate)])
    monkeypatch.setattr(search_papers, "count_queries", lambda *a: [])
    with pytest.raises(SystemExit):
        search_papers.main()
    assert candidate.read_text(encoding="utf-8") == '{"records": ["preserve"]}'
