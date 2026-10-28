"""보고서 피드백 4건 (사용자 2026-10-19): 범위 표 경로 중복, 표 쪽 나뉨 방지, 기술 핵심어 초록색, 논문 수 분포."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "alt"))

from common import keyword_chunks, scope_history, write_json  # noqa: E402
from fetch_affiliations import lead_country  # noqa: E402
from make_figures import UNKNOWN_LABEL, continent_of, distribution_counts  # noqa: E402


def test_scope_history_does_not_repeat_run_folder_already_in_reason(tmp_path):
    write_json(tmp_path / "topic.json", {"input": "x", "split_out": [
        {"field": "PINN", "reason": "새 결과 폴더 outputs/a 에서 세부 조사", "run": "outputs/a"},
        {"field": "SHAP", "reason": "따로 조사", "run": "outputs/b"}]})
    rows = dict((label + str(i), text) for i, (label, text) in enumerate(scope_history(tmp_path)))
    texts = list(rows.values())
    assert texts[1].count("outputs/a") == 1 and texts[2].endswith("→ 결과 폴더 outputs/b")


def test_keyword_chunks_longest_first_and_latin_boundary():
    chunks = keyword_chunks("물리-데이터 하이브리드와 PINNs, xPINN 비교", ["PINN", "물리-데이터 하이브리드", "하이브리드"])
    assert [c for c, tech in chunks if tech] == ["물리-데이터 하이브리드", "PINN"]  # xPINN 안에서는 맞추지 않음
    assert "".join(c for c, _ in chunks) == "물리-데이터 하이브리드와 PINNs, xPINN 비교"
    assert keyword_chunks("글", []) == [("글", False)] and keyword_chunks("", ["a"]) == []


def test_lead_country_corresponding_then_first_then_unknown():
    a = [{"author_position": "first", "countries": ["KR"]}, {"author_position": "last", "is_corresponding": True, "countries": ["NO"]}]
    assert lead_country(a) == ("NO", "corresponding")
    a[1]["countries"] = []  # 교신저자 국가가 없으면 1저자
    assert lead_country(a) == ("KR", "first")
    assert lead_country([{"author_position": "first", "countries": []}]) == (None, "unknown")


def test_distribution_counts_core_and_unknown_last():
    aff = {"works": {"W1": {"country": "KR"}, "W2": {"country": "NO"}, "W3": {"country": None}},
           "countries": {"KR": {"continent": "Asia"}, "NO": {"continent": "Europe"}}}
    pool = [{"openalex_id": w, "status": s} for w, s in (("W1", "selected"), ("W2", "other"), ("W3", "other"), ("W4", "selected"))]
    counts = distribution_counts(pool, lambda r: continent_of(r, aff))
    assert counts[-1] == (UNKNOWN_LABEL, 2, 1) and ("아시아", 1, 1) in counts
    assert distribution_counts(pool, lambda r: "가", ["나", "가"]) == [("나", 0, 0), ("가", 4, 2)]  # 정한 순서·0편 묶음


def test_docx_keep_together_short_table_and_box():
    from build_docx import Report
    rpt = Report()
    rpt.table(["a", "b"], [["1", "2"], ["3", "4"]], [3, 3])
    rpt.key_box("제목", ["한 줄", "두 줄"])
    short, box = rpt.doc.tables
    assert all(row._tr.trPr.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}cantSplit") is not None for row in short.rows)
    assert all(p.paragraph_format.keep_with_next for row in short.rows[:-1] for c in row.cells for p in c.paragraphs)
    assert all(p.paragraph_format.keep_with_next for p in box.rows[0].cells[0].paragraphs[:-1])
