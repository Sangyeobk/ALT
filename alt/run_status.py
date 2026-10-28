"""결과 폴더 상태 안내: 파일만 보고 끝난 단계와 다음 할 일을 보여 준다 (추가 모델 호출 없음).

    python alt/run_status.py outputs/<run>/ [--variant 초록]
    python alt/run_status.py            # 결과 폴더 목록 (주제·다음 단계) — /alt 시작 때 기존 조사 찾기

- `/alt`를 부르면 늘 먼저 기존 결과 폴더를 확인해 이어 하기를 고르게 한다 (새 세션·사용량 한도 뒤에도 긴 대화를 다시 읽지 않고 이어 감).
- **안내만** 한다: 파일이 있는지, JSON이 읽히는지, 앞 단계 파일보다 새로운지(오래된 결과 경고)만 본다. 내용이 맞는지는 판단하지 않는다.
- ⑥ 중간 확인(사용자)은 --confirm ⑥ 기록이 있을 때만 끝 (점수화가 그 뒤에 바뀌면 다시 확인). 교차 검증은 판정이 '통과'일 때만 끝.
- 교차 검증(⑤-1·⑩)·용어 검사·문서 검토·사용자 확인은 건너뛰지 않는다고 늘 알린다.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from common import OUTPUT_NAMES, PROJECT_DIR, add_variant, extra_files, load_topic, variant_name
from add_institution_docs import load_user_docs
from library import library_dir
from prepare_synthesis import CITABLE_STATUS
from refresh_check import slide_plan_status

DONE, TODO, CHECK, UNKNOWN = "끝", "안 함", "확인 필요", "알 수 없음"
PASS = "통과"  # 교차 검증 판정 중 '끝'으로 보는 것 (조건부 통과·실패는 확인 필요)
CHECKPOINTS = "checkpoints.json"  # 사용자 확인 기록 (⑥)
MARK = {DONE: "✓", TODO: "·", CHECK: "!", UNKNOWN: "?"}


def _readable(path: Path) -> bool:
    try:
        json.loads(path.read_text(encoding="utf-8"))
        return True
    except (OSError, ValueError):
        return False


def file_state(outputs: list[Path], prereqs: list[Path]) -> tuple[str, str]:
    """(상태, 설명): 없음 → 안 함 / JSON 깨짐·앞 단계보다 오래됨 → 확인 필요 / 그 밖 → 끝."""
    missing = [p.name for p in outputs if not p.is_file()]
    if missing:
        return TODO, "없음: " + ", ".join(missing)
    broken = [p.name for p in outputs if p.suffix == ".json" and not _readable(p)]
    if broken:
        return CHECK, "JSON 읽기 실패: " + ", ".join(broken)
    newest = max((p for p in prereqs if p.is_file()), key=lambda p: p.stat().st_mtime, default=None)
    stale = [p.name for p in outputs if newest and p.stat().st_mtime < newest.stat().st_mtime]
    if stale:
        return CHECK, f"앞 단계 파일({newest.name})보다 오래됨: " + ", ".join(stale)
    return DONE, ""


def steps(run: Path, variant: str) -> list[dict]:
    """단계 표: 이름, 상태, 설명, 다음 할 일. 순서 = SKILL 단계 순서."""
    v = lambda name: run / variant_name(name, variant)  # noqa: E731
    inputs = sorted(run.glob("relevance_input_*.json"))
    relevance = [run / p.name.replace("relevance_input_", "relevance_") for p in inputs] or [run / "relevance_1.json"]
    reviews = [run / "review_eval_claude.json", run / "review_eval_codex.json"]
    rounds = sorted((p for p in run.glob("verification_*.json") if "_outputs" not in p.name), key=lambda p: p.stat().st_mtime)
    products = [v(n) for n in OUTPUT_NAMES] + [run / "02_literature_map.png"]
    output_checks = [v(f"verification_{who}_outputs.json") for who in ("codex", "claude")]
    output_check = max((p for p in output_checks if p.is_file()), key=lambda p: p.stat().st_mtime, default=output_checks[0])
    document_checks = [v(f"doc_review_{who}.md") for who in ("codex", "claude")]
    document_check = max((p for p in document_checks if p.is_file()), key=lambda p: p.stat().st_mtime, default=document_checks[0])
    table = [
        ("② 검색", [run / "candidates.json"], [], "SKILL ①–②: 검색어 확장 → search_papers.py"),
        ("③ 학술지·철회 검사", [run / "venues.json", run / "integrity.json"], [run / "candidates.json"],
         "fetch_venues.py → check_integrity.py"),
        ("④ 관련성 채점", relevance, [], "prepare_relevance_batches.py → 묶음마다 alt-scorer"),  # 오래됨은 아래에서 같은 번호 입력과만 비교 (④-2 보강 묶음 때문)
        ("⑤ 점수화", [run / "scored.json"], relevance, "score_papers.py"),
        ("⑤-2 문헌조사논문 평가", [run / "review_eval_input.json"] + reviews, [],
         "review_contribution.py --prepare → alt-scorer → --verifier codex"),
        ("⑤ 점수화 (리뷰 평가 반영)", [run / "scored.json"], reviews, "score_papers.py 다시"),
        ("⑤-1 교차 검증", rounds[-1:] or [run / "verification_codex.json"], relevance, "cross_verify.py (비용 먼저 알림)"),
        ("⑥ 중간 확인 (사용자)", None, None, "기준별 편수·상위 10편을 보여 주고 사용자 확인 → run_status.py --confirm ⑥"),
        ("⑦ 인용 키·무료 PDF", [run / "references.json", v("synthesis_input.json")], [run / "scored.json"],
         f"prepare_synthesis.py → fetch_biblio.py → fetch_open_access.py"),
        ("⑧ 요약", [v("synthesis.json")], [v("synthesis_input.json")], "alt-writer (비용 먼저 알림)"),
        ("⑨ 산출물", products, [v("synthesis.json")],
         f"make_figures·export_references·write_markdown·build_docx·build_pptx --variant {variant}"),
        *([("⑨+ 조사 맞춤 결과물", [run / n for n in extra_files(run, variant)], [v("synthesis.json")],
             f"run_extras.py --variant {variant}")] if extra_files(run, variant) else []),
        ("⑩ 인용 검사", [v("citation_check.json")], products, f"check_citations.py --variant {variant}"),
        ("⑩ 용어 검사", [v("terms_check.json")], products, f"check_terms.py --variant {variant}"),
        ("⑩ 산출물 교차 검증", [output_check], products,
         f"cross_verify.py --outputs --variant {variant} (비용 먼저 알림)"),
        ("⑩ 문서 검토", [document_check], products, f"review_documents.py --variant {variant} (비용 먼저 알림)"),
    ]
    rows = {}
    for name, outputs, prereqs, action in table:
        state, note = user_check(run) if outputs is None else file_state(outputs, prereqs)
        rows[name] = {"step": name, "state": state, "note": note, "next": action}

    def flag(name: str, note: str) -> None:
        if rows[name]["state"] == DONE:
            rows[name].update(state=CHECK, note=note)

    stale = [o.name for i, o in zip(inputs, relevance) if o.is_file() and o.stat().st_mtime < i.stat().st_mtime]
    if stale:
        flag("④ 관련성 채점", "입력보다 오래됨: " + ", ".join(stale))
    candidates = run / "candidates.json"
    if candidates.is_file() and _readable(candidates) and all(p.is_file() and _readable(p) for p in relevance):  # ④-2 공통 인용 보강 뒤 채점 안 한 후보
        judged = {r.get("openalex_id") for p in relevance for r in _load(p) if isinstance(r, dict)}
        left = [r for r in (_load(candidates).get("records") or []) if r.get("openalex_id") not in judged]
        if left:
            flag("④ 관련성 채점", f"채점 안 된 후보 {len(left)}편 → prepare_relevance_batches.py --only-unscored --batches 1 → alt-scorer")
    refs, scored = run / "references.json", run / "scored.json"
    if refs.is_file() and scored.is_file() and _readable(refs) and _readable(scored):  # 선정·리뷰 목록과 인용 키 목록이 같은지 (시각 경고는 그대로 둠)
        listed = {r.get("openalex_id") for r in _load(scored).get("records", [])
                  if r.get("status") in CITABLE_STATUS or r.get("adjacent_listed")}  # prepare_synthesis와 같은 기준 — 기관 문서·인접 문헌 포함 (Codex 검토 2026-10-28)
        try:
            listed |= {d["openalex_id"] for d in load_user_docs(run)}  # 사용자가 넣은 기관 문서
        except SystemExit:
            pass  # docs.yaml을 덜 채움 — 그 단계(add_institution_docs)가 알림
        keyed = {r.get("openalex_id") for r in _load(refs).values() if isinstance(r, dict)}
        if listed != keyed:
            rows["⑦ 인용 키·무료 PDF"].update(state=CHECK, note=f"선정·리뷰·인접 목록과 인용 키 목록이 다름 ({len(listed)} / {len(keyed)}편) → prepare_synthesis.py 다시")
    for name, path, key in (("⑩ 인용 검사", v("citation_check.json"), "passed"), ("⑩ 용어 검사", v("terms_check.json"), "passed")):
        if path.is_file() and _readable(path) and not _load(path).get(key):
            flag(name, "검사 실패 기록 — ⑧로 돌아가 고친 뒤 다시")
    for name, path in (("⑤-1 교차 검증", rounds[-1] if rounds else None), ("⑩ 산출물 교차 검증", output_check)):
        if path and path.is_file() and _readable(path) and str(_load(path).get("verdict") or "").strip() != PASS:
            flag(name, f"판정: {_load(path).get('verdict') or '없음'} — 지적을 처리했는지 확인")
    plans = slide_plan_status(run)
    pending = [f"{name} ({status})" for name, status in plans.items() if status != "최신"]
    if pending:
        row = rows["⑨ 산출물"]
        row.update(state=CHECK, note="; ".join(filter(None, [row["note"], "구성안 갱신 필요: " + ", ".join(pending)])))
    return list(rows.values())


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def user_check(run: Path) -> tuple[str, str]:
    """⑥ 사용자 확인: run_status.py --confirm ⑥으로 남긴 기록이 점수화(scored.json)보다 뒤일 때만 끝."""
    path, scored = run / CHECKPOINTS, run / "scored.json"
    when = (_load(path).get("⑥") if path.is_file() and _readable(path) else None)
    if not when:
        return UNKNOWN, "확인 기록 없음 — 사용자에게 확인받은 뒤 --confirm ⑥"
    if scored.is_file() and datetime.fromisoformat(when).timestamp() < scored.stat().st_mtime:
        return CHECK, f"확인({when}) 뒤 점수화가 바뀜 — 다시 확인"
    return DONE, f"확인 {when}"


def next_step(rows: list[dict]) -> dict | None:
    """끝나지 않은 첫 단계 (안 함·알 수 없음). '!' 확인 필요는 경고로 보여 주고 진행 전에 사용자에게 묻는다."""
    return next((row for row in rows if row["state"] in (TODO, UNKNOWN)), None)


def finished_label(rows: list[dict]) -> str:
    """남은 단계가 없을 때 표시 — '!' 확인 필요(검사 실패·오래됨 등)가 남았으면 끝과 구분 (Codex 검토 2026-10-28)."""
    checks = [row["step"] for row in rows if row["state"] == CHECK]
    return f"없음 — 단 확인 필요 {len(checks)}건: {', '.join(checks)}" if checks else "없음 (끝)"

def run_topic(run: Path) -> str:
    """조사 주제: 확정 주제(topic.json) → 점수화 meta의 주제 → 검색어 첫 줄 → 없으면 '-'."""
    if load_topic(run).get("topic_ko"):
        return load_topic(run)["topic_ko"]
    for name, pick in (("scored.json", lambda m: m.get("topic")), ("candidates.json", lambda m: (m.get("queries") or [None])[0])):
        path = run / name
        if path.is_file() and _readable(path):
            data = _load(path)
            value = pick(data.get("meta", {}) if isinstance(data, dict) else {})
            if value:
                return str(value)
    return "-"


def list_runs(outputs_dir: Path, variant: str) -> list[dict]:
    """결과 폴더 목록 ('_'로 시작하는 보관·삭제 폴더와 레퍼런스 폴더 제외): 이름·주제·다음 단계."""
    runs = []
    library = library_dir().resolve()
    for run in sorted(p for p in outputs_dir.iterdir() if p.is_dir() and not p.name.startswith("_") and p.resolve() != library):
        rows = steps(run, variant)
        upcoming = next_step(rows)
        runs.append({"run": run.name, "topic": run_topic(run), "next": upcoming["step"] if upcoming else finished_label(rows)})
    return runs


WORKSPACE_MARK = ".alt_workspace"   # 이 폴더를 ALT 작업 폴더로 쓰겠다고 사용자가 정한 표시 (사용자 요청 2026-10-27)


def workspace_problem(folder: Path) -> str | None:
    """작업 폴더가 정해지지 않았으면 그 이유 — 결과(outputs/)가 세션을 연 폴더에 쌓이므로 엉뚱한 곳에 생기지 않게.
    홈 폴더·드라이브 맨 위는 늘 미지정, 그 밖에는 outputs/나 표시 파일이 있으면 작업 폴더로 봄."""
    folder = folder.resolve()
    if folder == Path.home().resolve() or folder == Path(folder.anchor):
        return "홈 폴더나 드라이브 맨 위에서 열림"
    if not (folder / "outputs").is_dir() and not (folder / WORKSPACE_MARK).is_file():
        return "ALT 작업 폴더로 정한 적 없는 폴더 (outputs/ 없음)"
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", type=Path, nargs="?", help="없으면 outputs/ 아래 결과 폴더 목록")
    parser.add_argument("--confirm", choices=["⑥"], help="사용자 확인을 받은 단계를 기록 (지금 시각)")
    parser.add_argument("--init-workspace", action="store_true", help="지금 폴더를 ALT 작업 폴더로 정함 (사용자가 고른 뒤에만)")
    add_variant(parser)
    args = parser.parse_args()
    if args.init_workspace:
        if workspace_problem(PROJECT_DIR) == "홈 폴더나 드라이브 맨 위에서 열림":
            raise SystemExit(f"[workspace] {PROJECT_DIR}는 작업 폴더로 쓰지 않음 — 결과가 쌓일 폴더를 만들어 그 폴더에서 다시 열 것")
        (PROJECT_DIR / "outputs").mkdir(exist_ok=True)
        (PROJECT_DIR / WORKSPACE_MARK).write_text(f"ALT 작업 폴더 (정한 날 {datetime.now().date()})\n", encoding="utf-8")
        print(f"[workspace] 작업 폴더로 정함: {PROJECT_DIR} (결과는 outputs/ 아래)")
        return
    if args.run_dir is None:
        problem = workspace_problem(PROJECT_DIR)
        if problem:  # SKILL '작업 폴더 확인' — 사용자에게 묻기 전에는 다른 단계를 진행하지 않음
            print(f"[workspace] 작업 폴더 미지정: {PROJECT_DIR} — {problem}")
            raise SystemExit(2)
        runs = list_runs(PROJECT_DIR / "outputs", args.variant) if (PROJECT_DIR / "outputs").is_dir() else []
        print(f"[status] 결과 폴더 {len(runs)}개" + ("" if runs else " — 새로 시작"))
        for r in runs:
            print(f" - {r['run']} | 주제: {r['topic']} | 다음: {r['next']}")
        return
    if args.confirm:
        path = args.run_dir / CHECKPOINTS
        record = _load(path) if path.is_file() and _readable(path) else {}
        record[args.confirm] = datetime.now().isoformat(timespec="seconds")
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[status] {args.confirm} 사용자 확인 기록 -> {path.name}")
    rows = steps(args.run_dir, args.variant)
    print(f"[status] {args.run_dir.name} — 파일로 본 안내, 내용 검토 아님")
    for row in rows:
        print(f" {MARK[row['state']]} {row['step']}" + (f" — {row['note']}" if row["note"] else ""))
    upcoming = next_step(rows)
    print(f"다음: {upcoming['step']} — {upcoming['next']}" if upcoming
          else f"다음: {finished_label(rows)} — 이후 사용자의 말은 피드백으로 처리 (SKILL '기본 동작')")
    print("알림: ⑥ 사용자 확인·교차 검증(⑤-1·⑩)·용어 검사·문서 검토는 건너뛰지 않는다. '!' 항목은 진행 전에 사용자에게 확인")


if __name__ == "__main__":
    main()
