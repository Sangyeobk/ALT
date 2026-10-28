"""처음 한 번 실행 환경 준비 (사용자 결정 2026-10-27 — 사용자가 직접 할 일 최소화)."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "alt"))

from setup_env import missing_modules, required_modules, venv_python  # noqa: E402


def test_required_modules_map_import_names_and_skip_dev_tools(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("python-docx>=1.2\npyyaml>=6.0  # yaml\npytest>=8\nrequests\n", encoding="utf-8")
    assert required_modules(req) == ["docx", "yaml", "requests"]


def test_check_reports_missing_venv_and_current_python_is_ready(tmp_path):
    assert missing_modules(venv_python(tmp_path / "none"), ["yaml"]) == ["yaml"]
    assert missing_modules(Path(sys.executable), ["json", "no_such_module_x"]) == ["no_such_module_x"]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}  # Windows 기본(cp949) 출력을 utf-8로 읽기 위해
    result = subprocess.run([sys.executable, str(ROOT / "alt" / "setup_env.py"), "--check", "--target", str(tmp_path / "none")],
                            capture_output=True, text=True, encoding="utf-8", env=env)
    assert result.returncode == 1 and "가상환경 없음" in result.stdout


def test_version_below_minimum_is_not_ready(tmp_path):
    from setup_env import required_specs
    req = tmp_path / "requirements.txt"
    req.write_text("pyyaml>=6.0\nrequests>=999\n", encoding="utf-8")
    specs = required_specs(req)
    assert specs == ["pyyaml|yaml|6.0", "requests|requests|999"]
    assert missing_modules(Path(sys.executable), specs) == ["requests"]  # 있지만 버전이 낮음
