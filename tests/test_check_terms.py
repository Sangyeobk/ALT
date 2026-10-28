from pathlib import Path

from check_terms import find_placeholders, find_variants
from common import keyword_tag, load_config, role_label

TERMS = [{"term": "대리모델", "variants": ["메타모델", "surrogate"]},
         {"term": "현장 계측", "variants": ["실측"]}]


def test_find_variants_reports_each_variant_with_context():
    hits = find_variants("메타모델로 학습한 Surrogate 결과를 실측과 비교", TERMS)
    assert [(t, f) for t, f, _ in hits] == [("대리모델", "메타모델"), ("대리모델", "Surrogate"), ("현장 계측", "실측")]
    assert "학습한" in hits[0][2]


def test_find_variants_ignores_canonical_terms_and_partial_english_words():
    assert find_variants("대리모델과 현장 계측 자료, surrogates", TERMS) == []


def test_find_variants_skips_paper_titles():
    title = "Surrogate modeling of wave loads"
    text = f"Kim, A. (2025). {title}. 대리모델 결과"
    assert find_variants(text, TERMS, [title]) == []
    assert len(find_variants(text, TERMS)) == 1


def test_keyword_tag():
    keywords = [{"id": "K1", "term": "검증 기준"}]
    assert keyword_tag({"keyword": "K1"}, keywords) == "[검증 기준] "
    assert keyword_tag({"keyword": "K9"}, keywords) == "" and keyword_tag({}, keywords) == ""


def test_find_placeholders_reports_roundabout_titles():
    hits = find_placeholders("[원리] 선택한 접근법의 기본 단계 / [분포] 문헌지도에서 보이는 것", ["선택한 접근법", "에서 보이는 것"])
    assert [p for p, _ in hits] == ["선택한 접근법", "에서 보이는 것"]
    assert find_placeholders("[원리] 데이터 기반 방법의 기본 단계", ["선택한 접근법"]) == []


def test_builder_code_has_no_placeholder_titles():
    """산출물을 만드는 코드에 자리표시 말이 고정돼 있지 않음 (사용자 피드백 2026-10-16)."""
    phrases = load_config()["output"]["placeholder_phrases"]
    code_dir = Path(__file__).resolve().parents[1] / "alt"
    for name in ("build_pptx.py", "build_docx.py", "write_markdown.py", "make_figures.py", "export_references.py"):
        text = (code_dir / name).read_text(encoding="utf-8")
        assert find_placeholders(text, phrases) == [], name


def test_role_label_prefers_synthesis_role_names():
    s = {"role_names": {"핵심": "하중 산정"}}
    assert role_label({"role": "핵심"}, s) == "하중 산정"
    assert role_label({"role": "확장"}, s) == load_config()["output"]["role_labels"]["확장"]  # 없으면 설정값


def test_verbatim_strings_are_not_counted_as_variants(tmp_path):
    """검색어 원문·입력 원문·범위 결정 이유는 그대로 옮긴 글이라 변이형이 아님 (10-16 결함: 'noon report …' 검색어로 실패)."""
    from check_terms import verbatim_strings
    from common import write_json
    write_json(tmp_path / "candidates.json", {"meta": {"queries": ["noon report ship fuel"]}, "records": []})
    write_json(tmp_path / "topic.json", {"input": "grey-box PINN", "scope_reason": "shaft power만",
                                         "split_out": [{"field": "a", "reason": "white-box"}]})
    names = verbatim_strings(tmp_path)
    terms = [{"term": "정오보고", "variants": ["noon report"]}, {"term": "회색상자", "variants": ["grey-box"]}]
    text = "검색어 'noon report ship fuel' / 입력 grey-box PINN / 본문에서 grey-box 모델"
    assert [found for _, found, _ in find_variants(text, terms, names)] == ["grey-box"]
