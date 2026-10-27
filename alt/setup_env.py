"""ALT 실행 환경 준비 — 처음 한 번, 사용자 대신 에이전트가 실행 (사용자 결정 2026-10-27: 사용자가 직접 할 일 최소화).
표준 라이브러리만 쓰므로 패키지가 없는 파이썬으로도 실행된다.

    python alt/setup_env.py --check     # 준비됐으면 'ready <파이썬 경로>' (종료 코드 0), 아니면 빠진 것 (종료 코드 1)
    python alt/setup_env.py             # 없으면 가상환경을 만들고 requirements.txt 패키지를 설치한 뒤 확인

가상환경 위치: %USERPROFILE%/.venvs/alt (OneDrive 같은 동기화 폴더 밖 — agent_guide.md '실행 환경'과 같음).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = Path.home() / ".venvs" / "alt"
IMPORT_NAMES = {"python-docx": "docx", "python-pptx": "pptx", "pyyaml": "yaml"}   # 패키지 이름 ≠ 불러올 이름인 것만
SKIP = {"pytest"}   # 개발용 — 조사 실행에는 필요 없음


def venv_python(target: Path) -> Path:
    return target / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def required_modules(requirements: Path) -> list[str]:
    names = []
    for line in requirements.read_text(encoding="utf-8").splitlines():
        name = line.split("#")[0].strip().split(">")[0].split("=")[0].split("<")[0].strip().lower()
        if name and name not in SKIP:
            names.append(IMPORT_NAMES.get(name, name))
    return names


def missing_modules(python: Path, modules: list[str]) -> list[str]:
    """그 파이썬에서 불러오지 못하는 모듈 (파이썬이 없으면 전부)."""
    if not python.is_file():
        return modules
    code = "import importlib.util,sys;print(' '.join(m for m in sys.argv[1:] if importlib.util.find_spec(m) is None))"
    result = subprocess.run([str(python), "-c", code, *modules], capture_output=True, text=True)
    return result.stdout.split() if result.returncode == 0 else modules


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET, help="가상환경 폴더 (시험용)")
    args = parser.parse_args()
    requirements = ROOT / "requirements.txt"
    modules = required_modules(requirements)
    python = venv_python(args.target)
    missing = missing_modules(python, modules)
    if not missing:
        print(f"ready {python}")
        return
    if args.check:
        print(f"[setup] 실행 환경 준비 필요 — {'가상환경 없음' if not python.is_file() else '빠진 패키지: ' + ', '.join(missing)} ({args.target})")
        raise SystemExit(1)
    if sys.version_info < (3, 10):
        raise SystemExit(f"[setup] 파이썬 3.10 이상 필요 (지금 {sys.version.split()[0]}) — 3.12 권장")
    if not python.is_file():
        print(f"[setup] 가상환경 만드는 중: {args.target}")
        venv.EnvBuilder(with_pip=True).create(args.target)
    print("[setup] 패키지 설치 중 (처음 한 번, 몇 분 걸릴 수 있음)…")
    result = subprocess.run([str(python), "-m", "pip", "install", "-q", "-r", str(requirements)], capture_output=True, text=True)
    if result.returncode != 0:  # 원문 그대로 보여 줌 (사내망 인증서·프록시 문제 등은 사용자·IT 확인 필요)
        raise SystemExit("[setup] 패키지 설치 실패:\n" + (result.stderr or result.stdout)[-2000:])
    missing = missing_modules(python, modules)
    if missing:
        raise SystemExit(f"[setup] 설치 뒤에도 빠진 패키지: {', '.join(missing)}")
    print(f"ready {python}")


if __name__ == "__main__":
    main()
