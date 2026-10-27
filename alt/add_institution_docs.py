"""사용자가 준 기관·선급 문서 PDF(선급 규칙·가이드, ISSC·ITTC·IMO 문서 등)를 문헌 목록에 넣기 (사용자 결정 2026-10-16).

    python alt/add_institution_docs.py outputs/<run>/      # standards/*.pdf → standards/docs.yaml 틀 (첫 쪽 글 포함)

1. 사용자가 결과 폴더 `standards/`에 PDF를 넣는다.
2. 이 스크립트가 새 PDF마다 `standards/docs.yaml`에 빈 칸과 첫 쪽 글(first_page)을 만든다.
3. Claude가 **첫 쪽 글에 적힌 것만으로** 칸을 채운다: org(기관 정식 이름), org_short(인용 키 앞부분, 영문 대문자로 시작하는 글자만 —
   예 KR, ISSC, DNV), title, year, doc_number(문서에 적힌 번호, 없으면 비움). 적혀 있지 않은 값은 지어내지 않고 비운다.
4. ⑦ prepare_synthesis.py가 `load_user_docs()`로 읽어 인용 가능 문헌(references.json)에 '사용자 제공' 기관·선급 문서로 넣고,
   PDF를 `papers/<인용 키>.pdf`로 복사한다 (전문 모드면 본문까지 읽음). 점수화하지 않는다 (사용자가 고른 문서).
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml
from pypdf import PdfReader

DOCS_DIR = "standards"
REQUIRED = ("org", "org_short", "title", "year")
FIRST_PAGE_CHARS = 1500


def first_page_text(pdf: Path) -> str:
    try:
        return (PdfReader(str(pdf)).pages[0].extract_text() or "")[:FIRST_PAGE_CHARS]
    except Exception:  # noqa: BLE001 — 스캔본·암호 PDF: 글을 못 읽으면 사용자가 직접 채우도록 비워 둠
        return ""


def docs_path(run_dir: Path) -> Path:
    return Path(run_dir) / DOCS_DIR / "docs.yaml"


def prepare(run_dir: Path) -> list[str]:
    """새 PDF마다 빈 항목 추가 → 추가한 파일 이름."""
    path = docs_path(run_dir)
    docs = (yaml.safe_load(path.read_text(encoding="utf-8")) or []) if path.is_file() else []
    known = {d["file"] for d in docs}
    added = []
    for pdf in sorted((Path(run_dir) / DOCS_DIR).glob("*.pdf")):
        if pdf.name not in known:
            docs.append({"file": pdf.name, **dict.fromkeys(REQUIRED), "doc_number": None, "first_page": first_page_text(pdf)})
            added.append(pdf.name)
    if docs:
        path.write_text(yaml.safe_dump(docs, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return added


def load_user_docs(run_dir: Path) -> list[dict]:
    """채워진 docs.yaml → 후보 레코드 형식 (references.json에 그대로 들어갈 칸). 빈 칸이 있으면 멈춤."""
    path = docs_path(run_dir)
    if not path.is_file():
        return []
    records = []
    for d in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
        empty = [k for k in REQUIRED if not d.get(k)]
        if empty or not re.fullmatch(r"[A-Z][A-Za-z]+", str(d.get("org_short") or "")):
            raise SystemExit(f"[standards] {d['file']}: 빈 칸 {empty} 또는 org_short 형식 오류 (영문 대문자로 시작하는 글자만) — docs.yaml을 채운 뒤 다시")
        records.append({
            "openalex_id": f"local:{d['file']}", "doi": None, "title": d["title"], "authors": [d["org"]], "year": int(d["year"]),
            "venue": d["org"], "org_short": d["org_short"], "doc_number": d.get("doc_number"), "category": "institution",
            "status": "institution_listed", "user_provided": True, "source_file": f"{DOCS_DIR}/{d['file']}",
            "relevance": None, "relevance_reason": "사용자 제공 문서 (점수화하지 않음)", "total_score": None, "stars": None,
            "score_parts": None, "fwci": None, "cited_by_count": None, "is_oa": False, "oa_url": None,
            "flags": ["사용자 제공"], "approach_tags": [], "structure_type": None, "abstract": None,
        })
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    added = prepare(args.run_dir)
    print(f"[standards] 새 PDF {len(added)}개: {', '.join(added) or '없음'} -> {docs_path(args.run_dir)}")
    if added:
        print("다음: 각 항목의 first_page 글에 적힌 것만으로 org·org_short·title·year·doc_number를 채운다 (없으면 비움)")


if __name__ == "__main__":
    main()
