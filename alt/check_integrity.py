"""철회 논문 검사(OpenAlex + Crossref) + 부실 학술지 의심 표시(DOAJ) → integrity.json

    python alt/check_integrity.py outputs/<run>/candidates.json   (먼저 fetch_venues.py 실행)

- 철회·철회 유사(withdrawal 등) → 제외 대상 (`exclude: true`)
- 우려 표명(expression of concern) → 표시만
- 무료 공개(OA) 학술지인데 DOAJ에 없음 (OpenAlex source의 is_oa·is_in_doaj 사용) → "확인 필요" 표시만 (부실이라고 단정하지 않음)
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from common import load_config, load_user_settings, read_json, write_json

CROSSREF_WORK_URL = "https://api.crossref.org/works/{doi}"


def crossref_notices(session: requests.Session, doi: str | None, mailto: str | None) -> list[str] | None:
    """해당 DOI를 갱신한 공지 종류 목록 (예: ['retraction']). 조회 실패면 None."""
    if not doi:
        return []
    bare = doi.replace("https://doi.org/", "")
    try:
        response = session.get(CROSSREF_WORK_URL.format(doi=bare), params={"mailto": mailto}, timeout=20)
    except requests.RequestException:
        return None
    if response.status_code == 404:
        return []  # Crossref 외 등록기관(DataCite 등) DOI
    if not response.ok:
        return None
    return [n.get("type") for n in response.json()["message"].get("updated-by") or []]


def judge(record: dict, notices: list[str] | None, listed: bool | None, rules: dict) -> dict:
    """한 논문의 검사 결과. 규칙(제외·표시할 공지 종류)은 config에서 받는다."""
    checked = notices is not None
    notices = notices or []
    exclude_hits = [n for n in notices if n in rules["exclude_notice_types"]]
    flag_hits = [n for n in notices if n in rules["flag_notice_types"]]
    retracted = bool(record.get("is_retracted")) or bool(exclude_hits)
    flags = []
    if retracted:
        flags.append("철회됨")
    flags += [f"공지: {n}" for n in flag_hits]
    if listed is False:
        flags.append("DOAJ 미등재 OA 학술지 (확인 필요)")
    return {
        "exclude": retracted,
        "crossref_notices": notices,
        "crossref_checked": checked,
        "doaj_listed": listed,
        "flags": flags,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("candidates", type=Path)
    args = parser.parse_args()

    rules = load_config()["integrity"]
    mailto = load_user_settings().get("email")
    records = read_json(args.candidates)["records"]
    session = requests.Session()

    with ThreadPoolExecutor(max_workers=rules["crossref_workers"]) as pool:
        notices = list(pool.map(lambda r: crossref_notices(session, r["doi"], mailto), records))

    venues = read_json(args.candidates.with_name("venues.json"))
    results = {}
    for record, record_notices in zip(records, notices):
        venue = venues.get(record.get("venue_id") or "", {})
        is_oa_journal = venue.get("is_oa") and venue.get("type") == "journal"  # 저장소(arXiv 등)·학회는 제외
        listed = venue.get("is_in_doaj") if is_oa_journal else None
        results[record["openalex_id"]] = judge(record, record_notices, listed, rules)

    out = args.candidates.with_name("integrity.json")
    write_json(out, results)
    excluded = sum(v["exclude"] for v in results.values())
    unchecked = sum(not v["crossref_checked"] for v in results.values())
    not_in_doaj = {r.get("venue_id") for r in records if results[r["openalex_id"]]["doaj_listed"] is False}
    oa_venues = [v for v in venues.values() if v.get("is_oa") and v.get("type") == "journal"]
    print(f"[integrity] {len(records)}편 검사: 철회 제외 {excluded}, Crossref 조회 실패 {unchecked}, "
          f"OA 학술지 {len(oa_venues)}개 중 DOAJ 미등재 {len(not_in_doaj)}개 -> {out}")


if __name__ == "__main__":
    main()
