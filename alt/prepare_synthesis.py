"""요약·분류 준비: 선정 논문 + 리뷰 목록에 인용 키(예: Kim2025a)를 매기고 → references.json, synthesis_input.json

    python alt/prepare_synthesis.py outputs/<run>/

- references.json: 산출물에서 인용할 수 있는 문헌 전부 (키 → 서지 정보). 인용 검사의 허용 목록이 된다.
- synthesis_input.json: Claude가 요약·분류할 때 읽는 파일 (초록 전문 포함)
"""

import argparse
import re
import shutil
import unicodedata
from collections import Counter
from pathlib import Path

from add_institution_docs import load_user_docs
from common import (KEY_REGISTRY, candidate_distribution, key_registry, load_config, load_topic, load_user_style, map_axis, read_json, run_reading_mode,
                    variant_name, write_json)

CITABLE_STATUS = ("selected", "review_listed", "institution_listed")  # 기관·선급 문서도 인용 가능 (사용자 결정 2026-10-16)
READING_MODES = ("abstract", "full")
READING_MODE_LABEL = {"abstract": "초록 모드", "full": "전문 모드"}
REVIEW_LEVELS = ("전문", "초록", "제목만")


def load_fulltext_notes(run_dir: Path) -> dict:
    """본문 정리 결과(fulltext_notes_<k>.json, 하위 에이전트가 씀) → {키: 정리}."""
    notes = {}
    for path in sorted(run_dir.glob("fulltext_notes_*.json")):
        notes.update(read_json(path)["notes"])
    for path in sorted(run_dir.glob("figure_picks_*.json")):  # 그림 고르기(맥락 정리 뒤 따로, 사용자 결정 2026-10-16)를 그 정리에 합침
        for key, pick in read_json(path)["notes"].items():
            if key in notes:
                notes[key] = {**notes[key], "figures": pick.get("figures", [])}
    return {key: note for key, note in notes.items() if not note.get("unreadable")}  # 깨져서 못 읽은 논문은 초록 수준


def review_level(key: str, abstract: str | None, notes: dict) -> str:
    """요약 단계가 실제로 읽는 수준. 본문 정리가 있어야 '전문' (PDF만 받아 둔 것은 전문이 아님)."""
    if key in notes:
        return "전문"
    return "초록" if abstract else "제목만"


def family_name(display_name: str | None) -> str:
    if not display_name:
        return "Anon"
    ascii_name = unicodedata.normalize("NFKD", display_name).encode("ascii", "ignore").decode()
    last = re.sub(r"[^A-Za-z]", "", ascii_name.split()[-1]) if ascii_name.split() else ""
    return last.capitalize() or "Anon"


def stable_keys(records: list[dict], previous: dict[str, str]) -> dict[str, str]:
    """다시 실행해도 이미 쓴 인용 키는 바꾸지 않는다 (previous: openalex_id → 지난 키, 지금 목록에 없는 논문 포함).
    새 논문만 키를 새로 매기고, 지난 키(빠진 논문 것도 — 돌아올 수 있음)와 겹치면 b, c… 를 붙인다."""
    fresh = assign_keys([r for r in records if r["openalex_id"] not in previous])
    keys = {r["openalex_id"]: previous[r["openalex_id"]] for r in records if r["openalex_id"] in previous}
    used = set(previous.values())
    for openalex_id, key in fresh.items():
        base = re.sub(r"(?<=\d)[a-z]$", "", key)
        candidate = key if key not in used and base not in used else next(
            base + s for s in "bcdefghijklmnopqrstuvwxyz" if base + s not in used)
        keys[openalex_id] = candidate
        used.add(candidate)
    return keys


def assign_keys(records: list[dict]) -> dict[str, str]:
    """openalex_id → 인용 키. 같은 저자·연도는 a, b, c… 를 붙인다 (입력 순서 기준)."""
    keys, used = {}, {}
    for record in records:
        name = record.get("org_short") or family_name((record.get("authors") or [None])[0])  # 사용자 제공 기관 문서: KR2024
        base = f"{name}{record.get('year') or 'nd'}"
        used[base] = used.get(base, 0) + 1
        keys[record["openalex_id"]] = base
    counts = {}
    for record in records:
        base = keys[record["openalex_id"]]
        if used[base] > 1:
            counts[base] = counts.get(base, 0) + 1
            keys[record["openalex_id"]] = base + "abcdefghijklmnopqrstuvwxyz"[counts[base] - 1]
    return keys


def variant_for(reading_mode: str, variant: str | None) -> str:
    """판 이름: 지정하지 않으면 전문 모드는 '전문활용', 초록 모드는 config 기본값."""
    return variant or ("전문활용" if reading_mode == "full" else load_config()["output"]["default_variant"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--reading-mode", choices=READING_MODES, default=None,
                        help="abstract = 초록만 / full = 본문 정리(fulltext_notes_*.json)가 있는 논문은 본문 기반 "
                             "(기본: 초록, 이 조사에서 전문을 쓴 적 있으면 전문 — common.run_reading_mode)")
    parser.add_argument("--keywords", default="",
                        help='사용자가 정한 핵심 키워드 (세미콜론으로 구분, 예: "검증 기준; 적용 범위"). 없으면 요약 에이전트가 고름')
    parser.add_argument("--variant", default=None, help="사용량 장부 단계 이름용 (파일 이름에는 붙지 않음)")
    args = parser.parse_args()
    args.reading_mode = args.reading_mode or run_reading_mode(args.run_dir)
    variant = variant_for(args.reading_mode, args.variant)

    scored = read_json(args.run_dir / "scored.json")
    citable = ([r for r in scored["records"] if r["status"] in CITABLE_STATUS or r.get("adjacent_listed")]  # 주목할 인접 문헌도 목록용으로
               + load_user_docs(args.run_dir))
    old_path = args.run_dir / "references.json"
    old = read_json(old_path) if old_path.is_file() else {}  # 다시 실행해도 전문 수집 기록(자동/수동)은 이어받음
    keys = stable_keys(citable, key_registry(args.run_dir))
    write_json(args.run_dir / KEY_REGISTRY, {**key_registry(args.run_dir), **keys})  # 빠진 논문의 키도 남김
    references = {}
    for r in citable:
        references[keys[r["openalex_id"]]] = {
            "key": keys[r["openalex_id"]], "openalex_id": r["openalex_id"], "doi": r["doi"], "title": r["title"],
            "authors": r["authors"], "year": r["year"], "venue": r["venue"], "category": r["category"],
            "status": r["status"], "update": r.get("update"), "relevance": r["relevance"], "relevance_reason": r["relevance_reason"],
            "total_score": r["total_score"], "stars": r["stars"], "score_parts": r["score_parts"],
            "fwci": r["fwci"], "cited_by_count": r["cited_by_count"], "is_oa": r["is_oa"], "oa_url": r["oa_url"],
            "flags": r["flags"], "approach_tags": r["approach_tags"], "structure_type": r["structure_type"],
            **{k: r[k] for k in ("doc_number", "user_provided", "source_file", "adjacent_listed", "impact_score") if r.get(k)},
            **{k: v for k, v in old.get(keys[r["openalex_id"]], {}).items() if k.startswith(("pdf_", "oa_pdf", "oa_landing", "manual_", "biblio"))},
        }
    write_json(args.run_dir / "references.json", references)
    for key, ref in references.items():  # 사용자 제공 기관 문서 PDF → papers/<키>.pdf (전문 모드에서 본문을 읽게)
        target = args.run_dir / "papers" / f"{key}.pdf"
        if ref.get("source_file") and not target.is_file():
            target.parent.mkdir(exist_ok=True)
            shutil.copy2(args.run_dir / ref["source_file"], target)
    notes = load_fulltext_notes(args.run_dir) if args.reading_mode == "full" else {}
    papers = []
    for r in citable:
        key = keys[r["openalex_id"]]
        paper = {**{k: references[key][k] for k in
                    ("key", "title", "year", "venue", "status", "relevance", "stars", "approach_tags", "structure_type")},
                 **{k: references[key][k] for k in ("doc_number", "user_provided") if references[key].get(k)},
                 **({"adjacent": True} if r.get("adjacent_listed") else {}),
                 "review_level": review_level(key, r["abstract"], notes), "abstract": r["abstract"]}
        if key in notes:
            paper["fulltext_notes"] = notes[key]
        papers.append(paper)
    levels = Counter(p["review_level"] for p in papers)
    records = scored["records"]
    input_name = variant_name("synthesis_input.json", variant)
    write_json(args.run_dir / input_name, {
        "meta": {**scored["meta"], "reading_mode": args.reading_mode, "review_levels": dict(levels),
                 "year_counts": dict(sorted(Counter(r["year"] for r in records).items())),
                 "candidate_distribution": candidate_distribution(records, load_config()["output"], map_axis(args.run_dir)),
                 "user_style": load_user_style(args.run_dir),  # 개인 스타일 (report_guide.md보다 우선)
                 "topic_confirmed": load_topic(args.run_dir),  # 사용자가 확정한 주제 — names는 이 이름 그대로
                 "user_keywords": [k.strip() for k in args.keywords.split(";") if k.strip()]},
        "papers": papers,
    })
    selected = sum(r["status"] == "selected" for r in citable)
    print(f"[synthesis] 인용 가능 문헌 {len(citable)}편 (선정 {selected}, 리뷰 {sum(r['status'] == 'review_listed' for r in citable)}, "
          f"기관·선급 {sum(r['status'] == 'institution_listed' for r in citable)}, "
          f"주목할 인접 {sum(bool(r.get('adjacent_listed')) for r in citable)}) -> references.json, {input_name}, "
          f"{READING_MODE_LABEL[args.reading_mode]} — 검토 수준 " + " · ".join(f"{k} {levels[k]}" for k in REVIEW_LEVELS if levels[k]))


if __name__ == "__main__":
    main()
