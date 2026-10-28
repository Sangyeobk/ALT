import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "alt"))

from score_papers import percentile_ranks, select, stars, weighted_total  # noqa: E402

WEIGHTS = {"relevance": 0.5, "citation": 0.3, "venue": 0.2}


def test_percentile_ranks_midrank_ties_and_none():
    ranks = percentile_ranks({"a": 1.0, "b": 2.0, "c": 2.0, "d": None})
    assert ranks["a"] == pytest.approx(1 / 6)
    assert ranks["b"] == ranks["c"] == pytest.approx(4 / 6)
    assert ranks["d"] is None


def test_weighted_total_renormalizes_missing_parts():
    full = weighted_total({"relevance": 1.0, "citation": 0.0, "venue": 0.0}, WEIGHTS)
    no_venue = weighted_total({"relevance": 1.0, "citation": 0.0, "venue": None}, WEIGHTS)
    assert full == pytest.approx(0.5)
    assert no_venue == pytest.approx(0.5 / 0.8)


def test_stars_bounds():
    assert stars(0.0) == 1 and stars(0.21) == 2 and stars(1.0) == 5


def make(key, total, exclude=False):
    return {"openalex_id": key, "total_score": total, "exclude": exclude, "relevance": 5}


def test_select_threshold_limit_and_retraction():
    records = [make("a", 0.9), make("b", 0.8, exclude=True), make("c", 0.7), make("d", 0.6), make("e", 0.4)]
    select(records, min_total=0.5, max_selected=2)
    status = {r["openalex_id"]: r["status"] for r in records}
    assert status == {"a": "selected", "b": "excluded_retracted", "c": "selected",
                      "d": "over_limit", "e": "below_threshold"}


def test_select_never_fills_with_below_threshold():
    records = [make("a", 0.6), make("b", 0.3), make("c", 0.2)]
    select(records, min_total=0.5, max_selected=30)
    assert [r["status"] for r in records].count("selected") == 1


def test_document_category_mapping():
    from score_papers import document_category
    assert document_category({"type": "article", "venue_type": "journal"}) == "journal"
    assert document_category({"type": "review", "venue_type": "journal"}) == "journal"
    assert document_category({"type": "conference-paper", "venue_type": "journal"}) == "conference"
    assert document_category({"type": "article", "venue_type": "repository"}) == "preprint"
    assert document_category({"type": "preprint", "venue_type": None}) == "preprint"
    assert document_category({"type": "dissertation", "venue_type": None}) == "other"


def test_reviews_are_listed_separately_from_selection():
    records = [make("a", 0.9), make("r1", 0.95), make("r2", 0.5), make("r3", 0.8), make("b", 0.7)]
    for r in records:
        r["is_review"] = r["openalex_id"].startswith("r")
        r["relevance"] = 2 if r["openalex_id"] == "r3" else 4
    select(records, min_total=0.6, max_selected=1, review_min_relevance=3, review_max=1)
    status = {r["openalex_id"]: r["status"] for r in records}
    assert status == {"a": "selected", "b": "over_limit", "r1": "review_listed",
                      "r2": "review_not_listed", "r3": "review_not_listed"}


def test_reviews_need_contribution_and_are_not_filled():
    records = [make("r1", 0.9), make("r2", 0.8), make("r3", 0.7)]
    for r in records:
        r["is_review"], r["relevance"] = True, 3
    select(records, min_total=0.6, max_selected=30, review_min_relevance=3, review_max=10,
           review_contributes={"r1": True, "r2": False})
    status = {r["openalex_id"]: r["status"] for r in records}
    assert status == {"r1": "review_listed", "r2": "review_not_listed", "r3": "review_not_listed"}


def test_is_review_prefers_claude_judgement():
    from score_papers import is_review
    pattern = r"\b(review|survey)\b"
    assert is_review({"type": "article", "title": "A review of X"}, {}, pattern)
    assert not is_review({"type": "article", "title": "Bathymetric survey"}, {"is_review": False}, pattern)
    assert not is_review({"type": "article", "title": "Reviewer bias"}, {}, pattern)


def test_relevance_floor_applies_before_threshold():
    records = [make("a", 0.9), make("b", 0.8)]
    records[0]["relevance"], records[1]["relevance"] = 3, 4
    select(records, min_total=0.5, max_selected=30, min_relevance=4)
    assert [r["status"] for r in records] == ["below_relevance", "selected"]


def test_combine_judgements_takes_lower_relevance():
    from score_papers import combine_judgements
    judged = {"relevance": 5, "reason": "x"}
    assert combine_judgements(judged, None)["verified"] is False
    combined = combine_judgements(judged, {"relevance": 3, "verifier": "codex", "is_review": True})
    assert combined["relevance"] == 3 and combined["relevance_original"] == 5
    assert combine_judgements({"relevance": 3}, {"relevance": 5})["relevance"] == 3


def test_adjacent_list_picks_high_impact_below_relevance_research_papers_only():
    """주목할 인접 문헌 (사용자 결정 2026-10-16): 관련성 미달 연구논문 중 관련성 하한 이상·영향 점수 하한 이상, 상위 M편만 (채우지 않음)."""
    from score_papers import mark_adjacent

    def rec(rid, status, relevance, citation, venue, category_weight=1.0):
        return {"openalex_id": rid, "status": status, "relevance": relevance, "category_weight": category_weight,
                "score_parts": {"relevance": relevance / 5, "citation": citation, "venue": venue}}
    records = [rec("A", "below_relevance", 3, 0.95, 0.9), rec("B", "below_relevance", 2, 0.9, 0.85),
               rec("C", "below_relevance", 3, 0.99, 0.99, 0.7),  # 사전 공개본: 가중치로 하한 아래
               rec("D", "below_relevance", 1, 1.0, 1.0),          # 관련성 너무 낮음
               rec("E", "selected", 5, 1.0, 1.0), rec("F", "below_relevance", 3, None, None),
               rec("G", "below_relevance", 2, 0.85, 0.8)]
    mark_adjacent(records, {"min_relevance": 2, "min_impact": 0.8, "max_listed": 2}, {"relevance": 0.5, "citation": 0.3, "venue": 0.2})
    assert [r["openalex_id"] for r in records if r.get("adjacent_listed")] == ["A", "B"]
    assert records[0]["impact_score"] == round(0.95 * 0.6 + 0.9 * 0.4, 4) and records[0]["status"] == "below_relevance"
