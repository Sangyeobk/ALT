"""사용량 장부: 하위 에이전트·Codex 호출의 토큰을 종류별로 결과 폴더에 쌓고 표로 보여 준다.

    python alt/usage_log.py add outputs/<run>/ --step 본문정리 --agent-id <id> [--estimate 31000]
    python alt/usage_log.py add-session outputs/<run>/ --step 주세션 --session-id <세션 id>
    python alt/usage_log.py show outputs/<run>/
    python alt/usage_log.py calibrate outputs/<run>/ --step 관련성 --before 17 --after 21
    python alt/usage_log.py budget --used-5h 17 --papers 520 [--fulltext 8]

- 하위 에이전트: Claude Code 기록 파일(~/.claude/projects/<작업폴더>/<세션>/subagents/agent-<id>.jsonl)에
  API 호출마다 남는 usage를 읽는다. 같은 호출이 여러 줄로 기록되므로 message.id로 중복을 뺀다.
- Codex: cross_verify.run_verifier가 `codex exec --json`의 turn.completed usage를 같은 형식으로 남긴다.
- 기록은 <run>/usage/<단계>_<id>.json 파일 하나씩 → 동시에 도는 에이전트가 서로 덮어쓰지 않음.
- 주 세션: 같은 기록 방식의 ~/.claude/projects/<작업폴더>/<세션 id>.jsonl (가장 큰 사용처 — 긴 문맥을 호출마다 다시 읽음).
- 금액으로 환산하지 않는다. 5시간 한도 %는 실측 보정으로만 추정 (사용자 결정 2026-10-16): 단계 전후 사용률(앱 get_usage)과
  그 단계의 장부 처리량을 calibrate로 쌓고, 그 비율(합계 % ÷ 합계 토큰)로 budget이 단계별 예상 %를 낸다.
  캐시 읽기를 한도에서 어떻게 세는지는 모르므로 비율에 그대로 녹인다. 단계 중 주 세션 사용도 사용률 변화에 들어간다.
- 출력 토큰은 기록 파일 값 — 실제보다 작게 남는 경우가 있어 참고만 (2026-10-16 확인: 130편 채점 호출들의 합계 276).
  Agent 결과의 subagent_tokens는 누적이 아니라 마지막 호출의 문맥 크기로 보임 (빈 호출 2건 — 가설) → 사용량은 이 장부 값으로 보고.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from common import load_config, read_json, write_json

FIELDS = ("calls", "input", "cache_write", "cache_read", "output")
TRANSCRIPTS = Path.home() / ".claude" / "projects"


def claude_usage(transcript: Path) -> dict:
    """하위 에이전트 기록 파일 → 모델·호출 수·종류별 토큰 합계."""
    seen, total, model = set(), dict.fromkeys(FIELDS, 0), None
    for line in transcript.read_text(encoding="utf-8").splitlines():
        message = json.loads(line).get("message") or {}
        usage = message.get("usage")
        if not usage or message.get("id") in seen:
            continue
        seen.add(message.get("id"))
        model = message.get("model") or model
        total["calls"] += 1
        total["input"] += usage.get("input_tokens", 0)
        total["cache_write"] += usage.get("cache_creation_input_tokens", 0)
        total["cache_read"] += usage.get("cache_read_input_tokens", 0)
        total["output"] += usage.get("output_tokens", 0)
    return {"source": "claude", "model": model, **total}


def codex_usage(events: str) -> dict | None:
    """`codex exec --json` 출력(줄마다 JSON) → 같은 형식. Codex의 input_tokens는 캐시를 포함하므로 캐시만큼 뺀다."""
    turns = []
    for line in events.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "turn.completed" and "usage" in event:
            turns.append(event["usage"])
    if not turns:
        return None
    total = dict.fromkeys(FIELDS, 0)
    for u in turns:
        cached = u.get("cached_input_tokens", 0)
        total["calls"] += 1  # ponytail: Codex는 턴 단위만 알려 줌 — 턴 안의 API 호출 수는 모름
        total["input"] += u.get("input_tokens", 0) - cached
        total["cache_read"] += cached
        total["cache_write"] += u.get("cache_write_input_tokens", 0)
        total["output"] += u.get("output_tokens", 0)
    return {"source": "codex", "model": None, **total}


def find_transcript(agent_id: str) -> Path:
    hits = sorted(TRANSCRIPTS.glob(f"*/*/subagents/agent-{agent_id}.jsonl"))
    if not hits:
        raise SystemExit(f"[usage] 기록 파일 없음: agent-{agent_id}.jsonl ({TRANSCRIPTS} 아래)")
    return hits[0]


def find_session(session_id: str) -> Path:
    hits = sorted(TRANSCRIPTS.glob(f"*/{session_id}.jsonl"))
    if not hits:
        raise SystemExit(f"[usage] 주 세션 기록 파일 없음: {session_id}.jsonl ({TRANSCRIPTS} 아래)")
    return hits[0]


def save(run_dir: Path, step: str, name: str, usage: dict, estimate: int | None = None) -> Path:
    path = Path(run_dir) / "usage" / f"{step}_{name}.json"
    write_json(path, {"step": step, "id": name, **usage, "estimate": estimate,
                      "recorded_at": datetime.now().isoformat(timespec="seconds")})
    return path


def summary(run_dir: Path) -> list[dict]:
    """단계별 합계 (기록 순서 유지). total = 입력 + 캐시 쓰기 + 캐시 읽기 + 출력 (누적 처리량)."""
    rows: dict[str, dict] = {}
    for path in sorted((Path(run_dir) / "usage").glob("*.json"), key=lambda p: p.stat().st_mtime):
        record = read_json(path)
        row = rows.setdefault(record["step"], {"step": record["step"], "runs": 0, "estimate": 0, **dict.fromkeys(FIELDS, 0)})
        row["runs"] += 1
        row["estimate"] += record.get("estimate") or 0
        for field in FIELDS:
            row[field] += record.get(field, 0)
    for row in rows.values():
        row["total"] = sum(row[f] for f in FIELDS if f != "calls")
    return list(rows.values())


def calibration_path() -> Path:
    return Path(os.path.expanduser(load_config()["usage"]["calibration_path"]))


def add_calibration(path: Path, run: str, step: str, before: float, after: float, tokens: int, model: str | None = None) -> dict:
    record = {"date": datetime.now().isoformat(timespec="seconds"), "run": run, "step": step,
              "before": before, "after": after, "tokens": tokens, "model": model}
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def step_model(run_dir: Path, step: str) -> str | None:
    """장부에서 그 단계를 돌린 모델 이름 (하위 에이전트 기록) — 보정 비율은 모델마다 다르므로 함께 남긴다."""
    models = [read_json(p).get("model") for p in sorted((Path(run_dir) / "usage").glob(f"{step}_*.json"))]
    return next((m for m in reversed(models) if m), None)


def pct_per_token(path: Path, model: str | None = None) -> float | None:
    """보정 비율 = 사용률 변화 합계 ÷ 처리량 합계. 기록이 없거나 변화가 1% 미만이면 None (사용률이 정수라 작은 단계는 0으로 보임).
    모델마다 한도 소모가 다르므로(2026-10-16: 같은 처리량에 Fable이 Opus 기록의 약 3배) 같은 모델 기록만 쓴다 —
    model이 없으면 가장 최근 기록의 모델. 모델 이름이 없는 옛 기록은 모델을 모를 때만 쓴다."""
    if not path.is_file():
        return None
    records = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    records = [r for r in records if r["tokens"] > 0 and r["after"] >= r["before"]]  # 한도 초기화를 건넌 기록은 뺌
    model = model or next((r.get("model") for r in reversed(records) if r.get("model")), None)
    if model:
        records = [r for r in records if r.get("model") == model]
    delta = sum(r["after"] - r["before"] for r in records)
    return delta / sum(r["tokens"] for r in records) if delta >= 1 else None


def budget(units: dict[str, int], reference: dict, ratio: float | None) -> list[dict]:
    """단계별 예상: 기준값(단위당 처리량) × 단위 수 → 토큰, × 보정 비율 → 5시간 한도 %. 단위가 0인 단계는 뺌."""
    rows = []
    for step, ref in reference.items():
        count = units.get(ref["per"], 0)
        if not count:
            continue
        tokens = ref["tokens"] * count if ref["tokens"] is not None else None
        pct = tokens * ratio if tokens is not None and ratio is not None else None
        rows.append({"step": step, "count": count, "per": ref["per"], "tokens": tokens, "pct": pct})
    return rows


def print_budget(rows: list[dict], used: float, ratio: float | None) -> None:
    print("| 단계 | 단위 수 | 추정 처리량 | 5시간 한도 대비 |")
    print("|---|---|---|---|")
    for r in rows:
        tokens = f"{r['tokens']:,}" if r["tokens"] is not None else "실측 없음"
        pct = f"약 {r['pct']:.1f}%" if r["pct"] is not None else "-"
        print(f"| {r['step']} | {r['count']} ({r['per']}) | {tokens} | {pct} |")
    known = [r for r in rows if r["pct"] is not None]
    if ratio is None:
        print("\n% 환산 불가 — 보정 기록 없음 (큰 단계 전후 사용률로 calibrate를 남기면 다음부터 표시). 처리량만 참고")
    elif known:
        total = sum(r["pct"] for r in known)
        print(f"\n합계 약 {total:.1f}% — 지금 {used:g}% 사용 → 실행 뒤 약 {used + total:.0f}% (추정, 주 세션 포함 실측 보정)")
        if used + total > 100:
            print("주의: 5시간 한도를 넘음 — 범위를 줄이거나 한도 초기화 뒤 나눠 실행")
    if any(r["tokens"] is None for r in rows):
        print("'실측 없음' 단계는 합계에 빠짐 — 실행 뒤 장부(show)로 기준값을 채움")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add", help="하위 에이전트 1개의 사용량을 기록")
    add.add_argument("run_dir", type=Path)
    add.add_argument("--step", required=True, help="단계 이름 (예: 관련성, 본문정리, 요약, 부분수정)")
    add.add_argument("--agent-id", required=True, help="Agent 결과에 나온 agentId")
    add.add_argument("--estimate", type=int, help="시작 전 글 분량 추정 토큰 (있으면 나란히 보고)")
    session = sub.add_parser("add-session", help="주 세션의 사용량을 기록 (세션 전체 누적)")
    session.add_argument("run_dir", type=Path)
    session.add_argument("--step", required=True)
    session.add_argument("--session-id", required=True, help="주 세션 id (기록 파일 이름)")
    show = sub.add_parser("show", help="단계별 합계 표")
    show.add_argument("run_dir", type=Path)
    calib = sub.add_parser("calibrate", help="단계 전후 5시간 사용률을 기록 (보정 비율)")
    calib.add_argument("run_dir", type=Path)
    calib.add_argument("--step", required=True)
    calib.add_argument("--before", type=float, required=True, help="단계 전 5시간 사용률 %%")
    calib.add_argument("--after", type=float, required=True, help="단계 뒤 5시간 사용률 %%")
    calib.add_argument("--tokens", type=int, help="처리량 (없으면 장부의 그 단계 합계)")
    plan = sub.add_parser("budget", help="단계별 예상 처리량과 5시간 한도 대비 %%")
    plan.add_argument("--used-5h", type=float, required=True, help="지금 5시간 사용률 %% (앱 get_usage)")
    plan.add_argument("--papers", type=int, default=0, help="관련성 채점할 후보 수")
    plan.add_argument("--fulltext", type=int, default=0, help="본문 정리할 논문 수")
    plan.add_argument("--no-run-steps", action="store_true", help="결과 1벌 단위 단계(요약 등) 빼기")
    plan.add_argument("--model", help="보정 비율을 낼 모델 이름 (없으면 가장 최근 보정 기록의 모델)")
    args = parser.parse_args()

    if args.command == "calibrate":
        tokens = args.tokens or next((r["total"] for r in summary(args.run_dir) if r["step"] == args.step), 0)
        if not tokens:
            raise SystemExit(f"[usage] 장부에 '{args.step}' 기록 없음 — --tokens로 직접 주기")
        model = step_model(args.run_dir, args.step)
        record = add_calibration(calibration_path(), str(args.run_dir), args.step, args.before, args.after, tokens, model)
        print(f"[usage] 보정 기록: {args.step} {args.before:g}% → {args.after:g}% / {tokens:,} 토큰 ({model or '모델 미상'}) -> {calibration_path()}")
        return
    if args.command == "budget":
        ratio = pct_per_token(calibration_path(), args.model)
        units = {"paper": args.papers, "fulltext": args.fulltext, "run": 0 if args.no_run_steps else 1}
        print_budget(budget(units, load_config()["usage"]["reference_tokens"], ratio), args.used_5h, ratio)
        return

    if args.command in ("add", "add-session"):
        source_id = args.agent_id if args.command == "add" else args.session_id
        transcript = find_transcript(source_id) if args.command == "add" else find_session(source_id)
        usage = claude_usage(transcript)
        path = save(args.run_dir, args.step, source_id, usage, getattr(args, "estimate", None))
        print(f"[usage] {args.step}: 호출 {usage['calls']}번, 입력 {usage['input']:,} · 캐시 쓰기 {usage['cache_write']:,} · "
              f"캐시 읽기 {usage['cache_read']:,} · 출력 {usage['output']:,} ({usage['model']}) -> {path}")
        return
    rows = summary(args.run_dir)
    if not rows:
        print("[usage] 기록 없음")
        return
    print("| 단계 | 실행 | 호출 | 입력 | 캐시 쓰기 | 캐시 읽기 | 출력(참고) | 누적 처리량 | 추정 |")
    print("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['step']} | {r['runs']} | {r['calls']} | {r['input']:,} | {r['cache_write']:,} | {r['cache_read']:,} | "
              f"{r['output']:,} | {r['total']:,} | {r['estimate']:,} |")


if __name__ == "__main__":
    main()
