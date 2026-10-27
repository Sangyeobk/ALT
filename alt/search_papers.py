"""OpenAlex 검색 + 시드 논문 인용 추적 → candidates.json

    python alt/search_papers.py --years 2025-2027 \
        --query "wave loads offshore structures machine learning" \
        --query "data-driven hydrodynamic loads offshore wind" \
        [--seed-doi 10.xxxx/yyyy ...] --out outputs/<run>/candidates.json

검색어 확장(동의어)은 SKILL 단계에서 Claude가 하고, 이 스크립트는 받은 검색어를 그대로 실행한다.
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path

import pyalex
from pyalex import Works
from pyalex.api import invert_abstract

from common import load_config, load_search_prefs, load_user_settings, write_json

OPENALEX_ID_BATCH = 50  # OpenAlex OR 필터 한 번에 넣을 수 있는 id 개수 (API 제한)


def to_record(work: dict, found_by: str) -> dict:
    """OpenAlex work → ALT 후보 레코드 (평평한 dict)."""
    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    open_access = work.get("open_access") or {}
    percentile = work.get("citation_normalized_percentile") or {}
    authors = [
        (a.get("author") or {}).get("display_name")
        for a in (work.get("authorships") or [])
    ]
    return {
        "openalex_id": work.get("id"),
        "doi": work.get("doi"),
        "title": work.get("title"),
        "year": work.get("publication_year"),
        "type": work.get("type"),
        "cited_by_count": work.get("cited_by_count"),
        "fwci": work.get("fwci"),
        "citation_percentile": percentile.get("value"),
        "venue": source.get("display_name"),
        "venue_id": source.get("id"),
        "venue_type": source.get("type"),
        "venue_issn_l": source.get("issn_l"),
        "publisher": source.get("host_organization_name"),  # 기관·선급 문서 분류용 (발행처)
        "is_oa": open_access.get("is_oa"),
        "oa_status": open_access.get("oa_status"),
        "oa_url": open_access.get("oa_url"),
        "authors": [a for a in authors if a],
        "abstract": invert_abstract(work.get("abstract_inverted_index")),
        "referenced_works": work.get("referenced_works") or [],
        "is_retracted": work.get("is_retracted"),
        "found_by": [found_by],
    }


def title_key(title: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (title or "").lower())


def version_rank(record: dict) -> tuple:
    """같은 논문의 여러 판 중 남길 판: 저널 출판본 > DOI 있음 > 나머지."""
    return (record.get("venue_type") == "journal", bool(record.get("doi")))


def merge_records(records: list[dict]) -> tuple[list[dict], int]:
    """OpenAlex id, 그다음 제목 기준 중복 제거 (프리프린트·저장소 사본은 출판본으로 합침).
    found_by는 합치고, 합쳐진 판의 id는 other_versions에 남긴다. (고유 목록, 제거된 중복 수) 반환."""
    merged: dict[str, dict] = {}
    for record in records:
        key = title_key(record["title"]) or record["openalex_id"]
        if key not in merged:
            merged[key] = {**record, "found_by": list(record["found_by"]), "other_versions": []}
            continue
        kept = merged[key]
        if record["openalex_id"] != kept["openalex_id"] and version_rank(record) > version_rank(kept):
            merged[key] = {**record, "found_by": kept["found_by"],
                           "other_versions": kept["other_versions"] + [kept["openalex_id"]]}
            kept = merged[key]
        elif record["openalex_id"] != kept["openalex_id"] and record["openalex_id"] not in kept["other_versions"]:
            kept["other_versions"].append(record["openalex_id"])
        for label in record["found_by"]:
            if label not in kept["found_by"]:
                kept["found_by"].append(label)
    return list(merged.values()), len(records) - len(merged)


def run_query(query, label: str, max_records: int) -> tuple[list[dict], dict]:
    expected = query.count()
    works = [w for page in query.paginate(per_page=min(200, max_records), n_max=max_records) for w in page]
    log = {"label": label, "expected_total": expected, "retrieved": len(works),
           "stopped_at_limit": len(works) < expected}
    return [to_record(w, label) for w in works], log


def seed_expansions(seed_doi: str, years: str, fields: list[str], max_records: int):
    """시드 논문의 참고문헌(backward)과 피인용(forward)을 기간 필터를 걸어 가져온다."""
    seed = Works()[f"https://doi.org/{seed_doi}"]
    seed_id = seed["id"].rsplit("/", 1)[-1]
    yield Works().filter(cites=seed_id, publication_year=years).select(fields), f"seed_cited_by:{seed_doi}"
    refs = [r.rsplit("/", 1)[-1] for r in seed.get("referenced_works") or []]
    for start in range(0, len(refs), OPENALEX_ID_BATCH):
        batch = "|".join(refs[start:start + OPENALEX_ID_BATCH])
        yield (Works().filter(openalex_id=batch, publication_year=years).select(fields),
               f"seed_references:{seed_doi}")


def count_queries(queries: list[str], years: str) -> list[dict]:
    """검색 전 편수만 조회한다. 후보 목록이나 채점 결과는 바꾸지 않는다."""
    settings = load_user_settings()
    pyalex.config.email = settings.get("email")
    pyalex.config.api_key = settings.get("openalex_key")
    return [{"query": text, "expected_total": Works().search(text).filter(publication_year=years).count()}
            for text in queries]


def search(queries: list[str], years: str, seed_dois: list[str]) -> tuple[list[dict], list[dict]]:
    """검색어마다 OpenAlex 검색 + 시드 논문 인용 추적 → (중복 포함 전체 레코드, 검색별 기록). 누적 갱신(merge_runs.py)도 씀."""
    config = load_config()["search"]
    settings = load_user_settings()
    pyalex.config.email = settings.get("email")
    pyalex.config.api_key = settings.get("openalex_key")
    fields = config["openalex_fields"]

    all_records, query_logs = [], []
    for text in queries:
        query = Works().search(text).filter(publication_year=years).select(fields)
        records, log = run_query(query, f"query:{text}", config["per_query_max_records"])
        all_records += records
        query_logs.append(log)
        print(f"[search] {text!r}: {log['retrieved']}/{log['expected_total']}")
    for doi in seed_dois:
        for query, label in seed_expansions(doi, years, fields, config["seed_expand_max_records"]):
            records, log = run_query(query, label, config["seed_expand_max_records"])
            all_records += records
            query_logs.append(log)
            print(f"[seed] {label}: {log['retrieved']}/{log['expected_total']}")
    return all_records, query_logs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--query", action="append", required=True)
    parser.add_argument("--years", required=True, help="예: 2025-2027")
    parser.add_argument("--seed-doi", action="append", default=[])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--count-only", action="store_true", help="검색어별 편수만 조회해 별도 JSON에 저장 (후보 수집 없음)")
    args = parser.parse_args()

    if args.count_only:
        if args.out.name.casefold() == "candidates.json":
            parser.error("편수 미리보기는 candidates.json 대신 query_counts.json 등에 저장")
        counts = count_queries(args.query, args.years)
        write_json(args.out, {"checked_at": datetime.now().isoformat(timespec="seconds"), "years": args.years, "queries": counts})
        for row in counts:
            print(f"[count] {row['query']}: {row['expected_total']}편 (중복 제거 전)")
        return

    all_records, query_logs = search(args.query, args.years, args.seed_doi)
    unique, duplicates = merge_records(all_records)
    write_json(args.out, {
        "meta": {
            "run_at": datetime.now().isoformat(timespec="seconds"),
            "years": args.years,
            "queries": args.query,
            "seed_dois": args.seed_doi,
            "search_prefs": load_search_prefs() or None,  # 검색어를 만들 때 참고한 검색 취향 (적용 기록 — 채점에는 안 씀)
            "query_logs": query_logs,
            "records_identified": len(all_records),
            "duplicates_removed": duplicates,
            "records_unique": len(unique),
        },
        "records": unique,
    })
    partial = [log["label"] for log in query_logs if log["stopped_at_limit"]]
    print(f"[done] identified {len(all_records)}, duplicates {duplicates}, unique {len(unique)} -> {args.out}")
    if partial:
        print(f"[note] 상한에 걸려 일부만 가져온 검색 {len(partial)}개 (config per_query_max_records)")


if __name__ == "__main__":
    main()
