"""참고문헌 서지 보강 (APA 7판용 권·호·쪽) → references.json의 각 문헌에 biblio 추가

    python alt/fetch_biblio.py outputs/<run>/

OpenAlex biblio(volume, issue, first_page, last_page)를 가져온다. 이미 받은 문헌은 건너뛴다.
prepare_synthesis.py를 다시 돌려도 biblio는 이어받는다.
"""

import argparse
from pathlib import Path

import pyalex
from pyalex import Works

from common import load_user_settings, read_json, write_json

OPENALEX_ID_BATCH = 50


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()

    settings = load_user_settings()
    pyalex.config.email = settings.get("email")
    pyalex.config.api_key = settings.get("openalex_key")

    path = args.run_dir / "references.json"
    references = read_json(path)
    key_of = {ref["openalex_id"]: key for key, ref in references.items()
              if "biblio" not in ref and not ref["openalex_id"].startswith("local:")}  # 사용자 제공 기관 문서는 OpenAlex에 없음
    ids = [i.rsplit("/", 1)[-1] for i in key_of]
    got = 0
    for start in range(0, len(ids), OPENALEX_ID_BATCH):
        batch = "|".join(ids[start:start + OPENALEX_ID_BATCH])
        for work in Works().filter(openalex_id=batch).select(["id", "biblio"]).get(per_page=OPENALEX_ID_BATCH):
            if work["id"] in key_of:
                references[key_of[work["id"]]]["biblio"] = work.get("biblio") or {}
                got += 1
    write_json(path, references)
    print(f"[biblio] {len(ids)}편 요청, {got}편 받음 -> {path}")


if __name__ == "__main__":
    main()
