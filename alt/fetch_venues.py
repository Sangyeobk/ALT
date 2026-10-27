"""후보 논문이 실린 학술지·학회(OpenAlex source) 정보 → venues.json

    python alt/fetch_venues.py outputs/<run>/candidates.json

저널 수준 점수(2yr_mean_citedness, h_index)와 DOAJ 등재 여부(is_oa, is_in_doaj)를 한 번에 가져온다.
"""

import argparse
from pathlib import Path

import pyalex
from pyalex import Sources

from common import load_user_settings, read_json, write_json

OPENALEX_ID_BATCH = 50
SOURCE_FIELDS = ["id", "display_name", "type", "is_oa", "is_in_doaj", "summary_stats", "host_organization_name"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("candidates", type=Path)
    args = parser.parse_args()

    settings = load_user_settings()
    pyalex.config.email = settings.get("email")
    pyalex.config.api_key = settings.get("openalex_key")

    venue_ids = sorted({r["venue_id"].rsplit("/", 1)[-1] for r in read_json(args.candidates)["records"] if r["venue_id"]})
    venues = {}
    for start in range(0, len(venue_ids), OPENALEX_ID_BATCH):
        batch = "|".join(venue_ids[start:start + OPENALEX_ID_BATCH])
        for source in Sources().filter(openalex_id=batch).select(SOURCE_FIELDS).get(per_page=OPENALEX_ID_BATCH):
            stats = source.get("summary_stats") or {}
            venues[source["id"]] = {
                "name": source.get("display_name"),
                "type": source.get("type"),
                "publisher": source.get("host_organization_name"),
                "is_oa": source.get("is_oa"),
                "is_in_doaj": source.get("is_in_doaj"),
                "two_year_mean_citedness": stats.get("2yr_mean_citedness"),
                "h_index": stats.get("h_index"),
            }
    out = args.candidates.with_name("venues.json")
    write_json(out, venues)
    print(f"[venues] {len(venue_ids)}개 요청, {len(venues)}개 받음 -> {out}")


if __name__ == "__main__":
    main()
