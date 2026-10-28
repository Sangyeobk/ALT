import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "alt"))

from check_integrity import judge  # noqa: E402

RULES = {"exclude_notice_types": ["retraction", "withdrawal", "removal"],
         "flag_notice_types": ["expression_of_concern"]}


def test_crossref_retraction_excludes():
    result = judge({"is_retracted": False}, ["correction", "retraction"], None, RULES)
    assert result["exclude"] and "철회됨" in result["flags"]


def test_openalex_retracted_flag_excludes_even_without_crossref():
    assert judge({"is_retracted": True}, [], None, RULES)["exclude"]


def test_correction_and_concern_do_not_exclude():
    result = judge({"is_retracted": False}, ["correction", "expression_of_concern"], True, RULES)
    assert not result["exclude"]
    assert result["flags"] == ["공지: expression_of_concern"]


def test_doaj_missing_is_flag_only():
    result = judge({"is_retracted": False}, [], False, RULES)
    assert not result["exclude"] and "DOAJ 미등재" in result["flags"][0]


def test_failed_crossref_lookup_is_reported_not_hidden():
    result = judge({"is_retracted": False}, None, None, RULES)
    assert result["crossref_checked"] is False and not result["exclude"]
