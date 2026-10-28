"""누적 갱신: 같은 주제로 다시 검색해 지난 후보에 새 논문을 더한다 (사용자 지정 방식 2026-10-13, 계획 docs/20261019_누적갱신_계획.md)

    python alt/merge_runs.py outputs/<run>/ --dry-run   # 다시 검색해 새 후보 편수·제목만 (파일 안 바꿈)
    python alt/merge_runs.py outputs/<run>/             # 지금 결과를 run_YYYYMMDD/에 보존 → 새 후보를 candidates.json에 더함

- 검색어·기간·시드 DOI는 지난번 그대로 (candidates.json meta) — 그사이 새로 나온·색인된 논문이 더해진다
- 지난 후보는 그대로 둔다 (관련성 채점·인용 키·본문 정리 유지). 다시 걸린 같은 논문은 인용 수·FWCI만 새 값으로 (전체 다시 점수화)
- 새 후보는 first_seen = 오늘. meta.updates에 기록 → score_papers가 보존 폴더의 선정과 비교해 NEW·'제외됨(이전 선정)' 표시
- 다음: fetch_venues → check_integrity → prepare_relevance_batches --only-unscored → 채점 → score_papers → … (SKILL '누적 갱신')
"""

from __future__ import annotations

import argparse
import shutil
from datetime import date, datetime
from pathlib import Path

from common import OUTPUT_NAMES, read_json, write_json
from search_papers import merge_records, search, title_key

SNAPSHOT_FILES = ["candidates.json", "scored.json", "references.json", "synthesis.json", "citation_keys.json",
                  "axis_assign.json", "topic.json", "02_literature_map.png", *OUTPUT_NAMES]
REFRESH_FIELDS = ("cited_by_count", "fwci", "citation_percentile")  # 시간이 지나면 바뀌는 값 — 같은 논문이면 새 값으로


def merge_new(old: list[dict], fresh: list[dict], today: str) -> tuple[list[dict], int, int]:
    """지난 후보(그대로) + 새 후보(지난 후보와 id·다른 판·제목이 겹치지 않는 것) → (합친 목록, 새 편수, 값 갱신 편수)."""
    unique_fresh, _ = merge_records(fresh)
    by_id = {v: r for r in old for v in (r["openalex_id"], *r.get("other_versions", []))}
    by_title = {title_key(r["title"]): r for r in old if title_key(r["title"])}
    added, refreshed = [], 0
    for f in unique_fresh:
        match = next((by_id[i] for i in (f["openalex_id"], *f.get("other_versions", [])) if i in by_id), None) \
            or by_title.get(title_key(f["title"]))
        if match is None:
            added.append({**f, "first_seen": today})
        elif match["openalex_id"] == f["openalex_id"]:  # 같은 판일 때만 (판마다 인용 값이 다름)
            match.update({k: f.get(k) for k in REFRESH_FIELDS})
            refreshed += 1
    return old + added, len(added), refreshed


def snapshot(run_dir: Path, stamp: str) -> Path:
    """지금 결과를 run_<stamp>/에 복사 (이미 있으면 _2, _3 …) — 이전 결과 보존·비교 기준."""
    out, n = run_dir / f"run_{stamp}", 2
    while out.exists():
        out, n = run_dir / f"run_{stamp}_{n}", n + 1
    out.mkdir()
    for name in SNAPSHOT_FILES:
        if (run_dir / name).is_file():
            shutil.copy2(run_dir / name, out / name)
    if (run_dir / "figures").is_dir():
        shutil.copytree(run_dir / "figures", out / "figures")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="다시 검색해 새 후보만 보여 줌 (파일 안 바꿈)")
    args = parser.parse_args()

    path = args.run_dir / "candidates.json"
    candidates = read_json(path)
    meta = candidates["meta"]
    fresh, logs = search(meta["queries"], meta["years"], meta.get("seed_dois") or [])
    records, added, refreshed = merge_new(candidates["records"], fresh, date.today().isoformat())
    print(f"[merge] 지난 검색 {meta['run_at'][:10]} 후보 {len(candidates['records'])}편 → 다시 검색 {len(fresh)}건, "
          f"새 후보 {added}편, 인용 값 갱신 {refreshed}편")
    for r in records[len(candidates["records"]):][:10]:
        print(f"  NEW 후보 {r['year']} {(r['title'] or '')[:90]}")
    if args.dry_run:
        return

    kept = snapshot(args.run_dir, meta["run_at"][:10].replace("-", ""))
    identified = meta["records_identified"] + len(fresh)
    meta.update({
        "updates": (meta.get("updates") or []) + [{"at": datetime.now().isoformat(timespec="seconds"), "snapshot": kept.name,
                                                   "previous_run_at": meta["run_at"], "retrieved": len(fresh),
                                                   "added": added, "refreshed": refreshed}],
        "first_run_at": meta.get("first_run_at") or meta["run_at"],
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "query_logs": logs,  # 지금 검색 상태 (상한 걸림 표시용)
        "records_identified": identified, "records_unique": len(records), "duplicates_removed": identified - len(records),
    })
    write_json(path, {"meta": meta, "records": records})
    print(f"[merge] 이전 결과 보존 → {kept.name}/, candidates.json {len(records)}편. 다음: fetch_venues → check_integrity → "
          "prepare_relevance_batches --only-unscored → 채점 → score_papers (SKILL '누적 갱신')")


if __name__ == "__main__":
    main()
