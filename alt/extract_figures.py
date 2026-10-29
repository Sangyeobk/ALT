"""전문 모드 전용: 원문 그림 다루기 (두 단계)

    python alt/extract_figures.py outputs/<run>/ --variant <판>   # 1) 목록만: 쪽별 캡션·이미지 수 → figure_index.json + figure_batches.json
    (alt-reader가 맥락 정리 + 캡션 목록으로 그림을 고름 → figure_picks_<n>.json, 지침 fulltext_guide.md '그림 고르기')
    python alt/extract_figures.py outputs/<run>/ --export --variant <판>   # 2) 고른 그림만 저장 → figures/src/<키>/ + 요약 figures에 붙임

- 후보를 전부 파일로 저장하면 논문 19편에 79MB(JPEG)·175MB(PNG)라서, 고른 것만 저장한다.
- 선정 논문만 다룬다 (리뷰 논문 제외 — 사용자 결정).
- 캡션(Fig. n / Figure n / Table n)이 줄 처음에 있는 쪽만 목록에 넣는다.
- 고른 그림이 image 번호면 그 쪽의 n번째 그림 이미지(작은 로고·아이콘 제외 순서), "page"면 쪽 전체를 그림으로 바꾼다
  (선으로 그린 도표·표는 이미지로 꺼낼 수 없어서). 쪽 그림은 캡션 위치 + 그림 개체(선·이미지) 범위로 잘라 낸다
  (사용자 피드백 2026-10-16: 쪽 전체는 슬라이드에서 읽을 수 없음). 범위를 못 찾으면 쪽 전체.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pypdfium2
from pypdf import PdfReader

from common import add_variant, load_config, read_json, run_language, variant_name, write_json
from extract_fulltext import target_keys

CAPTION_PATTERN = re.compile(r"^\s*((?:Fig\.|Figure|FIGURE|Table|TABLE)\s*\d+\s*(?:[.:|]\s*.*)?)$", re.MULTILINE)


def captions(text: str) -> list[str]:
    """쪽 글에서 캡션 줄: 줄 처음 + 번호 뒤에 . : | 또는 줄 끝.
    본문 속 'see Fig. 3', 'Fig. 1 illustrates …' 같은 언급은 빠진다."""
    return [m.group(1).strip()[:200] for m in CAPTION_PATTERN.finditer(text)]


def figure_images(page, min_pixels: int) -> list:
    """쪽 안의 그림 이미지 (작은 로고·아이콘 제외), PDF 안 순서대로."""
    found = []
    try:
        page_images = list(page.images)
    except Exception:  # 해석 못 하는 이미지 형식
        return found
    for image in page_images:
        try:
            pil = image.image
        except Exception:
            continue
        if pil is not None and pil.width * pil.height >= min_pixels:
            found.append(pil)
    return found


def index_paper(pdf: Path, rules: dict) -> dict:
    reader = PdfReader(pdf)
    pages = {}
    for number, page in enumerate(reader.pages, 1):
        found = captions(page.extract_text() or "")
        if found:
            pages[str(number)] = {"captions": found, "images": len(figure_images(page, rules["min_figure_pixels"]))}
    return {"page_count": len(reader.pages), "pages": pages}


GRAPHIC_TYPES, TEXT_TYPE = (2, 3, 5), 1  # pdfium 쪽 개체: 2 경로(선·도형), 3 이미지, 5 묶음(그림이 통째로 들어 있기도 함), 1 글


def caption_box(textpage, label: str) -> tuple | None:
    """캡션 첫 글자의 상자 (왼, 아래, 오른, 위 — PDF 좌표). 본문 속 언급('in Figure 7')은 빼고 줄 처음에 오는 것만."""
    number = re.fullmatch(r"(?:Fig\.|Figure)\s*(\d+)", label.strip(), re.IGNORECASE)
    labels = list(dict.fromkeys([label.strip(), f"Fig. {number[1]}", f"Figure {number[1]}"])) if number else [label]
    for candidate in labels:
        searcher = textpage.search(candidate, match_case=False)
        while match := searcher.get_next():
            index = match[0]
            if number and textpage.get_text_range(index + match[1], 1).isdigit():
                continue
            if index == 0 or textpage.get_text_range(index - 1, 1) in (chr(10), chr(13)):
                return textpage.get_charbox(index)
    return None


def figure_box(caption: tuple, graphics: list[tuple], texts: list[tuple], is_table: bool, page_size: tuple,
               rules: dict) -> tuple | None:
    """잘라 낼 상자 (PDF 좌표, 왼·아래·오른·위). 찾지 못하면 None (쪽 전체를 씀 — 추측해서 자르지 않음).
    - 그림(Figure): 캡션 위로 그림 개체(선·이미지)를 이어 붙인다. 캡션과 그림 사이에는 축 이름 같은 글이 있어
      첫 간격만 넉넉히(figure_crop_first_gap), 그다음은 figure_crop_gap 안에서만.
    - 표(Table): 선이 위·아래에만 있고 사이는 글이라, 캡션 아래로 글·선을 줄 간격(figure_crop_line_gap) 안에서 이어 가다가
      마지막 선에서 자른다.
    쪽 머리·꼬리 띠(머리글 줄·쪽 번호)와 쪽 거의 전체를 덮는 개체(테두리·배경)는 뺀다.
    ponytail: 위치만 보므로 그림과 바로 위 표의 줄이 위아래로 겹치면 표까지 함께 잘림 (Yang2024 그림 12) — 그때는 캡션 사이 경계 판단 추가."""
    width, height = page_size
    cap_l, cap_b, cap_r, cap_t = caption
    band = rules["figure_crop_page_band"] * height

    def usable(b):
        return (b[2] - b[0]) * (b[3] - b[1]) < 0.6 * width * height and b[1] < height - band and b[3] > band

    graphics = [b for b in graphics if usable(b)]
    if is_table:
        side = [b for b in graphics + [t for t in texts if usable(t)] if b[3] <= cap_b + 2]
        edge, picked = cap_b, []
        while more := [b for b in side if b not in picked and b[3] >= edge - rules["figure_crop_line_gap"]]:
            picked += more
            edge = min(edge, *(b[1] for b in more))
        lines = [b for b in picked if b in graphics]
        if not lines:
            return None
        bottom, top = min(b[1] for b in lines), cap_t
        picked = [b for b in picked if b[1] >= bottom - 1]
    else:
        side = [b for b in graphics if b[1] >= cap_t - 2]
        edge, picked, gap = cap_t, [], rules["figure_crop_first_gap"]
        while more := [b for b in side if b not in picked and b[1] <= edge + gap]:
            picked += more
            edge = max(edge, *(b[3] for b in more))
            gap = rules["figure_crop_gap"]
        if not picked:
            return None
        bottom, top = cap_b, edge
    margin = rules["figure_crop_margin"]
    left = max(0, min(cap_l, *(b[0] for b in picked)) - margin)
    right = min(width, max(cap_r, *(b[2] for b in picked)) + margin)
    box = (left, max(0, bottom - margin), right, min(height, top + margin))
    return box if (box[2] - box[0]) * (box[3] - box[1]) >= 0.03 * width * height else None


def page_boxes(page) -> tuple[list[tuple], list[tuple]]:
    """쪽의 그림 개체·글 개체 상자 (PDF 좌표). 쪽 크기의 묶음(쪽 전체를 감싼 것 — MDPI 등)은 풀어서 안을 보고,
    작은 묶음은 통째로 하나로 센다 (작은 묶음 안 좌표는 쪽 기준이 아닐 수 있음 — Gkerekos2019 사례)."""
    width, height = page.get_size()
    graphics, texts, opened = [], [], {}  # opened[깊이] = 그 깊이의 마지막 묶음을 풀었는지
    for obj in page.get_objects(max_depth=5):
        if not all(opened.get(level, False) for level in range(obj.level)):
            continue  # 풀지 않은 묶음의 안쪽
        box = tuple(obj.get_bounds())
        if obj.type == 5:
            opened[obj.level] = (box[2] - box[0]) * (box[3] - box[1]) >= 0.6 * width * height
            if opened[obj.level]:
                continue
        if obj.type in GRAPHIC_TYPES:
            graphics.append(box)
        elif obj.type == TEXT_TYPE:
            texts.append(box)
    return graphics, texts


def render_figure(pdf: Path, page_no: int, label: str, rules: dict):
    """쪽을 그림으로 바꾸고, 캡션·그림 개체 범위를 찾으면 그 부분만 잘라 낸다."""
    page = pypdfium2.PdfDocument(pdf)[page_no - 1]
    scale = rules["page_render_dpi"] / 72
    image = page.render(scale=scale).to_pil()
    caption = caption_box(page.get_textpage(), label) if label else None
    if caption is None:
        return image
    graphics, texts = page_boxes(page)
    width, height = page.get_size()
    box = figure_box(caption, graphics, texts, label.strip().lower().startswith("table"), (width, height), rules)
    if box is None:
        return image
    left, bottom, right, top = box
    if not label.strip().lower().startswith("table"):
        # 첫 글자 상자는 캡션 전체 높이가 아니다. 영문 캡션 일부를 잘라 붙이지 않고
        # 그림만 사용한다. 출처·한국어 캡션은 산출물 생성기가 별도로 붙인다.
        bottom = caption[3]
    return image.crop((int(left * scale), int((height - top) * scale), int(right * scale), int((height - bottom) * scale)))


def save_jpeg(pil, target: Path, rules: dict) -> None:
    """긴 변을 figure_max_side로 줄여 JPEG로 저장."""
    pil = pil.convert("RGB")
    pil.thumbnail((rules["figure_max_side"], rules["figure_max_side"]))
    pil.save(target, "JPEG", quality=rules["figure_jpeg_quality"])


def export_figure(run_dir: Path, key: str, pick: dict, rules: dict) -> str | None:
    """pick = {"page": 7, "image": 1 또는 "page"} → 저장한 파일 경로 (결과 폴더 기준), 못 하면 None."""
    pdf = run_dir / "papers" / f"{key}.pdf"
    page_no = int(pick["page"])
    out_dir = run_dir / "figures" / "src" / key
    out_dir.mkdir(parents=True, exist_ok=True)
    if pick.get("image") == "page":
        target = out_dir / f"p{page_no}_page.jpg"
        save_jpeg(render_figure(pdf, page_no, pick.get("fig", ""), rules), target, rules)
    else:
        images = figure_images(PdfReader(pdf).pages[page_no - 1], rules["min_figure_pixels"])
        n = int(pick.get("image") or 1)
        if not 1 <= n <= len(images):
            return None
        target = out_dir / f"p{page_no}_{n}.jpg"
        save_jpeg(images[n - 1], target, rules)
    return target.relative_to(run_dir).as_posix()


def attach_figures(run_dir: Path, variant: str) -> int:
    """그림 고르기 결과(figure_picks_*)를 요약의 figures에 붙임 — 그 논문이 속한 세부 주제로. 판단이 필요 없어 에이전트 없이 (사용자 결정 2026-10-16).
    예전 깊은 정리(fulltext_notes의 figures)는 요약 단계가 이미 골랐으므로 건드리지 않음. 이미 붙은 그림은 다시 넣지 않음."""
    path = run_dir / variant_name("synthesis.json", variant)
    picks = [(key, fig) for p in sorted(run_dir.glob("figure_picks_*.json")) for key, note in read_json(p)["notes"].items()
             for fig in note.get("figures", []) if fig.get("file")]
    if not picks or not path.is_file():
        return 0
    synthesis = read_json(path)
    topic_of = {k: t["id"] for t in synthesis.get("subtopics", []) for k in t["papers"]}
    have = {(f["key"], f["page"], f["fig"]) for f in synthesis.get("figures", [])}
    added = [{"key": k, "fig": f["fig"], "page": f["page"], "file": f["file"], "caption": f["caption"], "subtopic": topic_of[k]}
             for k, f in picks if k in topic_of and (k, f["page"], f["fig"]) not in have]
    synthesis["figures"] = synthesis.get("figures", []) + added
    write_json(path, synthesis)
    return len(added)


def load_notes_keys(run_dir: Path) -> set[str]:
    return {k for p in run_dir.glob("fulltext_notes_*.json") for k, n in read_json(p)["notes"].items() if not n.get("unreadable")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--export", action="store_true", help="고른 그림(figure_picks_*.json, 예전 fulltext_notes_*.json)만 저장")
    add_variant(parser)
    args = parser.parse_args()

    rules = load_config()["fulltext"]
    if args.export:
        saved, failed = 0, []
        for path in sorted([*args.run_dir.glob("fulltext_notes_*.json"), *args.run_dir.glob("figure_picks_*.json")]):
            data = read_json(path)
            for key, note in data["notes"].items():
                for fig in note.get("figures", []):
                    fig["file"] = export_figure(args.run_dir, key, fig, rules)
                    saved += fig["file"] is not None
                    if fig["file"] is None:
                        failed.append(f"{key} p.{fig['page']}")
            write_json(path, data)
        size = sum(f.stat().st_size for f in (args.run_dir / "figures" / "src").rglob("*.jpg")) / 1e6
        print(f"[figures] 고른 그림 {saved}개 저장 ({size:.1f} MB)" + (f", 못 찾음: {', '.join(failed)}" if failed else "")
              + f", 요약({variant_name('synthesis.json', args.variant)})에 새로 붙인 그림 {attach_figures(args.run_dir, args.variant)}개")
        return

    index_path = args.run_dir / "figure_index.json"
    index = {}
    references = read_json(args.run_dir / "references.json")
    for key in target_keys(args.run_dir, references, rules["figure_targets"], args.variant):  # 그림 고르기 대상
        pdf = args.run_dir / "papers" / f"{key}.pdf"
        if references[key]["status"] == "selected" and pdf.is_file():  # [사용자] 그림은 선정 논문에서만 (리뷰 논문 제외)
            try:
                index[key] = index_paper(pdf, rules)
            except Exception as error:  # 한 논문이 깨져도 나머지는 계속
                print(f"[figures] {key}: 목록 실패 ({type(error).__name__})")
    write_json(index_path, index)
    picked = {k for p in args.run_dir.glob("figure_picks_*.json") for k, n in read_json(p)["notes"].items() if n.get("figures")}
    noted = load_notes_keys(args.run_dir)
    todo = [k for k in index if k in noted and k not in picked]  # 맥락 정리가 있어야 고를 수 있음, 이미 고른 논문은 건너뜀
    number = max((int(p.stem.rsplit("_", 1)[1]) + 1 for p in args.run_dir.glob("figure_picks_*.json")), default=1)  # 이전 고르기 덮지 않음
    write_json(args.run_dir / "figure_batches.json", {"keys": todo, "output_file": f"figure_picks_{number}.json" if todo else None,
                                                     "language": run_language(args.run_dir)})  # 그림 설명(caption·why)의 언어
    print(f"[figures] {len(index)}편, 캡션 있는 쪽 {sum(len(p['pages']) for p in index.values())}개 -> figure_index.json · "
          f"그림 고를 논문 {len(todo)}편" + (f" -> figure_picks_{number}.json" if todo else ""))


if __name__ == "__main__":
    main()
