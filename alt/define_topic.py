"""주제 구체화 기록: 사용자가 확정한 주제·접근법·범위를 결과 폴더의 topic.json에 남긴다 (SKILL '0-1 주제 구체화').

    python alt/define_topic.py outputs/<run>/ --input "입력 원문" --topic-ko ... --topic-en ... \
        --approach-ko ... --approach-en ... --years 2025-2027 --include ... --exclude ... --question ... [--note ...]
    python alt/define_topic.py outputs/<run>/ --show
    python alt/define_topic.py outputs/<run>/ --axis-name "자료 종류" --axis-group "noon report: noon report"         --axis-group "AIS: ais, automatic identification" [--dry-run]   # 문헌지도 가로축만 정하거나 바꿈

- 입력은 애매할 수 있으므로(예: platform / structure) 시작 때 확정안을 사용자에게 확인받고 기록한다 (사용자 지시 2026-10-16).
- 이후 단계는 이 기록만 쓴다: 검색어(topic_en + 포함 범위), 관련성 채점 입력, 요약의 names, 결과물 제목·목적 장 첫 줄.
- 입력 원문은 바꾸지 않고 그대로 남긴다 (부록 '입력 원문 → 확정 주제').
- 범위가 정해진 과정 (사용자 피드백 2026-10-16: 기록이 없으면 제목과 입력·연구 문제가 달라 보임) — 결과물 목적 장 맨 앞에 나옴:
    --scope-reason "…"   입력과 확정 범위가 다를 때 이유 한 줄 (0-1에서 넓히거나 좁힌 안을 고른 경우)
    --split "분야: 이유"  세부 조사로 따로 떼어 낸 분야 (⑥ 중간 확인·⑧-1 세분화에서 사용자가 고른 경우, 여러 번·나중에 더할 수 있음)
    --split-run <폴더>   그 세부 조사의 결과 폴더 (같이 준 --split에, 없으면 마지막 split_out에 붙음 — 나중에 폴더가 생겼을 때)
    --parent <폴더>      이 조사가 세부 조사일 때 상위 조사 결과 폴더 (parent_run) — 목적 장 '상위 조사' 줄, fetch_open_access가 그 폴더의 PDF를 재사용
  주제 칸 없이 이 옵션만 주면 기존 topic.json에 더한다.
- 모호한 점 질의응답·검색어 (사용자 결정 2026-10-21 — 모호하면 묻고, 예상 검색어를 보여 주고 확정):
    --clarify "질문 => 답"   (여러 번) 부록 '입력 원문 → 확정 주제'에 '해석 확인'으로 나옴
    --query "..."            (여러 번) 확인받은 영어 검색어 — ② search_papers.py에 그대로 넣음
- 문헌지도·분포 행렬 가로축(`axis`, 사용자 결정 2026-10-16): 주제마다 묶음 이름과 낱말을 정하면 논문 제목·초록에서 낱말로 나눈다
  (common.map_axis). 정하지 않으면 config 구조물 묶음. `--dry-run`·`--show`는 scored.json이 있으면 묶음별 편수를 보여 준다.
"""

import argparse
from collections import Counter
from datetime import datetime
from pathlib import Path

from common import axis_group, load_config, map_axis, read_json, text_axis, write_json

FIELDS = {  # topic.json 칸 → 설명 (모두 필수, note만 선택)
    "input": "입력 원문 그대로", "topic_ko": "확정 주제 (국문)", "topic_en": "확정 주제 (영문, 검색·채점에 씀)",
    "approach_ko": "접근법 (국문)", "approach_en": "접근법 (영문)", "years": "기간 (예: 2025-2027)",
    "include": "포함 범위", "exclude": "제외 범위", "question": "조사 질문 한 줄",
}


def topic_record(values: dict, note: str = "") -> dict:
    """빈 칸이 있으면 실패 (확정 이름이 결과물에 그대로 쓰이므로)."""
    missing = [k for k in FIELDS if not (values.get(k) or "").strip()]
    if missing:
        raise SystemExit(f"[topic] 빈 칸: {', '.join(missing)}")
    record = {k: values[k].strip() for k in FIELDS}
    record["confirmed_at"] = datetime.now().isoformat(timespec="seconds")
    if note:
        record["note"] = note
    return record


def add_clarifications(record: dict, clarify: list[str], queries: list[str]) -> dict:
    """주제를 확정하며 물은 모호한 점과 답(사용자 결정 2026-10-21 — 부록에 나옴), 확인받은 검색어(① 그대로 씀)."""
    pairs = []
    for text in clarify:
        q, sep, a = text.partition("=>")
        if not sep or not q.strip() or not a.strip():
            raise SystemExit(f"[topic] --clarify 형식은 '질문 => 답' — 받은 값: {text!r}")
        pairs.append({"q": q.strip(), "a": a.strip()})
    if pairs:
        record["clarifications"] = pairs
    if queries:
        record["queries"] = [q.strip() for q in queries if q.strip()]
    return record


def add_scope_history(record: dict, reason: str, splits: list[str], split_run: str = "", parent: str = "") -> dict:
    """범위를 바꾼 이유·따로 떼어 낸 세부 조사(결과 폴더)·상위 조사를 기록에 더한다 (같은 분야는 새 이유로 바꿈)."""
    if reason.strip():
        record["scope_reason"] = reason.strip()
    if parent.strip():
        record["parent_run"] = parent.strip().replace("\\", "/").rstrip("/")
    today = datetime.now().date().isoformat()
    for text in splits:
        field, _, why = text.partition(":")
        if not field.strip() or not why.strip():
            raise SystemExit(f"[topic] --split 형식은 '분야: 이유' — 받은 값: {text!r}")
        rest = [x for x in record.get("split_out", []) if x["field"] != field.strip()]
        record["split_out"] = rest + [{"field": field.strip(), "reason": why.strip(), "date": today,
                                       **({"run": split_run.strip()} if split_run.strip() else {})}]
    if split_run.strip() and not splits:  # 나중에 결과 폴더가 생겼을 때 마지막 세부 조사에 붙임
        if not record.get("split_out"):
            raise SystemExit("[topic] --split-run은 --split 기록이 있어야 붙일 수 있음")
        record["split_out"][-1]["run"] = split_run.strip()
    return record


def parse_axis(name: str, groups: list[str]) -> dict:
    """'묶음 이름: 낱말1, 낱말2' 목록 → topic.json axis. 낱말은 제목·초록에서 낱말 첫머리로 맞춤 (대소문자 무시)."""
    parsed = []
    for text in groups:
        label, _, words = text.partition(":")
        words = [w.strip().lower() for w in words.split(",") if w.strip()]
        if not label.strip() or not words:
            raise SystemExit(f"[topic] 축 묶음 형식은 '이름: 낱말1, 낱말2' — 받은 값: {text!r}")
        parsed.append([label.strip(), words])
    if not name.strip() or len(parsed) < 2:
        raise SystemExit("[topic] 축 이름과 묶음 2개 이상 필요")
    return {"name": name.strip(), "groups": parsed}


def axis_counts(run_dir: Path, axis: dict) -> str:
    """문헌지도에 들어갈 후보(관련성 map_min_relevance점 이상)의 묶음별 편수 — 축을 고르기 전에 쏠림 확인."""
    path = run_dir / "scored.json"
    if not path.is_file():
        return "[topic] scored.json 없음 — 묶음별 편수는 ⑤ 점수화 뒤에 볼 수 있음"
    floor = load_config()["output"]["map_min_relevance"]
    pool = [r for r in read_json(path)["records"] if r["relevance"] >= floor and not r["exclude"]]
    counts = Counter(axis_group(r, axis) for r in pool)
    kind = "AI 분류" if axis.get("assign") else ("낱말 미리보기 — 실제 분류는 classify_axis.py" if axis["field"] == "text" else "채점 structure_type")
    return (f"[topic] 가로축 '{axis['name']}' ({kind}) — 관련성 {floor}점 이상 후보 {len(pool)}편: "
            + " · ".join(f"{g[0]} {counts[g[0]]}" for g in axis["groups"]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--show", action="store_true", help="기록된 확정 주제 보기")
    for key, help_text in FIELDS.items():
        parser.add_argument("--" + key.replace("_", "-"), dest=key, help=help_text)
    parser.add_argument("--note", default="", help="선택 — 예: 사후 기록")
    parser.add_argument("--axis-name", default="", help="문헌지도 가로축 이름 (예: 자료 종류)")
    parser.add_argument("--axis-group", action="append", default=[], help="'묶음 이름: 낱말1, 낱말2' (여러 번)")
    parser.add_argument("--dry-run", action="store_true", help="축 묶음별 편수만 보고 저장하지 않음")
    parser.add_argument("--scope-reason", default="", help="입력과 확정 범위가 다를 때 그 이유 한 줄")
    parser.add_argument("--split", action="append", default=[], help="'분야: 이유' — 세부 조사로 따로 떼어 낸 분야 (여러 번)")
    parser.add_argument("--split-run", default="", help="세부 조사의 결과 폴더 (예: outputs/20261016_ship_fuel_consumption__pinn_hybrid)")
    parser.add_argument("--parent", default="", help="세부 조사일 때 상위 조사 결과 폴더 (예: outputs/20261016_ship_fuel_consumption)")
    parser.add_argument("--clarify", action="append", default=[], help="'질문 => 답' — 주제 확정 때 물은 모호한 점 (여러 번)")
    parser.add_argument("--query", action="append", default=[], help="사용자가 확인한 영어 검색어 (여러 번) — ② 검색에 그대로 씀")
    args = parser.parse_args()
    history_args = (args.scope_reason, args.split, args.split_run, args.parent)
    parent_name = Path(args.parent.strip().replace("\\", "/").rstrip("/")).name
    if parent_name and not args.run_dir.resolve().name.startswith(parent_name + "__"):  # 사용자 결정 2026-10-19
        print(f"[topic] 주의: 세부 조사 폴더 이름은 '{parent_name}__<분야요약>'으로 — 이름만 보고 상위·하위 관계를 알 수 있게")

    path = args.run_dir / "topic.json"
    if args.show:
        print(read_json(path) if path.is_file() else "[topic] 확정 주제 없음 (topic.json)")
        print(axis_counts(args.run_dir, map_axis(args.run_dir)))
        return
    axis = parse_axis(args.axis_name, args.axis_group) if args.axis_name or args.axis_group else None
    only_axis = axis and not any(vars(args).get(k) for k in FIELDS)
    if axis and (args.dry_run or only_axis):
        print(axis_counts(args.run_dir, text_axis(axis)))
        if args.dry_run:
            return
        if not path.is_file():
            raise SystemExit("[topic] topic.json 없음 — 주제를 먼저 확정")
        record = read_json(path)
        record["axis"] = {**axis, "confirmed_at": datetime.now().isoformat(timespec="seconds")}
        write_json(path, record)
        print(f"[topic] 가로축 '{axis['name']}' 저장 -> {path}")
        return
    if any(history_args) and not any(vars(args).get(k) for k in FIELDS):  # 기존 기록에 더하기
        if not path.is_file():
            raise SystemExit("[topic] topic.json 없음 — 주제를 먼저 확정")
        record = add_scope_history(read_json(path), *history_args)
        write_json(path, record)
        print(f"[topic] 범위 결정 과정 기록 -> {path}")
        return
    record = add_scope_history(topic_record(vars(args), args.note), *history_args)
    record = add_clarifications(record, args.clarify, args.query)
    if axis:
        record["axis"] = {**axis, "confirmed_at": record["confirmed_at"]}
    args.run_dir.mkdir(parents=True, exist_ok=True)
    write_json(path, record)
    print(f"[topic] {record['topic_ko']} ({record['topic_en']}) · {record['approach_ko']} · {record['years']} -> {path}")


if __name__ == "__main__":
    main()
