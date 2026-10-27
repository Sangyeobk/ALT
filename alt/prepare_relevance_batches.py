"""관련성 채점용 입력 묶음 만들기 → relevance_input_<k>.json (Claude가 묶음별로 채점)

    python alt/prepare_relevance_batches.py outputs/<run>/candidates.json [--topic "..." --approach "..."]
        # 묶음 크기는 config relevance.batch_max_kb 이하 — 에이전트가 한 번에 읽음 (확정 주제 topic.json이 있으면 그것을 씀)
    python alt/prepare_relevance_batches.py outputs/<run>/candidates.json --only-unscored
        # 아직 채점 안 된 후보만 (④-2 공통 인용 보강 뒤) — 묶음 번호는 기존 다음부터라 덮어쓰지 않음
    python alt/prepare_relevance_batches.py outputs/<run>/candidates.json --check
        # 채점이 끝난 묶음 검사 (출력 파일·편수·id·칸) — 에이전트 자가 확인 대신 (토큰 절감 2026-10-27)
    --batches N 을 주면 크기 대신 묶음 개수로 나눔 (예전 방식)

채점 결과는 같은 폴더의 relevance_<k>.json 에
[{"openalex_id", "relevance", "reason", "low_confidence", "approach", "structure_type"}, ...] 로 쓴다.

토큰 절감 (사용자 승인 2026-10-27): 10-16 실측으로 채점 처리량의 91%가 '캐시 읽기' — 묶음(약 240 KB)을 여러 번 나눠 읽느라
호출마다 쌓인 문맥 전체가 다시 들어간 것으로 봄(추정). 그래서 한 번의 Read로 읽히는 크기 안에서 크게 묶고(묶음이 많으면 에이전트
기본 문맥이 묶음 수만큼 듦 — 10-27 실측 60 KB×4묶음이 한 묶음보다 45% 많음), 논문은 한 줄에 하나(들여쓰기 없음)로 쓴다.
"""

import argparse
import json
from pathlib import Path

from common import PACKAGE_DIR, load_config, map_axis, read_json, topic_context, write_json
from score_papers import relevance_format_errors


def paper_rows(records: list[dict], abstract_chars: int) -> list[dict]:
    return [{
        "openalex_id": r["openalex_id"],
        "title": r["title"],
        "year": r["year"],
        "venue": r["venue"],
        "abstract": (r["abstract"] or "")[:abstract_chars] or None,
    } for r in records]


def make_batches(records: list[dict], batch_count: int, abstract_chars: int) -> list[list[dict]]:
    papers = paper_rows(records, abstract_chars)
    return [papers[k::batch_count] for k in range(batch_count)]


def size_batches(papers: list[dict], max_bytes: int, overhead: int) -> list[list[dict]]:
    """앞에서부터 차례로 담되 묶음 파일이 max_bytes를 넘지 않게 (overhead = 기준·주제 등 묶음마다 들어가는 글)."""
    batches, current, size = [], [], overhead
    for p in papers:
        n = len(json.dumps(p, ensure_ascii=False).encode("utf-8")) + 2
        if current and size + n > max_bytes:
            batches.append(current)
            current, size = [], overhead
        current.append(p)
        size += n
    return batches + ([current] if current else [])


def write_compact(path: Path, head: dict, papers: list[dict]) -> None:
    """머리(주제·기준)는 들여쓰기, 논문은 한 줄에 하나 — 한 번의 Read로 읽히게 (줄 수·크기 최소)."""
    body = json.dumps(head, ensure_ascii=False, indent=1)[:-2]
    lines = ",\n".join(json.dumps(p, ensure_ascii=False) for p in papers)
    path.write_text(f'{body},\n "papers": [\n{lines}\n ]\n}}\n', encoding="utf-8")


def check_batches(run_dir: Path) -> list[str]:
    """묶음마다: 출력 파일이 있는지, 편수·id가 입력과 같은지, 칸 형식(score_papers와 같은 검사)."""
    errors = []
    for inp in sorted(run_dir.glob("relevance_input_[0-9]*.json")):
        data = read_json(inp)
        out = run_dir / data["output_file"]
        if not out.is_file():
            errors.append(f"{out.name}: 없음 (묶음 {inp.name} 채점 안 됨)")
            continue
        errors += relevance_format_errors([out])
        want = {p["openalex_id"] for p in data["papers"]}
        got = [r.get("openalex_id") for r in read_json(out) if isinstance(r, dict)]
        if set(got) != want or len(got) != len(want):
            errors.append(f"{out.name}: 편수·id 불일치 — 입력 {len(want)}편, 출력 {len(got)}편 (빠짐 {len(want - set(got))}, 모르는 id {len(set(got) - want)})")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("candidates", type=Path)
    parser.add_argument("--topic", help="확정 주제(topic.json)가 없을 때만")
    parser.add_argument("--approach", help="확정 주제(topic.json)가 없을 때만")
    parser.add_argument("--batches", type=int, help="묶음 개수로 나눔 (없으면 config relevance.batch_max_kb 크기로)")
    parser.add_argument("--only-unscored", action="store_true", help="relevance_*.json에 없는 후보만 (공통 인용 보강 뒤)")
    parser.add_argument("--check", action="store_true", help="채점이 끝난 묶음 검사")
    args = parser.parse_args()
    if args.check:
        errors = check_batches(args.candidates.parent)
        for e in errors:
            print(" -", e)
        print(f"[batch] 채점 묶음 검사 — " + ("통과" if not errors else f"오류 {len(errors)}건 (해당 묶음만 다시 채점)"))
        raise SystemExit(1 if errors else 0)

    # 확정 주제가 있으면 그 영문명과 포함·제외 범위로 채점 (SKILL '0-1 주제 구체화', 사용자 지시 2026-10-16)
    context = topic_context(args.candidates.parent, args.topic, args.approach)
    if not context["topic"] or not context["approach"]:
        raise SystemExit("[batch] 주제·접근법 없음 — define_topic.py로 확정하거나 --topic/--approach를 줌")
    config = load_config()["relevance"]
    records = read_json(args.candidates)["records"]
    rubric = (PACKAGE_DIR / "relevance_rubric.md").read_text(encoding="utf-8")
    axis = map_axis(args.candidates.parent)  # 주제 확정 때 정한 문헌지도 가로축이 있으면 채점 때 함께 고름 (사용자 결정 2026-10-16)
    if axis["field"] == "text":
        context["axis"] = {"name": axis["name"], "groups": [{"name": g, "hints": w} for g, w in axis["groups"][:-1]],
                           "unknown_label": axis["groups"][-1][0]}
    first = 1
    if args.only_unscored:
        run_dir = args.candidates.parent
        scored = {r["openalex_id"] for p in run_dir.glob("relevance_[0-9]*.json") for r in read_json(p)}
        records = [r for r in records if r["openalex_id"] not in scored]
        first = 1 + max((int(p.stem.rsplit("_", 1)[1]) for p in run_dir.glob("relevance_input_[0-9]*.json")), default=0)
        if not records:
            print("[batch] 채점 안 된 후보 없음")
            return
    head = {**context, "rubric": rubric, "output_file": "relevance_000.json"}
    if args.batches:
        batches = make_batches(records, min(args.batches, len(records)), config["abstract_chars"])
    else:
        overhead = len(json.dumps(head, ensure_ascii=False, indent=1).encode("utf-8"))
        batches = size_batches(paper_rows(records, config["abstract_chars"]), int(config["batch_max_kb"] * 1024), overhead)
    for k, papers in enumerate(batches, first):
        out = args.candidates.with_name(f"relevance_input_{k}.json")
        write_compact(out, {**head, "output_file": f"relevance_{k}.json"}, papers)
        print(f"[batch {k}] {len(papers)}편 ({out.stat().st_size // 1024} KB) -> {out}")
    print(f"[batch] 묶음 {len(batches)}개 — 에이전트는 묶음마다 1개, 동시에 최대 {config['parallel_agents']}개")


if __name__ == "__main__":
    main()
