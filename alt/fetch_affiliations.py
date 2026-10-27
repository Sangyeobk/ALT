"""후보 논문의 대표 소속 국가·대륙 → affiliations.json (분포 그림의 대륙별 막대용, 사용자 피드백 2026-10-19)

    python alt/fetch_affiliations.py outputs/<run>/

- 기준: 교신저자 소속 국가, 교신저자 표시가 없으면 1저자 소속 국가 (사용자 결정 2026-10-19). 둘 다 없으면 미상.
- 국가 → 대륙은 OpenAlex 국가 정보(countries)의 continent를 그대로 쓴다 (따로 표를 만들지 않음).
- 인터넷 조회만 하므로 토큰을 쓰지 않는다. 이미 받은 논문은 건너뛴다 (--force로 다시).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pyalex
import requests
from pyalex import Works

from common import load_user_settings, read_json, write_json

OPENALEX_ID_BATCH = 50


def lead_country(authorships: list[dict]) -> tuple[str | None, str]:
    """(국가 코드, 기준) — 교신저자 → 1저자 → 미상. 교신저자가 여럿이면 저자 순서상 처음."""
    for basis, pick in (("corresponding", lambda a: a.get("is_corresponding")),
                        ("first", lambda a: a.get("author_position") == "first")):
        for a in authorships or []:
            if pick(a) and a.get("countries"):
                return a["countries"][0], basis
    return None, "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--force", action="store_true", help="이미 받은 논문도 다시")
    args = parser.parse_args()

    settings = load_user_settings()
    pyalex.config.email = settings.get("email")
    pyalex.config.api_key = settings.get("openalex_key")
    path = args.run_dir / "affiliations.json"
    data = read_json(path) if path.is_file() and not args.force else {"works": {}, "countries": {}}

    ids = [r["openalex_id"] for r in read_json(args.run_dir / "candidates.json")["records"]]
    todo = [i.rsplit("/", 1)[-1] for i in ids if i not in data["works"]]
    for start in range(0, len(todo), OPENALEX_ID_BATCH):
        batch = "|".join(todo[start:start + OPENALEX_ID_BATCH])
        for work in Works().filter(openalex_id=batch).select(["id", "authorships"]).get(per_page=OPENALEX_ID_BATCH):
            country, basis = lead_country(work.get("authorships") or [])
            data["works"][work["id"]] = {"country": country, "basis": basis}
    for i in ids:  # OpenAlex에서 못 찾은 논문도 미상으로 남겨 다시 묻지 않음
        data["works"].setdefault(i, {"country": None, "basis": "unknown"})

    codes = sorted({w["country"] for w in data["works"].values() if w["country"]} - set(data["countries"]))
    if codes:
        params = {"per_page": 200, "mailto": settings.get("email")}
        if settings.get("openalex_key"):
            params["api_key"] = settings["openalex_key"]
        response = requests.get("https://api.openalex.org/countries", params=params, timeout=60)
        response.raise_for_status()
        for c in response.json()["results"]:
            if c["country_code"] in codes:
                data["countries"][c["country_code"]] = {"name": c["display_name"],
                                                        "continent": (c.get("continent") or {}).get("display_name")}
    write_json(path, data)
    bases = [w["basis"] for w in data["works"].values()]
    print(f"[affiliations] {len(bases)}편: 교신저자 {bases.count('corresponding')} · 1저자로 대신 {bases.count('first')} · "
          f"미상 {bases.count('unknown')} -> {path}")


if __name__ == "__main__":
    main()
