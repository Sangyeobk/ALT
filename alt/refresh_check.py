"""갱신 전 점검: 열려 있는 산출물 파일 + 지난 요약 이후 새로 생긴 전문

    python alt/refresh_check.py outputs/<run>/ [--reading-mode abstract|full] [--variant 전문활용]

- 열려 있는 파일(Excel·PowerPoint·Word)이 있으면 저장에 실패하므로 먼저 닫게 한다.
- 전문 모드에서, PDF는 있는데 요약 때 '전문'으로 읽지 않은 논문 = 새 전문 → 본문 정리·요약을 다시 해야 함.
- 마지막 줄 `RESYNTHESIZE=yes|no`를 보고 요약 재생성 여부를 정한다.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from common import add_variant, extra_files, load_config, read_json, review_info, run_reading_mode, variant_name

OUTPUT_FILES = ["01_배경학습.pptx", "03_보고서.docx", "04_발표.pptx", "05_참고문헌.xlsx"]


def slide_plan_status(run_dir: Path) -> dict[str, str]:
    """요약 이후 두 구성안을 다시 작성해야 하는지 각각 안내한다."""
    from slides_plan import DECK_FILES
    source = run_dir / "synthesis.json"
    if not source.is_file():
        return {}
    return {name: ("없음" if not (run_dir / name).is_file() else
                   "오래됨" if (run_dir / name).stat().st_mtime < source.stat().st_mtime else "최신")
            for _, name in DECK_FILES.values()}


def locked_files(run_dir: Path, variant: str) -> list[str]:
    locked = []
    for name in [variant_name(n, variant) for n in OUTPUT_FILES] + extra_files(run_dir, variant):
        path = run_dir / name
        try:
            if path.exists():
                with path.open("r+b"):
                    pass
        except PermissionError:
            locked.append(name)
    return locked


def new_fulltexts(run_dir: Path, level_of: dict[str, str]) -> list[str]:
    """맥락 정리 대상(config fulltext.context_statuses, 기관·선급 문서 제외)만 — 인접 문헌 PDF는 정리 대상이 아님 (10-19 거짓 경고)."""
    targets = load_config()["fulltext"]["context_statuses"]
    return sorted(key for key, ref in read_json(run_dir / "references.json").items()
                  if ref.get("status") in targets and ref.get("category") != "institution"
                  and (run_dir / "papers" / f"{key}.pdf").is_file() and level_of.get(key) != "전문")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--reading-mode", choices=("abstract", "full"), default=None, help="기본: common.run_reading_mode")
    add_variant(parser)
    args = parser.parse_args()
    args.reading_mode = args.reading_mode or run_reading_mode(args.run_dir)

    locked = locked_files(args.run_dir, args.variant)
    line, level_of = review_info(args.run_dir, args.variant)
    fresh = new_fulltexts(args.run_dir, level_of) if args.reading_mode == "full" else []
    print(f"[refresh] 지난 요약: {line}")
    for name, state in slide_plan_status(args.run_dir).items():
        print(f"[refresh] 구성안 {name}: {state}" + (" → prepare_slides.py로 입력 생성 후 구성안 다시 작성" if state != "최신" else ""))
    print(f"[refresh] 열려 있는 파일: {', '.join(locked) if locked else '없음'}" + (" → 닫고 다시 실행" if locked else ""))
    if args.reading_mode == "full":
        print(f"[refresh] 새 전문 {len(fresh)}편: {', '.join(fresh) if fresh else '없음'}")
    print(f"RESYNTHESIZE={'yes' if fresh else 'no'}")


if __name__ == "__main__":
    main()
