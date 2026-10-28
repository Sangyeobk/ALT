"""무료 공개(OA) 논문 전문 모으기 → papers/<키>.pdf, references.json에 결과 기록

    python alt/fetch_open_access.py outputs/<run>/

1. 사용자가 브라우저로 받아 papers/에 넣은 PDF(이름은 아무렇게나): 첫 페이지의 DOI(없으면 제목)로 논문을 찾아
   papers/<키>.pdf로 이름을 바꾼다. 못 찾으면 그대로 두고 알린다 (이름을 인용 키로 직접 바꿔도 됨).
2. 이미 있는 papers/<키>.pdf는 다시 받지 않는다.
2-1. 레퍼런스 폴더(config open_access.library_dir, alt/library.py)에 같은 논문(DOI, 없으면 제목)의 PDF가 있으면 복사해 온다
     (사용자가 직접 받은 것 포함 — 다시 받지 않음, 사용자 결정 2026-10-22). 끝에 이 조사의 새 PDF를 레퍼런스 폴더에 등록한다.
3. 나머지는 Unpaywall의 공개 위치(출판사·저장소·arXiv 등)를 차례로 시도한다.
   받은 파일이 실제 PDF(%PDF로 시작)가 아니면 버린다. 출판사가 막으면(403·봇 검사) 우회하지 않고 '수동'으로 남긴다.

pdf_status: downloaded(자동) / manual(사용자가 넣음) / manual_needed(공개 논문, 자동 수집 불가 → 링크로 직접 받기) / not_oa(무료 공개 아님)
"""

import argparse
import os
import shutil
import subprocess
import re
import webbrowser
from pathlib import Path

import requests
from pypdf import PdfReader

from common import load_config, load_user_settings, read_json, write_json
from library import Library, bare_doi, squash, sync_run

UNPAYWALL_URL = "https://api.unpaywall.org/v2/{doi}"
DOI_PATTERN = re.compile(r"10\.\d{4,9}/[^\s\"<>]+", re.IGNORECASE)


def is_pdf(first_bytes: bytes) -> bool:
    return first_bytes.startswith(b"%PDF")


def match_reference(text: str, references: dict) -> str | None:
    """PDF 첫 페이지 글 → 인용 키. DOI가 정확히 한 논문과 맞으면 그 논문, 아니면 제목이 들어 있는 논문 하나.
    여러 논문이 맞거나 하나도 없으면 None (잘못 연결하는 것보다 못 찾는 편이 낫다)."""
    found = {m.group(0).rstrip(".,;)]").lower() for m in DOI_PATTERN.finditer(text)}
    by_doi = {key for key, ref in references.items() if bare_doi(ref["doi"]) and bare_doi(ref["doi"]) in found}
    if len(by_doi) == 1:
        return by_doi.pop()
    page = squash(text)
    by_title = {key for key, ref in references.items() if len(squash(ref["title"])) >= 20 and squash(ref["title"])[:80] in page}
    return by_title.pop() if len(by_title) == 1 else None


def first_pages_text(path: Path, pages: int = 2) -> str:
    try:
        reader = PdfReader(path)
        return "\n".join(page.extract_text() or "" for page in reader.pages[:pages])
    except Exception:  # 깨진 PDF·암호 PDF
        return ""


def reuse_library_pdfs(references: dict, papers_dir: Path, lib: Library) -> list[str]:
    """레퍼런스 폴더(사용자 결정 2026-10-22)에 같은 논문의 PDF가 있으면 papers/<키>.pdf로 복사한다 — 다시 받지 않음
    (사용자가 직접 받은 것 포함, 처음은 PINN 세부 조사 2026-10-16 상위 조사 PDF 재사용). 상태는 manual, 출처는 manual_source."""
    copied = []
    for key, ref in references.items():
        src = lib.pdf_of(ref)
        if not src or (papers_dir / f"{key}.pdf").is_file():
            continue
        shutil.copy2(src, papers_dir / f"{key}.pdf")
        ref.update({"pdf_status": "manual", "manual_source": f"레퍼런스 폴더 {src.name}"})
        copied.append(key)
    return copied


def rename_manual(references: dict, papers_dir: Path) -> list[str]:
    """papers/에 사용자가 넣은 PDF(이름이 인용 키가 아닌 것)를 찾아 <키>.pdf로 이름을 바꾼다.
    못 찾으면 그대로 두고, 같은 키 파일이 이미 있으면 papers/_to_delete/로 옮긴다. 그 파일 이름(사유)을 돌려준다."""
    left = []
    for pdf in sorted(papers_dir.glob("*.pdf")):
        if pdf.stem in references:
            continue
        key = match_reference(first_pages_text(pdf), references)
        if key is None:
            left.append(f"{pdf.name}(논문 못 찾음)")
        elif (papers_dir / f"{key}.pdf").exists():  # 같은 논문이 이미 있음 → 지우지 않고 _to_delete/로 (업무 폴더 규칙)
            (papers_dir / "_to_delete").mkdir(exist_ok=True)
            pdf.rename(papers_dir / "_to_delete" / pdf.name)
            left.append(f"{pdf.name}({key}.pdf와 중복 → _to_delete/로 옮김)")
        else:
            pdf.rename(papers_dir / f"{key}.pdf")
            references[key].update({"pdf_status": "manual", "manual_source": pdf.name})
    return left


def fetch(session: requests.Session, url: str, target: Path, max_bytes: int) -> str:
    """PDF를 받아 저장. 결과: 'downloaded' / 'not_pdf' / 'too_large' / 'http_<code>' / 'error'."""
    try:
        with session.get(url, timeout=60, stream=True, allow_redirects=True) as response:
            if not response.ok:
                return f"http_{response.status_code}"
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > max_bytes:
                    return "too_large"
                chunks.append(chunk)
    except requests.RequestException:
        return "error"
    data = b"".join(chunks)
    if not is_pdf(data[:8]):
        return "not_pdf"
    target.write_bytes(data)
    return "downloaded"


def fetch_from_unpaywall(session, email: str, key: str, ref: dict, papers_dir: Path, max_bytes: int) -> None:
    try:
        response = session.get(UNPAYWALL_URL.format(doi=bare_doi(ref["doi"])), params={"email": email}, timeout=20)
        info = response.json() if response.ok else {}
    except (requests.RequestException, ValueError):
        info = {}
    best = info.get("best_oa_location") or {}
    locations = [best] + [loc for loc in info.get("oa_locations") or [] if loc != best]
    ref["oa_landing_url"] = best.get("url_for_landing_page") or ref.get("oa_url") or ref["doi"]
    ref["pdf_attempts"] = []
    for loc in locations:
        url = loc.get("url_for_pdf")
        if not url:
            continue
        result = fetch(session, url, papers_dir / f"{key}.pdf", max_bytes)
        ref["pdf_attempts"].append(f"{loc.get('host_type')}:{result}")
        if result == "downloaded":
            ref.update({"oa_pdf_url": url, "pdf_file": f"papers/{key}.pdf", "pdf_status": "downloaded"})
            return
    is_oa = info.get("is_oa", ref.get("is_oa"))
    ref["oa_pdf_url"] = next((loc["url_for_pdf"] for loc in locations if loc.get("url_for_pdf")), None)
    ref["pdf_status"] = "manual_needed" if is_oa else "not_oa"


def download_link(ref: dict) -> str | None:
    """무료 사본 위치, 없으면 doi.org 링크."""
    return ref.get("oa_landing_url") or ref.get("doi")


def open_in_edge(links: list[str]) -> None:
    """링크를 Edge 새 창에서 한꺼번에 연다 — 앱 안 브라우저로 열면 출판사가 사람 확인을 계속 요구함 (사용자 지시 2026-10-16).
    사용자의 브라우저에서 사람이 받는 것이고, 봇 검사를 우회하는 것이 아니다."""
    # 명령 셸(cmd)에 넘기면 '&'가 든 주소가 잘림 → Edge 실행 파일에 직접 (Codex 검토 2026-10-28). 없으면 기본 브라우저
    candidates = [shutil.which("msedge"), *(str(Path(os.environ.get(v, "")) / "Microsoft/Edge/Application/msedge.exe")
                                             for v in ("ProgramFiles(x86)", "ProgramFiles"))]
    edge = next((c for c in candidates if c and Path(c).is_file()), None)
    if edge:
        subprocess.run([edge, "--new-window", *links], check=False)
    else:
        for link in links:
            webbrowser.open(link)


def download_todo(references: dict) -> list[str]:
    """사용자가 직접 받을 논문 목록 — 인용 키·상태·실린 곳·제목과 **바로 열 수 있는 링크**를 함께 (사용자 지시 2026-10-16: DOI만으로는 받기 불편)."""
    labels = {"manual_needed": "직접 받기 필요", "not_oa": "무료 공개 아님(구독 필요)"}
    rows = []
    for key, ref in references.items():
        if ref.get("pdf_status") not in labels:
            continue
        link = download_link(ref) or "(링크 없음 — 제목으로 검색)"
        rows.append(f"{labels[ref['pdf_status']]} | {key} | {ref.get('venue') or ''} | {link} | {(ref.get('title') or '')[:80]}")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--open-edge", action="store_true", help="직접 받을 논문 링크를 Edge 새 창에서 연다")
    args = parser.parse_args()

    references = read_json(args.run_dir / "references.json")
    if args.open_edge:  # 지난 수집 결과의 '직접 받을' 목록만 연다 — 다시 받지 않음 (Codex 검토 2026-10-28: 옵션이 연결돼 있지 않았음)
        links = [link for ref in references.values() if ref.get("pdf_status") in ("manual_needed", "not_oa") and (link := download_link(ref))]
        if links:
            open_in_edge(links)
        print(f"[oa] Edge 새 창에서 링크 {len(links)}개를 엶" if links else "[oa] 직접 받을 논문 없음")
        return
    email = load_user_settings().get("email")
    if not email:
        raise SystemExit("이메일이 없습니다: python alt/settings.py --email ...")
    max_bytes = load_config()["open_access"]["max_pdf_mb"] * 1024 * 1024
    papers_dir = args.run_dir / "papers"
    papers_dir.mkdir(exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = f"ALT literature tool (mailto:{email})"

    left = rename_manual(references, papers_dir)
    lib = Library()
    copied = reuse_library_pdfs(references, papers_dir, lib)
    if copied:
        print(f"[oa] 레퍼런스 폴더에 있는 PDF {len(copied)}편 복사 (다시 받지 않음): {', '.join(copied)}")
    for key, ref in references.items():
        if (papers_dir / f"{key}.pdf").is_file():
            ref["pdf_file"] = f"papers/{key}.pdf"
            if ref.get("pdf_status") != "downloaded":  # 이 단계가 받은 기록이 없으면 사용자가 넣은 것
                ref["pdf_status"] = "manual"
            continue
        ref.update({"pdf_file": None, "oa_landing_url": ref.get("oa_url") or ref["doi"]})
        if not ref["doi"]:  # Unpaywall은 DOI로만 찾음 → OpenAlex 공개 사본 주소를 직접 시도 (10-19 결함: arXiv 논문이 '무료 공개 아님')
            result = fetch(session, ref["oa_url"], papers_dir / f"{key}.pdf", max_bytes) if ref.get("oa_url") else "no_url"
            ref["pdf_attempts"] = [f"openalex:{result}"]
            ref.update({"oa_pdf_url": ref.get("oa_url"), "pdf_file": f"papers/{key}.pdf", "pdf_status": "downloaded"} if result == "downloaded"
                       else {"pdf_status": "manual_needed" if ref.get("is_oa") else "not_oa"})
            continue
        fetch_from_unpaywall(session, email, key, ref, papers_dir, max_bytes)

    write_json(args.run_dir / "references.json", references)
    added, _ = sync_run(args.run_dir, lib)  # 새로 받은 PDF(직접 받은 것 포함)는 레퍼런스 폴더에 등록
    lib.save()
    if added:
        print(f"[oa] 레퍼런스 폴더에 새 PDF {added}편 등록 -> {lib.root}")
    statuses = {}
    for ref in references.values():
        statuses[ref["pdf_status"]] = statuses.get(ref["pdf_status"], 0) + 1
    print(f"[oa] {len(references)}편: {statuses} -> {papers_dir}")
    todo = download_todo(references)
    if todo:
        print(f"[oa] 직접 받을 논문 {len(todo)}편 (상태 | 인용 키 | 실린 곳 | 링크 | 제목) — 받은 PDF는 {papers_dir}에 아무 이름으로:")
        print("\n".join(todo))
    if left:
        print(f"[oa] 이름을 바꾸지 않은 PDF {len(left)}개 — 논문을 못 찾은 것은 이름을 인용 키로 바꾸면 연결됨 (예: Tan2025.pdf): "
              f"{', '.join(left)}")


if __name__ == "__main__":
    main()
