"""용어 검사: synthesis.json의 terms(대표 용어 → 쓰지 말 변이형)대로 산출물이 대표 용어만 쓰는지 + 자리표시 말(config placeholder_phrases)이 없는지 → 있으면 실패

    python alt/check_terms.py outputs/<run>/

검사 대상은 인용 검사와 같은 산출물 5종. 대표 용어 안에 들어 있는 글자는 변이형으로 세지 않는다.
영문 변이형은 대소문자를 가리지 않고 단어 단위로 찾는다 (예: 'surrogate'는 'surrogates'에서는 안 찾음 — 복수형은 따로 적음).
논문 제목·학술지 이름(references.json)은 원문 고유명사라 검사 전에 지운다 (참고문헌 목록·원문 그림 설명의 'Surrogate …' 등).
"""

import argparse
import re
from pathlib import Path

from check_citations import output_texts
from common import add_variant, load_config, read_json, variant_name, verbatim_strings, write_json

SNIPPET_CHARS = 20


def variant_pattern(variant: str) -> re.Pattern:
    """영문은 단어 경계(앞뒤가 영문자가 아님), 한글은 글자 그대로."""
    escaped = re.escape(variant)
    if re.search(r"[A-Za-z]", variant):
        escaped = rf"(?<![A-Za-z]){escaped}(?![A-Za-z])"
    return re.compile(escaped, re.IGNORECASE)


def strip_proper_names(text: str, names: list[str]) -> str:
    """논문 제목·학술지 이름 같은 원문 고유명사를 지운다 (긴 것부터 — 짧은 이름이 긴 이름 일부를 먼저 지우지 않게)."""
    for name in sorted({n for n in names if n}, key=len, reverse=True):
        text = re.sub(re.escape(name), " ", text, flags=re.IGNORECASE)
    return text


def find_variants(text: str, terms: list[dict], proper_names: list[str] = ()) -> list[tuple[str, str, str]]:
    """(대표 용어, 찾은 변이형, 앞뒤 글) 목록. 고유명사와 대표 용어 자리는 먼저 지워서 변이형으로 세지 않는다."""
    text = strip_proper_names(text, list(proper_names))
    hits = []
    for term in terms:
        cleaned = re.sub(re.escape(term["term"]), " " * len(term["term"]), text, flags=re.IGNORECASE)
        for variant in term.get("variants", []):
            for m in variant_pattern(variant).finditer(cleaned):
                snippet = text[max(0, m.start() - SNIPPET_CHARS):m.end() + SNIPPET_CHARS].replace("\n", " ")
                hits.append((term["term"], m.group(0), snippet))
    return hits


def find_placeholders(text: str, phrases: list[str]) -> list[tuple[str, str]]:
    """(자리표시 말, 앞뒤 글) 목록 — '선택한 접근법'처럼 실제 이름을 돌려 말한 곳 (사용자 피드백 2026-10-16)."""
    return [(p, text[max(0, m.start() - SNIPPET_CHARS):m.end() + SNIPPET_CHARS].replace("\n", " "))
            for p in phrases for m in re.finditer(re.escape(p), text)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", type=Path)
    add_variant(parser)
    args = parser.parse_args()

    terms = read_json(args.run_dir / variant_name("synthesis.json", args.variant)).get("terms", [])
    if not terms:
        print("[terms] synthesis.json에 terms가 없음 → 검사할 용어 없음 (요약 단계에서 정해야 함)")
        write_json(args.run_dir / variant_name("terms_check.json", args.variant), {"passed": False, "reason": "terms 없음"})
        raise SystemExit(1)
    references = read_json(args.run_dir / "references.json")
    proper_names = ([r.get("title") for r in references.values()] + [r.get("venue") for r in references.values()]
                    + verbatim_strings(args.run_dir))
    texts, unreadable = output_texts(args.run_dir, args.variant)
    phrases = load_config()["output"].get("placeholder_phrases", [])
    failed, counts, placeholders = bool(unreadable), {}, {}
    for name, text in texts.items():
        hits = find_variants(text, terms, proper_names)
        loose = find_placeholders(text, phrases)
        failed |= bool(hits) or bool(loose)
        counts[name], placeholders[name] = len(hits), len(loose)
        print(f"[terms] {name}: 변이형 {len(hits)}곳, 자리표시 말 {len(loose)}곳")
        for term, found, snippet in hits[:10]:
            print(f"    '{found}' → '{term}'  …{snippet}…")
        for phrase, snippet in loose[:10]:
            print(f"    자리표시 '{phrase}' → 실제 이름·요지로  …{snippet}…")
    for name in unreadable:
        print(f"[terms] {name}: 읽지 못함 (Word·PowerPoint에서 열려 있으면 닫고 다시 실행) → 확인 못 함")
    write_json(args.run_dir / variant_name("terms_check.json", args.variant),  # 결과 기록 (run_status가 ⑩ 상태로 읽음)
               {"passed": not failed, "variants": counts, "placeholders": placeholders, "unreadable": unreadable})
    print(f"[terms] {'실패' if failed else '통과'} — 대표 용어 {len(terms)}개")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
