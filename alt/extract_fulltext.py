"""전문 모드 전용: 받아 둔 PDF → 본문 글 papers/<키>.txt (쪽마다 [[p.N]] 표시, 서론·선행연구·참고문헌 목록은 잘라 분량을 줄임)

    python alt/extract_fulltext.py outputs/<run>/ [--force]

- 대상 (사용자 결정 2026-10-16): config fulltext.context_statuses 논문(핵심논문·문헌조사논문) 중 PDF가 있는 것 전부 — 맥락 정리.
  기관·선급 문서는 길어서 뺀다. 그림 고르기 대상은 따로(fulltext.figure_targets, target_keys — extract_figures.py).
- 이미 만든 .txt가 PDF보다 새것이면 건너뛴다 (--force면 다시 만듦).
- 본문 정리(fulltext_notes_<k>.json)가 이미 있는 논문은 대상에서 뺀다 → 세션을 다시 돌려도 같은 논문을 다시 읽지 않음 (--redo면 포함).
  레퍼런스 폴더(alt/library.py)에 같은 PDF의 맥락 정리가 있으면 가져와 새 번호 파일에 쓴다 (사용자 결정 2026-10-22, reused_from에 출처).
  시작할 때 이 조사에서 이미 끝낸 맥락 정리를 레퍼런스 폴더에 등록한다.
  새 묶음 번호는 기존 정리 파일 다음 번호부터 (덮어쓰기 방지). fulltext_batches.json의 batches = {"묶음 번호": [키, …]}.
- 글이 거의 안 나오는 PDF(스캔본 등)는 .txt를 만들지 않는다 → 그 논문은 초록 수준으로 남는다.
- 마지막에 본문 정리를 나눠 맡을 묶음과 사용량 추정을 fulltext_batches.json에 쓴다 (묶음당 논문 수 = config fulltext.papers_per_batch).
"""

from __future__ import annotations

import argparse
import math
import re
from pathlib import Path

from pypdf import PdfReader

from common import load_config, read_json, variant_name, write_json
from library import Library, sync_run

PAGE_MARK = re.compile(r"\[\[p\.\d+\]\]")


def cut_references(text: str, headings: list[str]) -> str:
    """마지막 '참고문헌' 제목 줄부터 끝까지 잘라낸다. 제목이 본문 앞쪽 절반에만 있으면 자르지 않는다."""
    pattern = re.compile(rf"^\s*(\d+\.?\s*)?({'|'.join(map(re.escape, headings))})\s*$", re.MULTILINE)
    matches = [m for m in pattern.finditer(text) if m.start() > len(text) * 0.5]
    return text[:matches[-1].start()].rstrip() if matches else text


def trim_sections(text: str, words: list[str], max_ratio: float) -> tuple[str, int]:
    """번호 붙은 서론·선행연구 절('1. Introduction' 등)을 다음 번호 절('2. …') 전까지 잘라낸다 → (글, 잘라낸 글자 수).
    잘린 부분의 쪽 표시 [[p.N]]는 남겨 뒤 글의 쪽 번호가 맞게 한다. 잘라낼 양이 max_ratio를 넘으면 자르지 않는다.
    ponytail: 번호 없는 제목(예: 'INTRODUCTION'만)은 알아보지 못해 그대로 둠 — 그런 학술지가 많으면 제목 사전 방식 추가"""
    start = re.compile(rf"^\s*(\d+)\.?\s+(?:{'|'.join(map(re.escape, words))})\b[^\n]{{0,40}}$", re.IGNORECASE | re.MULTILINE)
    pieces, cursor, removed = [], 0, 0
    for m in start.finditer(text):
        if m.start() < cursor:
            continue
        following = re.compile(rf"^\s*{int(m.group(1)) + 1}\.?\s+[A-Z][^\n]{{2,80}}$", re.MULTILINE).search(text, m.end())
        if not following:
            continue
        cut = text[m.start():following.start()]
        pieces += [text[cursor:m.start()], "".join(f"{mark}\n" for mark in PAGE_MARK.findall(cut))]
        removed += len(cut)
        cursor = following.start()
    if removed > len(text) * max_ratio:
        return text, 0
    return "".join(pieces) + text[cursor:], removed


def pdf_text(path: Path) -> str:
    """쪽마다 [[p.N]] 표시를 넣는다 → 본문 정리에서 쪽 번호로 근거를 단다."""
    try:
        return "\n".join(f"[[p.{i}]]\n{page.extract_text() or ''}" for i, page in enumerate(PdfReader(path).pages, 1))
    except Exception:  # 깨진 PDF·암호 PDF
        return ""


def context_keys(references: dict, statuses: list[str]) -> list[str]:
    """맥락 정리 대상: 보고서가 인용하는 핵심논문·문헌조사논문 (기관·선급 문서 제외 — 사용자 결정 2026-10-16)."""
    return [k for k, ref in references.items() if ref.get("status") in statuses and ref.get("category") != "institution"]


def target_keys(run_dir: Path, references: dict, mode: str, variant: str) -> list[str]:
    """그림 고르기 대상 (config fulltext.figure_targets): priority = 이 판 요약의 fulltext_priority 중 맥락 정리가 있는 논문 / all = 맥락 정리한 논문 전부.
    fulltext_priority는 '다음에 읽을 논문'이라 본문이 없는 논문만 남기도 함 (PINN 세부 조사 2026-10-16: 대상 0편) → 그때는 맥락 정리한 논문 전부."""
    noted = [k for k in references if k in noted_keys(run_dir)]
    if mode == "all":
        return noted
    synthesis = run_dir / variant_name("synthesis.json", variant)
    if not synthesis.is_file():
        raise SystemExit(f"[fulltext] figure_targets: priority는 요약({synthesis.name})의 fulltext_priority가 필요함 → ⑧ 먼저")
    priority = [p["key"] for p in read_json(synthesis)["conclusion"]["fulltext_priority"] if p["key"] in noted]
    if not priority and noted:
        print("[fulltext] 우선 논문에 맥락 정리가 없음(다음에 읽을 논문 목록) → 맥락 정리한 논문 전부에서 그림을 고름")
    return priority or noted


def noted_keys(run_dir: Path) -> set[str]:
    """이미 본문 정리(fulltext_notes_<k>.json)가 있는 논문 — 못 읽은 것(unreadable)도 시도한 것으로 셈 (다시 읽지 않음)."""
    return {key for path in run_dir.glob("fulltext_notes_*.json") for key in read_json(path)["notes"]}


def reuse_library_notes(run_dir: Path, references: dict, keys: list[str], lib: Library) -> dict[str, tuple[dict, str]]:
    """레퍼런스 폴더에 같은 논문의 맥락 정리가 있으면 그 정리를 쓴다 (사용자 결정 2026-10-22 — 다시 읽지 않음).
    맥락 정리는 주제와 상관없는 항목(목적·방법·자료·검증·수치·결과·한계)이라 그대로 쓸 수 있고,
    쪽 번호가 PDF 기준이라 PDF 파일이 똑같을 때만 쓴다 (Library.note_of). → {키: (정리, 출처 '조사/키')}"""
    found = {}
    for key in keys:
        hit = lib.note_of(references[key], run_dir / (references[key].get("pdf_file") or f"papers/{key}.pdf"))
        if hit:
            found[key] = hit
    return found


def next_batch_number(run_dir: Path) -> int:
    """새 묶음 번호는 기존 fulltext_notes_<k>.json 다음부터 → 이전 정리 파일을 덮어쓰지 않음."""
    numbers = [int(m.group(1)) for p in run_dir.glob("fulltext_notes_*.json") if (m := re.fullmatch(r"fulltext_notes_(\d+)\.json", p.name))]
    return max(numbers, default=0) + 1


def make_batches(sizes: dict[str, int], per_batch: int) -> list[list[str]]:
    """글자 수가 비슷하게 (큰 것부터 가장 가벼운 묶음에 넣기), 묶음 수 = ⌈편수 / 묶음당 논문 수⌉."""
    batches = [[] for _ in range(max(1, math.ceil(len(sizes) / per_batch)))]
    load = [0] * len(batches)
    for key, size in sorted(sizes.items(), key=lambda kv: -kv[1]):
        i = min((i for i in range(len(batches)) if len(batches[i]) < per_batch), key=lambda i: load[i])
        batches[i].append(key)
        load[i] += size
    return batches


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--force", action="store_true", help="이미 만든 .txt도 다시 만든다 (자르기 규칙을 바꿨을 때)")
    parser.add_argument("--redo", action="store_true", help="본문 정리가 이미 있는 논문도 다시 정리 대상에 넣는다 (기본: 건너뜀 — 토큰 절약)")
    args = parser.parse_args()

    rules = load_config()["fulltext"]
    references = read_json(args.run_dir / "references.json")
    done = set() if args.redo else noted_keys(args.run_dir)
    targets = context_keys(references, rules["context_statuses"])
    lib = Library()
    if sync_run(args.run_dir, lib)[1]:  # 지난번에 이 조사에서 끝낸 맥락 정리를 레퍼런스 폴더에 등록
        lib.save()
    reused = {} if args.redo else reuse_library_notes(args.run_dir, references, [k for k in targets if k not in done], lib)
    if reused:  # 새 번호 파일 하나에 — 어디서 가져왔는지는 reused_from
        write_json(args.run_dir / f"fulltext_notes_{next_batch_number(args.run_dir)}.json",
                   {"notes": {k: note for k, (note, _) in reused.items()}, "reused_from": {k: src for k, (_, src) in reused.items()}})
        print(f"[fulltext] 레퍼런스 폴더의 맥락 정리 {len(reused)}편 가져옴 (같은 PDF — 다시 읽지 않음): "
              + ", ".join(f"{k}←{src}" for k, (_, src) in reused.items()))
        done |= set(reused)
    skipped = [k for k in targets if k in done]
    readable, trimmed, unreadable = {}, {}, []
    for key in (k for k in targets if k not in done):
        pdf = args.run_dir / (references[key].get("pdf_file") or f"papers/{key}.pdf")
        if not pdf.is_file():
            continue
        txt = pdf.with_suffix(".txt")
        if args.force or not (txt.is_file() and txt.stat().st_mtime >= pdf.stat().st_mtime):
            text = cut_references(pdf_text(pdf), rules["references_headings"])
            if len(text) < rules["min_text_chars"]:
                txt.unlink(missing_ok=True)
                unreadable.append(key)
                continue
            text, trimmed[key] = trim_sections(text, rules["trim_section_words"], rules["max_trim_ratio"])
            txt.write_text(text, encoding="utf-8")
        readable[key] = len(txt.read_text(encoding="utf-8"))

    first = next_batch_number(args.run_dir)
    batches = {str(first + i): keys for i, keys in enumerate(make_batches(readable, rules["papers_per_batch"]) if readable else [])}
    tokens = {k: n // rules["chars_per_token"] for k, n in readable.items()}
    write_json(args.run_dir / "fulltext_batches.json", {
        "batches": batches, "unreadable": unreadable, "skipped_already_noted": skipped,
        "estimate": {"basis": f"글자 수 ÷ {rules['chars_per_token']} (추정, 한 번 읽는 양)", "tokens": tokens,
                     "total_tokens": sum(tokens.values()), "trimmed_chars": trimmed}})
    not_trimmed = [k for k, n in trimmed.items() if n == 0]
    print(f"[fulltext] 본문 {len(readable)}편 (약 {sum(readable.values()) // 1000}k 글자 ≈ {sum(tokens.values()) // 1000}k 토큰 추정), "
          f"묶음 {len(batches)}개 × 최대 {rules['papers_per_batch']}편"
          + (f" (번호 {first}–{first + len(batches) - 1})" if batches else "")
          + (f", 이미 정리된 {len(skipped)}편은 건너뜀" if skipped else "")
          + (f", 서론·선행연구 잘라냄 {sum(trimmed.values()) // 1000}k 글자" if trimmed else "")
          + (f", 못 자름(제목 인식 안 됨): {', '.join(not_trimmed)}" if not_trimmed else "")
          + (f", 글을 못 읽은 PDF {len(unreadable)}편(초록 수준): {', '.join(unreadable)}" if unreadable else ""))


if __name__ == "__main__":
    main()
