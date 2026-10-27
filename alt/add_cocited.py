"""④-2 공통 인용 보강: 관련성 높은 후보들이 함께 인용하는데 검색 후보에 없는 문헌(분야 고전)을 후보에 더한다.

    python alt/add_cocited.py outputs/<run>/ --dry-run   # 더할 편수·제목·채점 토큰 추정만 (파일 안 바꿈) → 사용자 승인
    python alt/add_cocited.py outputs/<run>/             # candidates.json에 더함 (첫 보강 전 원본은 candidates.before_cocited.json)

- 대상: ④ 채점(relevance_*.json)에서 관련성 min_relevance점 이상인 후보의 참고문헌(referenced_works)을 세어,
  max(min_count, min_share × 그 편수)편 이상이 인용했고 **검색 기간 안**이며 후보에 없는 문헌 (config search.cocited)
- 세부 조사(폴더 `<이 폴더>__<이름>`, 또는 topic.json parent_run이 이 폴더)가 더한 고전 중 이 조사 후보에 없는 것도 더한다
  (사용자 결정 2026-10-19: 세부 조사에서 찾은 놓친 고전은 상위 조사에 반영)
- 원인 (2026-10-19 점검, docs/20261016_놓친고전_계획.md): 초록·본문 색인이 없는 고전은 제목으로만 검색되어 긴 검색어에 안 걸림
- 더한 문헌은 found_by `cocited:<인용 편수>[:<세부 조사 폴더>]` → 같은 기준으로 채점하되 ⑤에서 핵심논문과 따로
  '공통 인용 고전' 목록 (config scoring.cocited, 사용자 결정 2026-10-19)
- 다시 돌리면 아직 없는 것만 더한다. 다음: fetch_venues → check_integrity → prepare_relevance_batches --only-unscored → 채점
"""

from __future__ import annotations

import argparse
import math
import shutil
from collections import Counter
from pathlib import Path

import pyalex
from pyalex import Works

from common import PROJECT_DIR, load_config, load_topic, load_user_settings, read_json, write_json
from search_papers import OPENALEX_ID_BATCH, title_key, to_record

COCITED = "cocited"


def short_id(openalex_id: str | None) -> str:
    return (openalex_id or "").rsplit("/", 1)[-1]


def is_cocited(record: dict) -> bool:
    return any(label.startswith(COCITED + ":") for label in record.get("found_by") or [])


def cocited_count(record: dict) -> int:
    return max((int(label.split(":")[1]) for label in record.get("found_by") or [] if label.startswith(COCITED + ":")), default=0)


def in_years(year: int | None, years: str) -> bool:
    lo, hi = (int(y) for y in years.split("-"))
    return year is not None and lo <= year <= hi


def load_relevance(run_dir: Path) -> dict[str, int]:
    return {r["openalex_id"]: r["relevance"] for f in sorted(run_dir.glob("relevance_[0-9]*.json")) for r in read_json(f)}


def known_ids(records: list[dict]) -> set[str]:
    return {short_id(r["openalex_id"]) for r in records} | {short_id(v) for r in records for v in r.get("other_versions") or []}


def cocited_targets(records: list[dict], relevance: dict[str, int], rules: dict) -> tuple[dict[str, int], int, int]:
    """({후보 밖 문헌 id: 인용 편수}, 인용 편수 기준, 기준 이상 편수). 한 논문이 같은 문헌을 여러 번 적어도 1번.
    이미 더한 고전의 참고문헌은 세지 않는다 (검색 후보 기준)."""
    base = [r for r in records if not is_cocited(r) and relevance.get(r["openalex_id"], 0) >= rules["min_relevance"]]
    threshold = max(rules["min_count"], math.ceil(rules["min_share"] * len(base)))
    counts = Counter()
    for r in base:
        counts.update({short_id(w) for w in r.get("referenced_works") or []})
    known = known_ids(records)
    return {w: n for w, n in counts.items() if n >= threshold and w not in known}, threshold, len(base)


def child_runs(run_dir: Path) -> list[Path]:
    """세부 조사 폴더: 이름이 `<이 폴더>__…` 이거나 topic.json parent_run이 이 폴더."""
    run_dir = Path(run_dir).resolve()
    children = []
    for p in sorted(run_dir.parent.iterdir()):
        if not p.is_dir() or p == run_dir:
            continue
        parent = load_topic(p).get("parent_run")
        if p.name.startswith(run_dir.name + "__") or (parent and Path(parent).name == run_dir.name):
            children.append(p)
    return children


def child_classics(run_dir: Path, records: list[dict], years: str) -> list[dict]:
    """세부 조사가 더한 고전 중 이 조사 기간 안이고 후보에 없는 것 (found_by 끝에 세부 조사 폴더 이름)."""
    known, titles = known_ids(records), {title_key(r["title"]) for r in records}
    found = {}
    for child in child_runs(run_dir):
        path = child / "candidates.json"
        for r in (read_json(path)["records"] if path.is_file() else []):
            sid = short_id(r["openalex_id"])
            if (is_cocited(r) and in_years(r.get("year"), years) and sid not in known
                    and title_key(r["title"]) not in titles and sid not in found):
                found[sid] = {**r, "found_by": [f"{COCITED}:{cocited_count(r)}:{child.name}"], "other_versions": []}
    return list(found.values())


def new_records(works: list[dict], targets: dict[str, int], records: list[dict]) -> tuple[list[dict], int]:
    """받은 문헌 → 후보 레코드 (공통 인용 많은 순). 제목이 같은 후보가 이미 있으면(다른 판) 빼고 그 수를 함께 반환."""
    titles = {title_key(r["title"]) for r in records}
    added = [{**to_record(w, f"{COCITED}:{targets[short_id(w['id'])]}"), "other_versions": []} for w in works]
    kept = [r for r in added if not title_key(r["title"]) or title_key(r["title"]) not in titles]
    return sorted(kept, key=lambda r: -cocited_count(r)), len(added) - len(kept)


def fetch(ids: list[str], fields: list[str]) -> list[dict]:
    """id 필터 (검색이 아니라 호출당 비용이 작음)."""
    works = []
    for start in range(0, len(ids), OPENALEX_ID_BATCH):
        works += Works().filter(openalex_id="|".join(ids[start:start + OPENALEX_ID_BATCH])).select(fields).get(per_page=OPENALEX_ID_BATCH)
    return works


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="더할 편수·토큰 추정만 보여 줌")
    args = parser.parse_args()
    run_dir = args.run_dir if args.run_dir.is_absolute() else PROJECT_DIR / args.run_dir

    config = load_config()
    rules = config["search"]["cocited"]
    path = run_dir / "candidates.json"
    candidates = read_json(path)
    meta, records = candidates["meta"], candidates["records"]
    relevance = load_relevance(run_dir)
    if not relevance:
        raise SystemExit("[cocited] 관련성 채점(relevance_*.json)이 없음 — ④ 채점 뒤에 실행")

    targets, threshold, base = cocited_targets(records, relevance, rules)
    settings = load_user_settings()
    pyalex.config.email = settings.get("email")
    pyalex.config.api_key = settings.get("openalex_key")
    works = fetch(sorted(targets), config["search"]["openalex_fields"]) if targets else []
    in_period = [w for w in works if in_years(w.get("publication_year"), meta["years"])]
    own, same_title = new_records(in_period, targets, records)
    from_children = child_classics(run_dir, records + own, meta["years"])
    added = own + from_children
    per_paper = config["usage"]["reference_tokens"]["관련성"]["tokens"]
    print(f"[cocited] 관련성 {rules['min_relevance']}점 이상 {base}편 · 기준 {threshold}편 이상 공통 인용 → 후보 밖 {len(targets)}편 "
          f"(기간 {meta['years']} 밖 {len(works) - len(in_period)}, 같은 제목 후보 있음 {same_title}) → 더할 문헌 {len(own)}편"
          + (f" + 세부 조사에서 {len(from_children)}편" if from_children else ""))
    print(f"[cocited] 초록 없음 {sum(not r['abstract'] for r in added)}편 (⑤에서 인용 백분위가 낮으면 제외, 높으면 제목으로 채점·전문 확인 필요)")
    print(f"[cocited] ④ 채점 토큰 추정 약 {len(added) * per_paper:,} (1편 {per_paper:,} × {len(added)}편, config usage.reference_tokens.관련성)")
    for r in added[:15]:
        print(f"  - {r['found_by'][0]} | {r['year']} | {r['title']}")
    if args.dry_run or not added:
        print("[cocited] 더할 문헌 없음" if not added else "[cocited] 미리보기만 — 승인 뒤 --dry-run 없이")
        return
    backup = path.with_name("candidates.before_cocited.json")
    if not backup.exists():
        shutil.copy2(path, backup)
    before = meta.get("cocited") or {}
    meta["cocited"] = {**rules, "base": base, "threshold": threshold, "eligible": len(targets),
                       "out_of_period": len(works) - len(in_period), "same_title_as_candidate": same_title,
                       "added_total": before.get("added_total", 0) + len(added),
                       "from_children": before.get("from_children", 0) + len(from_children)}
    meta["records_identified"] += len(added)
    meta["records_unique"] += len(added)
    write_json(path, {"meta": meta, "records": records + added})
    print(f"[cocited] {len(added)}편 더함 -> {path} (원본 {backup.name})")
    print("다음: fetch_venues.py → check_integrity.py → prepare_relevance_batches.py --only-unscored --batches 1 → alt-scorer")


if __name__ == "__main__":
    main()
