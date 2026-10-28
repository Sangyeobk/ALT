"""리뷰 기여 평가 — 불완전한 평가로 '두 AI 모두 기여'를 만들지 않음 (Codex 검토 2026-10-28)."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "alt"))

from review_contribution import contribution_votes, evaluation_problems  # noqa: E402


def test_incomplete_or_duplicated_evaluations_stop_scoring(tmp_path):
    (tmp_path / "review_eval_input.json").write_text(json.dumps({"papers": [{"openalex_id": "a"}, {"openalex_id": "b"}]}), encoding="utf-8")
    full = [{"openalex_id": "a", "contributes": True}, {"openalex_id": "b", "contributes": False}]
    assert evaluation_problems(full, {"a", "b"}) == []
    assert evaluation_problems([{"openalex_id": "a", "contributes": "false"}, full[1]], {"a", "b"})  # 문자열
    (tmp_path / "review_eval_claude.json").write_text(json.dumps(full), encoding="utf-8")
    (tmp_path / "review_eval_codex.json").write_text(json.dumps([full[0], full[0]]), encoding="utf-8")  # 중복 + b 빠짐
    with pytest.raises(SystemExit):
        contribution_votes(tmp_path)
    (tmp_path / "review_eval_codex.json").write_text(json.dumps(full), encoding="utf-8")
    assert contribution_votes(tmp_path) == {"a": True, "b": False}
