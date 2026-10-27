"""발표 구성안 입력 만들기·검사 (⑨-1, 사용자 결정 2026-10-21 — 양식 규칙에 맞춰 발표를 다시 씀)

    python alt/prepare_slides.py outputs/<run>/                 # slides_input.json (alt-writer가 alt/slides_guide.md대로 slides.json을 씀)
    python alt/prepare_slides.py outputs/<run>/ --check         # slides.json 검사 (글자 수 한도·칸·그림·표·인용 키)
    python alt/prepare_slides.py outputs/<run>/ --deck learn    # 01_배경학습: slides_learn_input.json → slides_learn.json (--check도 같음)

양식에 장 종류 목록(config output.pptx_templates.<양식>.catalog)이 있을 때만 쓴다. 없으면 build_pptx.py가 예전 방식으로 만든다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from build_pptx import TALK_SECTIONS, pptx_style
from common import (display_names, load_config, load_topic, map_axis, read_json, report_title, review_info, scope_history, sections,
                    topic_line, write_json)
from export_references import EXCEL_SHEETS
from report_facts import method_lines
from slides_plan import (DECK_FILES, LEARN_FIGURE_PREFIX, LEARN_SECTIONS, LEARN_TAIL, check_learn_plan, check_plan, figure_choices,
                         load_catalog, slot_limits)


def types_input(style: dict, catalog: dict) -> dict:
    limits = slot_limits(style, catalog)
    return {name: {"use": kind["use"], "slots": limits[name],
                   **({"image": True} if "image" in kind else {}), **({"table": True} if "table" in kind else {})}
            for name, kind in catalog["types"].items()}


def build_input(run_dir: Path, style: dict, catalog: dict) -> dict:
    s = read_json(run_dir / "synthesis.json")
    scored = read_json(run_dir / "scored.json")
    refs = read_json(run_dir / "references.json")
    meta = scored["meta"]
    level_of = review_info(run_dir, None)[1]
    chosen = [sid for sid in sections("slide", run_dir) if sid in TALK_SECTIONS]
    return {
        "guide": "alt/slides_guide.md",
        "title": report_title(run_dir, s, refs),
        "topic_line": topic_line(run_dir, refs),
        "searched_on": meta["run_at"][:10],
        "scope_history": [list(row) for row in scope_history(run_dir)],
        "sections": [{"id": sid, "name": TALK_SECTIONS[sid][0]} for sid in chosen],
        "facts": {"prisma": meta["prisma"], "subtopics": len(s.get("subtopics", [])), "map_axis": map_axis(run_dir)["name"],
                  "method_lines": [line for line, _ in method_lines(meta, scored["records"], load_config(), level_of, load_topic(run_dir))],
                  "excel_sheets": [list(row) for row in EXCEL_SHEETS]},
        "types": types_input(style, catalog),
        "figures": figure_choices(run_dir, s),
        "ref_keys": sorted(refs),
        "synthesis": s,
    }


def build_learn_input(run_dir: Path, style: dict, catalog: dict) -> dict:
    """01_배경학습 구성안 입력 — 요약 전체 대신 배경 부분만 (용어 표·읽는 법은 코드가 붙이므로 뺌)."""
    s = read_json(run_dir / "synthesis.json")
    refs = read_json(run_dir / "references.json")
    meta = read_json(run_dir / "scored.json")["meta"]
    background = {k: v for k, v in s["background"].items() if k != "glossary"}
    return {
        "guide": "alt/slides_guide.md ('배경학습' 절)",
        "deck": "learn",
        "title": report_title(run_dir, s, refs),
        "topic_line": topic_line(run_dir, refs),
        "searched_on": meta["run_at"][:10],
        "names": display_names(run_dir, s, meta),
        "sections_count": LEARN_SECTIONS,
        "tail_section": LEARN_TAIL,
        "types": types_input(style, catalog),
        "figures": [f for f in figure_choices(run_dir, s) if f["file"].startswith(LEARN_FIGURE_PREFIX)],
        "ref_keys": sorted(refs),
        "background": background,
        "subtopics": [{"name": t["name"], "role": t.get("role"), "lead": t.get("lead")} for t in s.get("subtopics", [])],
        "role_names": s.get("role_names"),
        "approach_roles": s.get("approach_roles"),
        "reviews_guide": s.get("reviews_guide", []),
        "tech_keywords": s.get("tech_keywords", []),
        "abbreviations": s.get("abbreviations", {}),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--deck", choices=list(DECK_FILES), default="talk")
    args = parser.parse_args()
    style = pptx_style()
    catalog = load_catalog(style)
    if catalog is None or style["path"] is None:
        sys.exit("[slides] 이 양식에는 장 종류 목록이 없음 — build_pptx.py가 예전 방식으로 만듦")
    input_file, slides_file = DECK_FILES[args.deck]
    if args.check:
        plan = read_json(args.run_dir / slides_file)
        errors = check_plan(plan, catalog, slot_limits(style, catalog), set(read_json(args.run_dir / "references.json")), args.run_dir)
        if args.deck == "learn":
            errors += check_learn_plan(plan)
        for e in errors:
            print(" -", e)
        print(f"[slides] {slides_file} {len(plan.get('slides', []))}장 — " + ("통과" if not errors else f"오류 {len(errors)}건"))
        sys.exit(1 if errors else 0)
    data = (build_learn_input if args.deck == "learn" else build_input)(args.run_dir, style, catalog)
    write_json(args.run_dir / input_file, data)
    print(f"[slides] {input_file}: 장 종류 {len(data['types'])}개, 그림 {len(data['figures'])}개")


if __name__ == "__main__":
    main()
