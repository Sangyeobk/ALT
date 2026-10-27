"""점수화·선정: 관련성 + 인용 영향력 + 학술지 수준 → scored.json

    python alt/score_papers.py outputs/<run>/

같은 폴더의 candidates.json, venues.json, integrity.json, relevance_*.json 을 읽는다.
- 관련성: Claude 채점 0–5 → /5
- 인용: FWCI의 후보 집합 안 백분위 (FWCI 없으면 OpenAlex citation_normalized_percentile, 그것도 없으면 '없음')
- 학술지: 2년 평균 피인용·h-index 각각의 후보 집합 안 백분위의 평균 (학술지 정보 없으면 '없음')
- '없음' 항목은 빼고 나머지 가중치로 다시 나눠 계산한다 (0점 처리하지 않음)
- 문헌 종류(저널/학회/프리프린트/기타)별 가중치를 곱한다 (config category_weights)
- 선정: 철회 제외 → 관련성 하한 이상 → 기준 점수 이상 → 총점 순 최대 N편
- 리뷰(문헌조사) 논문은 N편과 따로 관리: 관련성 하한 이상, 총점 순 최대 M편 → 'review_listed'
- 주목할 인접 문헌(사용자 결정 2026-10-16): 관련성 미달(below_relevance) 연구논문 중 관련성 adjacent.min_relevance 이상,
  영향 점수(관련성 뺀 인용·학술지 가중평균 × 문헌 종류 가중치) 하한 이상, 순서대로 최대 M편 → adjacent_listed: true (status는 그대로 — 흐름도 편수 불변)
- 교차 검증(verifier_rechecks.json)이 있으면 [사용자 결정] 관련성은 두 AI 중 **낮은 점수**, 리뷰는 **한쪽이라도 리뷰면 리뷰**
- [사용자 결정 2026-10-19] 초록 없는 후보: 인용 백분위가 no_abstract_min_citation 미만이면 제외(excluded_no_abstract),
  높거나 인용 정보가 없으면 제목으로 채점한 그대로 두고 '전문 확인 필요' 표시. 이때 관련성은 no_abstract_max_relevance점까지만 인정
- [사용자 결정 2026-10-19] 공통 인용 고전(add_cocited.py로 더한 문헌): 핵심논문과 따로 cocited_listed (관련성 하한 이상, 공통 인용
  많은 순 최대 M편, 채우지 않음). 인용·학술지 백분위는 검색 후보만 모집단으로 계산해 핵심논문 점수가 고전 때문에 바뀌지 않음
"""

from __future__ import annotations

import argparse
import math
import re
from datetime import date
from pathlib import Path

from add_cocited import cocited_count, is_cocited
from classify_axis import notes_by_id
from common import RELEVANCE_PASSED, load_config, read_json, scoring_config, write_json
from review_contribution import contribution_votes


def percentile_ranks(values: dict[str, float | None], population: set[str] | None = None) -> dict[str, float | None]:
    """값이 있는 것끼리 백분위(0–1, 동점은 중간 순위). 값이 없으면 None. population이 있으면 그 키들의 값을 기준으로 순위를 매김."""
    present = sorted(v for k, v in values.items() if v is not None and (population is None or k in population))
    n = len(present)
    ranks = {}
    for key, value in values.items():
        if value is None or n == 0:
            ranks[key] = None
            continue
        below = sum(1 for v in present if v < value)
        equal = sum(1 for v in present if v == value)
        ranks[key] = (below + 0.5 * equal) / n
    return ranks


def weighted_total(parts: dict[str, float | None], weights: dict[str, float]) -> float:
    """없는 항목(None)을 빼고 가중평균."""
    used = {k: v for k, v in parts.items() if v is not None}
    weight_sum = sum(weights[k] for k in used)
    return sum(weights[k] * v for k, v in used.items()) / weight_sum


def combine_judgements(judged: dict, recheck: dict | None) -> dict:
    """만든 AI의 채점 + 검증 AI의 재채점 → 낮은 관련성. 원래 값은 남긴다. (리뷰 판정은 score()에서 OR)"""
    if not recheck:
        return {**judged, "verified": False}
    return {**judged, "verified": True, "relevance_original": judged["relevance"],
            "verifier_relevance": recheck["relevance"], "verifier": recheck.get("verifier"),
            "relevance": min(judged["relevance"], recheck["relevance"])}


def capped_relevance(relevance: int, has_text: bool, cap: int | None) -> int:
    """초록도 본문 정리도 없이 제목만으로 채점한 논문은 관련성을 cap점까지만 인정 (사용자 결정 2026-10-19 — 제목만으로 5점·1위가 되는 것 방지.
    본문을 읽어 정리한 논문은 내용이 확인됐으므로 제외)."""
    return min(relevance, cap) if cap is not None and not has_text else relevance


def _has_name(text: str, names: list[str]) -> bool:
    """기관 이름이 단어로 들어 있음 (대소문자 구분 — ABS 등 약어가 다른 단어 일부와 섞이지 않게)."""
    return any(re.search(rf"(?<![A-Za-z]){re.escape(name)}(?![A-Za-z])", text) for name in names)


def is_institution(record: dict, rules: dict) -> bool:
    """기관·선급 문서: ① 학술지가 아닌 곳에 실렸고 실린 곳·발행처 이름에 기관 이름이 있음, 또는
    ② 제목에 기관 이름과 문서 단어(committee·report·guideline 등)가 함께 있음 (ISSC 위원회 보고서의 저장소 사본·학술지 요약본)."""
    where = " ".join(filter(None, (record.get("venue"), record.get("publisher"))))
    if record.get("venue_type") != "journal" and _has_name(where, rules["names"]):
        return True
    title = record.get("title") or ""
    return _has_name(title, rules["names"]) and any(re.search(rf"(?<![A-Za-z]){re.escape(w)}(?![A-Za-z])", title, re.I) for w in rules.get("doc_words", []))


def document_category(record: dict, institutions: dict | None = None) -> str:
    """OpenAlex 문헌 type + 실린 곳 type → journal / conference / preprint / other, 기관·선급 문서면 institution."""
    work_type, venue_type = record.get("type"), record.get("venue_type")
    if institutions and is_institution(record, institutions):
        return "institution"
    if work_type == "conference-paper":
        return "conference"
    if work_type == "preprint" or venue_type == "repository":
        return "preprint"
    if work_type in ("article", "review") and venue_type == "journal":
        return "journal"
    return "other"


def stars(total: float) -> int:
    return max(1, min(5, math.ceil(total * 5)))


def is_review(record: dict, judged: dict, title_pattern: str) -> bool:
    """리뷰 논문 판정: Claude 채점 결과(is_review) 우선, 없으면 OpenAlex type 또는 제목 단어."""
    if "is_review" in judged:
        return bool(judged["is_review"])
    return record.get("type") == "review" or bool(re.search(title_pattern, record.get("title") or "", re.I))


def select(records: list[dict], min_total: float, max_selected: int,
           review_min_relevance: int = 0, review_max: int = 0, min_relevance: int = 0,
           review_contributes: dict[str, bool] | None = None, institutions: dict | None = None,
           no_abstract_min_citation: float | None = None) -> None:
    """status: excluded_retracted / excluded_no_abstract / cocited_not_listed(→ mark_cocited) / below_relevance / below_threshold
    / over_limit / selected / review_listed / review_not_listed.
    review_contributes가 있으면 '본문 기여'로 평가된 리뷰만 목록에 올린다 (max는 상한일 뿐, 채우지 않음)."""
    rank = review_rank = institution_rank = 0
    for record in sorted(records, key=lambda r: r["total_score"], reverse=True):
        if record["exclude"]:
            record["status"] = "excluded_retracted"
        elif no_abstract_min_citation is not None and not record.get("abstract") and (
                record["score_parts"]["citation"] is not None and record["score_parts"]["citation"] < no_abstract_min_citation):
            record["status"] = "excluded_no_abstract"  # 인용 정보가 없으면 판단 근거가 없으므로 남김 (사용자 2026-10-19)
        elif is_cocited(record):  # 공통 인용 고전: 핵심논문과 따로 (mark_cocited가 목록을 고름)
            record["status"] = "cocited_not_listed"
        elif record.get("category") == "institution" and institutions:  # 기관·선급 문서: 핵심논문과 따로 (관련성 순 아님 — 총점 순)
            eligible = record["relevance"] >= institutions["min_relevance"]
            institution_rank += eligible
            ok = eligible and institution_rank <= institutions["max_listed"]
            record["status"] = "institution_listed" if ok else "institution_not_listed"
        elif record.get("is_review"):
            eligible = record["relevance"] >= review_min_relevance and (
                review_contributes is None or review_contributes.get(record["openalex_id"], False))
            review_rank += eligible
            ok = eligible and review_rank <= review_max
            record["status"] = "review_listed" if ok else "review_not_listed"
        elif record["relevance"] < min_relevance:
            record["status"] = "below_relevance"
        elif record["total_score"] < min_total:
            record["status"] = "below_threshold"
        else:
            rank += 1
            record["status"] = "selected" if rank <= max_selected else "over_limit"


def mark_cocited(records: list[dict], rules: dict) -> None:
    """공통 인용 고전 중 관련성 하한 이상을 공통 인용 많은 순 최대 M편 → cocited_listed (채우지 않음)."""
    pool = [r for r in records if r["status"] == "cocited_not_listed" and r["relevance"] >= rules["min_relevance"]]
    for r in sorted(pool, key=lambda r: (-cocited_count(r), -r["total_score"]))[:rules["max_listed"]]:
        r["status"] = "cocited_listed"


def mark_adjacent(records: list[dict], rules: dict, weights: dict[str, float]) -> None:
    """관련성은 선정 하한 아래지만 인용·학술지 점수가 높은 연구논문 → adjacent_listed (핵심논문과 따로 참고용, 채우지 않음)."""
    impact_weights = {k: v for k, v in weights.items() if k != "relevance"}
    pool = []
    for r in records:
        r.pop("adjacent_listed", None)
        parts = {k: r["score_parts"].get(k) for k in impact_weights}
        if r["status"] != "below_relevance" or r["relevance"] < rules["min_relevance"] or all(v is None for v in parts.values()):
            continue
        r["impact_score"] = round(weighted_total(parts, impact_weights) * r["category_weight"], 4)
        if r["impact_score"] >= rules["min_impact"]:
            pool.append(r)
    for r in sorted(pool, key=lambda r: -r["impact_score"])[:rules["max_listed"]]:
        r["adjacent_listed"] = True


UPDATE_NEW, UPDATE_DROPPED = "NEW", "제외됨(이전 선정)"


def mark_update(records: list[dict], previous_selected: set[str]) -> tuple[int, int]:
    """누적 갱신(사용자 지정 방식): 이번에 핵심논문에 새로 든 논문 → NEW (새로 검색된 것 + 순위가 오른 기존 후보, 사용자 결정 2026-10-19),
    이전 핵심논문인데 빠진 논문 → 제외됨(이전 선정). (NEW 편수, 제외 편수)"""
    for r in records:
        r.pop("update", None)
        if r["status"] == "selected" and r["openalex_id"] not in previous_selected:
            r["update"] = UPDATE_NEW
        elif r["openalex_id"] in previous_selected and r["status"] != "selected":
            r["update"] = UPDATE_DROPPED
    return (sum(r.get("update") == UPDATE_NEW for r in records), sum(r.get("update") == UPDATE_DROPPED for r in records))


def relevance_format_errors(files: list[Path]) -> list[str]:
    """채점 파일 형식 검사 — 에이전트 자가 확인에 맡기지 않음 (10-16 결함: 칸 이름을 'score'로 쓰고도 '확인 통과'라고 보고)."""
    errors = []
    for f in files:
        for i, r in enumerate(read_json(f)):
            rel = r.get("relevance") if isinstance(r, dict) else None
            if not isinstance(r, dict) or not r.get("openalex_id") or not isinstance(rel, int) or not 0 <= rel <= 5:
                errors.append(f"{f.name} {i}번째: openalex_id·relevance(0–5 정수) 필요 — 받은 칸 {sorted(r) if isinstance(r, dict) else type(r).__name__}")
    return errors


def score(run_dir: Path, config: dict) -> dict:
    candidates = read_json(run_dir / "candidates.json")
    venues = read_json(run_dir / "venues.json")
    integrity = read_json(run_dir / "integrity.json")
    files = sorted(run_dir.glob("relevance_[0-9]*.json"))
    if errors := relevance_format_errors(files):
        raise SystemExit(f"[score] 채점 파일 형식 오류 {len(errors)}건 — 해당 묶음을 고치거나 다시 채점:\n  " + "\n  ".join(errors[:10]))
    relevance = {r["openalex_id"]: r for f in files for r in read_json(f)}
    rechecks_path = run_dir / "verifier_rechecks.json"
    rechecks = read_json(rechecks_path) if rechecks_path.is_file() else {}
    records = candidates["records"]

    missing = [r["openalex_id"] for r in records if r["openalex_id"] not in relevance]
    if missing:
        raise SystemExit(f"관련성 채점이 없는 논문 {len(missing)}편: {missing[:5]} ...")

    rules = config["scoring"]
    searched = {r["openalex_id"] for r in records if not is_cocited(r)}  # 백분위 모집단 = 검색 후보 (고전을 더해도 핵심논문 점수 그대로)
    fwci_rank = percentile_ranks({r["openalex_id"]: r["fwci"] for r in records}, searched)
    venue_of = {r["openalex_id"]: venues.get(r["venue_id"] or "", {}) for r in records}
    citedness_rank = percentile_ranks({k: v.get("two_year_mean_citedness") for k, v in venue_of.items()}, searched)
    h_rank = percentile_ranks({k: v.get("h_index") for k, v in venue_of.items()}, searched)
    recent_from = date.today().year - rules["recent_citation_window_years"] + 1
    read_in_full = set(notes_by_id(run_dir))  # 본문 정리가 있는 논문 (관련성 상한 제외)

    for record in records:
        key = record["openalex_id"]
        judged = combine_judgements(relevance[key], rechecks.get(key))
        citation = fwci_rank[key] if fwci_rank[key] is not None else record["citation_percentile"]
        venue_parts = [p for p in (citedness_rank[key], h_rank[key]) if p is not None]
        relevance_score = capped_relevance(judged["relevance"], bool(record.get("abstract")) or key in read_in_full,
                                           rules["no_abstract_max_relevance"])
        parts = {
            "relevance": relevance_score / 5,
            "citation": citation,
            "venue": sum(venue_parts) / len(venue_parts) if venue_parts else None,
        }
        flags = list(integrity[key]["flags"])
        if record["year"] and record["year"] >= recent_from:
            flags.append("인용 집계 기간 짧음")
        if judged.get("low_confidence"):
            flags.append("초록 없음 (제목으로 채점 — 전문 확인 필요)")
        if judged.get("verified") and judged["relevance_original"] != judged["verifier_relevance"]:
            flags.append(f"교차 검증 이견: {judged['relevance_original']}점 vs {judged['verifier']} "
                         f"{judged['verifier_relevance']}점 → 낮은 점수 채택")
        if relevance_score < judged["relevance"]:
            flags.append(f"초록 없음 → 관련성 {judged['relevance']}점을 상한 {relevance_score}점으로")
        category = document_category(record, rules["institutions"])
        base_score = weighted_total(parts, rules["weights"])
        record.update({
            "category": category,
            "is_review": (is_review(record, relevance[key], rules["review"]["title_pattern"])
                          or bool((rechecks.get(key) or {}).get("is_review"))),
            "category_weight": rules["category_weights"][category],
            "base_score": round(base_score, 4),
            "relevance": relevance_score,
            "relevance_reason": judged["reason"],
            "verified": judged["verified"],
            "relevance_original": judged.get("relevance_original"),
            "verifier_relevance": judged.get("verifier_relevance"),
            "approach_tags": judged.get("approach", []),
            "structure_type": judged.get("structure_type"),
            "score_parts": parts,
            "total_score": round(base_score * rules["category_weights"][category], 4),
            "exclude": integrity[key]["exclude"],
            "flags": flags,
        })
        record["stars"] = stars(record["total_score"])

    select(records, rules["min_total_score"], rules["max_selected"],
           rules["review"]["min_relevance"], rules["review"]["max_listed"], rules["min_relevance"],
           contribution_votes(run_dir), rules["institutions"], rules["no_abstract_min_citation"])
    mark_cocited(records, rules["cocited"])
    mark_adjacent(records, rules["adjacent"], rules["weights"])
    update = None
    if updates := candidates["meta"].get("updates"):  # 누적 갱신 — 보존 폴더(이전 결과)의 선정과 비교 (merge_runs.py)
        last = updates[-1]
        base = read_json(run_dir / last["snapshot"] / "scored.json")
        new, dropped = mark_update(records, {r["openalex_id"] for r in base["records"] if r["status"] == "selected"})
        fresh = [r for r in records if r.get("first_seen") == last["at"][:10]]  # 이번 갱신에서 더한 후보
        update = {"base": last["snapshot"], "base_date": last["previous_run_at"][:10], "added_candidates": last["added"],
                  "new": new, "dropped": dropped,
                  # 새 논문은 인용 집계 기간이 짧아 총점에서 밀리기 쉬움 → 관련성은 통과했는데 빠진 편수를 따로 밝힘 (2026-10-19 시연)
                  "fresh_passed_not_selected": sum(r["status"] in ("below_threshold", "over_limit") for r in fresh)}
    records.sort(key=lambda r: r["total_score"], reverse=True)
    count = lambda status: sum(r["status"] == status for r in records)  # noqa: E731
    meta = candidates["meta"]
    first_batch = run_dir / "relevance_input_1.json"  # 사용자가 넣은 주제·접근법 (검색어를 만든 출발점)
    asked = {k: v for k, v in read_json(first_batch).items() if k in ("topic", "approach")} if first_batch.is_file() else {}
    return {
        "meta": {
            **meta,
            **asked,
            "weights": rules["weights"],
            "category_weights": rules["category_weights"],
            "min_relevance": rules["min_relevance"],
            "min_total_score": rules["min_total_score"],
            "max_selected": rules["max_selected"],
            "review_rules": {k: rules["review"][k] for k in ("min_relevance", "max_listed")},
            "adjacent_rules": rules["adjacent"],
            "update": update,
            "prisma": {
                "identified": meta["records_identified"],
                "duplicates_removed": meta["duplicates_removed"],
                "screened": len(records),
                "excluded_retracted": count("excluded_retracted"),
                "excluded_no_abstract": count("excluded_no_abstract"),  # 초록 없음 + 인용 백분위 낮음 (사용자 2026-10-19)
                "cocited_listed": count("cocited_listed"),  # 공통 인용 고전 (별도 목록)
                "cocited_not_listed": count("cocited_not_listed"),
                "below_relevance": count("below_relevance"),
                "below_threshold": count("below_threshold"),
                "over_limit": count("over_limit"),
                "selected": count("selected"),
                "reviews_listed": count("review_listed"),
                "reviews_not_listed": count("review_not_listed"),
                "institutions_listed": count("institution_listed"),
                "institutions_not_listed": count("institution_not_listed"),
                "adjacent_listed": sum(bool(r.get("adjacent_listed")) for r in records),  # 관련성 미달 안에 포함된 참고 목록
            },
        },
        "records": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()

    config = load_config()
    config["scoring"], overrides = scoring_config(args.run_dir)
    result = score(args.run_dir, config)
    result["meta"]["scoring_overrides"] = overrides  # 기본값과 다른 기준 — 보고서 부록·엑셀에 자동 표시
    write_json(args.run_dir / "scored.json", result)
    for o in overrides:
        print(f"[score] 주의: 기본값과 다른 기준 {o['key']} {o['default']} → {o['value']} ({o['source']}) — 권장하지 않음, 결과에 표시됨")

    prisma, totals = result["meta"]["prisma"], [r["total_score"] for r in result["records"] if r["status"] in RELEVANCE_PASSED]
    print(f"[score] 후보 {prisma['screened']} → 선정 {prisma['selected']} "
          f"(관련성 미달 {prisma['below_relevance']}, 기준 미달 {prisma['below_threshold']}, 상한 초과 {prisma['over_limit']}, 철회 {prisma['excluded_retracted']}, "
          f"초록 없음·인용 낮음 제외 {prisma['excluded_no_abstract']}) "
          f"+ 리뷰 논문 별도 {prisma['reviews_listed']}편 (해당 없음 {prisma['reviews_not_listed']}) "
          f"+ 기관·선급 문서 별도 {prisma['institutions_listed']}편 (목록 외 {prisma['institutions_not_listed']})"
          + (f" + 공통 인용 고전 별도 {prisma['cocited_listed']}편 (목록 외 {prisma['cocited_not_listed']})"
             if prisma["cocited_listed"] + prisma["cocited_not_listed"] else ""))
    if update := result["meta"].get("update"):
        print(f"  누적 갱신: {update['base_date']} 결과 대비 새 후보 {update['added_candidates']}편 → 핵심논문 NEW {update['new']}편, "
              f"제외됨(이전 선정) {update['dropped']}편")
    for cut in config["scoring"]["report_thresholds"]:
        print(f"  기준 {cut:.2f} 이상: {sum(t >= cut for t in totals)}편")
    title_only = [r["title"][:50] for r in result["records"] if r["status"] == "selected" and any("초록 없음" in f for f in r["flags"])]
    if title_only:  # 제목만으로 채점한 논문이 선정에 들어가면 중간 확인에서 보이게 (PINN 세부 조사 2026-10-16: 30편 중 8편, 1위 포함)
        print(f"  주의: 초록 없이 제목만으로 채점한 핵심논문 {len(title_only)}편 (신뢰도 낮음, 엑셀 비고에 표시) — 예: {title_only[0]}…")


if __name__ == "__main__":
    main()
