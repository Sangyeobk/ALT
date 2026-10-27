"""문헌지도 가로축 AI 분류 (사용자 결정 2026-10-16) — 낱말 분류는 미분류가 많아, AI가 제목·초록(·본문 정리)을 읽고 묶음을 고른다.

    python alt/classify_axis.py outputs/<run>/ --prepare --batches 2   # axis_input_<k>.json (관련성 map_min_relevance점 이상 후보)
    python alt/classify_axis.py outputs/<run>/ --prepare --fulltext    # 본문 정리가 생겼는데 아직 전문 근거로 안 나눈 논문만 (다시 분류)
    (alt-scorer 에이전트가 axis_input_<k>.json → axis_<k>.json, 기준 alt/axis_rubric.md)
    python alt/classify_axis.py outputs/<run>/ --merge                  # axis_<k>.json → axis_assign.json
    python alt/classify_axis.py outputs/<run>/ --from-relevance         # ④ 채점이 axis_group을 함께 고른 경우 (새 조사)

- 근거가 깊어지면(제목 → 초록 → 전문) 다시 나누고, 바뀐 배정은 이전 값을 history에 남긴다. 얕은 근거로 깊은 근거를 덮지 않는다.
- 근거가 없으면 config axis_unknown_label('초록에 없음') — 추측 배정 안 함 (사용자 결정).
- 축(topic.json axis)을 바꾸면 이전 배정은 쓰이지 않는다 (common.axis_assignments) → --prepare부터 다시.
"""

import argparse
from collections import Counter
from datetime import datetime
from pathlib import Path

from common import PACKAGE_DIR, axis_group, axis_labels, key_registry, load_config, map_axis, read_json, write_json
from prepare_synthesis import load_fulltext_notes

RUBRIC_PATH = PACKAGE_DIR / "axis_rubric.md"
BASIS_RANK = {"제목": 0, "초록": 1, "전문": 2}
NOTE_FIELDS = ("objective", "method", "data")  # 본문 정리에서 분류에 쓰는 칸 (목적·방법·자료)


def text_axis_or_exit(run_dir: Path) -> dict:
    axis = map_axis(run_dir)
    if axis["field"] != "text":
        raise SystemExit("[axis] 주제별 축 없음 — define_topic.py --axis-name ... --axis-group ...으로 먼저 정함")
    return axis


def map_pool(run_dir: Path) -> list[dict]:
    """문헌지도에 들어가는 후보 (make_figures reference_map과 같은 범위)."""
    floor = load_config()["output"]["map_min_relevance"]
    return [r for r in read_json(run_dir / "scored.json")["records"] if r["relevance"] >= floor and not r["exclude"]]


def notes_by_id(run_dir: Path) -> dict[str, dict]:
    """본문 정리(인용 키 기준) → {openalex_id: 목적·방법·자료}. references.json이 없으면(⑦ 전) 없음."""
    oid_of = {key: oid for oid, key in key_registry(run_dir).items()}  # 인용 목록에서 빠진 논문도 (10-19)
    if not oid_of:
        return {}
    return {oid_of[key]: {f: (note.get(f) or {}).get("text") for f in NOTE_FIELDS}
            for key, note in load_fulltext_notes(run_dir).items() if oid_of.get(key)}


def load_assign(run_dir: Path, axis: dict) -> dict:
    path = run_dir / "axis_assign.json"
    head = {"name": axis["name"], "labels": axis_labels(axis)}
    data = read_json(path) if path.is_file() else None
    return data if data and data["axis"] == head else {"axis": head, "assign": {}}


def prepare(run_dir: Path, batches: int, fulltext_only: bool) -> int:
    axis, notes = text_axis_or_exit(run_dir), notes_by_id(run_dir)
    assign = load_assign(run_dir, axis)["assign"]
    pool = map_pool(run_dir)
    if fulltext_only:
        pool = [r for r in pool if r["openalex_id"] in notes and (assign.get(r["openalex_id"]) or {}).get("basis") != "전문"]
    chars = load_config()["relevance"]["abstract_chars"]
    papers = [{"openalex_id": r["openalex_id"], "title": r["title"], "abstract": (r.get("abstract") or "")[:chars] or None,
               **({"fulltext": notes[r["openalex_id"]]} if r["openalex_id"] in notes else {})} for r in pool]
    head = {"axis": {"name": axis["name"], "groups": [{"name": g, "hints": w} for g, w in axis["groups"][:-1]]},
            "unknown_label": axis["groups"][-1][0], "rubric": RUBRIC_PATH.read_text(encoding="utf-8")}
    tokens = sum(len(str(p)) for p in papers) // load_config()["fulltext"]["chars_per_token"]
    # 읽을 글이 작으면 묶음 1개 — 에이전트 고정 문맥(약 12k)이 글보다 커서 나누면 더 든다 (2026-10-16: 7편 3.5k를 2묶음으로 나눔)
    count = 1 if tokens < load_config()["relevance"]["axis_batch_min_tokens"] else max(1, min(batches, len(papers)))
    files = []
    for k in range(count):
        write_json(run_dir / f"axis_input_{k + 1}.json", {**head, "output_file": f"axis_{k + 1}.json", "papers": papers[k::count]})
        files.append(f"axis_{k + 1}.json")
    write_json(run_dir / "axis_batches.json", {"outputs": files if papers else [], "prepared_at": datetime.now().isoformat(timespec="seconds")})
    print(f"[axis] {len(papers)}편 → 묶음 {count if papers else 0}개 (읽을 글 약 {tokens:,}토큰 — 추정, 에이전트 고정 문맥 별도)")
    return len(papers)


def validate(entries: list[dict], expected: set[str], labels: list[str]) -> None:
    got = [e.get("openalex_id") for e in entries]
    problems = []
    if set(got) != expected or len(got) != len(set(got)):
        problems.append(f"id 불일치 (입력 {len(expected)}, 출력 {len(got)}, 빠짐 {len(expected - set(got))})")
    bad = [e.get("openalex_id") for e in entries if e.get("axis_group") not in labels or e.get("basis") not in BASIS_RANK]
    if bad:
        problems.append(f"묶음 이름·근거가 목록에 없음 {len(bad)}편 (예: {bad[:3]})")
    if problems:
        raise SystemExit("[axis] " + " / ".join(problems))


def update(run_dir: Path, axis: dict, entries: list[dict], source: str) -> int:
    """배정 갱신 — 근거가 같거나 깊을 때만 덮고, 바뀌면 이전 값을 history에. 바뀐 편수를 돌려줌."""
    data = load_assign(run_dir, axis)
    now, changed = datetime.now().isoformat(timespec="seconds"), 0
    for e in entries:
        prev = data["assign"].get(e["openalex_id"])
        if prev and BASIS_RANK[e["basis"]] < BASIS_RANK[prev["basis"]]:
            continue
        new = {"group": e["axis_group"], "basis": e["basis"], "reason": e.get("reason", ""), "source": source, "at": now,
               "history": (prev or {}).get("history", [])}
        if prev and (prev["group"], prev["basis"]) != (new["group"], new["basis"]):
            new["history"] = new["history"] + [{k: prev[k] for k in ("group", "basis", "at")}]
            changed += prev["group"] != new["group"]
        data["assign"][e["openalex_id"]] = new
    write_json(run_dir / "axis_assign.json", data)
    return changed


def merge(run_dir: Path) -> None:
    axis = text_axis_or_exit(run_dir)
    batches = read_json(run_dir / "axis_batches.json")
    entries = []
    for name in batches["outputs"]:
        out, inp = run_dir / name, run_dir / name.replace("axis_", "axis_input_")
        if not out.is_file() or out.stat().st_mtime < inp.stat().st_mtime:
            raise SystemExit(f"[axis] {name} 없음 또는 입력보다 오래됨 — 에이전트 분류부터")
        part = read_json(out)
        validate(part, {p["openalex_id"] for p in read_json(inp)["papers"]}, axis_labels(axis))
        entries += part
    changed = update(run_dir, axis, entries, "분류")
    report(run_dir, f"{len(entries)}편 반영, 묶음이 바뀐 논문 {changed}편")


def from_relevance(run_dir: Path) -> None:
    """④ 채점 결과의 axis_group (축을 주제 확정 때 정한 새 조사). 초록이 없으면 근거 '제목'."""
    axis = text_axis_or_exit(run_dir)
    pool_ids = {r["openalex_id"] for r in map_pool(run_dir)}
    entries = [{"openalex_id": e["openalex_id"], "axis_group": e.get("axis_group"), "reason": e.get("axis_reason", ""),
                "basis": "제목" if e.get("low_confidence") else "초록"}
               for path in sorted(run_dir.glob("relevance_[0-9]*.json")) for e in read_json(path) if e["openalex_id"] in pool_ids]
    if not any(e["axis_group"] for e in entries):
        raise SystemExit("[axis] 채점 결과에 axis_group 없음 — --prepare로 따로 분류")
    validate(entries, pool_ids, axis_labels(axis))
    update(run_dir, axis, entries, "관련성 채점")
    report(run_dir, f"{len(entries)}편 반영")


def report(run_dir: Path, head: str) -> None:
    axis, pool = map_axis(run_dir), map_pool(run_dir)
    counts = Counter(axis_group(r, axis) for r in pool)
    missing = sum(r["openalex_id"] not in axis["assign"] for r in pool)
    print(f"[axis] {head} → '{axis['name']}': " + " · ".join(f"{g} {counts[g]}" for g in axis_labels(axis))
          + (f" (AI 배정 없는 {missing}편은 낱말 미리보기)" if missing else ""))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", type=Path)
    step = parser.add_mutually_exclusive_group(required=True)
    step.add_argument("--prepare", action="store_true")
    step.add_argument("--merge", action="store_true")
    step.add_argument("--from-relevance", action="store_true")
    parser.add_argument("--batches", type=int, default=2)
    parser.add_argument("--fulltext", action="store_true", help="--prepare: 본문 정리가 생긴 논문만 다시 분류")
    args = parser.parse_args()
    if args.prepare:
        prepare(args.run_dir, args.batches, args.fulltext)
    elif args.merge:
        merge(args.run_dir)
    else:
        from_relevance(args.run_dir)


if __name__ == "__main__":
    main()
