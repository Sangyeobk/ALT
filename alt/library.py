"""레퍼런스 폴더 (사용자 결정 2026-10-22): 모든 조사의 전문 PDF와 맥락 정리를 한 곳(config open_access.library_dir)에 모아
새 조사에서 다시 받거나 다시 읽지 않는다.

    python alt/library.py --sync outputs/<run>/     # 그 조사의 PDF·맥락 정리를 레퍼런스 폴더에 등록 (조사 폴더는 바꾸지 않음)
    python alt/library.py --show                    # 등록된 편수

- 파일 이름: 첫 저자 성 + 연도 + DOI (예: Tan2025_10.1016_j.marstruc.2024.103775.pdf, 사용자 지시 — 저자로 알아보게).
  DOI가 없으면 제목 앞부분. 목록은 library.json — {논문 id: {file, doi, title, year, sha256, source, note?, note_from?}}.
- 같은 논문인지: DOI, 없으면 제목 글자(20자 이상). 먼저 등록된 PDF가 그 논문의 PDF (다른 판은 등록하지 않음).
- 맥락 정리는 그 PDF와 **파일이 똑같은** 조사의 것만 등록·사용 (쪽 번호가 PDF 기준 — 판이 다르면 쪽이 어긋남).
- 조사 폴더에는 복사해서 쓴다 (결과 폴더 하나만 넘겨도 완결 — 사용자 결정 2026-10-22).
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
from uuid import uuid4
from datetime import date
from pathlib import Path

from common import PROJECT_DIR, load_config, read_json, write_json

TITLE_MIN_CHARS = 20      # 이보다 짧은 제목은 같은 논문 판별에 쓰지 않음 (잘못 맞을 수 있음)
NAME_TITLE_CHARS = 40     # DOI 없는 논문의 파일 이름에 넣을 제목 글자 수


def bare_doi(doi: str | None) -> str:
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", doi or "", flags=re.IGNORECASE).lower()


def squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def paper_id(ref: dict) -> str:
    """조사 사이에서 같은 논문을 알아보는 값: DOI, 없으면 제목 글자만."""
    doi = bare_doi(ref.get("doi"))
    title = squash(ref.get("title") or "")
    return f"doi:{doi}" if doi else (f"title:{title}" if len(title) >= TITLE_MIN_CHARS else "")


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def library_dir() -> Path:
    return PROJECT_DIR / load_config()["open_access"]["library_dir"]


def library_name(ref: dict) -> str:
    """저자성연도_DOI.pdf — 파일 이름에 못 쓰는 글자는 '_'."""
    from prepare_synthesis import family_name
    authors = ref.get("authors") or []
    if isinstance(authors, str):  # 예전 기록: 문자열로 저장된 목록
        authors = re.findall(r"'([^']+)'", authors) or [authors]
    head = f"{family_name(authors[0] if authors else None)}{ref.get('year') or 'nd'}"
    tail = bare_doi(ref.get("doi")) or squash(ref.get("title") or "")[:NAME_TITLE_CHARS]
    return re.sub(r"[^\w.-]", "_", f"{head}_{tail}") + ".pdf"


class Library:
    def __init__(self, root: Path | None = None):
        self.root = root or library_dir()
        self.index_path = self.root / "library.json"
        self.items = read_json(self.index_path) if self.index_path.is_file() else {}

    def save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        write_json(self.index_path, self.items)

    def pdf_of(self, ref: dict) -> Path | None:
        item = self.items.get(paper_id(ref))
        return self.root / item["file"] if item and (self.root / item["file"]).is_file() else None

    def add_pdf(self, ref: dict, pdf: Path, source: str) -> bool:
        """처음 보는 논문이면 PDF를 복사해 등록 (이미 있으면 그대로 — 먼저 등록된 판이 기준)."""
        pid = paper_id(ref)
        if not pid or not pdf.is_file() or self.pdf_of(ref):
            return False
        name = library_name(ref)
        self.root.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pdf, self.root / name)
        self.items[pid] = {"file": name, "doi": bare_doi(ref.get("doi")), "title": ref.get("title"), "year": ref.get("year"),
                           "sha256": file_hash(pdf), "source": source, "added": date.today().isoformat()}
        return True

    def note_of(self, ref: dict, pdf: Path) -> tuple[dict, str] | None:
        """이 PDF와 똑같은 파일의 맥락 정리 → (정리, 출처)."""
        item = self.items.get(paper_id(ref))
        if item and "note" in item and pdf.is_file() and file_hash(pdf) == item["sha256"]:
            return item["note"], item["note_from"]
        return None

    def add_note(self, ref: dict, pdf: Path, note: dict, source: str) -> bool:
        item = self.items.get(paper_id(ref))
        if not item or "note" in item or not pdf.is_file() or file_hash(pdf) != item["sha256"]:
            return False
        item.update({"note": note, "note_from": source})
        return True

    def replace_pdf(self, ref: dict, pdf: Path, source: str) -> Path:
        """레퍼런스 판만 교체한다. 기존 PDF·정리는 보존하고 새 판의 쪽 정리는 비운다."""
        from pypdf import PdfReader
        try:
            if not PdfReader(pdf).pages:
                raise ValueError("쪽이 없는 PDF")
        except Exception as error:
            raise ValueError(f"유효한 PDF가 아님: {pdf.name}") from error
        pid = paper_id(ref)
        current = self.pdf_of(ref)
        if current is None:
            raise ValueError("레퍼런스에 등록된 논문만 교체 가능 — 먼저 --sync")
        old = self.items[pid]
        digest = file_hash(current)
        backup = self.root / "_versions" / digest / current.name
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            shutil.copy2(current, backup)
            write_json(backup.with_suffix(".json"), old)
        # 같은 PDF 판으로 돌아온 뒤 정리를 새로 썼을 수 있으므로 메타데이터는 매번 보존한다.
        write_json(backup.with_name(f"{backup.stem}.metadata_{uuid4().hex}.json"), old)
        replacement_hash = file_hash(pdf)
        if digest == replacement_hash:
            return backup
        staged = current.with_suffix(".replacement.pdf")
        shutil.copy2(pdf, staged)
        staged.replace(current)
        self.items[pid] = {k: v for k, v in old.items() if k not in ("note", "note_from")}
        self.items[pid].update(sha256=replacement_hash, source=source, added=date.today().isoformat())
        return backup


def sync_run(run_dir: Path, lib: Library) -> tuple[int, int]:
    """조사 폴더의 PDF·맥락 정리를 레퍼런스 폴더에 등록 → (새 PDF 수, 새 정리 수). 조사 폴더는 읽기만."""
    path = run_dir / "references.json"
    if not path.is_file():
        return 0, 0
    references = read_json(path)
    notes = {k: n for p in sorted(run_dir.glob("fulltext_notes_*.json")) for k, n in read_json(p)["notes"].items()}
    added_pdf = added_note = 0
    for key, ref in references.items():
        if not ref.get("pdf_file"):
            continue
        pdf = run_dir / ref["pdf_file"]
        added_pdf += lib.add_pdf(ref, pdf, f"{run_dir.name}/{key}")
        if key in notes:
            added_note += lib.add_note(ref, pdf, notes[key], f"{run_dir.name}/{key}")
    return added_pdf, added_note


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sync", type=Path, action="append", default=[], help="등록할 조사 결과 폴더 (여러 번)")
    parser.add_argument("--show", action="store_true")
    parser.add_argument("--replace-pdf", type=Path, help="등록된 레퍼런스를 새 판 PDF로 교체 (기존 판 보존)")
    parser.add_argument("--run", type=Path, help="논문 키가 있는 조사 폴더")
    parser.add_argument("--key", help="교체할 논문의 인용 키")
    args = parser.parse_args()
    if args.replace_pdf and (not args.run or not args.key):
        parser.error("--replace-pdf에는 --run과 --key가 필요함")
    lib = Library()
    if args.replace_pdf:
        ref = read_json(args.run / "references.json")[args.key]
        backup = lib.replace_pdf(ref, args.replace_pdf, f"replacement/{args.key}")
        lib.save()
        print(f"[library] 교체 완료, 기존 판 보존: {backup.relative_to(lib.root)}")
        print("[library] 새 조사는 새 PDF 사용. 기존 조사 복사본은 유지. 새 판의 맥락 정리는 다시 필요함.")
    for run_dir in args.sync:
        pdfs, notes = sync_run(run_dir, lib)
        print(f"[library] {run_dir.name}: 새 PDF {pdfs}편, 새 맥락 정리 {notes}편")
    if args.sync:
        lib.save()
    print(f"[library] {lib.root}: PDF {len(lib.items)}편, 맥락 정리 {sum('note' in i for i in lib.items.values())}편")


if __name__ == "__main__":
    main()
