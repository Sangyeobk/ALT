"""보고서·발표의 구성·문장·명확성 검토 — 결과를 만든 AI와 다른 AI(기본 Codex/GPT)가 편집자 관점으로 읽기 전용 검토

    python alt/review_documents.py outputs/<run>/ [--verifier codex|claude] [--variant 초록]   # → doc_review_<검토자>_<판>.md

사실 검증(지어낸 문헌·숫자)은 cross_verify.py --outputs가 맡고, 이 스크립트는 읽기 쉬움·구성만 본다.
검토자에게 .docx·.pptx를 직접 읽게 하지 않고 본문을 글(doc_review_input_<판>.md)로 뽑아 준다 — Codex 샌드박스에서
파이썬·XML 읽기가 막혀 '확인 불가'로 끝난 적이 있음 (2026-10-16).
"""

import argparse
from pathlib import Path

from check_citations import output_texts
from common import PACKAGE_DIR, add_variant, load_config, variant_name
from cross_verify import run_verifier

PROMPT_PATH = PACKAGE_DIR / "doc_review_prompt.md"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--verifier", choices=["codex", "claude"])
    add_variant(parser)
    args = parser.parse_args()
    config = load_config()
    verifier = args.verifier or config["verification"]["default_verifier"]
    report = (args.run_dir / variant_name(f"doc_review_{verifier}.md", args.variant)).resolve()
    docs = {name: variant_name(name, args.variant) for name in ("03_보고서.docx", "04_발표.pptx", "doc_review_input.md")}
    texts, unreadable = output_texts(args.run_dir, args.variant)
    missing = [actual for actual in list(docs.values())[:2] if actual not in texts]
    if missing:
        raise SystemExit(f"[doc-review] 본문을 읽지 못함: {', '.join(missing + unreadable)} (없거나 Word·PowerPoint에서 열려 있음)")
    (args.run_dir / docs["doc_review_input.md"]).write_text(
        "\n\n".join(f"===== {actual} =====\n{texts[actual]}" for actual in list(docs.values())[:2]), encoding="utf-8")
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    for name, actual in docs.items():  # 한 폴더에 여러 판이 있으므로 이번 판의 파일 이름으로
        prompt = prompt.replace(f"`{name}`", f"`{actual}`")
    print(f"[doc-review] {verifier}로 보고서·발표 검토 중…", flush=True)
    result = run_verifier(verifier, args.run_dir, report, prompt, step=variant_name("문서검토", args.variant))
    if result.returncode != 0 or not report.is_file():
        raise SystemExit(f"[doc-review] 검토자 실행 실패 (code {result.returncode}): {result.stderr[-800:]}")
    print(f"[doc-review] 완료 -> {report}")


if __name__ == "__main__":
    main()
