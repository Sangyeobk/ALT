import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "alt"))

import cross_verify  # noqa: E402
from usage_log import claude_usage, codex_usage, save, summary  # noqa: E402


def line(message_id, usage, model="claude-x"):
    return json.dumps({"type": "assistant", "message": {"id": message_id, "model": model, "usage": usage}})


def test_claude_usage_counts_each_call_once(tmp_path):
    u1 = {"input_tokens": 2, "cache_creation_input_tokens": 67494, "cache_read_input_tokens": 0, "output_tokens": 7}
    u2 = {"input_tokens": 5, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 67494, "output_tokens": 50}
    transcript = tmp_path / "agent-x.jsonl"
    transcript.write_text("\n".join([json.dumps({"type": "user"}), line("m1", u1), line("m1", u1), line("m2", u2)]),
                          encoding="utf-8")  # 같은 호출(m1)이 두 줄로 기록됨
    usage = claude_usage(transcript)
    assert usage["calls"] == 2 and usage["model"] == "claude-x"
    assert (usage["input"], usage["cache_write"], usage["cache_read"], usage["output"]) == (7, 67594, 67494, 57)


def test_codex_usage_separates_cached_input():
    events = "\n".join(['{"type":"thread.started"}', "not json",
                        '{"type":"turn.completed","usage":{"input_tokens":18771,"cached_input_tokens":13440,'
                        '"cache_write_input_tokens":0,"output_tokens":5}}'])
    usage = codex_usage(events)
    assert (usage["calls"], usage["input"], usage["cache_read"], usage["output"]) == (1, 5331, 13440, 5)
    assert codex_usage("no events") is None


def test_records_are_separate_files_and_summed_by_step(tmp_path):
    base = {"source": "claude", "model": "m", "calls": 1, "input": 1, "cache_write": 10, "cache_read": 0, "output": 2}
    save(tmp_path, "본문정리", "a1", base, estimate=100)
    save(tmp_path, "본문정리", "a2", base, estimate=50)  # 병렬 에이전트 — 서로 덮어쓰지 않음
    save(tmp_path, "요약", "a3", base)
    rows = {r["step"]: r for r in summary(tmp_path)}
    assert len(list((tmp_path / "usage").glob("*.json"))) == 3
    assert rows["본문정리"]["runs"] == 2 and rows["본문정리"]["total"] == 26 and rows["본문정리"]["estimate"] == 150
    assert rows["요약"]["calls"] == 1


def fake_codex(stdout, report_text="보고서"):
    def run(command, **kwargs):
        Path(command[command.index("-o") + 1]).write_text(report_text, encoding="utf-8")  # codex가 -o로 쓰는 보고서
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")
    return run


def test_run_verifier_logs_codex_usage_and_keeps_report(tmp_path, monkeypatch):
    events = '{"type":"turn.completed","usage":{"input_tokens":10,"cached_input_tokens":4,"output_tokens":3}}'
    monkeypatch.setattr(cross_verify.subprocess, "run", fake_codex(events))
    report = tmp_path / "verification_codex.md"
    result = cross_verify.run_verifier("codex", tmp_path, report, "prompt", step="교차검증")
    assert result.returncode == 0 and report.read_text(encoding="utf-8") == "보고서"
    [record] = summary(tmp_path)
    assert record["step"] == "교차검증" and record["input"] == 6 and record["cache_read"] == 4


def test_run_verifier_without_usage_only_warns(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cross_verify.subprocess, "run", fake_codex("plain text"))
    report = tmp_path / "r.md"
    cross_verify.run_verifier("codex", tmp_path, report, "prompt", step="문서검토")
    assert report.is_file() and not (tmp_path / "usage").exists()
    assert "사용량을 읽지 못함" in capsys.readouterr().out


def test_codex_command_asks_for_json_events():
    assert "--json" in cross_verify.verifier_command("codex", Path("run"), Path("run/r.md"))

def test_add_session_reads_main_transcript(tmp_path, monkeypatch):
    import usage_log
    session = tmp_path / "projects" / "F--work" / "sess-1.jsonl"
    session.parent.mkdir(parents=True)
    u = {"input_tokens": 3, "cache_creation_input_tokens": 50, "cache_read_input_tokens": 400, "output_tokens": 9}
    session.write_text("\n".join([line("s1", u), line("s1", u), line("s2", u)]), encoding="utf-8")
    monkeypatch.setattr(usage_log, "TRANSCRIPTS", tmp_path / "projects")
    monkeypatch.setattr(sys, "argv", ["x", "add-session", str(tmp_path), "--step", "주세션", "--session-id", "sess-1"])
    usage_log.main()
    [row] = summary(tmp_path)
    assert row["step"] == "주세션" and row["calls"] == 2 and row["cache_read"] == 800


def test_calibration_ratio_needs_real_change(tmp_path):
    from usage_log import add_calibration, pct_per_token
    path = tmp_path / "calib.jsonl"
    assert pct_per_token(path) is None                       # 기록 없음
    add_calibration(path, "run", "관련성", 17, 17, 400_000)   # 사용률이 정수라 변화 0 → 아직 환산 못 함
    assert pct_per_token(path) is None
    add_calibration(path, "run", "본문정리", 20, 24, 1_600_000)
    add_calibration(path, "run", "요약", 90, 5, 300_000)       # 한도 초기화를 건넌 기록은 뺌
    assert abs(pct_per_token(path) - 4 / 2_000_000) < 1e-12


def test_budget_rows_and_unknown_steps(capsys):
    from usage_log import budget, print_budget
    reference = {"관련성": {"per": "paper", "tokens": 3050}, "본문정리": {"per": "fulltext", "tokens": 278000},
                 "요약": {"per": "run", "tokens": None}}
    rows = budget({"paper": 520, "fulltext": 0, "run": 1}, reference, ratio=1e-5)
    assert [r["step"] for r in rows] == ["관련성", "요약"]       # 본문 정리 0편 → 뺌
    assert rows[0]["tokens"] == 1_586_000 and abs(rows[0]["pct"] - 15.86) < 1e-9
    assert rows[1]["tokens"] is None and rows[1]["pct"] is None
    print_budget(rows, used=90, ratio=1e-5)
    out = capsys.readouterr().out
    assert "약 15.9%" in out and "실행 뒤 약 106%" in out and "한도를 넘음" in out and "실측 없음" in out
    print_budget(rows, used=17, ratio=None)
    assert "% 환산 불가" in capsys.readouterr().out


def test_pct_per_token_uses_same_model_records_only(tmp_path):
    """모델마다 한도 소모가 달라 같은 모델 기록으로만 보정 (10-16: 같은 처리량에 Fable이 Opus 기록의 약 3배)."""
    from usage_log import add_calibration, pct_per_token
    path = tmp_path / "cal.jsonl"
    add_calibration(path, "r", "관련성", 2, 3, 2_000_000, "opus")
    add_calibration(path, "r", "관련성", 11, 20, 3_000_000, "fable")
    assert pct_per_token(path, "opus") == 1 / 2_000_000
    assert pct_per_token(path) == 9 / 3_000_000  # 기본: 가장 최근 기록의 모델
    assert pct_per_token(path, "haiku") is None


def test_budget_without_usage_percent_and_lists_unknown_steps(capsys):
    from usage_log import print_budget
    print_budget([{"step": "관련성", "count": 10, "per": "paper", "tokens": 1000, "pct": 2.0}], None, 0.002, ["본문정리"])
    out = capsys.readouterr().out
    assert "지금 사용률은 확인 못 함" in out and "실행 뒤" not in out and "본문정리" in out


def test_other_service_is_a_separate_row(tmp_path):
    from usage_log import save, summary
    base = {"calls": 1, "input": 10, "cache_write": 0, "cache_read": 0, "output": 0, "model": None}
    save(tmp_path, "문헌조사논문평가", "a", {"source": "claude", **base})
    save(tmp_path, "문헌조사논문평가", "b", {"source": "codex", **base})
    rows = {(r["step"], r["source"]): r["total"] for r in summary(tmp_path)}
    assert rows == {("문헌조사논문평가", "claude"): 10, ("문헌조사논문평가", "codex"): 10}  # 합치지 않음, 보정은 claude 행만
