"""보고서·발표가 함께 쓰는 '검색·선정 사실' (scored.json에서 계산 — Claude가 쓰지 않음, 숫자가 산출물마다 같게)."""

from __future__ import annotations

from collections import Counter

from common import axis_group, axis_labels, role_label, tr, tr_later

# 값은 한국어 원문 그대로 (표시하는 곳에서 tr)
CATEGORY_LABEL = {"journal": tr_later("저널"), "conference": tr_later("학회"), "preprint": tr_later("프리프린트"),
                  "other": tr_later("기타"), "institution": tr_later("기관·선급")}
PDF_SOURCE_LABEL = {"downloaded": tr_later("자동"), "manual": tr_later("수동"), "manual_needed": tr_later("직접 받기 필요"),
                    "not_oa": tr_later("무료 공개 아님")}


NAME_PARTICLES = {"van", "von", "de", "der", "den", "da", "di", "du", "la", "le", "dos", "das", "del", "della", "ten", "ter"}
APA_MAX_AUTHORS = 20  # APA 7판: 20명까지 모두, 21명 이상은 앞 19명 … 마지막 저자


def apa_author(display_name: str) -> str:
    """'Weikai Tan' → 'Tan, W.' / 'Sanne van Essen' → 'van Essen, S.' / 'Jia-Wang Chen' → 'Chen, J.-W.'"""
    parts = display_name.replace(",", " ").split()
    if len(parts) == 1:
        return parts[0]
    surname_start = len(parts) - 1
    while surname_start > 1 and parts[surname_start - 1].lower() in NAME_PARTICLES:
        surname_start -= 1
    initials = " ".join("-".join(f"{piece[0]}." for piece in given.split("-") if piece) for given in parts[:surname_start])
    return f"{' '.join(parts[surname_start:])}, {initials}"


def apa_author_list(authors: list[str]) -> str:
    names = [apa_author(a) for a in authors]
    if len(names) > APA_MAX_AUTHORS:
        return ", ".join(names[:APA_MAX_AUTHORS - 1]) + ", . . . " + names[-1]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + ", & " + names[-1]


def apa_reference(key: str, ref: dict) -> list[tuple[str, bool]]:
    """APA 7판 참고문헌 한 항목 → [(글, 기울임)]. 연도 뒤 a·b는 인용 키를 따른다 (본문 [Yung2025a]와 대응)."""
    suffix = key[-1] if key[-1].isalpha() and key[-2].isdigit() else ""
    b = ref.get("biblio") or {}
    pages = "–".join(p for p in (b.get("first_page"), b.get("last_page")) if p)
    authors = ", ".join(ref.get("authors") or []) if ref.get("user_provided") else apa_author_list(ref.get("authors") or [])  # 기관명은 그대로
    number = f" ({ref['doc_number']})" if ref.get("doc_number") else ""
    head = f"{authors} ({ref.get('year') or 'n.d.'}{suffix}). {ref['title'].rstrip('.')}{number}. "
    parts = [(head, False)]
    if ref.get("venue"):
        parts.append((ref["venue"], True))
        if b.get("volume"):
            parts += [(", ", False), (str(b["volume"]), True)]
            if b.get("issue"):
                parts.append((f"({b['issue']})", False))
        if pages:
            parts.append((f", {pages}", False))
        parts.append((". ", False))
    if ref.get("doi"):
        parts.append((ref["doi"], False))
    return parts


def apa_sort_key(item: tuple[str, dict]) -> tuple:
    """알파벳순: 첫 저자 성 → 연도 → a·b (APA 7판)."""
    key, ref = item
    first = apa_author((ref.get("authors") or [key])[0]).lower()
    return first, ref.get("year") or 0, key


def fulltext_label(ref: dict) -> str:
    """전문 확보 상태: '✓ 자동' / '✓ 수동' / '직접 받기 필요' / '무료 공개 아님'."""
    return ("✓ " if ref.get("pdf_file") else "") + tr(PDF_SOURCE_LABEL.get(ref.get("pdf_status"), tr_later("미확인")))


def role_of(s: dict) -> dict[str, str]:
    """논문 키 → 속한 분야의 역할 표시 이름 (synthesis 전체를 받음 — 주제별 role_names)."""
    return {k: role_label(t, s) for t in s.get("subtopics", []) for k in t["papers"]}


def method_lines(meta: dict, records: list[dict], rules: dict, level_of: dict[str, str],
                 topic: dict | None = None) -> list[tuple[str, bool]]:
    """3장 '검색·선정 방법과 한계'의 사실 목록: (문장, 강조)."""
    p, w, cw = meta["prisma"], meta["weights"], meta["category_weights"]
    years = Counter(r["year"] for r in records)
    lo, hi = (int(y) for y in str(meta["years"]).split("-"))
    missing = [y for y in range(lo, hi + 1) if not years.get(y)]
    passed = p["selected"] + p["below_threshold"] + p["over_limit"]
    reviews = p["reviews_listed"] + p["reviews_not_listed"]
    institutions = p.get("institutions_listed", 0) + p.get("institutions_not_listed", 0)
    cocited = p.get("cocited_listed", 0) + p.get("cocited_not_listed", 0)  # 공통 인용 고전 (별도 목록, 사용자 2026-10-19)
    no_abstract = p.get("excluded_no_abstract", 0)  # 초록 없음 + 인용 백분위 낮음 → 제외 (사용자 2026-10-19)
    research = p["screened"] - p["excluded_retracted"] - no_abstract - reviews - institutions - cocited  # 관련성 채점 모집단
    capped = [q for q in meta.get("query_logs", []) if q.get("stopped_at_limit")]
    review = meta.get("review_rules") or rules["scoring"]["review"]
    overrides = meta.get("scoring_overrides", [])
    title_only = sorted(k for k, v in level_of.items() if v == "제목만")
    # 검증 문구는 실제 수행한 만큼만 (생략·미확인을 완료로 쓰지 않음 — Codex 검토 2026-10-28)
    verified = sum(bool(r.get("verified")) for r in records)
    evaluators = meta.get("review_evaluators")  # 없으면 이 값을 기록하기 전 조사
    review_judged = (tr("'본문 기여' 기준으로 AI 2개가 평가해 둘 다 통과한") if evaluators and evaluators >= 2
                     else tr("'본문 기여' 기준으로 AI 1개가 평가해 통과한 (독립 평가 생략)") if evaluators == 1
                     else tr("'본문 기여' 평가 없이 관련성 기준으로 고른") if evaluators == 0
                     else tr("관련성 기준을 넘고 목록에 오른 (본문 기여 평가 여부는 기록 없음)"))
    # '머리말: 설명' 한 줄씩 (보고서에서 머리말을 굵게 표시). 검색어는 누가 무엇에서 만들었는지와 원문까지 (사용자 피드백 2026-10-15)
    asked = (tr("입력 원문 '{input}' → 확정 주제 '{topic}' · 접근법 '{approach}'",
                input=topic["input"], topic=topic["topic_en"], approach=topic["approach_en"]) if topic
             else tr("입력 주제 '{topic}' · 접근법 '{approach}'", topic=meta["topic"], approach=meta["approach"])
             if meta.get("topic") and meta.get("approach")
             else tr("입력 주제·접근법"))
    confirmed = bool(topic) and topic.get("queries") == meta["queries"]  # 주제 확정 때 사용자가 확인한 검색어 그대로 (사용자 결정 2026-10-21)
    query_list = " / ".join(f"'{q}'" for q in meta["queries"])
    cocited_added = (meta.get("cocited") or {}).get("added_total", 0)
    outside_uncited = sum(r["status"] in OUTSIDE and r["cited_by_count"] == 0 for r in records)
    lines = [
        ((tr("검색어: {asked}을 바탕으로 AI가 만들고 사용자가 확인한 영어 검색어 {n}개 — {queries}",
             asked=asked, n=len(meta["queries"]), queries=query_list) if confirmed
          else tr("검색어: {asked}을 바탕으로 AI가 만든 영어 검색어 {n}개 — {queries}",
                  asked=asked, n=len(meta["queries"]), queries=query_list)), False),
        (tr("검색: {date}, OpenAlex — 출판 {years} 조건, 실제 후보는 {by_year}", date=meta["run_at"][:10], years=meta["years"],
            by_year="·".join(tr("{year}년 {n}편", year=y, n=n) for y, n in sorted(years.items())))
         + (tr(" ({years}년 없음)", years=", ".join(map(str, missing))) if missing else ""), False),
        *([(tr("공통 인용 고전: 관련성 {min_relevance}점 이상 후보 {base}편 중 {threshold}편 이상이 함께 인용한 "
               "검색 밖 문헌 {added}편을 더해 같은 기준으로 채점 (기간 밖 {out_of_period}편은 제외) → 관련성 통과 "
               "{listed}편을 핵심논문과 따로 목록에 둠 (엑셀 '공통 인용 고전') — 초록 없는 고전이 검색에서 빠지는 한계 보완",
               min_relevance=c["min_relevance"], base=c["base"], threshold=c["threshold"], added=c["added_total"],
               out_of_period=c["out_of_period"], listed=p.get("cocited_listed", 0)),
             False)] if (c := meta.get("cocited")) and c.get("added_total") else []),
        *([(tr("초록 없는 후보: 인용 백분위가 낮은 {n}편은 제외, 높은 논문은 제목으로 채점하고 '전문 확인 필요' 표시", n=no_abstract), False)]
          if no_abstract else []),
        (tr("핵심논문 선정: 후보 {screened}편 → 연구 논문 {research}편(리뷰 {reviews}편 분리) → 관련성 {min_relevance}점 이상 "
            "{passed}편 → 총점 순 {selected}편", screened=p["screened"], research=research, reviews=reviews,
            min_relevance=meta["min_relevance"], passed=passed, selected=p["selected"]), True),
        (tr("총점: 관련성 {w_relevance} · 인용 {w_citation} · 학술지 {w_venue} 가중평균 × 문헌 종류 가중치 "
            "(저널 {w_journal} · 학회 {w_conference} · 프리프린트 {w_preprint}) — 인용·학술지는 검색 후보 {n}편 안의 백분위",
            w_relevance=w["relevance"], w_citation=w["citation"], w_venue=w["venue"], w_journal=cw["journal"],
            w_conference=cw["conference"], w_preprint=cw["preprint"], n=p["screened"] - cocited_added), False),
        ((tr("분석 편수: 기준 {min_total_score}은 {basis} — 품질 판정 기준이 아님",
             min_total_score=meta["min_total_score"], basis=tr(rules["scoring"]["min_total_score_basis"]))
          if rules["scoring"].get("min_total_score_basis") and not any(o["key"] == "min_total_score" for o in overrides)
          else tr("분석 편수: 총점 {min_total_score} 이상 — 총점은 조사 우선순위이며 품질 판정이 아님", min_total_score=meta["min_total_score"]))
         + (tr(" (상한 때문에 빠진 논문 {n}편)", n=p["over_limit"]) if p["over_limit"] else ""), True),
        (tr("선정 밖 점검: 관련성은 통과했지만 빠진 {n}편 (총점 미달 {below}편 · 상한 초과 {over}편, 그중 인용 0회 {uncited}편) "
            "— 엑셀 '선정 밖 목록'", n=p["below_threshold"] + p["over_limit"], below=p["below_threshold"], over=p["over_limit"],
            uncited=outside_uncited), False),
        (tr("문헌조사논문(리뷰): 관련성 {min_relevance}점 이상 후보를 {judged} {n}편 (최대 {max_listed}편, 채우지 않음) — 핵심논문 통계에 섞지 않음",
            min_relevance=review["min_relevance"], judged=review_judged, n=p["reviews_listed"], max_listed=review["max_listed"]), False),
        *([(tr("기관·선급 문서: 검색 후보 중 {n}편(실린 곳·발행처가 기관·선급) → 관련성 기준 통과 {listed}편을 "
               "따로 목록에 둠 (핵심논문 통계에 섞지 않음)", n=institutions, listed=p.get("institutions_listed", 0)), False)]
          if institutions else []),
        ((tr("교차 채점: 다른 AI가 {n}편의 관련성을 다시 채점해 낮은 점수 채택 — 재현 가능한 절차일 뿐 신뢰성 입증은 아님", n=verified)
          if verified else tr("교차 채점: 하지 않음 — 관련성은 채점한 AI 하나의 판단")), False),
    ]
    if update := meta.get("update"):  # 누적 갱신 (사용자 지정 방식, merge_runs.py)
        lines.insert(2, (tr("누적 갱신: {base_date} 검색 결과에 같은 검색어로 다시 찾은 새 후보 {added}편을 더해 "
                            "전체를 다시 점수화 → 새로 든 핵심논문 {new}편(NEW), 밀려난 이전 핵심논문 {dropped}편 "
                            "(엑셀 '이전 선정 제외', 이전 결과는 {base}/)", base_date=update["base_date"],
                            added=update["added_candidates"], new=update["new"], dropped=update["dropped"], base=update["base"])
                         + (tr(" — 새 후보 중 관련성은 통과했지만 총점 미달 {n}편 (출판 직후라 인용이 적음, 엑셀 '선정 밖 목록')", n=n)
                            if (n := update.get("fresh_passed_not_selected")) else ""), True))
    if overrides:
        lines.append((tr("기본값과 다른 선정 기준 (사용자 변경 — 권장 기준 아님): {items}",
                         items=" · ".join(f"{o['key']} {o['default']}→{o['value']}({tr(o['source'])})" for o in overrides)), True))
    if capped:
        lines.append((tr("검색 한계: 검색어마다 상위 {retrieved}편만 받음(예상 총 {expected}편), 검색원 1곳", retrieved=capped[0]["retrieved"],
                         expected="·".join(f"{q['expected_total']:,}" for q in capped)), True))
    if title_only:
        lines.append((tr("제목만 검토: 수집 메타데이터에 초록이 없는 {n}편 ({keys})", n=len(title_only), keys=", ".join(title_only)), False))
    return lines


# 쓰는 곳에서 tr(ADJACENT_NOTE)
ADJACENT_NOTE = tr_later("관련성은 선정 기준 아래지만 인용·학술지 점수가 높은 연구논문 — 핵심논문과 별도 참고용, 본문 근거로 쓰지 않음 (점수는 후보 안 상대 순위)")


def adjacent_rows(s: dict, refs: dict) -> list[list]:
    """주목할 인접 문헌 표 (사용자 결정 2026-10-16): [인용 키, 제목, 연도·실린 곳, 피인용, 관련성, 알아 둘 이유]."""
    return [[a["key"], refs[a["key"]]["title"], f"{refs[a['key']]['year']} · {refs[a['key']].get('venue') or ''}",
             refs[a["key"]].get("cited_by_count"), tr("{n}점", n=refs[a["key"]]["relevance"]), a["why"]] for a in s.get("adjacent_guide", [])]


def claim_basis(claim: dict, level_of: dict[str, str]) -> str:
    """편수 주장의 근거 수준 표시 — 요약이 '초록 판독'으로 적었어도 해당 논문 중 본문을 읽은 것이 있으면 그대로 밝힘
    (10-16 Codex 지적: 전문으로 확인한 논문이 섞여도 '초록 판독'으로만 표기)."""
    if claim.get("basis") != "초록 판독":
        return tr(claim.get("basis", ""))  # 요약이 쓴 코드 ('자동 집계' 등) — 표시할 때 번역
    levels = {level_of.get(k) for k in claim.get("keys", [])}
    return (tr("전문 판독") if levels == {"전문"} else tr("초록·전문 판독")) if "전문" in levels else tr("초록 판독")


OUTSIDE = {"below_threshold": tr_later("총점 미달"), "over_limit": tr_later("상한 초과")}  # 관련성은 통과했지만 핵심논문에서 빠진 상태 → 표시 이유 (값은 쓰는 곳에서 tr)


def excluded_rows(records: list[dict], axis: dict) -> list[list]:
    """관련성은 통과했지만 총점 미달·상한 초과로 빠진 논문 (총점 순) — 마지막 칸이 빠진 이유 (10-16 결함: 두 경우가 섞여 '총점 미달'로만 안내)."""
    out = [r for r in records if r["status"] in OUTSIDE]
    rank_from = sum(r["status"] == "selected" for r in records)
    return [[rank_from + i, r["title"], r["year"], tr(CATEGORY_LABEL.get(r["category"], r["category"])), r["cited_by_count"],
             r["relevance"], f"{r['total_score']:.2f}", tr(axis_group(r, axis)), tr(OUTSIDE[r["status"]])]
            for i, r in enumerate(sorted(out, key=lambda r: -r["total_score"]), 1)]


def excluded_comparison(records: list[dict], axis: dict) -> list[list]:
    """핵심논문 vs 선정 밖 분포 비교표: [항목, 핵심논문, 선정 밖]. 가로축(map_axis) 행은 '<축 이름>: 묶음'."""
    sel = [r for r in records if r["status"] == "selected"]
    out = [r for r in records if r["status"] in OUTSIDE]

    def count(pool, key):
        return Counter(key(r) for r in pool)

    rows = []
    for label, key, values in (
            (tr("출판 연도"), lambda r: r["year"], sorted({r["year"] for r in sel + out})),
            (tr("문헌 종류"), lambda r: CATEGORY_LABEL.get(r["category"], r["category"]), list(CATEGORY_LABEL.values())),
            (tr(axis["name"]), lambda r: axis_group(r, axis), axis_labels(axis))):
        a, b = count(sel, key), count(out, key)
        rows += [[f"{label}: {tr(str(v))}", a[v], b[v]] for v in values if a[v] or b[v]]  # 묶음 값은 코드 — 표시만 번역
    rows.append([tr("인용 0회"), sum(r["cited_by_count"] == 0 for r in sel), sum(r["cited_by_count"] == 0 for r in out)])
    rows.append([tr("관련성 5점"), sum(r["relevance"] == 5 for r in sel), sum(r["relevance"] == 5 for r in out)])
    return [[tr("합계"), len(sel), len(out)]] + rows


if __name__ == "__main__":  # 최소 확인
    axis = {"name": "구조물", "groups": [["풍력", ["wind"]], ["기타", [""]]], "field": "structure_type"}
    recs = [{"status": "selected", "year": 2025, "category": "journal", "structure_type": "floating wind", "cited_by_count": 3,
             "relevance": 5, "title": "A", "total_score": 0.7},
            {"status": "below_threshold", "year": 2026, "category": "conference", "structure_type": "FPSO", "cited_by_count": 0,
             "relevance": 4, "title": "B", "total_score": 0.5}]
    assert excluded_rows(recs, axis) == [[2, "B", 2026, "학회", 0, 4, "0.50", "기타", "총점 미달"]]
    table = excluded_comparison(recs, axis)
    assert table[0] == ["합계", 1, 1] and ["구조물: 기타", 0, 1] in table and ["인용 0회", 0, 1] in table
    print("ok")
