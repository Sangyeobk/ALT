import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "alt"))

from cross_verify import agreement, last_json_block, verifier_command  # noqa: E402


def test_claude_default_install_is_found_without_path(monkeypatch, tmp_path):
    import cross_verify
    binary = tmp_path / ".local" / "bin" / "claude.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"binary")
    monkeypatch.setattr(cross_verify.shutil, "which", lambda _: None)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert verifier_command("claude", tmp_path, tmp_path / "report.md")[0] == str(binary)


def test_outputs_without_variant_still_include_report_and_slides():
    from cross_verify import target_files_note
    note = target_files_note("verify_input_outputs.json", "")
    assert "03_report.docx" in note and "04_presentation.pptx" in note
    assert "보지 않음" not in note


def test_codex_desktop_cli_can_be_found_without_path(monkeypatch, tmp_path):
    import cross_verify
    executable = tmp_path / "AppData/Local/OpenAI/Codex/bin/version/codex.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"binary")
    monkeypatch.setattr(cross_verify.shutil, "which", lambda _: None)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert verifier_command("codex", tmp_path, tmp_path / "review.md")[0] == str(executable)


def test_verification_reads_office_text_without_giving_verifier_shell_access(tmp_path):
    from docx import Document
    from cross_verify import verification_outputs
    doc = Document()
    doc.add_paragraph("A documented claim [Kim2026]")
    doc.save(tmp_path / "03_report.docx")
    snapshot = verification_outputs(tmp_path, "")
    assert "A documented claim [Kim2026]" in snapshot["output_texts"]["03_report.docx"]
    assert snapshot["unreadable_outputs"] == []


def test_failed_claude_login_preserves_previous_report(monkeypatch, tmp_path):
    import subprocess
    import cross_verify
    report = tmp_path / "verification_claude.md"
    report.write_text("previous review", encoding="utf-8")
    monkeypatch.setattr(cross_verify.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a[0], 1, "Failed to authenticate: OAuth session expired", ""))
    result = cross_verify.run_verifier("claude", tmp_path, report, "prompt", "test")
    assert result.returncode == 1
    assert report.read_text(encoding="utf-8") == "previous review"
    assert "OAuth session expired" in report.with_suffix(".failed.log").read_text(encoding="utf-8")


def test_agreement_counts_gaps_and_boundary_flips():
    sample = [{"openalex_id": "a", "relevance": 5, "is_review": False},
              {"openalex_id": "b", "relevance": 4, "is_review": False},
              {"openalex_id": "c", "relevance": 3, "is_review": True},
              {"openalex_id": "d", "relevance": 2, "is_review": False}]
    rechecks = [{"openalex_id": "a", "verifier_relevance": 5, "verifier_is_review": False},
                {"openalex_id": "b", "verifier_relevance": 3, "verifier_is_review": False},
                {"openalex_id": "c", "verifier_relevance": 5, "verifier_is_review": False}]
    stats = agreement(sample, rechecks, min_relevance=4)
    assert stats["compared"] == 3 and stats["missing_in_report"] == 1
    assert stats["exact_match"] == 1 and stats["within_1"] == 2
    assert stats["gap_2_or_more"] == ["c"]
    assert stats["selection_boundary_flipped"] == ["b", "c"]
    assert stats["review_judgement_flipped"] == ["c"]


def test_last_json_block_takes_final_block():
    text = 'x ```json\n{"verdict": "old"}\n``` y ```json\n{"verdict": "통과", "relevance_rechecks": []}\n```'
    assert last_json_block(text)["verdict"] == "통과"
    assert last_json_block("no block") is None


def test_verifier_commands_are_read_only():
    codex = verifier_command("codex", Path("run"), Path("run/report.md"))
    assert "read-only" in codex and codex[-1] == "-"
    claude = verifier_command("claude", Path("run"), Path("run/report.md"))
    assert "--allowedTools" in claude and "Write" not in claude and "Bash" not in claude


def test_merge_rechecks_accumulates(tmp_path):
    from cross_verify import merge_rechecks
    path = tmp_path / "verifier_rechecks.json"
    merge_rechecks(path, "codex", [{"openalex_id": "a", "verifier_relevance": 3, "verifier_is_review": False}])
    merged = merge_rechecks(path, "codex", [{"openalex_id": "b", "verifier_relevance": 5}])
    assert set(merged) == {"a", "b"} and merged["a"]["relevance"] == 3 and merged["b"]["is_review"] is None


def test_incomplete_verifier_response_is_not_applied():
    from cross_verify import recheck_problems
    sample = [{"openalex_id": "a"}, {"openalex_id": "b"}]
    ok = [{"openalex_id": "a", "verifier_relevance": 4, "verifier_is_review": False}, {"openalex_id": "b", "verifier_relevance": 0, "verifier_is_review": False}]
    assert recheck_problems(sample, ok) == []
    assert recheck_problems(sample, ok[:1])  # 빠진 논문
    assert recheck_problems(sample, ok + ok[:1])  # 중복
    assert recheck_problems(sample, [ok[0], {"openalex_id": "b", "verifier_relevance": "3"}])  # 문자열 점수
    assert recheck_problems(sample, [{**ok[0], "verifier_is_review": "false"}, ok[1]])  # 문자열 리뷰 판정
    assert recheck_problems(sample, [ok[0], {"openalex_id": "b", "verifier_relevance": 0}])  # 리뷰 판정 빠짐
