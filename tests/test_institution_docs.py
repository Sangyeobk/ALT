"""기관·선급 문서 = 문헌의 한 카테고리 (사용자 결정 2026-10-16): 분류·별도 목록·사용자 PDF·인용 키·참고문헌 형식."""
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "alt"))

from add_institution_docs import load_user_docs  # noqa: E402
from export_references import bibtex  # noqa: E402
from prepare_synthesis import assign_keys  # noqa: E402
from report_facts import apa_reference  # noqa: E402
from score_papers import document_category, select  # noqa: E402

NAMES = {"names": ["ISSC", "ITTC", "ABS", "Korean Register", "Lloyd's Register"], "doc_words": ["committee", "report", "guideline"]}


def test_institution_only_outside_journals_and_by_whole_word():
    assert document_category({"type": "book-chapter", "venue": "Proceedings of the 21st ISSC", "venue_type": "conference"}, NAMES) == "institution"
    assert document_category({"type": "report", "venue": None, "publisher": "Lloyd's Register", "venue_type": None}, NAMES) == "institution"
    assert document_category({"type": "article", "venue": "ITTC Journal", "venue_type": "journal"}, NAMES) == "journal"  # 학술지는 논문
    assert document_category({"type": "report", "venue": "ABSTRACTS of OMAE", "venue_type": None}, NAMES) == "other"  # 단어 일부는 아님
    assert document_category({"type": "report", "venue": "Proceedings of the 21st ISSC", "venue_type": None}) == "other"  # 목록 없으면 기존대로
    # 제목: 기관 이름 + 문서 단어 → 실린 곳과 상관없이 (ISSC 위원회 보고서의 저장소 사본·학술지 요약본, 10-16 OpenAlex 확인)
    assert document_category({"type": "article", "venue": "Marine Structures", "venue_type": "journal",
                              "title": "Summary of the ISSC report of committee II.2: dynamic response"}, NAMES) == "institution"
    assert document_category({"type": "article", "venue": "Marine Structures", "venue_type": "journal",
                              "title": "Highlights and future research areas from ISSC 2022"}, NAMES) == "journal"  # 문서 단어 없음
    assert document_category({"type": "article", "venue": "Ocean Eng.", "venue_type": "journal",
                              "title": "Seakeeping tests reported against classification guidelines"}, NAMES) == "journal"  # 기관 이름 없음


def test_institution_docs_listed_apart_from_selection():
    records = []
    for oid, total, category, relevance in (("a", 0.9, "journal", 4), ("i1", 0.95, "institution", 4),
                                            ("i2", 0.8, "institution", 2), ("b", 0.7, "journal", 4)):
        records.append({"openalex_id": oid, "total_score": total, "category": category, "relevance": relevance,
                        "exclude": False, "is_review": False})
    select(records, min_total=0.6, max_selected=1, institutions={"min_relevance": 3, "max_listed": 10})
    status = {r["openalex_id"]: r["status"] for r in records}
    assert status == {"i1": "institution_listed", "i2": "institution_not_listed", "a": "selected", "b": "over_limit"}


def write_docs(run, docs):
    (run / "standards").mkdir(parents=True, exist_ok=True)
    (run / "standards" / "docs.yaml").write_text(yaml.safe_dump(docs, allow_unicode=True), encoding="utf-8")


def test_user_docs_need_filled_fields_and_get_org_keys(tmp_path):
    assert load_user_docs(tmp_path) == []
    write_docs(tmp_path, [{"file": "a.pdf", "org": "Korean Register", "org_short": "KR", "title": "Guidance for X",
                           "year": 2024, "doc_number": "GC-01-E"}])
    [doc] = load_user_docs(tmp_path)
    assert doc["openalex_id"] == "local:a.pdf" and doc["status"] == "institution_listed" and doc["user_provided"]
    assert assign_keys([doc]) == {"local:a.pdf": "KR2024"}
    write_docs(tmp_path, [{"file": "b.pdf", "org": "ISSC", "org_short": "", "title": "Report", "year": 2018}])
    with pytest.raises(SystemExit):        # 원문에서 못 채운 칸이 있으면 멈춤 (지어내지 않음)
        load_user_docs(tmp_path)


def test_institution_reference_formats():
    ref = {"key": "KR2024", "category": "institution", "user_provided": True, "authors": ["Korean Register"], "year": 2024,
           "title": "Guidance for X", "venue": "Korean Register", "doc_number": "GC-01-E", "doi": None}
    text = "".join(t for t, _ in apa_reference("KR2024", ref))
    assert text.startswith("Korean Register (2024). Guidance for X (GC-01-E). ")   # 기관명은 사람 이름처럼 줄이지 않음
    entry = bibtex(ref)
    assert entry.startswith("@techreport{KR2024") and "institution = {Korean Register}" in entry and "number = {GC-01-E}" in entry
