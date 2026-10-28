"""맞춤 결과물 스크립트는 SKILL대로 인자 <run> 하나로 실행 (Codex 검토 2026-10-28 — 예전엔 --variant를 덧붙여 실패)."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_extras_script_gets_only_run_dir(tmp_path):
    extras = tmp_path / "project" / "extras"
    extras.mkdir(parents=True)
    (extras / "one.py").write_text(
        "import sys, pathlib\nassert len(sys.argv) == 2, sys.argv\n(pathlib.Path(sys.argv[1]) / '07_x.txt').write_text('ok')\n",
        encoding="utf-8")
    (tmp_path / "project" / "extras.yaml").write_text("- name: x\n  script: one.py\n  outputs: [07_x.txt]\n", encoding="utf-8")
    result = subprocess.run([sys.executable, str(ROOT / "alt" / "run_extras.py"), str(tmp_path)], capture_output=True)
    assert result.returncode == 0 and (tmp_path / "07_x.txt").is_file()
