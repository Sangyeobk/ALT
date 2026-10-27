"""AI가 만든 한국어 조어를 영어 원어로 되돌리기 (사용자 결정 2026-10-27 — '흑상자(black-box)'처럼 이해를 막는 말). AI 토큰 없이 코드로.

    python alt/swap_terms.py outputs/<run>/ --map outputs/_development/term_swap_20261027.yaml            # 미리보기 (바뀔 곳 수)
    python alt/swap_terms.py outputs/<run>/ --map outputs/_development/term_swap_20261027.yaml --apply    # 원본을 _backup_terms_<날짜>/에 두고 바꿈

바꾸기 표 (사용자가 확인한 것만):
    - from: [흑상자, 블랙박스]      # 지금 쓰는 말 (긴 말부터 바꿈)
      to: black-box                 # 대표 용어가 됨 — 옛 말은 쓰지 말 변이형으로 (check_terms가 다시 나오면 잡음)
      explain: 물리식 없이 자료만으로 학습한 모델   # 선택 — abbreviations에 넣어 산출물마다 첫 등장에 '(설명)'이 붙음

바꾸는 파일: synthesis.json(본문 전체·terms·abbreviations), slides.json, slides_learn.json. 그 뒤 산출물은 다시 만들어야 함.
"""

from __future__ import annotations

import argparse
import shutil
from datetime import date
from pathlib import Path

import yaml

from common import read_json, write_json

FILES = ["synthesis.json", "slides.json", "slides_learn.json"]


def load_map(path: Path) -> list[dict]:
    rows = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    for row in rows:
        if not row.get("to") or not row.get("from"):
            raise SystemExit(f"[swap] 'from'·'to'가 모두 있어야 함: {row}")
        row["from"] = [f for f in row["from"] if f and f != row["to"]]
        # '조어(원어)'·'원어(조어)'는 원어 하나로 — 그냥 바꾸면 'PGNN(PGNN)'이 됨 (긴 말부터 바꾸므로 먼저 맞음)
        row["pairs"] = [(f"{a}{sp}({b})", row["to"]) for f in row["from"] for a, b in ((f, row["to"]), (row["to"], f)) for sp in ("", " ")]
        row["pairs"] += [(f, row["to"]) for f in row["from"]]
    return rows


def all_pairs(rows: list[dict]) -> list[tuple[str, str]]:
    return sorted((p for row in rows for p in row["pairs"]), key=lambda p: -len(p[0]))


def replace_text(text: str, pairs: list[tuple[str, str]], counts: dict) -> str:
    for old, new in pairs:
        n = text.count(old)
        if n:
            counts[old] = counts.get(old, 0) + n
            text = text.replace(old, new)
    return text


def walk(value, pairs, counts):
    """JSON 안의 모든 글자 값을 바꿈 (키 이름은 그대로)."""
    if isinstance(value, str):
        return replace_text(value, pairs, counts)
    if isinstance(value, list):
        return [walk(v, pairs, counts) for v in value]
    if isinstance(value, dict):
        return {k: walk(v, pairs, counts) for k, v in value.items()}
    return value


def swap_terms_field(terms: list[dict], rows: list[dict]) -> list[dict]:
    """대표 용어를 원어로, 옛 대표 용어·조어는 변이형으로. 원어 자체는 변이형에서 뺌 (대소문자 무시)."""
    out = [dict(t, variants=list(t.get("variants", []))) for t in terms]
    for row in rows:
        olds, new = set(row["from"]), row["to"]
        hit = [t for t in out if t["term"] in olds or t["term"] == new]
        entry = hit[0] if hit else {"term": new, "variants": []}
        merged = [entry["term"], *entry["variants"], *(v for t in hit[1:] for v in [t["term"], *t["variants"]]), *row["from"]]
        entry["term"] = new
        entry["variants"] = list(dict.fromkeys(v for v in merged if v.lower() != new.lower()))
        out = [t for t in out if t not in hit] + [entry]
    return out


def swap_synthesis(s: dict, rows: list[dict], counts: dict) -> dict:
    pairs = all_pairs(rows)
    terms = swap_terms_field(s.get("terms", []), rows)
    out = walk({k: v for k, v in s.items() if k != "terms"}, pairs, counts)
    out["terms"] = terms
    abbreviations = dict(out.get("abbreviations") or {})
    for row in rows:
        if row.get("explain") and row["to"] not in abbreviations:
            abbreviations[row["to"]] = row["explain"]
    if abbreviations:
        out["abbreviations"] = abbreviations
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--map", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    rows = load_map(args.map)
    pairs = all_pairs(rows)
    backup = args.run_dir / f"_backup_terms_{date.today():%Y%m%d}"
    for name in FILES:
        path = args.run_dir / name
        if not path.is_file():
            continue
        counts: dict = {}
        data = read_json(path)
        new = swap_synthesis(data, rows, counts) if name == "synthesis.json" else walk(data, pairs, counts)
        print(f"[swap] {name}: " + (", ".join(f"{k}→{dict(pairs)[k]} {n}곳" for k, n in sorted(counts.items(), key=lambda kv: -kv[1])) or "바뀔 곳 없음"))
        if args.apply and new != data:
            backup.mkdir(exist_ok=True)
            if not (backup / name).exists():  # 같은 날 두 번 돌려도 처음 원본을 지킴
                shutil.copy2(path, backup / name)
            write_json(path, new)
    if args.apply:
        print(f"[swap] 바꿈 (원본: {backup}) — 산출물을 다시 만들 것")


if __name__ == "__main__":
    main()
