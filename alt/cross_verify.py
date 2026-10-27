"""교차 검증: 결과를 만든 AI와 **다른 AI**가 독립적으로 검증 → verification_<검증자>.md

    python alt/cross_verify.py outputs/<run>/ [--verifier codex|claude]

- Claude Code로 실행했으면 Codex가 검증하고 (기본값), Codex로 실행했으면 --verifier claude 로 Claude Code가 검증한다.
- 검증자는 읽기 전용으로 실행한다. 표본(선정 + 경계 + 리뷰)과 산출물을 받아 판정하고 관련성을 다시 채점한다.
- 관련성 일치율은 이 스크립트가 직접 계산한다 (검증자 보고의 JSON 블록 사용).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from common import (OUTPUT_NAMES, PACKAGE_DIR, add_variant, candidate_distribution, load_config, map_axis, read_json, topic_context,
                    variant_name, write_json)
from usage_log import codex_usage, save as save_usage
from check_citations import output_texts

PROMPT_PATH = PACKAGE_DIR / "verify_prompt.md"
RUBRIC_PATH = PACKAGE_DIR / "relevance_rubric.md"
SCORING_METHOD = (
    "score_parts: relevance=관련성/5, citation=FWCI의 후보 집합 내 백분위(없으면 OpenAlex citation_normalized_percentile), "
    "venue=학술지 2년 평균 피인용·h-index 백분위의 평균. base_score=값이 있는 항목만으로 가중평균(가중치 재배분), "
    "total_score=base_score×category_weight. 백분위는 후보 전체 기준이라 표본만으로는 재계산 불가 — "
    "base_score·total_score가 score_parts로부터 맞게 계산됐는지만 확인한다."
)


def verifier_command(verifier: str, run_dir: Path, report_path: Path) -> list[str]:
    """검증자별 읽기 전용 비대화형 실행 명령. 프롬프트는 표준입력으로 넘긴다.
    Codex는 --json(표준출력 = 사용량이 든 이벤트 줄), 보고서는 -o 파일로 받는다."""
    if verifier == "codex":
        installed = list((Path.home() / "AppData/Local/OpenAI/Codex/bin").glob("*/codex.exe"))
        newest = max(installed, key=lambda p: p.stat().st_mtime, default=None)
        executable = shutil.which("codex") or (str(newest) if newest else "codex")
        return [executable, "exec", "-s", "read-only", "--skip-git-repo-check",
                "--ephemeral", "--json", "-C", str(run_dir), "-o", str(report_path), "-"]
    if verifier == "claude":
        installed = Path.home() / ".local" / "bin" / "claude.exe"
        executable = shutil.which("claude") or (str(installed) if installed.is_file() else "claude")
        return [executable, "-p", "--tools", "Read,Glob,Grep", "--allowedTools", "Read", "Glob", "Grep",
                "--permission-mode", "dontAsk", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}']
    raise ValueError(f"unknown verifier: {verifier}")


def run_verifier(verifier: str, run_dir: Path, report_path: Path, prompt: str, step: str) -> subprocess.CompletedProcess:
    """검증자 실행 (cross_verify·review_contribution·review_documents 공통). 보고서는 report_path에 남고,
    Codex 사용량은 사용량 장부(<run>/usage/)에 기록한다 — 못 읽으면 경고만 하고 결과 처리는 그대로."""
    run_dir = Path(run_dir).resolve()
    result = subprocess.run(verifier_command(verifier, run_dir, Path(report_path).resolve()),
                            input=prompt, text=True, encoding="utf-8", capture_output=True, cwd=run_dir,
                            timeout=load_config()["verification"]["timeout_seconds"])
    if verifier == "claude":
        if result.returncode == 0:
            Path(report_path).write_text(result.stdout, encoding="utf-8")
        else:
            Path(report_path).with_suffix(".failed.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        return result
    usage = codex_usage(result.stdout)
    if usage:
        save_usage(run_dir, step, f"codex_{datetime.now():%Y%m%d%H%M%S}", usage)
    else:
        print("[usage] Codex 사용량을 읽지 못함 — 검증 결과는 그대로 처리", flush=True)
    return result


def build_sample(scored: dict, borderline_count: int, skip_ids: set[str] = frozenset()) -> list[dict]:
    """검증 표본: 선정 전부 + 리뷰 목록 전부 + 선정 바로 아래(경계) 논문 n편. skip_ids(이미 검증됨)는 뺀다."""
    records = [r for r in scored["records"] if r["openalex_id"] not in skip_ids]
    picked = [r for r in records if r["status"] in ("selected", "review_listed")]
    borderline = [r for r in records if r["status"] in ("below_relevance", "below_threshold", "over_limit")]
    picked += borderline[:borderline_count]
    return [{k: r.get(k) for k in ("openalex_id", "doi", "title", "year", "venue", "abstract", "relevance",
                                   "relevance_reason", "is_review", "category", "category_weight", "fwci",
                                   "citation_percentile", "score_parts", "base_score", "total_score", "status")}
            for r in picked]


def candidate_counts(records: list[dict]) -> dict:
    """전체 후보의 상태 × 관련성 편수 — 산출물 검증에서 탈락·통과 편수를 대조할 근거 (10-16 결함: 검증 입력에 전체 후보가 없어 '확인 불가')."""
    out: dict[str, dict[str, int]] = {}
    for r in records:
        by_rel = out.setdefault(r["status"], {})
        by_rel[str(r["relevance"])] = by_rel.get(str(r["relevance"]), 0) + 1
    return out


def agreement(sample: list[dict], rechecks: list[dict], min_relevance: int) -> dict:
    """원래 관련성과 검증자 관련성 비교: 일치율, 2점 이상 차이, 선정 경계(하한) 뒤집힘."""
    original = {p["openalex_id"]: p for p in sample}
    pairs = [(original[r["openalex_id"]], r) for r in rechecks if r.get("openalex_id") in original]
    big_gap = [p["openalex_id"] for p, r in pairs if abs(p["relevance"] - r["verifier_relevance"]) >= 2]
    flipped = [p["openalex_id"] for p, r in pairs
               if (p["relevance"] >= min_relevance) != (r["verifier_relevance"] >= min_relevance)]
    review_flip = [p["openalex_id"] for p, r in pairs
                   if "verifier_is_review" in r and bool(p["is_review"]) != bool(r["verifier_is_review"])]
    return {
        "compared": len(pairs),
        "missing_in_report": len(sample) - len(pairs),
        "exact_match": sum(p["relevance"] == r["verifier_relevance"] for p, r in pairs),
        "within_1": sum(abs(p["relevance"] - r["verifier_relevance"]) <= 1 for p, r in pairs),
        "gap_2_or_more": big_gap,
        "selection_boundary_flipped": flipped,
        "review_judgement_flipped": review_flip,
    }


def merge_rechecks(path: Path, verifier: str, rechecks: list[dict]) -> dict:
    """검증자 재채점을 누적 파일(verifier_rechecks.json)에 합친다. 점수 결정 규칙은 score_papers.py가 적용."""
    merged = read_json(path) if path.is_file() else {}
    for r in rechecks:
        merged[r["openalex_id"]] = {"verifier": verifier, "relevance": r["verifier_relevance"],
                                    "is_review": r.get("verifier_is_review")}
    write_json(path, merged)
    return merged


def last_json_block(text: str) -> dict | None:
    blocks = re.findall(r"```json\s*(\{.*?\})\s*```", text, re.S)
    try:
        return json.loads(blocks[-1]) if blocks else None
    except json.JSONDecodeError:
        return None


def relevance_rounds(run_dir: Path, verifier: str) -> list[Path]:
    """관련성 검증 회차 보고서만 (verification_<x>.md, verification_<x>_<N>.md) — 산출물 회차(_outputs_<판>)는 세지 않음."""
    return [p for p in run_dir.glob(f"verification_{verifier}*.md")
            if re.fullmatch(rf"verification_{re.escape(verifier)}(_\d+)?\.md", p.name)]


def target_files_note(input_name: str, variant: str | None) -> str:
    """검증자에게 이번에 볼 파일을 정확히 알려 줌 — 한 폴더에 여러 판(초록·전문활용)이 있어 섞이지 않게."""
    outputs = (["02_문헌지도.png"] + [variant_name(n, variant) for n in OUTPUT_NAMES]) if variant is not None else []
    return ("## 이번 검증 대상 파일 (아래 규칙의 파일 이름보다 우선)\n"
            f"- 입력: `{input_name}`\n- 산출물: {', '.join(f'`{n}`' for n in outputs) if outputs else '보지 않음'}\n"
            + ("- Office 본문은 입력의 output_texts에 파일별로 추출되어 있음. 셸 실행 없이 이 본문을 검증함. "
               "unreadable_outputs에 있는 파일은 확인 불가로 보고함. 화면 배치는 별도 화면 검사 대상임.\n" if outputs else "") + "\n")


def verification_outputs(run_dir: Path, variant: str) -> dict:
    texts, unreadable = output_texts(run_dir, variant)
    return {"output_texts": texts, "unreadable_outputs": unreadable}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--verifier", choices=["codex", "claude"])
    parser.add_argument("--only-unverified", action="store_true", help="이미 재채점된 논문은 표본에서 뺀다 (2회차 이후)")
    parser.add_argument("--from-report", action="store_true", help="검증자를 다시 부르지 않고 기존 보고서만 다시 읽는다")
    parser.add_argument("--outputs", action="store_true",
                        help="산출물 검사 회차: 표본 = 인용 가능 문헌(선정+리뷰). 재채점은 기록만 하고 선정에는 반영하지 않음")
    add_variant(parser)
    args = parser.parse_args()

    config = load_config()
    rules = config["verification"]
    verifier = args.verifier or rules["default_verifier"]
    scored = read_json(args.run_dir / "scored.json")
    rechecks_path = args.run_dir / "verifier_rechecks.json"
    skip = set(read_json(rechecks_path)) if args.only_unverified and rechecks_path.is_file() else set()
    sample = build_sample(scored, 0 if args.outputs else rules["borderline_count"], skip)
    if not sample:
        print("[verify] 새로 검증할 논문 없음")
        return
    allowed = sorted({r["doi"] for r in scored["records"] if r["doi"]} | {r["openalex_id"] for r in scored["records"]})
    input_name = "verify_input_outputs.json" if args.outputs else "verify_input.json"  # 판 이름이 없어져 산출물 검증 입력을 따로 (2026-10-19)
    write_json(args.run_dir / input_name, {
        "meta": {k: scored["meta"].get(k) for k in ("weights", "category_weights", "min_relevance",
                                                    "min_total_score", "max_selected", "prisma", "scoring_overrides")},
        **topic_context(args.run_dir, scored["meta"].get("topic"), scored["meta"].get("approach")),
        "scoring_method": SCORING_METHOD,
        "rubric": RUBRIC_PATH.read_text(encoding="utf-8"),
        "papers": sample,
        "allowed_references": allowed,
        **({"candidate_counts": candidate_counts(scored["records"]),  # 산출물 회차만: 전체 후보 집계·문헌지도 분포
            "candidate_distribution": candidate_distribution(scored["records"], config["output"], map_axis(args.run_dir))}
           if args.outputs else {}),
        "citation_keys": ({k: {"doi": r["doi"], "title": r["title"], "openalex_id": r["openalex_id"]}
                           for k, r in read_json(args.run_dir / "references.json").items()}
                          if (args.run_dir / "references.json").is_file() else {}),
        **(verification_outputs(args.run_dir, args.variant) if args.outputs else {}),
    })

    round_no = len(relevance_rounds(args.run_dir, verifier)) + (0 if args.from_report else 1)
    report_path = args.run_dir / (variant_name(f"verification_{verifier}_outputs.md", args.variant) if args.outputs else
                                  f"verification_{verifier}.md" if round_no <= 1 else f"verification_{verifier}_{round_no}.md")
    if not args.from_report:
        prompt = target_files_note(input_name, args.variant if args.outputs else None) + PROMPT_PATH.read_text(encoding="utf-8")
        print(f"[verify] {verifier}로 검증 중… 표본 {len(sample)}편", flush=True)
        result = run_verifier(verifier, args.run_dir, report_path, prompt,
                              step=variant_name("교차검증_산출물", args.variant) if args.outputs else "교차검증")
        if result.returncode != 0 or not report_path.is_file():
            raise SystemExit(f"[verify] 검증자 실행 실패 (code {result.returncode}): {(result.stderr or result.stdout)[-800:]}")

    parsed = last_json_block(report_path.read_text(encoding="utf-8"))
    if parsed is None:
        raise SystemExit(f"[verify] 보고서에 JSON 블록이 없음 → {report_path} 직접 확인 필요")
    stats = agreement(sample, parsed["relevance_rechecks"], scored["meta"]["min_relevance"])
    if not args.outputs:
        merge_rechecks(rechecks_path, verifier, parsed["relevance_rechecks"])
    write_json(report_path.with_suffix(".json"), {"verdict": parsed.get("verdict"), "agreement": stats})
    print(f"[verify] 판정: {parsed.get('verdict')} | 관련성 일치 {stats['exact_match']}/{stats['compared']}, "
          f"±1 이내 {stats['within_1']}, 2점 이상 차이 {len(stats['gap_2_or_more'])}, "
          f"선정 경계 뒤집힘 {len(stats['selection_boundary_flipped'])}, 리뷰 판정 다름 {len(stats['review_judgement_flipped'])} "
          f"-> {report_path}")


if __name__ == "__main__":
    main()
