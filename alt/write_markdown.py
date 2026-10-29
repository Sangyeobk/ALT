"""마크다운 산출물 → 00_summary.md (한 쪽 요약), 06_context.md (코딩용 배경)

    python alt/write_markdown.py outputs/<run>/
"""

import argparse
from pathlib import Path

from common import (Abbreviations, add_variant, cite, keyword_tag, read_json, report_title, review_info, role_label, scope_history, topic_line,
                    tr, use_language, variant_name, verbatim_strings)


def bullets(items: list[dict], field: str = "text") -> list[str]:
    return [f"- {item[field]}{cite(item)}" for item in items]


def summary_md(s: dict, meta: dict, references: dict, review_line: str, run_dir: Path) -> str:
    """한 쪽 요약 — 보고서와 같은 흐름(목적 → 발견 → 한계 → 쟁점 → 다음 단계)을 짧게."""
    p, sc, kw = meta["prisma"], s["scope"], s.get("keywords", [])
    asked = topic_line(run_dir, references)
    lines = [f"# {report_title(run_dir, s, references)}", "",
             tr("> 검색일 {run_date} · 후보 {screened}편 → 핵심논문 **{selected}편** + 문헌조사논문 {reviews}편 별도 "
                "(관련성 {min_relevance}점 이상, 기준 점수 {min_total_score}, 교차 검증 반영). "
                "괄호 [ ] 안은 근거 논문 인용 키 — `05_references.xlsx`에서 찾을 수 있음",
                run_date=meta["run_at"][:10], screened=p["screened"], selected=p["selected"], reviews=p["reviews_listed"],
                min_relevance=meta["min_relevance"], min_total_score=meta["min_total_score"]), "", f"> {review_line}", "",
             tr("## 조사 목적과 범위"), *([f"- {asked}"] if asked else []), *[f"- {label}: {text}" for label, text in scope_history(run_dir)],
             tr("- 연구 문제: {question}", question=sc["question"]),
             *([tr("- 핵심 키워드 (결론까지 따라가는 판단 기준):"), *[f"  - **{k['term']}**: {k['plain']} — {k['question']}" for k in kw]] if kw else []),
             tr("- 흐름: {flow}", flow=" → ".join(sc["flow"])),
             tr("- 핵심: {core}", core=sc["core"]), tr("- 활용·확장: {extension}", extension=sc["extension"]),
             tr("- 제외: {excluded}", excluded=sc["excluded"]), "",
             tr("## 주요 발견"), *[f"{i}. {keyword_tag(m, kw)}**{m['text']}**{cite(m)}" for i, m in enumerate(s["key_messages"], 1)], "",
             tr("## 자료의 한계"), *bullets(s["limitations"]), "",
             tr("## 다음 검토"), *bullets(s["next_steps"]), "",
             tr("## 분야"), *[tr("- **{name}** [{role}] ({n}편): {problem} — {io}", name=t["name"], role=role_label(t, s), n=len(t["papers"]),
                                problem=t["problem"], io=t["io"]) for t in s["subtopics"]], "",
             *([tr("## 분야 간 종합"), *[f"- {keyword_tag(x, kw)}{x['text']}{cite(x)}" for x in s["cross_synthesis"]], ""]
               if s.get("cross_synthesis") else []),
             tr("## 후속 검토 쟁점 (우선순위 순)"),
             *[tr("{priority}. {tag}{observation}{cites} → 전문 검토 질문: {question}", priority=i.get("priority", "-"), tag=keyword_tag(i, kw),
                  observation=i["observation"], cites=cite(i), question=i["question"])
               for i in sorted(s["issues"], key=lambda i: i.get("priority", 99))], "",
             tr("## 연구 방향 (관찰 / 가설)"), *[f"- [{tr(o.get('kind', ''))}] {o['text']}{cite(o)}" for o in s["outlook"]]]
    lines += ["", tr("## 결론"), *[f"- {keyword_tag(q, kw) or '[' + tr(q.get('kind', '')) + '] '}{q['text']}{cite(q)}" for q in s["conclusion"].get("points", [])],
              *([tr("> **종합**: {closing}", closing=s["conclusion"]["closing"])] if s["conclusion"].get("closing") else []),
              "", tr("## 전문 검토 우선 논문"), *[f"{n}. **[{q['key']}]** {q['reason']}" for n, q in enumerate(s["conclusion"]["fulltext_priority"], 1)],
              *(["", tr("## 문헌조사논문"),
                 *[f"- **[{r['key']}]** {references[r['key']]['title']} — {r['why_read']}" for r in s["reviews_guide"] if r.get("core", True)], ""]
                if s.get("reviews_guide") else [""]),  # 문헌조사논문이 없으면 빈 절을 두지 않음
              *([tr("## 주목할 인접 문헌 (핵심논문과 별도, 본문 근거 아님)"),
                 *[f"- **[{a['key']}]** {references[a['key']]['title']} — {a['why']}" for a in s["adjacent_guide"]], ""]
                if s.get("adjacent_guide") else [])]
    abbr = Abbreviations(s.get("abbreviations"), verbatim_strings(run_dir))  # 약어는 처음 나올 때 풀어 씀 (입력 원문·검색어는 그대로)
    return "\n".join(abbr(line) for line in lines)


def context_md(s: dict, references: dict, review_line: str, level_of: dict) -> str:
    c = s["context"]
    lines = [tr("# 코딩용 배경 자료 (context.md)"), "",
             tr("> 사용법: 이 파일을 새 프로젝트 폴더에 두고 Claude Code에 \"이 context.md를 배경으로 ○○를 만들어 줘\"라고 요청."),
             tr("> 근거 표시 [키]는 `05_references.xlsx`·`05_references.bib`의 인용 키, [일반 개념]은 교과서 수준 지식."),
             tr("> 수식·기법은 원문 확인 후 쓸 것. {review_line}", review_line=review_line), "",
             tr("## 문제 정의"), c["problem_statement"], "",
             tr("## 지배 방정식·기본 관계"), *[f"- **{e['name']}**: `{e['equation']}` — {e['meaning']} [{e['source']}]"
                                              for e in c["governing_equations"]], "",
             tr("## 주요 기법 (입력 → 출력)"), *[f"- **{m['name']}**: {m['inputs']} → {m['outputs']}. {m['notes']}{cite(m)}"
                                              for m in c["methods"]], "",
             tr("## 데이터·벤치마크"), *[f"- {d['name']} ({tr(d.get('kind') or '')}, {tr(d.get('access') or '접근 미확인')}) — {d.get('link') or tr('링크 없음')} "
                                       f"[{'; '.join(d.get('used_by', []))}]" for d in s.get("datasets_benchmarks", [])], "",
             tr("## 오픈소스"), *([f"- {o['name']} — {o.get('link') or tr('링크 확인 필요')}{cite(o)}" for o in c["open_source"]]
                                or [tr("- 초록에서 확인된 오픈소스 없음")]), "",
             tr("## 주의할 점"), *bullets(c["pitfalls"]), "",
             tr("## 방법 비교표"), tr("| 키 | 검토 | 방법 | 입력 | 출력 | 검증 | 구조물 |"), "|---|---|---|---|---|---|---|",
             *[f"| {m['key']} | {tr(level_of.get(m['key'], ''))} | {m['method']} | {m['input']} | {m['output']} | {m['validation']} | {m['structure']} |"
               for m in s["method_comparison"]], "",
             *([tr("## 수치 비교표 (본문 수치, 쪽 번호)"), tr("| 키 | 지표 | 값 | 조건 | 쪽 |"), "|---|---|---|---|---|",
                *[f"| {m['key']} | {m['metric']} | {m['value']} | {m['condition']} | p.{m['page']} |" for m in s["metrics_table"]], ""]
               if s.get("metrics_table") else []),
             tr("## 참고문헌"), *[f"- [{k}] {', '.join(r['authors'][:3])}{tr(' 외') if len(r['authors']) > 3 else ''} ({r['year']}). "
                             f"{r['title']}. {r['venue'] or ''}. {r['doi'] or ''}" for k, r in references.items()], ""]
    abbr = Abbreviations(s.get("abbreviations"), [x for r in references.values() for x in (r.get("title"), r.get("venue")) if x])  # 약어는 문서에서 처음 나올 때 풀어 씀 (논문 제목·학술지 이름은 그대로)
    return "\n".join(abbr(line) for line in lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", type=Path)
    add_variant(parser)
    args = parser.parse_args()
    use_language(args.run_dir)

    synthesis = read_json(args.run_dir / variant_name("synthesis.json", args.variant))
    meta = read_json(args.run_dir / "scored.json")["meta"]
    references = read_json(args.run_dir / "references.json")
    review_line, level_of = review_info(args.run_dir, args.variant)
    summary, context = variant_name("00_summary.md", args.variant), variant_name("06_context.md", args.variant)
    (args.run_dir / summary).write_text(summary_md(synthesis, meta, references, review_line, args.run_dir), encoding="utf-8")
    (args.run_dir / context).write_text(context_md(synthesis, references, review_line, level_of), encoding="utf-8")
    print(f"[markdown] {summary}, {context}")


if __name__ == "__main__":
    main()
