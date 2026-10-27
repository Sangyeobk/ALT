"""개인 설정 저장: 이메일(Unpaywall·Crossref 연락처)과 API 키(모두 선택).

    python alt/settings.py --email name@example.com
    python alt/settings.py --openalex-key --from-clipboard   # 키를 복사해 두고 실행 (화면·명령 기록에 남지 않음)
    python alt/settings.py --elsevier-key      # 키는 화면에 보이지 않게 입력받음 (명령 기록에 남지 않게)
    python alt/settings.py --core-key
    python alt/settings.py --skip-openalex-key  # OpenAlex 키 안내를 거절했다고 기록 (다음부터 묻지 않음)
    python alt/settings.py --show                 # 설정 + 개인 스타일·검색 취향 내용
    python alt/settings.py --add-style "결론은 표 없이 세 줄로" --run 20261013_test_waveloads
    python alt/settings.py --add-search-pref "부유식 해상풍력(FOWT)은 늘 검색어에 포함" --run 20261013_test_waveloads
    python alt/settings.py --set-scoring max_selected=20 [--project outputs/<run>]   # 선정 기준 (권장하지 않음 — 경고 출력)
"""

import argparse
import subprocess
from datetime import date
from getpass import getpass

from pathlib import Path

from common import (SCORING_WARNING, USER_SEARCH_PREFS_PATH, USER_SETTINGS_PATH, USER_STYLE_PATH, add_preference, load_search_prefs,
                    load_user_settings, load_user_style, save_user_settings, set_scoring)

PROMPTED_KEYS = {"openalex_key": "OpenAlex API key", "elsevier_key": "Elsevier API key", "core_key": "CORE API key"}


def read_clipboard() -> str:
    """Windows 클립보드 글 (키를 화면·명령 기록에 남기지 않고 넣기 위해)."""
    return subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
                          capture_output=True, text=True, check=True).stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email")
    parser.add_argument("--openalex-key", action="store_true")
    parser.add_argument("--skip-openalex-key", action="store_true", help="키 안내 거절 기록 (예산 소진 때만 다시 안내)")
    parser.add_argument("--elsevier-key", action="store_true")
    parser.add_argument("--core-key", action="store_true")
    parser.add_argument("--from-clipboard", action="store_true")
    parser.add_argument("--show", action="store_true")
    parser.add_argument("--add-style", metavar="TEXT", help="개인 스타일(문체·구성 취향) 한 줄 추가")
    parser.add_argument("--add-search-pref", metavar="TEXT", help="검색 취향 한 줄 추가 (① 검색어 확장에만 쓰임)")
    parser.add_argument("--run", help="취향이 나온 결과 폴더 이름 (기록용)")
    parser.add_argument("--set-scoring", metavar="KEY=VALUE", help="선정 기준 바꾸기 (config.yaml scoring 항목, 권장하지 않음)")
    parser.add_argument("--project", type=Path, help="--set-scoring을 이 결과 폴더(조사)에만 적용 (project/settings.yaml)")
    args = parser.parse_args()

    if args.set_scoring:
        print(f"주의: {SCORING_WARNING}")
        print(f"saved: {set_scoring(args.set_scoring, args.project)} — 다음 점수화(⑤)부터 반영")
        return

    if args.show:
        settings = load_user_settings()
        print(f"file: {USER_SETTINGS_PATH}")
        print(f"email: {'set' if settings.get('email') else 'missing'}")
        if settings.get("scoring"):
            print(f"scoring (기본값과 다른 선정 기준 — 권장하지 않음): {settings['scoring']}")
        for name in PROMPTED_KEYS:
            declined = settings.get(f"{name}_declined")
            print(f"{name}: {'set' if settings.get(name) else f'not set (declined {declined})' if declined else 'not set (optional)'}")
        for label, path, text in (("report_style", USER_STYLE_PATH, load_user_style()),
                                  ("search_prefs", USER_SEARCH_PREFS_PATH, load_search_prefs())):
            print(f"--- {label}: {path}" + ("" if text else " (없음)"))
            if text:
                print(text.rstrip())
        return
    if args.add_style or args.add_search_pref:
        for kind, text in (("style", args.add_style), ("search", args.add_search_pref)):
            if text:
                print(f"added: {add_preference(kind, text, args.run)}")
        return
    if "@" not in (args.email or "@"):
        parser.error("email looks invalid")
    keys = {name: (read_clipboard() if args.from_clipboard else getpass(f"{label}: ")).strip()
            for name, label in PROMPTED_KEYS.items() if getattr(args, name)}
    if args.from_clipboard and len(keys) != 1:
        parser.error("--from-clipboard는 키 하나와 함께 쓴다 (--openalex-key, --elsevier-key, --core-key 중 하나)")
    if any(len(k) < 16 or " " in k for k in keys.values()):  # 클립보드에 키가 아닌 글이 있을 때
        parser.error("키 모양이 아님 (16자 미만이거나 공백 포함) — 키를 다시 복사하고 실행")
    declined = {"openalex_key_declined": date.today().isoformat()} if args.skip_openalex_key else {}
    path = save_user_settings(email=args.email, **keys, **declined)
    print(f"saved: {path}")


if __name__ == "__main__":
    main()
