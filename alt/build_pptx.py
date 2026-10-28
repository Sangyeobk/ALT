"""PPT 2종 → 04_presentation.pptx (문헌조사 발표), 01_background.pptx (주제 배경 이해용)

    python alt/build_pptx.py outputs/<run>/ [--deck all|talk|learn]

발표 양식(config output.pptx_template → pptx_templates)을 복제해 표지·마무리 슬라이드만 남기고 본문을 새로 만든다 (원본은 읽기만).
양식에 장 구분 장이 있으면 큰 장 앞에 넣고, 본문 장에는 양식의 꾸밈(테두리 선 등)을 복사한다. 글꼴은 전부 맑은 고딕, 색은 양식마다.
구성: 제목 28pt 좌상단(영문 섹션명), 소제목 `[태그] 국문 요지`, 본문 14–16pt 개조식, 강조 줄·핵심 결론 상자·표 머리줄은 양식 색.
원문 그림 번호·주석만 주석 색(빨강). 발표자 노트 없음.
"""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.dml import MSO_FILL
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE, MSO_SHAPE_TYPE
from pptx.oxml.ns import qn
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.util import Cm, Emu, Pt

from common import (PRISMA_NOTE, PROJECT_DIR, Abbreviations, verbatim_strings, add_variant, cite as cite_all, display_names, keyword_chunks, keyword_tag, load_config, tech_keywords, load_topic, map_axis, read_json, report_title,
                    review_info, role_label, scope_history, sections, topic_line, variant_name)
from export_references import EXCEL_SHEETS
from report_facts import adjacent_rows, excluded_comparison, excluded_rows, fulltext_label, method_lines, role_of
from slides_plan import (DECK_FILES, LEARN_TAIL, TABLE_MAX_ROWS, check_learn_plan, check_plan, figure_sources, load_catalog, slot_limits,
                         weighted_len)

CITE_SHOWN = load_config()["output"]["cite_shown"]


def cite(item: dict) -> str:
    """발표에는 대표 인용 키만 (나머지는 '외 N편')."""
    return cite_all(item, CITE_SHOWN)

FONT = "맑은 고딕"
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
RELS_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"  # 그림·링크 파일 연결 속성
CLOSING_WIDEN = 1.6  # 마무리 장 짧은 줄 칸 폭 배수 — 맑은 고딕이 양식 글꼴보다 넓음
FRAME_LINE_CM, FRAME_TICK_CM = 0.1, 2.1  # 양식 테두리 지우기: 이 두께 이하를 선으로, 가장자리에 붙은 이 길이 이하를 테두리 끝 막대로 봄
CANVAS_W, CANVAS_H = 33.867, 19.05  # 코드가 위치를 잡는 화면 (cm) — 양식 크기가 다르면 Deck이 비율대로 바꿈
# 색은 양식마다 (config output.pptx_templates colors, 사용자 결정 2026-10-21)
BODY_TOP, BODY_LEFT, BODY_WIDTH = 3.9, 1.0, 31.8
MAX_BULLETS = 6
SUBTITLE_FULL_SIZE_CHARS = 30   # 이보다 긴 소제목은 15pt로 줄여 한 줄에
TABLE_ROWS_PER_SLIDE = 8

BODY_BOTTOM = 17.6               # 본문 아래 끝 (cm) — 그 아래는 쪽 번호·로고
PT_CM = 0.0353                   # 1 pt = 0.0353 cm
SUBTOPIC_PAPER_ROWS = 5          # 분야 장 아래 '이 분야 논문' 표의 최대 행 수
SUBTOPIC_TABLE_MIN_CM = 4.5      # 분야 장 아래 남은 높이가 이보다 작으면 논문 표를 다음 장에 (머리 행 + 2행 + 안내 줄 정도)
SUBTOPIC_SIZE = 14               # 분야 장 글 크기 (pt) — (1)(2)(3) 전개로 줄이 늘어 15 → 14


def est_lines(text: str, width_cm: float, size: float) -> int:
    """글이 칸에서 몇 줄이 될지 어림 — 한글 한 글자 폭 ≈ 글자 크기, 약어 풀이로 늘어날 몫 15%를 더함 (넉넉하게)."""
    per_line = max(1.0, width_cm / (size * PT_CM * 0.95))
    return max(1, -(-int(len(text) * 1.15) // int(per_line)))


def bullets_height(items: list[tuple[str, bool]], width_cm: float, size: float) -> float:
    """Deck.bullets 글머리의 높이 어림 (cm): 줄 높이 1.2배 + 문단 뒤 8 pt."""
    return sum(est_lines("• " + text, width_cm, size) * size * PT_CM * 1.2 + 8 * PT_CM for text, _ in items)


def sections_height(parts: list[tuple[str, list[tuple[str, bool]]]], width_cm: float, size: float) -> float:
    """Deck.sections 높이 어림 (cm): 머리말 한 줄씩 + 글머리."""
    return sum(size * PT_CM * 1.2 + 4 * PT_CM + bullets_height(items, width_cm, size) for _, items in parts)


def bullets_pages(items: list[tuple[str, bool]], first: tuple[float, float], rest: tuple[float, float],
                  size: float) -> list[list[tuple[str, bool]]]:
    """글머리를 장에 나눠 담기 (사용자 피드백 2026-10-16: 방법 장이 화면 아래로 넘침). first·rest = (폭, 높이) cm.
    첫 장에는 강조 줄을 먼저 확보하고 남는 자리에 나머지를 원래 순서대로 — 장 안에서는 원래 순서를 지킨다."""
    def fits(chosen, box):
        return bullets_height(chosen, box[0], size) <= box[1]

    first_page = [i for i, (_, emphasis) in enumerate(items) if emphasis]
    for i in range(len(items)):
        if i not in first_page and fits([items[j] for j in sorted(first_page + [i])], first):
            first_page.append(i)
    pages, page = [[items[j] for j in sorted(first_page)]], []
    for i, item in enumerate(items):
        if i in first_page:
            continue
        if page and not fits(page + [item], rest):
            pages.append(page)
            page = []
        page.append(item)
    return pages + ([page] if page else [])




def pptx_style(name: str | None = None) -> dict:
    """발표 양식 설정 (config output.pptx_templates) — 파일이 없으면 plain (사용자 결정 2026-10-21)."""
    out = load_config()["output"]
    styles = out["pptx_templates"]
    style = dict(styles[name or out["pptx_template"]])
    path = PROJECT_DIR / style["file"] if style.get("file") else None
    if path is not None and not path.is_file():
        print(f"[pptx] 양식 파일 없음 ({path}) — 무늬 없는 기본 양식(plain)으로 만듦")
        path, style = None, dict(styles["plain"])
    style["path"] = path
    return style


def set_font(run) -> None:
    """글꼴은 전부 맑은 고딕 (사용자 결정 2026-10-21) — 영문(latin)과 한글(ea) 모두."""
    run.font.name = FONT
    rpr = run._r.get_or_add_rPr()
    rpr.set("lang", "ko-KR")  # 한국어로 지정해야 PowerPoint가 한글을 단어 단위로 줄바꿈 (eaLnBrk="0"과 함께)
    ea = rpr.find(qn("a:ea"))
    if ea is None:
        ea = rpr.makeelement(qn("a:ea"), {})
        rpr.find(qn("a:latin")).addnext(ea)
    ea.set("typeface", FONT)


def plain_template() -> Presentation:
    """양식 파일이 없을 때 쓰는 무늬 없는 16:9 양식 — 표지(제목·머리글 글상자)와 마무리 한 장.
    공개 저장소에는 양식 파일을 넣지 않으므로 받은 사람도 바로 만들 수 있게 한다."""
    prs = Presentation()
    prs.slide_width, prs.slide_height = Cm(CANVAS_W), Cm(CANVAS_H)
    blank = prs.slide_layouts[6]
    cover, closing = prs.slides.add_slide(blank), prs.slides.add_slide(blank)
    for slide, text, y, h, size in ((cover, "Title", 6.5, 4.0, 36), (cover, "Header", 1.0, 1.2, 14), (closing, "Thank you", 8.0, 2.5, 36)):
        p = slide.shapes.add_textbox(Cm(2.0), Cm(y), Cm(29.9), Cm(h)).text_frame.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        r = p.add_run()
        r.text = text
        r.font.size, r.font.bold, r.font.color.rgb = Pt(size), True, RGBColor(0x00, 0x20, 0x60)
    return prs


class Deck:
    def __init__(self, style: dict, abbreviations: dict | None = None, protected: list[str] | None = None):
        self.abbr = Abbreviations(abbreviations, protected)  # 약어는 자료에서 처음 나올 때 풀어 씀 (입력 원문·검색어는 그대로)
        self.tech: list[str] = []  # 기술 핵심어 — 본문에서 따로 표시 (사용자 피드백 2026-10-19, 요약 tech_keywords)
        self.style = style
        self.c = {k: RGBColor.from_string(v) for k, v in style["colors"].items()}
        self.body_bold = style.get("body_bold", True)
        path = style.get("path")
        self.prs = Presentation(str(path)) if path else plain_template()
        # 양식의 원래 장은 새 장을 다 만든 뒤 표지·마무리만 남기고 지운다 (먼저 지우면 새 슬라이드 파일 이름이 겹침)
        self.originals = list(self.prs.slides)
        picks = style.get("slides", {})
        pick = lambda key, default: self.originals[picks[key] - 1] if key in picks else default
        self.cover, self.closing = pick("cover", self.originals[0]), pick("closing", self.originals[-1])
        self.section_src, self.body_src = pick("section", None), pick("body", None)
        self.blank = self.prs.slide_layouts[style.get("blank_layout", 1 if path else 6)]  # 예전 KR 양식은 1번이 '빈 화면'
        # 코드는 33.9×19.1 cm 화면에 위치를 잡는다 → 양식의 본문 영역(content_box)에 비율대로 넣음 (글자 크기도 같은 비율)
        box = style.get("content_box")
        if box:
            self.k = min(box[2] / CANVAS_W, box[3] / CANVAS_H)
            self.ox, self.oy = box[0] + (box[2] - CANVAS_W * self.k) / 2, box[1] + (box[3] - CANVAS_H * self.k) / 2
        else:
            self.k, self.ox, self.oy = self.prs.slide_width / Cm(CANVAS_W), 0.0, 0.0

    def x(self, v: float):
        return Cm(self.ox + v * self.k)

    def y(self, v: float):
        return Cm(self.oy + v * self.k)

    def d(self, v: float):
        """길이 (폭·높이)."""
        return Cm(v * self.k)

    def pt(self, v: float):
        return Pt(v * self.k)

    def _delete(self, slide):
        id_list = self.prs.slides._sldIdLst
        for sld_id in list(id_list):
            if self.prs.part.related_part(sld_id.rId) is slide.part:
                self.prs.part.drop_rel(sld_id.rId)
                id_list.remove(sld_id)
                return

    def _copy_shapes(self, src, dst, text_too: bool) -> None:
        """양식 장의 도형을 새 장 맨 뒤 층에 같은 순서로 복사 — 꾸밈(테두리 선·원)은 장마다 그려져 있음.
        그림·링크가 가리키는 파일 연결(r:embed 등)은 새 장에 다시 이어 준다."""
        tree = dst.shapes._spTree
        shapes = [sh for sh in src.shapes if text_too or not (sh.has_text_frame and sh.text_frame.text.strip())]
        for i, sh in enumerate(shapes):
            element = copy.deepcopy(sh._element)
            for node in element.iter():
                for attr in [a for a in node.attrib if a.startswith("{%s}" % RELS_NS)]:
                    rel = src.part.rels.get(node.get(attr))
                    if rel is None:
                        continue
                    target = rel.target_ref if rel.is_external else rel.target_part
                    node.set(attr, dst.part.relate_to(target, rel.reltype, is_external=rel.is_external))
            tree.insert(2 + i, element)

    def _slide_like(self, src, text_too: bool, drop_frame: bool = True):
        """양식 장 src와 같은 공통 틀로 새 장 — 틀에서 딸려 온 빈 자리표시 상자는 지우고 src의 도형을 복사.
        drop_frame=False면 테두리를 남김 (칸 번호가 양식 도형 순서라 채운 뒤에 지울 때)."""
        s = self.prs.slides.add_slide(src.slide_layout)
        for ph in list(s.placeholders):
            ph._element.getparent().remove(ph._element)
        self._copy_shapes(src, s, text_too)
        if drop_frame:
            self._drop_frame(s)
        return s

    def _drop_frame(self, slide) -> None:
        """바깥 테두리·테두리 끝 짧은 막대·화면을 가로지르는 구분선을 지움 (style drop_frame, 사용자 피드백 2026-10-21).
        내용을 잇는 선(목차 연결선·항목 세로줄 등)은 길어서 남는다."""
        if not self.style.get("drop_frame"):
            return
        width, height = Emu(self.prs.slide_width).cm, Emu(self.prs.slide_height).cm
        for sh in list(slide.shapes):
            if sh.has_text_frame and sh.text_frame.text.strip() or sh.shape_type in (MSO_SHAPE_TYPE.PICTURE, MSO_SHAPE_TYPE.TABLE):
                continue
            left, top, w, h = (Emu(v).cm for v in (sh.left, sh.top, sh.width, sh.height))
            try:
                filled = sh.fill.type == MSO_FILL.SOLID
                color = str(sh.fill.fore_color.rgb) if filled else None
            except (TypeError, AttributeError):
                filled, color = False, None
            if color in self.style.get("drop_fill_colors", []):  # 회색 원·면 같은 배경 꾸밈 (사용자 피드백 2026-10-21)
                sh._element.getparent().remove(sh._element)
                continue
            thin = min(w, h) <= FRAME_LINE_CM
            at_edge = left <= 0.05 or top <= 0.05 or left + w >= width - 0.05 or top + h >= height - 0.05
            frame = not filled and w >= 0.75 * width and h >= 0.7 * height
            tick = thin and max(w, h) <= FRAME_TICK_CM and at_edge
            divider = thin and (h >= 0.95 * height or w >= 0.95 * width)
            if frame or tick or divider:
                sh._element.getparent().remove(sh._element)

    def set_cover(self, title_lines: list[str], header: str):
        boxes = [sh for sh in self.cover.shapes if sh.has_text_frame and sh.text_frame.text.strip()]
        big = max(boxes, key=lambda sh: sh.height)
        small = min(boxes, key=lambda sh: sh.height)
        self._replace_text(big, title_lines)
        self._replace_text(small, [header])
        sizes = self.style.get("cover_sizes")  # 양식 원래 크기는 한글 제목이 넘침
        if sizes:
            for i, p in enumerate(big.text_frame.paragraphs):
                for r in p.runs:
                    r.font.size = Pt(sizes[0] if i == 0 else sizes[1])

    @staticmethod
    def _replace_text(shape, lines):
        tf = shape.text_frame
        first = tf.paragraphs[0]
        template_run = copy.deepcopy(first.runs[0]._r) if first.runs else None
        for p in tf.paragraphs[1:]:
            p._p.getparent().remove(p._p)
        for r in list(first.runs):
            r._r.getparent().remove(r._r)
        for i, line in enumerate(lines):
            p = first if i == 0 else tf.add_paragraph()
            if template_run is not None:
                new_r = copy.deepcopy(template_run)
                end = p._p.find(qn("a:endParaRPr"))  # 문단 끝 표시보다 앞에 (뒤에 두면 PowerPoint가 글을 버림)
                if end is not None:
                    end.addprevious(new_r)
                else:
                    p._p.append(new_r)
                p.runs[-1].text = line
            else:
                p.add_run().text = line
            for r in p.runs:
                set_font(r)

    def section(self, number: int, name: str) -> None:
        """장 구분 슬라이드 (양식의 번호·장 이름 장) — 큰 장 앞에. 양식에 없으면 만들지 않음."""
        if self.section_src is None:
            return
        s = self._slide_like(self.section_src, text_too=True)
        for sh in s.shapes:
            if sh.has_text_frame and sh.text_frame.text.strip():
                self._replace_text(sh, [f"{number:02d}"] if sh.text_frame.text.strip().isdigit() else [name])

    def _tidy_closing(self) -> None:
        """마무리 장: 예시 연락처 줄만 지우고 출처 문구(무료 이용 조건)는 남김. 글꼴은 맑은 고딕."""
        drop = self.style.get("closing_drop", [])
        for sh in self.closing.shapes:
            if not sh.has_text_frame:
                continue
            paragraphs = sh.text_frame.paragraphs
            for p in paragraphs[1:]:
                if any(word in "".join(r.text for r in p.runs) for word in drop):
                    p._p.getparent().remove(p._p)
            for p in sh.text_frame.paragraphs:
                for r in p.runs:
                    set_font(r)
            if sh.text_frame.text.strip() and all(len(p.text) <= 40 for p in sh.text_frame.paragraphs):  # 짧은 줄은 넓은 글꼴로 바뀌어도 한 줄로 (아이콘 등 글 없는 칸 제외)
                sh.text_frame.word_wrap = False
                # 줄바꿈 끔을 무시하는 보기 프로그램도 있어 칸 자체를 넓힘 (사용자 피드백 2026-10-21: 'Thanks!'의 '!'가 아래로)
                left, top, height = sh.left, sh.top, sh.height  # 위치를 틀에서 물려받는 칸은 폭만 정하면 높이가 0이 됨
                sh.left, sh.top, sh.height = left, top, height
                sh.width = min(int(sh.width * CLOSING_WIDEN), self.prs.slide_width - left)

    # ---------- 구성안(slides.json)으로 양식 장 채우기 (사용자 결정 2026-10-21 — 양식 규칙에 맞춰 다시 씀) ----------
    def _fill_paragraphs(self, shape, texts: list[str], repeat: bool = False) -> None:
        """글이 있는 예시 문단을 차례로 바꿈 — 문단·글자 서식은 양식 그대로, 글꼴만 맑은 고딕. 남는 예시 문단은 지움.
        굵지 않은 본문 문단의 기술 핵심어는 굵게."""
        paragraphs = list(shape.text_frame.paragraphs)
        filled = [p for p in paragraphs if "".join(r.text for r in p.runs).strip()]
        if repeat and filled:
            while len(filled) < len(texts):
                shape.text_frame._txBody.append(copy.deepcopy(filled[0]._p))
                filled = [p for p in shape.text_frame.paragraphs if p.text.strip()]
            paragraphs = list(shape.text_frame.paragraphs)
        for p, text in zip(filled, texts):
            p_pr = p._p.get_or_add_pPr()
            p_pr.set("eaLnBrk", "0")  # 한글 단어 중간에서 줄을 바꾸지 않음
            p_pr.set("latinLnBrk", "0")
            if p.alignment in (PP_ALIGN.JUSTIFY, PP_ALIGN.DISTRIBUTE):  # 단어 단위 줄바꿈과 겹치면 글자 사이가 벌어짐
                p.alignment = PP_ALIGN.LEFT
            runs = [r for r in p.runs]
            model = copy.deepcopy(runs[0]._r)
            for r in runs:
                r._r.getparent().remove(r._r)
            body = not runs[0].font.bold
            for piece, is_tech in keyword_chunks(text, self.tech if body else []):
                new_r = copy.deepcopy(model)
                end = p._p.find(qn("a:endParaRPr"))
                if end is not None:
                    end.addprevious(new_r)
                else:
                    p._p.append(new_r)
                run = p.runs[-1]
                run.text = piece
                set_font(run)
                if is_tech:
                    run.font.bold = True
        if len(texts) < len(filled):  # 쓰지 않은 예시 문단(과 그 뒤 빈 문단)은 지움
            cut = paragraphs.index(filled[len(texts)])
            for p in paragraphs[cut:]:
                p._p.getparent().remove(p._p)

    @staticmethod
    def _widen(shape, width_cm: float, anchor: str) -> None:
        center = shape.left + shape.width / 2
        shape.width = Cm(width_cm)
        if anchor == "center":
            shape.left = int(center - shape.width / 2)

    def _place_image(self, slide, path: Path, box: list[float], source: str | None) -> None:
        """그림을 자리(box, cm) 안에 비율대로 가운데 — 원문 그림이면 아래에 출처 줄."""
        left, top, width, height = box
        caption_h = 0.7 if source else 0.0
        pic = slide.shapes.add_picture(str(path), Cm(left), Cm(top))
        scale = min(Cm(width) / pic.width, Cm(height - caption_h) / pic.height)
        pic.width, pic.height = int(pic.width * scale), int(pic.height * scale)
        pic.left, pic.top = int(Cm(left) + (Cm(width) - pic.width) / 2), int(Cm(top) + (Cm(height - caption_h) - pic.height) / 2)
        if source:
            p = slide.shapes.add_textbox(Cm(left), pic.top + pic.height, Cm(width), Cm(caption_h)).text_frame.paragraphs[0]
            p.alignment = PP_ALIGN.CENTER
            r = p.add_run()
            r.text = source
            set_font(r)
            r.font.size, r.font.color.rgb = Pt(10), self.c["subtitle"]

    def _place_table(self, slide, table: dict, box: list[float]) -> None:
        """표: 머리 행 회색, 가는 선 — 열 폭은 칸 글 길이에 비례."""
        header, rows = table["header"], table["rows"]
        left, top, width, height = box
        lengths = [max(4.0, *(weighted_len(str(r[j])) for r in [header] + rows)) for j in range(len(header))]
        frame = slide.shapes.add_table(len(rows) + 1, len(header), Cm(left), Cm(top), Cm(width), Cm(min(height, 1.1 * (len(rows) + 1))))
        frame.table.first_row = frame.table.horz_banding = False
        for j, n in enumerate(lengths):
            frame.table.columns[j].width = int(Cm(width) * n / sum(lengths))
        for i, row in enumerate([header] + rows):
            for j, value in enumerate(row):
                cell = frame.table.cell(i, j)
                cell.fill.solid()
                cell.fill.fore_color.rgb = self.c["header_fill"] if i == 0 else WHITE
                cell.text = ""
                cell.vertical_anchor = MSO_ANCHOR.MIDDLE  # 표 글은 상하좌우 가운데 (사용자 피드백 2026-10-21)
                cell.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER
                run = cell.text_frame.paragraphs[0].add_run()
                run.text = str(value)
                set_font(run)
                run.font.size, run.font.bold, run.font.color.rgb = Pt(11), i == 0, self.c["text"]
                tc_pr = cell._tc.get_or_add_tcPr()
                for k, side in enumerate(("a:lnL", "a:lnR", "a:lnT", "a:lnB")):  # 선은 칸 채우기보다 앞에 (문서 규칙 순서)
                    line = tc_pr.makeelement(qn(side), {"w": "9525"})
                    fill = line.makeelement(qn("a:solidFill"), {})
                    fill.append(fill.makeelement(qn("a:srgbClr"), {"val": str(self.c["text"])}))
                    line.append(fill)
                    tc_pr.insert(k, line)

    def plan_slide(self, kind: dict, spec: dict, run_dir: Path, number: int, sources: dict) -> None:
        """구성안의 한 장: 양식 장을 통째로 복제해 칸만 바꿈 (표지는 양식의 표지 장을 그대로 씀)."""
        src = self.originals[kind["slide"] - 1]
        s = src if src is self.cover else self._slide_like(src, text_too=True, drop_frame=False)
        shapes = list(s.shapes)  # 양식 장과 같은 순서
        for name, slot in (kind.get("slots") or {}).items():
            texts = spec["slots"][name]
            texts = [texts] if isinstance(texts, str) else texts
            shape = shapes[slot["shape"]]
            if slot.get("source"):
                source_slide, source_shape = slot["source"]
                model = self.originals[source_slide - 1].shapes[source_shape]
                # Copy the exact body-title geometry and typography, retaining this shape's id.
                shape.left, shape.top, shape.width, shape.height = model.left, model.top, model.width, model.height
                shape._element.replace(shape._element.txBody, copy.deepcopy(model._element.txBody))
            if slot.get("widen"):
                self._widen(shape, *slot["widen"])
            if slot.get("box"):
                shape.left, shape.top, shape.width, shape.height = [Cm(value) for value in slot["box"]]
                shape.text_frame.vertical_anchor = MSO_ANCHOR.TOP
                shape.text_frame.word_wrap = True
                shape.text_frame.auto_size = MSO_AUTO_SIZE.NONE
            shift = self.style.get("title_shift")  # 본문 장 제목을 왼쪽 위로 — 테두리 안쪽 여백이 필요 없어짐 (사용자 피드백 2026-10-21)
            if shift and (name == "title" or slot.get("is_title")) and src is not self.cover and "number" not in kind:
                shape.left += Cm(shift[0])
                shape.top += Cm(shift[1])
            self._fill_paragraphs(shape, texts, repeat=slot.get("repeat", False))
            if "space_after_pt" in slot:
                for paragraph in shape.text_frame.paragraphs:
                    paragraph.space_after = Pt(slot["space_after_pt"])
            if slot.get("anchor") == "bottom":  # 글이 칸보다 짧아도 아래 칸(부제)에 붙게 — 넓힌 표지 제목이 한 줄이 되면 사이가 벌어짐
                shapes[slot["shape"]].text_frame.vertical_anchor = MSO_ANCHOR.BOTTOM
        if "number" in kind:  # 맑은 고딕은 양식 글꼴보다 넓어 두 자리가 줄바꿈됨 → 줄바꿈 끔
            self._fill_paragraphs(shapes[kind["number"]], [f"{number:02d}"])
            shapes[kind["number"]].text_frame.word_wrap = False
        drop = kind.get("remove", []) + [i for key in ("image", "table") if key in kind for i in kind[key].get("remove", [])]
        for i in drop:  # 장 종류 목록이 지우라고 한 도형 (그림·표 자리의 예시, 필요 없는 꾸밈)
            shapes[i]._element.getparent().remove(shapes[i]._element)
        for i in kind.get("keep", []):  # 그대로 두는 번호 칸: 양식에 높이가 다른 칸이 섞여 있어(목차 02·03) 정사각형·가운데로 맞춤
            box = shapes[i]
            box.height = box.width
            box.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
            box.text_frame.word_wrap = False
            box.text_frame.auto_size = MSO_AUTO_SIZE.NONE  # 글에 맞춰 칸이 줄지 않게
            for p in box.text_frame.paragraphs:
                p.alignment = PP_ALIGN.CENTER
        for sh in s.shapes:  # 그대로 둔 글(예시 번호 등)도 맑은 고딕 (사용자 결정 2026-10-21 — 전부)
            if sh.has_text_frame:
                for p in sh.text_frame.paragraphs:
                    for r in p.runs:
                        set_font(r)
        if "image" in kind:
            self._place_image(s, run_dir / spec["image"], kind["image"]["box"], sources.get(spec["image"]))
        if "table" in kind:
            self._place_table(s, spec["table"], kind["table"]["box"])
        if s is not self.cover:  # 표지는 finish에서
            self._drop_frame(s)

    def finish(self, out: Path):
        self._tidy_closing()
        self._drop_frame(self.cover)
        self._drop_frame(self.closing)
        for slide in self.originals:
            if slide is not self.cover and slide is not self.closing:
                self._delete(slide)
        id_list = self.prs.slides._sldIdLst
        closing_id = next(s for s in id_list if self.prs.part.related_part(s.rId) is self.closing.part)
        id_list.remove(closing_id)
        id_list.append(closing_id)
        self.prs.save(str(out))

    # ---------- 슬라이드 요소 (위치·크기는 33.9×19.1 cm 화면 기준 — x/y/d/pt가 양식에 맞게 바꿈) ----------
    def slide(self, title: str, subtitle: str | None = None):
        s = self._slide_like(self.body_src, text_too=False) if self.body_src is not None else self.prs.slides.add_slide(self.blank)
        self.text(s, title, 0.13, 0.67, 33.43, 1.45, 28, self.c["title"], bold=True, mark=False)
        if subtitle:  # 요지처럼 긴 소제목은 한 줄에 들어가게 글자를 줄이고 폭을 넓힘 (본문과 겹치지 않게)
            long = len(subtitle) > SUBTITLE_FULL_SIZE_CHARS
            # 소제목에서는 약어를 풀지 않음 — 풀이는 본문 첫 등장에서 (풀이가 붙으면 두 줄이 돼 본문과 겹침, 사용자 결정 2026-10-16)
            box = self.text(s, subtitle, 0.1, 2.52, 33.4 if long else 26.0, 1.11, 15 if long else 20, self.c["subtitle"],
                            bold=True, expand=False, mark=False)
            box.text_frame.paragraphs[0].runs[0].font.underline = self.style.get("subtitle_underline", True)
        return s

    def runs(self, p, text, size, bold, color, mark=True):
        """문단에 글을 넣되 기술 핵심어는 따로 표시 (제목·소제목은 mark=False)."""
        for piece, is_tech in keyword_chunks(text, self.tech if mark else []):
            r = p.add_run()
            r.text = piece
            set_font(r)
            r.font.size, r.font.bold = self.pt(size), True if is_tech else bold
            r.font.color.rgb = self.c["tech"] if is_tech else color

    def text(self, slide, text, x, y, w, h, size, color=None, bold=None, align=None, fill=None, shape=False, expand=True, mark=True):
        color = self.c["text"] if color is None else color
        bold = self.body_bold if bold is None else bold
        if shape:
            box = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, self.x(x), self.y(y), self.d(w), self.d(h))
            box.fill.solid()
            box.fill.fore_color.rgb = fill or WHITE
            box.line.color.rgb = self.c["text"]
        else:
            box = slide.shapes.add_textbox(self.x(x), self.y(y), self.d(w), self.d(h))
        tf = box.text_frame
        tf.word_wrap = True
        for i, line in enumerate((self.abbr(text) if expand else text).split("\n")):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            if align:
                p.alignment = align
            self.runs(p, line, size, bold, color, mark)
        return box

    def bullets(self, slide, items: list[tuple[str, bool]], top=BODY_TOP, height=13.5, size=15, left=BODY_LEFT, width=BODY_WIDTH):
        box = slide.shapes.add_textbox(self.x(left), self.y(top), self.d(width), self.d(height))
        tf = box.text_frame
        tf.word_wrap = True
        for i, (line, emphasis) in enumerate(items):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.space_after = self.pt(8)
            p._p.get_or_add_pPr().set("latinLnBrk", "0")  # 영어 단어를 줄 끝에서 자르지 않음
            self.runs(p, "• " + self.abbr(line), size, True if emphasis else self.body_bold,
                      self.c["emphasis"] if emphasis else self.c["text"])
        return box

    def sections(self, slide, parts: list[tuple[str, list[tuple[str, bool]]]], top=BODY_TOP, size=14, left=BODY_LEFT,
                 width=BODY_WIDTH):
        """머리말 (1)(2)(3) 아래 글머리 — 보고서 분야 절과 같은 전개 (사용자 결정 2026-10-19). 머리말은 제목 색, 핵심어 표시 없음."""
        box = slide.shapes.add_textbox(self.x(left), self.y(top), self.d(width), self.d(sections_height(parts, width, size)))
        tf = box.text_frame
        tf.word_wrap = True
        first = True
        for head, items in parts:
            p = tf.paragraphs[0] if first else tf.add_paragraph()
            p.space_before, p.space_after, first = self.pt(0 if first else 4), self.pt(2), False
            self.runs(p, head, size, True, self.c["title"], mark=False)
            for line, emphasis in items:
                p = tf.add_paragraph()
                p.space_after = self.pt(8)
                p._p.get_or_add_pPr().set("latinLnBrk", "0")  # 영어 단어를 줄 끝에서 자르지 않음
                self.runs(p, "• " + self.abbr(line), size, True if emphasis else self.body_bold,
                          self.c["emphasis"] if emphasis else self.c["text"])
        return box

    def key_box(self, slide, title, lines, top=BODY_TOP, height=None, size=16):
        # 줄이 하나면 번호 없이 — 외톨이 '1.'은 목록처럼 보임 (사용자 피드백 2026-10-16)
        text = title + "\n" + ("\n".join(f"{i}. {line}" for i, line in enumerate(lines, 1)) if len(lines) > 1 else "".join(lines))
        box = self.text(slide, text, BODY_LEFT, top, BODY_WIDTH, height or (1.6 + 1.9 * len(lines)), size,
                        self.c["box_text"], fill=self.c["box_fill"], shape=True)
        box.text_frame.paragraphs[0].runs[0].font.color.rgb = self.c.get("box_title", self.c["box_text"])
        return box

    def table(self, slide, header, rows, widths, top=BODY_TOP, size=11, left=BODY_LEFT):
        shape = slide.shapes.add_table(len(rows) + 1, len(header), self.x(left), self.y(top), self.d(sum(widths)),
                                       self.d(1.0 * (len(rows) + 1)))
        table = shape.table
        for j, w in enumerate(widths):
            table.columns[j].width = self.d(w)
        for i, row in enumerate([header] + rows):
            for j, value in enumerate(row):
                cell = table.cell(i, j)
                cell.text = ""
                cell.fill.solid()
                cell.fill.fore_color.rgb = self.c["header_fill"] if i == 0 else WHITE
                cell.vertical_anchor = MSO_ANCHOR.MIDDLE  # 표 글은 상하좌우 가운데 (사용자 피드백 2026-10-21)
                for k, line in enumerate(self.abbr(str(value if value is not None else "")).split(chr(10))):
                    p = cell.text_frame.paragraphs[0] if k == 0 else cell.text_frame.add_paragraph()
                    p.alignment = PP_ALIGN.CENTER
                    self.runs(p, line, size, i == 0, self.c["text"], mark=i > 0)  # 머리 행은 핵심어 표시 안 함
        return shape

    def image(self, slide, path: Path, top=BODY_TOP, max_w=31.8, max_h=14.6, left=None):
        if not path.is_file():
            self.text(slide, f"(그림 없음: {path.name})", BODY_LEFT, top, 20, 1, 14)
            return
        pic = slide.shapes.add_picture(str(path), self.x(left if left is not None else BODY_LEFT), self.y(top))
        scale = min(self.d(max_w) / pic.width, self.d(max_h) / pic.height)
        pic.width, pic.height = int(pic.width * scale), int(pic.height * scale)
        if left is None:  # 화면 가운데
            pic.left = int(self.x(CANVAS_W / 2) - pic.width / 2)

    def arrow(self, slide, x1, y1, x2, y2, color=None):
        """주석용 화살표 (원문 그림 번호와 같은 색)."""
        line = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, self.x(x1), self.y(y1), self.x(x2), self.y(y2))
        line.line.color.rgb = color or self.c["annotation"]
        line.line.width = self.pt(2.25)
        tail = line.line._get_or_add_ln().makeelement(qn("a:tailEnd"), {"type": "triangle", "w": "med", "len": "med"})
        line.line._get_or_add_ln().append(tail)
        return line

    def numbered_box(self, slide, title, lines, x, y, w, h, size=13):
        """번호 주석 상자: 첫 줄(번호·제목)은 주석 색, 나머지는 본문 개조식."""
        box = self.text(slide, title + "\n" + "\n".join("• " + line for line in lines), x, y, w, h, size, shape=True)
        box.text_frame.vertical_anchor = MSO_ANCHOR.TOP
        for i, p in enumerate(box.text_frame.paragraphs):
            p.alignment = PP_ALIGN.LEFT
            for r in p.runs:
                if r.font.color.rgb != self.c["tech"]:
                    r.font.color.rgb = self.c["annotation"] if i == 0 else self.c["text"]
        return box

    def flow(self, slide, steps: list[str], top=6.0, highlight_last=True):
        n = len(steps)
        gap, w = 1.2, (BODY_WIDTH - 1.2 * (n - 1)) / n
        for i, step in enumerate(steps):
            x = BODY_LEFT + i * (w + gap)
            last = highlight_last and i == n - 1
            self.text(slide, step, x, top, w, 2.6, 16, self.c["highlight_text"] if last else None,
                      fill=self.c["highlight_fill"] if last else WHITE, shape=True, align=PP_ALIGN.CENTER)
            if i < n - 1:
                arrow = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, self.x(x + w + 0.15), self.y(top + 0.9), self.d(gap - 0.3), self.d(0.8))
                arrow.fill.solid()
                arrow.fill.fore_color.rgb = self.c["arrow"]
                arrow.line.fill.background()


def chunks(items, size):
    """최대 size개씩, 슬라이드마다 비슷한 개수로 나눈다 (마지막 장에 1–2줄만 남지 않게)."""
    if not items:
        return [[]]
    parts = -(-len(items) // size)
    per = -(-len(items) // parts)
    return [items[i:i + per] for i in range(0, len(items), per)]


# ---------- 발표 장 (id는 report_guide.md · config output.slide_sections, 보고서와 같은 흐름) ----------
def table_slides(deck, title, subtitle, header, rows, widths, per=TABLE_ROWS_PER_SLIDE, size=11):
    for part, chunk in enumerate(chunks(rows, per)):
        deck.table(deck.slide(title, subtitle + (" (계속)" if part else "")), header, chunk, widths, size=size)


def talk_purpose(deck, c):
    sc = c.s["scope"]
    slide = deck.slide("Purpose & Scope", "[목적] 무엇을 왜 조사했나")
    deck.bullets(slide, [(sc["question"], True)], height=2.4, size=16)
    show_flow = "landscape" not in sections("slide", c.run_dir)  # 흐름도는 연구 접근 장에 한 번만
    if show_flow:
        deck.flow(slide, sc["flow"], top=6.6)
    asked = topic_line(c.run_dir, c.refs).partition(": ")[2]  # 확정 주제 이름 그대로 (사용자 지시 2026-10-16)
    history = scope_history(c.run_dir)  # 입력 원문 → 범위 결정 → 세부 조사 (사용자 피드백 2026-10-16)
    rows = [*[[label, text] for label, text in history[:2]], *([["주제", asked]] if asked else []),
            *[[label, text] for label, text in history[2:]],
            ["핵심", sc["core"]], ["활용·확장", sc["extension"]], ["제외", sc["excluded"]]]
    deck.table(slide, ["구분", "범위"], rows, [4.0, 27.8], top=10.4 if show_flow else 6.6, size=13 if len(rows) <= 5 else 12)
    if c.kw:  # 핵심 키워드: 이 발표가 결론까지 따라가는 판단 기준
        slide = deck.slide("Purpose & Scope", "[키워드] 조사 전체에 쓰는 판단 기준")
        deck.table(slide, ["핵심 키워드", "뜻", "각 연구에 묻는 것"],
                   [[k["term"], k["plain"], k["question"]] for k in c.kw], [6.0, 14.0, 11.8], size=14)
    if sc.get("problem_types"):
        slide = deck.slide("Purpose & Scope", "[목적] 문제 유형 — 입력·출력이 달라 같은 지표로 비교할 수 없음")
        deck.table(slide, ["문제 유형", "입력", "출력", "왜 필요한가"],
                   [[t["name"], t["input"], t["output"], t["why"]] for t in sc["problem_types"]], [6.0, 8.0, 8.0, 9.8], size=13)
        if sc.get("framing"):
            deck.bullets(slide, [(sc["framing"], True)], top=15.6, height=2.4, size=14)


def talk_summary(deck, c):
    p = c.meta["prisma"]
    slide = deck.slide("Key Insight", "[인사이트] " + ((c.s.get("leads") or {}).get("summary") or "주요 발견"))
    deck.key_box(slide, "Key Message :", [keyword_tag(m, c.kw) + m["text"] + cite(m) for m in c.s["key_messages"]], size=16)
    deck.bullets(slide, [("유의점: " + i["text"], False) for i in c.s["limitations"][:2]]
                 + [(f"근거: 핵심논문 {p['selected']}편·문헌조사논문 {p['reviews_listed']}편 — {c.review_line}", False)],
                 top=13.4, height=4, size=12)


def talk_method(deck, c):
    subtitle = "[선별] 검색·선정 방법과 한계"
    lines = method_lines(c.meta, c.records, c.config, c.level_of, load_topic(c.run_dir))
    size = 12
    pages = bullets_pages(lines, (18.6, BODY_BOTTOM - 3.8), (BODY_WIDTH, BODY_BOTTOM - BODY_TOP), size)
    slide = deck.slide("Methodology", subtitle)
    deck.image(slide, c.run_dir / "figures" / "prisma.png", top=3.8, max_w=13.5, max_h=14.5, left=0.6)
    deck.bullets(slide, pages[0], left=14.6, width=18.6, top=3.8, height=BODY_BOTTOM - 3.8, size=size)
    for page in pages[1:]:  # 넘치는 줄은 다음 장에 전체 폭으로 (사용자 피드백 2026-10-16)
        deck.bullets(deck.slide("Methodology", subtitle + " (계속)"), page, height=BODY_BOTTOM - BODY_TOP, size=size)


def talk_landscape(deck, c):
    flow_png, roles_png = c.run_dir / "figures" / c.vname("theory_flow.png"), c.run_dir / "figures" / c.vname("limit_response.png")
    leads, ap = c.s.get("leads") or {}, display_names(c.run_dir, c.s, c.meta)["approach"]
    if flow_png.is_file():  # 장당 메시지 하나: 흐름도+문헌 / 한계→대응
        slide = deck.slide("Research Approaches", "[위치] " + (leads.get("landscape") or f"기술 흐름에서 {ap} 연구의 위치"))
        deck.image(slide, flow_png, top=3.7, max_h=14.6)
    if roles_png.is_file():
        slide = deck.slide("Research Approaches", "[접근] " + (leads.get("roles") or f"기존 방법의 한계 → {ap}의 역할"))
        deck.image(slide, roles_png, top=4.2, max_h=13.5)
    else:
        slide = deck.slide("Research Approaches", "[접근] " + (leads.get("roles") or leads.get("landscape") or f"{ap}의 역할"))
        deck.flow(slide, c.s["scope"]["flow"], top=3.9)
    if c.s.get("approach_roles") and not roles_png.is_file():
        deck.table(slide, ["접근(역할)", "예측 대상", "주로 쓰는 자료", "확인해야 할 성능"],
                   [[a["role"], a["target"], a["data"], a["check"]] for a in c.s["approach_roles"]],
                   [6.0, 8.6, 8.2, 9.0], top=7.6, size=12)
    slide = deck.slide("Research Approaches", "[분포] " + (leads.get("map") or f"문헌지도 — {c.axis['name']} × 접근법별 후보 분포"))
    # 그림은 왼쪽에 크게, 관찰은 오른쪽 칸 (사용자 피드백 2026-10-16: 아래에 두면 그림 높이가 묶여 작음)
    deck.image(slide, c.run_dir / "02_literature_map.png", top=3.7, max_w=22.5, max_h=BODY_BOTTOM - 3.7, left=BODY_LEFT)
    deck.bullets(slide, [(i["text"] + cite(i), n == 0) for n, i in enumerate(c.s["map_observations"])],
                 top=4.0, left=24.0, width=BODY_LEFT + BODY_WIDTH - 24.0, height=BODY_BOTTOM - 4.0, size=12)
    dist_png = c.run_dir / "figures" / "distribution.png"
    if dist_png.is_file():  # 논문 수 분포 — 대륙·축·접근법 (사용자 피드백 2026-10-19)
        slide = deck.slide("Research Approaches", f"[통계] 논문 수 분포 — {c.axis['name']}·접근법·대륙 (남색 = 핵심논문)")
        deck.image(slide, dist_png, top=3.9, max_h=BODY_BOTTOM - 3.9)


def subtopic_papers_table(deck, slide, c, t, top: float) -> None:
    """분야 장 아래 빈 자리에 '이 분야 논문' 표 — 요약의 method_comparison에서 (새 내용 없음). 대표 연구 먼저,
    화면에 들어가는 만큼만 (최대 SUBTOPIC_PAPER_ROWS), 나머지는 엑셀 안내 (사용자 피드백 2026-10-16: 분야 장 아래가 비어 있음)."""
    by_key = {m["key"]: m for m in c.s.get("method_comparison", [])}
    keys = list(dict.fromkeys([r["key"] for r in t.get("representatives", [])] + t["papers"]))
    rows_all = [[k, by_key[k].get("method", ""), by_key[k].get("input", ""), by_key[k].get("validation", "")]
                for k in keys if k in by_key]
    widths, size, note_h = [3.8, 9.0, 8.0, 11.0], 10, 0.8
    height, rows = 0.8, []  # 머리 행
    for row in rows_all[:SUBTOPIC_PAPER_ROWS]:
        row_h = max(est_lines(str(v), w - 0.3, size) for v, w in zip(row, widths)) * size * PT_CM * 1.2 + 0.3
        if top + height + row_h > BODY_BOTTOM - note_h:
            break
        rows.append(row)
        height += row_h
    if not rows:
        return
    deck.table(slide, ["인용 키", "방법", "입력 자료", "검증·결과"], rows, widths, top=top, size=size)
    if len(rows_all) > len(rows):
        deck.text(slide, f"외 {len(rows_all) - len(rows)}편 — 05_references 엑셀 '방법 비교' 시트", BODY_LEFT, top + height + 0.15,
                  BODY_WIDTH, note_h, 11, bold=False)


def talk_subtopics(deck, c):
    tree_png = c.run_dir / "figures" / c.vname("tech_tree.png")
    if tree_png.is_file():  # 분야별 장 앞에 전체 지도 한 장 (사용자 결정 2026-10-16)
        ap = display_names(c.run_dir, c.s, c.meta)["approach"]
        slide = deck.slide("Subtopics", "[계통] " + ((c.s.get("leads") or {}).get("subtopics")
                                                    or f"{ap} 연구 {len(c.s['subtopics'])}개 분야의 구성"))
        deck.image(slide, tree_png, top=3.7, max_h=14.6)
    for t in c.s["subtopics"]:
        # 보고서 분야 절과 같은 전개 (사용자 결정 2026-10-19): 요지(소제목) → (1) 목적과 방법 → (2) 주요 결과 → (3) 종합 및 남은 과제.
        # 슬라이드는 적게 — 결과 2개·남은 과제 1개, '핵심 범위와의 관계'는 보고서에만
        slide = deck.slide("Subtopics", f"[{t['name']}] " + (t.get("lead") or t["problem"]))
        parts = [("(1) 연구 목적과 방법", [(f"목적: {t['problem']} — {role_label(t, c.s)}, {len(t['papers'])}편", False),
                                       *([("방법: " + t["approaches"], False)] if t.get("approaches") else []),
                                       ("입력 → 출력: " + t["io"], False)]),
                 ("(2) 주요 결과", [(i["text"] + cite(i), False) for i in t["reported"][:2]]),
                 ("(3) 종합 및 남은 과제", [*([("종합: " + t["synthesis"], False)] if t.get("lead") and t.get("synthesis") else []),
                                         *[("남은 과제: " + u, True) for u in t["unverified"][:1]]])]
        parts = [(head, items) for head, items in parts if items]
        deck.sections(slide, parts, size=SUBTOPIC_SIZE)
        table_top = BODY_TOP + sections_height(parts, BODY_WIDTH, SUBTOPIC_SIZE) + 0.3
        if BODY_BOTTOM - table_top < SUBTOPIC_TABLE_MIN_CM:  # 표 자리가 모자라면 다음 장에 (표가 사라지지 않게)
            slide, table_top = deck.slide("Subtopics", f"[{t['name']}] 이 분야 논문 — 방법·입력·검증"), BODY_TOP
        subtopic_papers_table(deck, slide, c, t, table_top)
        figures = [f for f in c.s.get("figures", []) if f["subtopic"] == t["id"]][:2]
        if figures:  # 전문 모드: 원문 그림 + 빨간 번호·출처 (KR 발표 양식)
            slide = deck.slide("Subtopics", f"[원문 그림] {t['name']}")
            width = BODY_WIDTH / len(figures) - 0.6
            for i, fig in enumerate(figures):
                left = BODY_LEFT + i * (width + 0.6)
                deck.text(slide, f"({i + 1})", left, 3.7, 1.6, 0.9, 16, deck.c["annotation"], bold=True)
                deck.image(slide, c.run_dir / fig["file"], top=4.7, max_w=width, max_h=9.6, left=left)
                deck.numbered_box(slide, f"({i + 1}) {fig['key']} {fig['fig']} (p.{fig['page']})", [fig["caption"]],
                                  left, 14.6, width, 2.6)
    if c.s.get("keyword_matrix") and c.kw:  # 분야 × 핵심 키워드 — 결론의 키워드 판단이 여기서 나옴
        width = 23.8 / len(c.kw)
        deck.table(deck.slide("Subtopics", "[종합] " + ((c.s.get("leads") or {}).get("matrix") or "분야 × 핵심 키워드 판단")),
                   ["분야"] + [k["term"] for k in c.kw],
                   [[t["name"]] + [c.s["keyword_matrix"].get(t["id"], {}).get(k["id"], "미확인") for k in c.kw] for t in c.s["subtopics"]],
                   [8.0] + [width] * len(c.kw), size=12)
    metric_rows = [[m["key"], m["metric"], m["value"], m["condition"], f"p.{m['page']}"] for m in c.s.get("metrics_table", [])]
    if metric_rows:  # 전문 모드
        table_slides(deck, "Subtopics", "[비교] 수치 비교표 — 각 연구의 검증 조건에서 보고된 값", ["인용 키", "지표", "값", "조건", "쪽"],
                     metric_rows, [4.6, 4.4, 4.0, 15.4, 3.4])


def talk_issues(deck, c):
    issues = sorted(c.s["issues"], key=lambda i: i.get("priority", 99))
    table_slides(deck, "Open Issues", "[쟁점] 아직 답이 없는 질문 (순위: 이 조사의 판단)", ["순위", "열린 질문", "근거가 된 관찰"],
                 [[i.get("priority", ""), keyword_tag(i, c.kw) + i["question"], i["observation"] + cite(i)] for i in issues],
                 [1.8, 14.0, 16.0], per=5, size=12)
    slide = deck.slide("Open Issues", "[방향] " + ((c.s.get("leads") or {}).get("outlook") or "관찰된 접근과 가설"))
    deck.image(slide, c.run_dir / "figures" / "gap_matrix.png", top=3.7, max_h=6.6)
    outlook = sorted(c.s["outlook"], key=lambda o: o.get("kind") != "관찰")[:MAX_BULLETS]
    deck.bullets(slide, [(f"[{o.get('kind', '')}] {o['text']}{cite(o)}", False) for o in outlook],
                 top=10.8, height=7.5, size=12)


def talk_conclusion(deck, c):
    """결론: 연구 동향에 대한 판단 (독자가 논문을 직접 볼 것을 전제하지 않음, 읽기 목록 없음)."""
    slide = deck.slide("Conclusion", "[결론] " + ((c.s.get("leads") or {}).get("conclusion") or "연구 동향에 대한 판단"))
    points = c.s["conclusion"].get("points", [])
    if c.kw:  # 핵심 키워드마다 한 줄 판단 (분야×키워드 표의 요약)
        deck.table(slide, ["핵심 키워드", "판단"], [[keyword_tag(p, c.kw).strip("[] "), p["text"] + cite(p)] for p in points],
                   [6.0, 25.8], size=14)
    else:
        deck.bullets(slide, [(f"[{p.get('kind', '')}] {p['text']}{cite(p)}", p.get("kind") == "한계") for p in points],
                     height=11.5, size=14)
    if c.s["conclusion"].get("closing"):
        deck.key_box(slide, "Key Message : 종합", [c.s["conclusion"]["closing"]], top=15.2, height=2.6, size=15)


def talk_appendix_excel(deck, c):
    slide = deck.slide("Appendix", "[상세 자료] 05_references.xlsx 시트 안내")
    deck.table(slide, ["시트", "내용"], [[name, desc] for name, desc in EXCEL_SHEETS], [7.0, 24.8], size=12)


def talk_appendix_methods(deck, c):
    role = role_of(c.s)
    table_slides(deck, "Appendix", "[부록] 핵심논문 비교표", ["인용 키", "역할·관련성", "검토", "해결 문제", "방법", "구조물"],
                 [[m["key"], f"{role.get(m['key'], '')} · {c.refs[m['key']]['relevance']}점", c.level_of.get(m["key"], ""),
                   m.get("problem", ""), m["method"], m["structure"]] for m in c.s["method_comparison"]],
                 [4.0, 3.4, 2.0, 8.4, 9.6, 4.4])


def talk_appendix_excluded(deck, c):
    rows = excluded_rows(c.records, c.axis)
    slide = deck.slide("Appendix", f"[부록] 선정 밖 {len(rows)}편 점검 — 핵심논문과 분포 비교")
    comparison = excluded_comparison(c.records, c.axis)
    structure = [r for r in comparison if str(r[0]).startswith(c.axis["name"] + ": ")]
    deck.table(slide, ["항목", "핵심논문", "선정 밖"], [r for r in comparison if r not in structure], [8.6, 3.0, 3.0], size=10)
    deck.table(slide, [c.axis["name"], "핵심논문", "선정 밖"], [[r[0].split(": ", 1)[1], r[1], r[2]] for r in structure],
               [8.6, 3.0, 3.0], size=10, left=17.4)
    deck.bullets(slide, [("관련성 기준은 통과했지만 총점 미달·상한 초과로 빠진 논문 — 선정 편수 제한이 결론을 바꾸는지 확인하기 위한 표", True)],
                 top=16.2, height=1.6, size=13)
    if rows:
        table_slides(deck, "Appendix", "[부록] 선정 밖 논문 목록", ["순위", "제목", "연도", "종류", "인용", "관련성", "총점", c.axis["name"], "이유"],
                     rows, [1.8, 12.6, 1.9, 2.4, 1.7, 2.0, 2.0, 5.0, 2.4], size=10)


def talk_appendix_reviews(deck, c):
    table_slides(deck, "Appendix", "[부록] 문헌조사논문 (핵심논문과 별도)", ["인용 키", "제목", "쓰임", "정리한 내용"],
                 [[r["key"] + (" ★먼저" if r.get("core") else ""), c.refs[r["key"]]["title"], r.get("use", ""), r["why_read"]]
                  for r in c.s["reviews_guide"]], [5.0, 12.4, 3.6, 10.8], per=7)


def talk_appendix_adjacent(deck, c):  # 주목할 인접 문헌 (사용자 결정 2026-10-16) — 없으면 장을 만들지 않음
    if c.s.get("adjacent_guide"):
        table_slides(deck, "Appendix", "[부록] 주목할 인접 문헌 (핵심논문과 별도)", ["인용 키", "제목", "연도·실린 곳", "피인용", "관련성", "알아 둘 이유"],
                     adjacent_rows(c.s, c.refs), [4.0, 9.6, 5.4, 2.0, 2.0, 8.8], per=7)


def talk_appendix_data(deck, c):
    rows = [[d["name"], d.get("kind") or "", d.get("access") or "접근 미확인", ", ".join(d.get("used_by", []))]
            for d in c.s.get("datasets_benchmarks", [])]
    if rows:
        table_slides(deck, "Appendix", "[부록] 데이터·벤치마크 — 접근 상태 구분", ["이름", "종류", "접근 상태", "사용 논문"], rows,
                     [12.0, 5.0, 5.0, 9.8])


TALK_SECTIONS = {"summary": ("Key Insight", talk_summary), "landscape": ("Research Approaches", talk_landscape),
                 "subtopics": ("Subtopics", talk_subtopics), "issues": ("Open Issues", talk_issues),
                 "conclusion": ("Conclusion", talk_conclusion),
                 "appendix_purpose": ("Appendix", talk_purpose), "appendix_method": ("Appendix", talk_method),
                 "purpose": ("Purpose & Scope", talk_purpose), "method": ("Methodology", talk_method),
                 "appendix_excel": ("Appendix", talk_appendix_excel),
                 "appendix_methods": ("Appendix", talk_appendix_methods), "appendix_excluded": ("Appendix", talk_appendix_excluded),
                 "appendix_reviews": ("Appendix", talk_appendix_reviews), "appendix_data": ("Appendix", talk_appendix_data),
                 "appendix_adjacent": ("Appendix", talk_appendix_adjacent)}


class TalkContext:
    def __init__(self, s: dict, scored: dict, refs: dict, run_dir: Path, variant: str):
        self.s, self.meta, self.records, self.refs, self.run_dir = s, scored["meta"], scored["records"], refs, run_dir
        self.vname = lambda name: variant_name(name, variant)
        self.config = load_config()
        self.axis = map_axis(run_dir)  # 문헌지도·분포 가로축 (주제별)
        self.method_of = {m["key"]: m for m in s["method_comparison"]}
        self.review_line, self.level_of = review_info(run_dir, variant)
        self.kw = s.get("keywords", [])  # 핵심 키워드 (없으면 예전 형식)


def build_talk(deck: Deck, s: dict, scored: dict, refs: dict, run_dir: Path, variant: str) -> None:
    c = TalkContext(s, scored, refs, run_dir, variant)
    deck.set_cover(["LITERATURE SURVEY", report_title(run_dir, s, refs)], f"ALT Literature Survey (검색일 {c.meta['run_at'][:10]})")
    chosen = [sid for sid in sections("slide", run_dir) if sid in TALK_SECTIONS]  # 보고서 전용 장(용어·참고문헌)은 건너뜀
    names = list(dict.fromkeys(TALK_SECTIONS[sid][0] for sid in chosen))
    slide = deck.slide("Contents")
    for i, name in enumerate(names):
        deck.text(slide, str(i + 1), 2.0, 3.6 + i * 1.6, 1.2, 1.2, 16, WHITE, bold=True, fill=deck.c["title"], shape=True, align=PP_ALIGN.CENTER)
        deck.text(slide, name, 3.8, 3.65 + i * 1.6, 25, 1.2, 18)
    seen = set()
    for sid in chosen:
        name = TALK_SECTIONS[sid][0]
        if name not in seen:  # 큰 장 앞에 장 구분 — 번호는 목차와 같음 (사용자 승인 2026-10-21)
            seen.add(name)
            deck.section(names.index(name) + 1, name)
        TALK_SECTIONS[sid][1](deck, c)


def build_talk_plan(deck: Deck, plan: dict, catalog: dict, run_dir: Path, s: dict) -> None:
    """구성안(slides.json)대로 발표를 양식 장으로 다시 씀 (사용자 결정 2026-10-21). 장 구분 번호는 순서대로 매김."""
    sources, number = figure_sources(s), 0
    samples = {"".join(r.text for r in p.runs).strip() for kind in catalog["types"].values()
               for sh in deck.originals[kind["slide"] - 1].shapes if sh.has_text_frame for p in sh.text_frame.paragraphs}
    for spec in plan["slides"]:
        number += spec["type"] == "section"
        deck.plan_slide(catalog["types"][spec["type"]], spec, run_dir, number, sources)
    # 양식의 예시 글이 남았으면 실패 (번호처럼 짧은 글은 제외)
    kept = {id(sl) for sl in deck.originals if sl is not deck.cover}
    left = sorted({"".join(r.text for r in p.runs).strip() for sl in deck.prs.slides if id(sl) not in kept
                   for sh in sl.shapes if sh.has_text_frame for p in sh.text_frame.paragraphs} & {t for t in samples if len(t) > 3})
    if left:
        sys.exit(f"[pptx] 양식 예시 글이 남음: {left[:5]}")


def build_learn_plan(deck: Deck, plan: dict, catalog: dict, run_dir: Path, s: dict, meta: dict, refs: dict) -> None:
    """01_background: 구성안(slides_learn.json) 장 → 코드가 붙이는 마지막 장 구분 '용어와 읽는 법'
    (용어 표는 양식 표 장에, 읽는 법은 지금 그림 그대로 — 사용자 결정 2026-10-21)."""
    build_talk_plan(deck, plan, catalog, run_dir, s)
    types = catalog["types"]
    number = sum(spec["type"] == "section" for spec in plan["slides"]) + 1
    deck.plan_slide(types["section"], {"slots": {"title": LEARN_TAIL}}, run_dir, number, {})
    abbr = Abbreviations(s.get("abbreviations"))  # 용어 사전은 찾아보는 곳이라 항목마다 정식 명칭을 다시 보여 줌
    glossary = s["background"]["glossary"]
    for part, chunk in enumerate(chunks(glossary, TABLE_MAX_ROWS)):
        spec = {"slots": {"title": ["보고서·발표에 나오는 용어" + (" (계속)" if part else "")]},
                "table": {"header": ["용어", "쉬운 설명"], "rows": [[abbr(g["term"]), g["plain"]] for g in chunk]}}
        deck.plan_slide(types["table"], spec, run_dir, number, {})
    build_how_to_read(deck, s, meta, refs, run_dir)


def load_plan(run_dir: Path, deck_name: str, style: dict, catalog: dict, refs: dict) -> dict:
    """구성안 읽기 + 검사 — 없거나 검사에 실패하면 멈춤."""
    plan_file = DECK_FILES[deck_name][1]
    if not (run_dir / plan_file).is_file():
        sys.exit(f"[pptx] {plan_file} 없음 — prepare_slides.py --deck {deck_name} → alt-writer(slides_guide.md) 먼저")
    plan = read_json(run_dir / plan_file)
    errors = check_plan(plan, catalog, slot_limits(style, catalog), set(refs), run_dir)
    errors += check_learn_plan(plan) if deck_name == "learn" else []
    if errors:
        sys.exit(f"[pptx] {plan_file} 검사 실패:\n - " + "\n - ".join(errors))
    return plan


def build_how_to_read(deck: Deck, s: dict, meta: dict, refs: dict, run_dir: Path) -> None:
    """[사용자 지정] 읽는 법 2장: 실제 화면 예시 + 빨간 번호 (1)(2)(3) + 화살표."""
    w = meta["weights"]
    message = s["key_messages"][0]
    key = (message.get("cites") or [next(iter(refs))])[0]
    sentence = message["text"] if len(message["text"]) <= 40 else message["text"][:40].rsplit(" ", 1)[0] + " …"

    slide = deck.slide("How to Read", "[읽는 법 ①] 보고서·발표의 글 읽기")
    deck.text(slide, "예시 (보고서·발표에 실제로 나오는 형태)", BODY_LEFT, 3.7, 20, 0.9, 13, bold=False)
    deck.text(slide, f"“{sentence}”", BODY_LEFT, 4.7, 19.6, 1.8, 15, shape=True)
    deck.text(slide, f"[{key}]", 21.0, 4.7, 5.6, 1.8, 16, deck.c["annotation"], shape=True, align=PP_ALIGN.CENTER)
    deck.text(slide, "★" * (refs[key]["stars"] or 0), 27.2, 4.7, 5.6, 1.8, 18, shape=True, align=PP_ALIGN.CENTER)
    deck.arrow(slide, 23.8, 6.5, 23.8, 8.2)
    deck.arrow(slide, 30.0, 6.5, 30.0, 8.2)
    deck.numbered_box(slide, "(1) 근거 논문 이름표 (인용 키)",
                      ["첫 저자 성 + 발표 연도 (같으면 끝에 a·b)",
                       "05_references.xlsx '인용 키' 열에서 찾기 → 제목·원문 링크"], 14.6, 8.4, 12.0, 3.6)
    deck.numbered_box(slide, "(2) ★ = 총점 5단계",
                      [f"총점 = 관련성 {w['relevance']} + 인용 {w['citation']} + 학술지 {w['venue']}",
                       "조사 우선순위 점수 (논문 품질 판정 아님)"], 27.0, 8.4, 5.9, 3.6, size=12)
    deck.numbered_box(slide, "(3) [일반 개념]",
                      ["논문이 아니라 교과서 수준 설명", "출처 논문이 없는 기본 지식"], BODY_LEFT, 12.8, 10.0, 3.4)
    deck.numbered_box(slide, f"(4) 관련성 0–5점",
                      ["주제와 얼마나 직접 맞는가", f"AI 두 개가 채점 → 낮은 점수 채택, {meta['min_relevance']}점 이상만 선정"],
                      11.4, 12.8, 10.6, 3.4)
    deck.numbered_box(slide, "(5) 리뷰 논문",
                      ["다른 연구를 모아 정리한 논문", "30편과 따로 관리 → 처음 공부할 때 먼저 읽기"], 22.4, 12.8, 10.4, 3.4)

    slide = deck.slide("How to Read", "[읽는 법 ②] 그림 읽기")
    axis_name = map_axis(run_dir)["name"]
    figures = [(run_dir / "02_literature_map.png", "(1) 문헌지도",
                [f"가로 = {axis_name}, 세로 = 접근법, 원 크기 = 총점", "남색 = 핵심논문, ◆ = 문헌조사논문, 회색 = 기타 후보",
                 "번호 = 핵심논문 상위 (오른쪽 목록)"]),
               (run_dir / "figures" / "prisma.png", "(2) 문헌 선별 흐름도",
                ["PRISMA 흐름도 형식 참조", "위 → 아래: 단계마다 남은 편수", "오른쪽 상자: 빠진 이유와 편수", "노란 상자: 핵심논문"]),
               (run_dir / "figures" / "gap_matrix.png", "(3) 후보 문헌 분포",
                [f"칸 숫자 = 그 접근법 × {axis_name} 편수", "진할수록 조사 표본에 많음", "· (0편) = 표본에서 미확인 (연구 부재 아님)"])]
    for i, (path, title, lines) in enumerate(figures):
        left = BODY_LEFT + i * 10.75
        deck.text(slide, title.split(" ")[0], left, 3.7, 1.6, 0.9, 16, deck.c["annotation"], bold=True)
        deck.image(slide, path, top=4.7, max_w=10.2, max_h=6.6, left=left)
        deck.numbered_box(slide, title, lines, left, 11.6, 10.2, 4.6)

    slide = deck.slide("How to Read", "[읽는 법 ③] 문헌 선별 흐름도 (PRISMA)")
    deck.bullets(slide, [(line, i == len(PRISMA_NOTE) - 1) for i, line in enumerate(PRISMA_NOTE)], width=14.8, size=14)
    deck.image(slide, run_dir / "figures" / "prisma.png", max_w=16.0, max_h=13.5, left=BODY_LEFT + 15.8)


def build_learn(deck: Deck, s: dict, meta: dict, refs: dict, run_dir: Path, variant: str) -> None:
    b = s["background"]
    deck.set_cover(["BACKGROUND STUDY", report_title(run_dir, s, refs)], f"ALT 배경학습 자료 ({meta['run_at'][:10]})")

    slide = deck.slide("Purpose", "[안내] 이 자료의 목적과 읽는 순서")
    deck.bullets(slide, [(b["purpose"], True), ("문헌조사 결과가 아니라, 결과물을 쉽게 읽기 위한 배경 설명", False)], height=3.5)
    deck.flow(slide, ["00_summary", "01_background\n(이 자료)", "02_literature_map", "03_report\n04_presentation", "05_references\n06_context"],
              top=8.5, highlight_last=False)

    # 소제목은 장의 요지 (background.leads) — 없으면 실제 이름으로. 자리표시 말(config placeholder_phrases)은 쓰지 않음 (사용자 피드백 2026-10-16)
    leads, ap = b.get("leads") or {}, display_names(run_dir, s, meta)["approach"]
    slide = deck.slide("Big Picture", "[큰 그림] " + (leads.get("big_picture") or " → ".join(b["big_picture"])))
    deck.flow(slide, b["big_picture"], top=5.5)
    deck.bullets(slide, [(b["big_picture_note"], False)], top=10.0, height=3)

    tree_png = run_dir / "figures" / variant_name("tech_tree.png", variant)
    if tree_png.is_file():  # 큰 그림 다음에 분야 구성 (사용자 결정 2026-10-16)
        slide = deck.slide("Big Picture", f"[분야] {ap} 연구는 {len(s['subtopics'])}개 분야로 나뉨")
        deck.image(slide, tree_png, top=3.7, max_h=14.6)

    for c in b["concepts"]:
        slide = deck.slide("Key Concepts", f"[개념] {c['name']}")
        deck.bullets(slide, [(c["plain"], False)], height=4.5, size=18)
        deck.key_box(slide, "왜 중요한가 :", [c["why"]], top=9.0, size=18)
        deck.text(slide, f"근거: {c['source']}", BODY_LEFT, 16.6, 30, 0.9, 11, bold=False)

    slide = deck.slide("Approaches", "[비교] " + (leads.get("approaches") or f"기존 방법과 {ap}의 원리·장단점"))
    deck.table(slide, ["접근법", "원리", "장점", "한계"],
               [[a["approach"], a["principle"], a["pros"], a["cons"]] for a in b["approach_comparison"]], [4.0, 11.0, 8.4, 8.4], size=13)

    slide = deck.slide("Approaches", "[원리] " + (leads.get("basics") or f"{ap}의 기본 단계"))
    deck.flow(slide, b["data_driven_basics"], top=5.5)

    for part, chunk in enumerate(chunks(b["glossary"], 8)):
        slide = deck.slide("Glossary", "[용어] 보고서·발표에 나오는 용어" + (" (계속)" if part else ""))
        # 용어 사전은 찾아보는 곳이라 앞에서 풀었더라도 항목마다 정식 명칭을 다시 보여 준다
        terms = [Abbreviations(s.get("abbreviations"))(g["term"]) for g in chunk]
        deck.table(slide, ["용어", "쉬운 설명"], [[t, g["plain"]] for t, g in zip(terms, chunk)], [9.5, 22.3], size=13)

    build_how_to_read(deck, s, meta, refs, run_dir)

    rows = [[r["key"], r["why_read"]] for r in s["reviews_guide"]]
    if rows:  # 문헌조사논문이 없으면(좁은 세부 조사) 빈 장을 두지 않음
        # 이름형 소제목 — 요지로 쓰면 아래 표의 리뷰 요약과 겹침 (사용자 결정 2026-10-16)
        slide = deck.slide("Further Study", f"[참고] {ap} 연구를 정리한 문헌조사논문")
        deck.table(slide, ["인용 키", "읽으면 좋은 이유"], rows[:10], [5.0, 26.8], size=11)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--deck", choices=["all", "talk", "learn"], default="all")
    add_variant(parser)
    args = parser.parse_args()

    style = pptx_style()
    s = read_json(args.run_dir / variant_name("synthesis.json", args.variant))
    scored = read_json(args.run_dir / "scored.json")
    meta = scored["meta"]
    refs = read_json(args.run_dir / "references.json")
    catalog = load_catalog(style) if style["path"] else None  # 장 종류 목록이 있는 양식: 구성안대로 다시 씀 (⑨-1에서 alt-writer가 씀)
    if args.deck in ("all", "talk"):
        deck = Deck(style, s.get("abbreviations"), verbatim_strings(args.run_dir))
        deck.tech = tech_keywords(s)
        if catalog:
            build_talk_plan(deck, load_plan(args.run_dir, "talk", style, catalog, refs), catalog, args.run_dir, s)
        else:
            build_talk(deck, s, scored, refs, args.run_dir, args.variant)
        out = variant_name("04_presentation.pptx", args.variant)
        deck.finish(args.run_dir / out)
        print(f"[pptx] {out} {len(deck.prs.slides)}장")
    if args.deck in ("all", "learn"):
        deck = Deck(style, s.get("abbreviations"), verbatim_strings(args.run_dir))
        deck.tech = tech_keywords(s)
        if catalog:  # 배경학습도 같은 방식 (사용자 결정 2026-10-21)
            build_learn_plan(deck, load_plan(args.run_dir, "learn", style, catalog, refs), catalog, args.run_dir, s, meta, refs)
        else:
            build_learn(deck, s, meta, refs, args.run_dir, args.variant)
        out = variant_name("01_background.pptx", args.variant)
        deck.finish(args.run_dir / out)
        print(f"[pptx] {out} {len(deck.prs.slides)}장")


if __name__ == "__main__":
    main()
