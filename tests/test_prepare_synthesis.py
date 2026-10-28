import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "alt"))

from fetch_open_access import is_pdf  # noqa: E402
from prepare_synthesis import assign_keys, family_name  # noqa: E402


def test_family_name_ascii_and_fallback():
    assert family_name("José Müller") == "Muller"
    assert family_name(None) == "Anon"


def test_assign_keys_suffixes_only_collisions():
    records = [{"openalex_id": "1", "authors": ["A Kim"], "year": 2025},
               {"openalex_id": "2", "authors": ["B Kim"], "year": 2025},
               {"openalex_id": "3", "authors": ["C Lee"], "year": 2026}]
    assert assign_keys(records) == {"1": "Kim2025a", "2": "Kim2025b", "3": "Lee2026"}


def test_apa_reference_format():
    from report_facts import apa_author, apa_reference
    assert apa_author("Sanne van Essen") == "van Essen, S."
    assert apa_author("Jia-Wang Chen") == "Chen, J.-W."
    assert apa_author("D. Stamenov") == "Stamenov, D."
    ref = {"authors": ["Weikai Tan", "Pu Ren", "Hao Chen"], "year": 2025, "title": "Data-driven modelling",
           "venue": "Marine Structures", "doi": "https://doi.org/10.1/x",
           "biblio": {"volume": "100", "issue": "2", "first_page": "1", "last_page": "9"}}
    text = "".join(t for t, _ in apa_reference("Tan2025", ref))
    assert text == ("Tan, W., Ren, P., & Chen, H. (2025). Data-driven modelling. Marine Structures, 100(2), 1–9. "
                    "https://doi.org/10.1/x")
    assert "(2025a)" in "".join(t for t, _ in apa_reference("Tan2025a", ref))


def test_stable_keys_keep_previous_and_avoid_collisions():
    from prepare_synthesis import stable_keys
    records = [{"openalex_id": "1", "authors": ["A Singh"], "year": 2025},
               {"openalex_id": "2", "authors": ["B Singh"], "year": 2025}]
    assert stable_keys(records, {"1": "Singh2025"}) == {"1": "Singh2025", "2": "Singh2025b"}
    # 목록에서 빠진 논문(1)의 키는 새 논문(2)이 가져가지 않음 — 돌아오면 같은 키, 본문 정리도 그대로 찾음 (10-19)
    assert stable_keys(records[1:], {"1": "Singh2025"}) == {"2": "Singh2025b"}


def test_review_level_needs_fulltext_notes_for_full():
    from prepare_synthesis import review_level
    assert review_level("Tan2025", "abstract", {"Tan2025": {}}) == "전문"
    assert review_level("Tan2025", "abstract", {}) == "초록"
    assert review_level("Xing2026", None, {}) == "제목만"


def test_cite_adds_page_numbers_for_fulltext_claims():
    from common import cite
    assert cite({"cites": ["Tan2025", "Lee2026"], "pages": {"Tan2025": 7}}) == " [Tan2025, p.7; Lee2026]"
    assert cite({"cites": [], "source": "일반 개념"}) == " [일반 개념]"
    assert cite({"cites": ["A2025", "B2025", "C2025", "D2025"]}, limit=3) == " [A2025; B2025; C2025 외 1편]"


def test_cut_references_only_cuts_late_heading():
    from extract_fulltext import cut_references
    body = "Intro\nReferences\nearly mention kept\n" + "body text\n" * 50
    assert cut_references(body + "References\n[1] A. Kim", ["References"]) == body.rstrip()
    assert cut_references(body, ["References"]) == body


def test_is_pdf():
    assert is_pdf(b"%PDF-1.7") and not is_pdf(b"<html>")


def test_cited_keys_finds_bracketed_and_cell_keys():
    from check_citations import cited_keys
    text = "주장 [Kim2025a; Lee2026] 그리고 [일반 개념]\nPark2025\n제목 2025년 [ISSC 2018 아님]"
    assert cited_keys(text) == {"Kim2025a", "Lee2026", "Park2025"}


def test_cite_format():
    from common import cite
    assert cite({"cites": ["A2025", "B2026"]}) == " [A2025; B2026]"
    assert cite({"cites": [], "source": "일반 개념"}) == " [일반 개념]"
    assert cite({"cites": []}) == ""


def test_abbreviations_expand_first_occurrence_only():
    from common import Abbreviations
    abbr = Abbreviations({"RAO": "Response Amplitude Operator", "RB": "Regression-Based"})
    assert abbr("RAO 계산") == "RAO(Response Amplitude Operator) 계산"
    assert abbr("다시 RAO") == "다시 RAO"
    other = Abbreviations({"RAO": "Response Amplitude Operator"})
    assert other("RAO (응답진폭연산자)") == "RAO (Response Amplitude Operator, 응답진폭연산자)"
    assert Abbreviations({"RB": "Regression-Based"})("회귀 기반(RB) 방법") == "회귀 기반(RB, Regression-Based) 방법"
    assert Abbreviations({"CFD": "Computational Fluid Dynamics"})("해석(CFD 등)") == "해석(CFD, Computational Fluid Dynamics 등)"
    assert Abbreviations({"RAO": "x"})("RAOS and PRAO") == "RAOS and PRAO"


def test_abbreviations_skip_formulas_and_verbatim_text():
    from common import Abbreviations
    abbr = Abbreviations({"MF": "Membership Function"})  # 10-16 결함: 연료식 기호 MF에 풀이가 붙음
    assert abbr("식 `MF = ΔPB · SFOC` 이후 3 MF") == "식 `MF = ΔPB · SFOC` 이후 3 MF(Membership Function)"
    raw = "PINN·물리-데이터 하이브리드"  # 입력 원문은 그대로 — 풀이는 그 뒤 처음 나올 때
    abbr = Abbreviations({"PINN": "Physics-Informed Neural Network"}, protected=[raw])
    assert abbr(f"입력 원문: {raw}") == f"입력 원문: {raw}"
    assert abbr("PINN 연구") == "PINN(Physics-Informed Neural Network) 연구"


def test_abbreviations_do_not_expand_twice():
    from common import Abbreviations
    table = {"RAO": "Response Amplitude Operator"}
    once = Abbreviations(table)("RAO (응답진폭연산자)")
    assert Abbreviations(table)(once) == once
