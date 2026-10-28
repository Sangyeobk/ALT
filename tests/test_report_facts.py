"""산출물의 검증 문구는 실제 수행한 만큼만 (Codex 검토 2026-10-28 — 생략한 검증을 완료로 쓰지 않음)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "alt"))

from common import load_config  # noqa: E402
from report_facts import method_lines  # noqa: E402

PRISMA = {"screened": 10, "excluded_retracted": 0, "reviews_listed": 1, "reviews_not_listed": 0,
          "selected": 3, "below_threshold": 1, "over_limit": 0}


def lines_for(evaluators, verified):
    meta = {"prisma": PRISMA, "weights": {"relevance": 0.5, "citation": 0.6, "venue": 0.2},
            "category_weights": {"journal": 1, "conference": 0.9, "preprint": 0.8}, "years": "2025-2025",
            "queries": ["q"], "run_at": "2026-10-28", "min_relevance": 4, "min_total_score": 0.6}
    if evaluators is not None:
        meta["review_evaluators"] = evaluators
    records = [{"year": 2025, "status": "selected", "cited_by_count": 1, "verified": verified}]
    return " ".join(text for text, _ in method_lines(meta, records, load_config(), {}))


def test_wording_follows_evaluators_and_verification():
    assert "AI 2개가 평가해 둘 다 통과" in lines_for(2, True) and "다른 AI가 1편의 관련성을 다시 채점" in lines_for(2, True)
    one = lines_for(1, False)
    assert "AI 1개가 평가해 통과한 (독립 평가 생략)" in one and "교차 채점: 하지 않음" in one and "AI 2개" not in one
    assert "평가 없이" in lines_for(0, False)
    old = lines_for(None, False)  # 평가자 수를 기록하기 전 조사 — 수행 여부를 단정하지 않음
    assert "AI 2개" not in old and "평가 여부는 기록 없음" in old
