"""그림 → figures/ : 문헌지도(02_literature_map.png), 문헌 선별 흐름도(PRISMA 흐름도 형식 참조), 후보 문헌 분포 행렬(gap_matrix.png),
배경 이론 + 문헌 통계 그림 2종(theory_flow.png, limit_response.png — synthesis.json에 해당 항목이 있을 때만)

    python alt/make_figures.py outputs/<run>/

- 문헌지도: 관련성 map_min_relevance점 이상 후보 전체. 가로 = 주제별 축 묶음(common.map_axis, 기본 구조물), 세로 = 접근법, 원 크기 = 총점
  남색 = 선정, ◆ = 리뷰 목록, 회색 = 기타 후보. 선정 상위 N편(총점)만 인용 키 이름표
- 분포 행렬: 관련성 기준 이상 후보 전체를 접근법 × 구조물로 센 표 (빈 칸 = 조사 표본 내 미확인, 연구 부재가 아님)
- 흐름도(theory_flow): 공학적 흐름 단계마다 기존 방법[일반 개념] → 조사 접근법 분야·편수 → 학습·검증 자료 구성
- 한계→대응(limit_response): 기존 방법의 한계 → 조사 접근법의 역할 → 편수·자료·대표 연구 → 확인해야 할 성능
  편수는 모두 synthesis.json의 논문 키로 코드가 센다 (글로 쓴 숫자를 옮기지 않음)
"""

from __future__ import annotations

import argparse
import math
import re
import textwrap
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.font_manager import FontProperties  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

from common import add_variant, axis_group, axis_labels, display_names, load_config, map_axis, read_json, role_label, variant_name  # noqa: E402
from figure_layout import (Diagram, BAR_HEIGHT_PT, CELL_PAD_PT, OUTER_PAD_PT, ROW_GAP_PT,
                           SAVE_PAD_IN, TEXT_GAP_PT)  # noqa: E402

# Report layout proportions and font sizes; presentation drawings retain their own layout.
FLOW_LABEL_FRACTION = 0.14
TREE_ROOT_FRACTION = 0.60
TREE_BRANCH_PT = 28
REFERENCE_FONT_PT = 10.5
BAR_LABEL_PAD_PT = 2
PRISMA_MAIN_FRACTION = 0.43


def primary_approach(tags: list[str], labels: dict) -> str:
    """대표 접근법: 데이터 기반 > 하이브리드 > CFD > 실험 > 이론 > 기타 순으로 가장 앞의 것."""
    order = ["data-driven", "hybrid", "cfd", "experiment", "theory", "other"]
    lowered = {t.lower() for t in tags or []}
    for tag in order:
        if tag in lowered:
            return labels[tag]
    return labels["other"]


def cell_offsets(n: int, half: float = 0.4) -> list[tuple[float, float]]:
    """칸 하나에 n개 점을 겹치지 않게 놓을 격자 위치 (칸 중심 기준, ±half 안). 칸이 가로로 넓어 열을 더 많이 둔다."""
    cols = math.ceil(math.sqrt(n * 1.5))
    rows = math.ceil(n / cols)
    step_x, step_y = 2 * half / cols, 2 * half / max(rows, 2)
    return [((i % cols - (cols - 1) / 2) * step_x, (i // cols - (rows - 1) / 2) * step_y) for i in range(n)]


MAP_STYLE = {"selected": ("o", "#002060", 0.9), "review_listed": ("D", "#185FA5", 0.9), "other": ("o", "#BBBBBB", 0.5)}


def reference_map(records: list[dict], references: dict, rules: dict, axis: dict, out: Path) -> None:
    key_of = {ref["openalex_id"]: key for key, ref in references.items()}
    pool = [r for r in records if r["relevance"] >= rules["map_min_relevance"] and not r["exclude"]]
    columns = axis_labels(axis)
    rows = list(dict.fromkeys(rules["approach_labels"].values()))
    cells: dict[tuple[int, int], list] = {}
    for r in pool:
        col = columns.index(axis_group(r, axis))
        row = rows.index(primary_approach(r["approach_tags"], rules["approach_labels"]))
        cells.setdefault((col, row), []).append(r)

    top = sorted((r for r in pool if r["status"] == "selected"), key=lambda r: -r["total_score"])[:rules["map_label_top_n"]]
    top_number = {r["openalex_id"]: i for i, r in enumerate(top, 1)}  # 이름표가 겹치지 않게 점에는 번호, 이름은 오른쪽 목록
    fig, ax = plt.subplots(figsize=(14, 7.5))
    for (col, row), items in cells.items():
        items.sort(key=lambda r: (r["status"] not in MAP_STYLE, -r["total_score"]))  # 선정·리뷰를 칸 앞쪽에
        offsets = cell_offsets(len(items))
        shrink = min(1.0, 12 / len(items)) ** 0.5  # 붐비는 칸은 점을 작게
        for r, (dx, dy) in zip(items, offsets):
            marker, color, alpha = MAP_STYLE.get(r["status"], MAP_STYLE["other"])
            highlighted = r["status"] in ("selected", "review_listed")
            is_new = r.get("update") == "NEW"  # 누적 갱신으로 새로 든 핵심논문 — 빨간 테두리 (사용자 지정 방식)
            ax.scatter(col + dx, row + dy, s=(30 + 330 * max(r["total_score"] - 0.3, 0) / 0.6) * shrink, marker=marker,
                       color=color, alpha=alpha, edgecolors="red" if is_new else "black" if highlighted else "none",
                       linewidths=1.8 if is_new else 0.5, zorder=3 if highlighted else 2)
            if r["openalex_id"] in top_number:
                ax.text(col + dx, row + dy, str(top_number[r["openalex_id"]]), ha="center", va="center",
                        fontsize=7, color="white", fontweight="bold", zorder=4)
    ax.set_xticks(range(len(columns)), [c.replace("·", "·\n", 1) for c in columns], fontsize=9)
    ax.set_yticks(range(len(rows)), rows, fontsize=10)
    ax.set_xlim(-0.5, len(columns) - 0.5)
    ax.set_ylim(-0.5, len(rows) - 0.5)
    ax.invert_yaxis()
    ax.set_xticks([x + 0.5 for x in range(len(columns) - 1)], minor=True)
    ax.set_yticks([y + 0.5 for y in range(len(rows) - 1)], minor=True)
    ax.grid(True, which="minor", color="#dddddd", zorder=0)
    ax.tick_params(which="minor", length=0)
    counts = {s: sum(r["status"] == s for r in pool) for s in ("selected", "review_listed")}
    for status, label in (("selected", "핵심논문"), ("review_listed", "문헌조사논문"), ("other", "기타 후보")):
        marker, color, alpha = MAP_STYLE[status]
        ax.scatter([], [], marker=marker, color=color, alpha=alpha, s=60, label=label,
                   edgecolors="none" if status == "other" else "black", linewidths=0.5)
    if any(r.get("update") == "NEW" for r in pool):
        ax.scatter([], [], marker="o", color=MAP_STYLE["selected"][1], s=60, edgecolors="red", linewidths=1.8,
                   label="NEW (누적 갱신으로 새로 든 핵심논문)")
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=9, frameon=False)
    ax.text(1.02, 0.8, "핵심논문 상위 (총점 순)\n" + "\n".join(f"{i}  {key_of.get(r['openalex_id'], '')}"
                                                          + (" NEW" if r.get("update") == "NEW" else "") for i, r in enumerate(top, 1)),
            transform=ax.transAxes, va="top", fontsize=9, linespacing=1.5)
    ax.set_title(f"문헌지도 — 관련성 {rules['map_min_relevance']}점 이상 후보 {len(pool)}편 "
                 f"(핵심논문 {counts['selected']} · 문헌조사논문 {counts['review_listed']} · 기타 {len(pool) - sum(counts.values())}), "
                 f"원 크기 = 총점, 번호 = 핵심논문 상위 {len(top)}편", fontsize=11, loc="left")
    fig.tight_layout()
    fig.savefig(out, dpi=200, bbox_inches="tight", pad_inches=SAVE_PAD_IN)
    plt.close(fig)


CONTINENT_KO = {"Asia": "아시아", "Europe": "유럽", "North America": "북미", "South America": "남미", "Africa": "아프리카",
                "Oceania": "오세아니아", "Antarctica": "남극"}
UNKNOWN_LABEL = "미상"


def distribution_counts(pool: list[dict], key, order: list[str] | None = None) -> list[tuple[str, int, int]]:
    """(묶음, 전체 편수, 핵심논문 편수) — order가 있으면 그 순서(0편 묶음도), 없으면 편수 많은 순 + 미상은 맨 뒤."""
    total, core = Counter(), Counter()
    for r in pool:
        label = key(r)
        total[label] += 1
        core[label] += r["status"] == "selected"
    labels = order or sorted(total, key=lambda g: (g == UNKNOWN_LABEL, -total[g]))
    return [(g, total[g], core[g]) for g in labels]


def continent_of(record: dict, affiliations: dict) -> str:
    work = affiliations.get("works", {}).get(record["openalex_id"]) or {}
    country = affiliations.get("countries", {}).get(work.get("country") or "", {})
    return CONTINENT_KO.get(country.get("continent"), country.get("continent")) or UNKNOWN_LABEL


def distribution(records: list[dict], rules: dict, axis: dict, affiliations: dict, out: Path) -> int:
    """논문 수 분포 (사용자 피드백 2026-10-19): 대륙별·축(활용 목적 등)별·접근법별 가로 막대를 한 그림에.
    대상은 문헌지도와 같은 후보, 막대 안 남색 = 핵심논문. 대륙은 교신저자 → 없으면 1저자 소속 (affiliations.json, 없으면 그 막대 생략)."""
    pool = [r for r in records if r["relevance"] >= rules["map_min_relevance"] and not r["exclude"]]
    panels = []
    if affiliations.get("works"):
        bases = Counter((affiliations["works"].get(r["openalex_id"]) or {}).get("basis", "unknown") for r in pool)
        panels.append((f"대륙별{chr(10)}(교신저자 {bases['corresponding']} · 1저자로 대신 {bases['first']} · 미상 {bases['unknown']})",
                       distribution_counts(pool, lambda r: continent_of(r, affiliations))))
    panels.append((f"{axis['name']}별", distribution_counts(pool, lambda r: axis_group(r, axis), axis_labels(axis))))
    approaches = list(dict.fromkeys(rules["approach_labels"].values()))
    panels.append(("접근법별", distribution_counts(pool, lambda r: primary_approach(r["approach_tags"], rules["approach_labels"]),
                                                approaches)))
    rows = max(len(p[1]) for p in panels)
    fig, axes = plt.subplots(1, len(panels), figsize=(FIG_WIDTH_IN, 0.42 * rows + 1.6))
    for ax, (title, counts) in zip(axes, panels):
        labels = [c[0] for c in counts]
        y = range(len(counts))
        ax.barh(y, [c[1] - c[2] for c in counts], left=[c[2] for c in counts], color="#BFBFBF")
        ax.barh(y, [c[2] for c in counts], color=NAVY)
        for i, (_, total, core) in enumerate(counts):
            ax.text(total, i, f" {total}" + (f" ({core})" if core else ""), va="center", fontsize=9)
        ax.set_yticks(list(y), labels, fontsize=10)
        ax.invert_yaxis()
        ax.set_xlim(0, max(c[1] for c in counts) * 1.35 or 1)
        ax.set_title(title, fontsize=10.5, loc="left")
        ax.spines[["top", "right"]].set_visible(False)
        ax.tick_params(axis="x", labelsize=8)
    fig.suptitle(f"논문 수 분포 — 관련성 {rules['map_min_relevance']}점 이상 후보 {len(pool)}편 "
                 f"(남색 = 핵심논문, 괄호 = 핵심논문 편수)", fontsize=12, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(out, dpi=200, bbox_inches="tight", pad_inches=SAVE_PAD_IN)
    plt.close(fig)
    return len(pool)


def prisma(meta: dict, out: Path) -> None:
    p = meta["prisma"]
    reviews = p["reviews_listed"] + p["reviews_not_listed"]
    institutions = p.get("institutions_listed", 0) + p.get("institutions_not_listed", 0)  # 기관·선급 문서 (별도 목록)
    cocited = p.get("cocited_listed", 0) + p.get("cocited_not_listed", 0)  # 공통 인용 고전 (별도 목록, 사용자 2026-10-19)
    no_abstract = p.get("excluded_no_abstract", 0)  # 초록 없음 + 인용 낮음 제외 (사용자 2026-10-19)
    after_retraction = p["screened"] - p["excluded_retracted"] - no_abstract
    passed = p["selected"] + p["below_threshold"] + p["over_limit"]  # 관련성 하한 통과 (총점과 무관)
    main = [("검색으로 찾은 문헌" + (" + 공통 인용 고전" if cocited else ""), p["identified"]), ("중복 제거 후", p["screened"]),
            ("연구 논문 (리뷰·기관 문서 제외)", after_retraction - reviews - institutions - cocited), (f"관련성 {meta['min_relevance']}점 이상", passed),
            ("핵심논문", p["selected"])]
    side = [(f"중복 제거 {p['duplicates_removed']}편", 0),
            (f"철회 제외 {p['excluded_retracted']}편" + (f" · 초록 없음·인용 낮음 제외 {no_abstract}편" if no_abstract else "")
             + f"\n리뷰 {reviews}편 → 문헌조사논문 후보로 별도 평가\n"
             f"(목록 {p['reviews_listed']} · 목록 외 {p['reviews_not_listed']})"
             + (f"\n기관·선급 문서 {institutions}편 → 별도 목록 {p.get('institutions_listed', 0)}" if institutions else "")
             + (f"\n공통 인용 고전 {cocited}편 → 별도 목록 {p.get('cocited_listed', 0)}" if cocited else ""), 1),
            (f"관련성 {meta['min_relevance']}점 미만 {p['below_relevance']}편", 2),
            (f"총점 {meta['min_total_score']} 미만 {p['below_threshold']}편\n상한({meta['max_selected']}편) 초과 {p['over_limit']}편", 3)]
    d = Diagram()
    y = d.title("문헌 선별 흐름도 (PRISMA 흐름도 형식 참조)")
    main_width = d.inner_width * PRISMA_MAIN_FRACTION
    side_x = d.left + main_width + TREE_BRANCH_PT
    side_width = d.width - OUTER_PAD_PT - side_x
    main_blocks = [d.block(f"{label}\n{n}편", main_width - 2 * CELL_PAD_PT) for label, n in main]
    side_blocks = [d.block(text, side_width - 2 * CELL_PAD_PT, size=REFERENCE_FONT_PT) for text, _ in side]
    center_x = d.left + main_width / 2
    for i, ((label, _), block) in enumerate(zip(main, main_blocks)):
        height = block.height + 2 * CELL_PAD_PT
        d.cell(d.left, y, main_width, height, [block], YELLOW if label == "핵심논문" else "white")
        y += height
        if i < len(side_blocks):
            side_block = side_blocks[i]
            side_height = side_block.height + 2 * CELL_PAD_PT
            # Keep exclusions beside the arrow between the two affected stages.
            next_y = y + side_height + 2 * TEXT_GAP_PT
            d.cell(side_x, y + TEXT_GAP_PT, side_width, side_height, [side_block], GRAY_FILL)
            d.arrow(center_x, y + 2, center_x, next_y - 2)
            d.arrow(center_x, (y + next_y) / 2, side_x - 2, (y + next_y) / 2)
            y = next_y
    note = d.block(f"+ 문헌조사논문(본문 기여 평가 통과) {p['reviews_listed']}편"
                   + (f" · 기관·선급 문서 {p.get('institutions_listed', 0)}편" if institutions else ""),
                   d.inner_width, size=REFERENCE_FONT_PT, color="#185FA5")
    d.text(note, d.left, y + ROW_GAP_PT)
    d.save(out, y + ROW_GAP_PT + note.height)


def gap_matrix(records: list[dict], rules: dict, axis: dict, out: Path) -> int:
    pool = [r for r in records if r["relevance"] >= rules["gap_matrix_min_relevance"] and not r["exclude"]]
    approaches = list(rules["approach_labels"].values())
    groups = axis_labels(axis)
    counts = Counter((rules["approach_labels"].get(t.lower(), "기타"), axis_group(r, axis))
                     for r in pool for t in (r["approach_tags"] or ["other"]))
    data = [[counts[(a, g)] for g in groups] for a in approaches]
    fig, ax = plt.subplots(figsize=(13, 4.8))
    ax.imshow(data, cmap="Blues", aspect="auto")
    peak = max(max(row) for row in data) or 1
    for i, row in enumerate(data):
        for j, v in enumerate(row):
            ax.text(j, i, str(v) if v else "·", ha="center", va="center", fontsize=10,
                    color="white" if v > peak * 0.6 else ("#A32D2D" if v == 0 else "black"))
    ax.set_xticks(range(len(groups)), [g.replace("·", "·\n", 1) for g in groups], fontsize=9)
    ax.set_yticks(range(len(approaches)), approaches, fontsize=10)
    ax.set_title(f"후보 문헌 분포 — 관련성 {rules['gap_matrix_min_relevance']}점 이상 후보 {len(pool)}편, 접근법 × {axis['name']} "
                 "(접근법 중복 포함: 칸 합계 ≠ 편수 · = 조사 표본 내 미확인)",
                 fontsize=11, loc="left")
    fig.tight_layout()
    fig.savefig(out, dpi=200, bbox_inches="tight", pad_inches=SAVE_PAD_IN)
    plt.close(fig)
    return len(pool)


# ---------- 배경 이론 + 문헌 통계 ----------
UNKNOWN_SOURCE = "미기재"
SOURCE_COLORS = ["#185FA5", "#70AD47", "#C00000", "#BFBFBF"]  # 설정의 자료 종류 순서 + 미기재(마지막)
NAVY, YELLOW, GRAY_FILL = "#002060", "#FFF2CC", "#F2F2F2"


def source_counts(keys: list[str], source_of: dict, labels: list[str]) -> dict:
    """논문 키 목록의 학습·검증 자료 종류별 편수 (한 논문이 여러 종류면 각각 셈, 없으면 미기재)."""
    counts = dict.fromkeys(labels + [UNKNOWN_SOURCE], 0)
    for key in keys:
        for label in source_of.get(key) or [UNKNOWN_SOURCE]:
            counts[label] += 1
    return counts


def checked_sources(s: dict, labels: list[str]) -> dict:
    source_of = {m["key"]: m.get("data_source") or [] for m in s["method_comparison"]}
    wrong = {x for v in source_of.values() for x in v} - set(labels)
    if wrong:
        raise ValueError(f"data_source에 설정(output.data_source_labels)에 없는 값: {sorted(wrong)}")
    return source_of


def stage_summary(s: dict, labels: list[str]) -> list[dict]:
    """흐름 단계마다: 기존 방법, 그 단계에 놓인 분야(이름·편수·역할), 학습·검증 자료 구성."""
    flow, methods = s["scope"]["flow"], s["scope"]["stage_methods"]
    if len(methods) != len(flow):
        raise ValueError("scope.stage_methods는 scope.flow와 같은 개수여야 함")
    unplaced = [t["id"] for t in s["subtopics"] if t.get("stage") not in flow]
    if unplaced:
        raise ValueError(f"subtopics[].stage가 scope.flow에 없음: {unplaced}")
    source_of = checked_sources(s, labels)
    stages = []
    for name, method in zip(flow, methods):
        subs = [t for t in s["subtopics"] if t["stage"] == name]
        keys = [k for t in subs for k in t["papers"]]
        stages.append({"name": name, "method": method, "papers": len(keys),
                       "subtopics": [(t["name"], len(t["papers"]), t["role"]) for t in subs],
                       "sources": source_counts(keys, source_of, labels)})
    return stages


def role_summary(s: dict, labels: list[str]) -> list[dict]:
    """접근(역할)마다: 기존 방법의 한계, 예측 대상, 편수, 학습·검증 자료, 대표 연구, 확인해야 할 성능."""
    source_of = checked_sources(s, labels)
    by_id = {t["id"]: t for t in s["subtopics"]}
    rows = []
    for a in s["approach_roles"]:
        subs = [by_id[i] for i in a["subtopic_ids"]]
        keys = [k for t in subs for k in t["papers"]]
        reps = [r["key"] for t in subs for r in t.get("representatives", [])]
        rows.append({"role": a["role"], "target": a["target"], "limit": a["limit"], "check": a["check"],
                     "papers": len(keys), "sources": source_counts(keys, source_of, labels), "reps": reps[:3]})
    return rows


def wrap(text: str, width: int) -> str:
    return textwrap.fill(text, width, break_long_words=False)


FIG_WIDTH_IN = 10.5  # 보고서 폭 16.5 cm(6.5인치)에 넣으면 약 0.62배 → 글자 13 pt ≈ 보고서 8 pt (사용자 피드백 2026-10-15: 글이 너무 작음)


def source_bar(ax, x: float, y: float, width: float, height: float, counts: dict, fontsize: float = 12) -> None:
    """자료 종류 구성 막대 (100% 누적, 칸 안에 편수 — 칸이 좁으면 생략)."""
    total = sum(counts.values())
    if not total:
        return
    for (label, n), color in zip(counts.items(), SOURCE_COLORS):
        w = width * n / total
        if n:
            ax.add_patch(plt.Rectangle((x, y), w, height, fc=color, ec="white", lw=0.8))
            font = FontProperties(family=plt.rcParams["font.family"], size=fontsize, weight="bold")
            label_width = ax.figure.canvas.get_renderer().get_text_width_height_descent(str(n), font, False)[0] * 72 / ax.figure.dpi
            if w >= label_width + 2 * BAR_LABEL_PAD_PT:
                ax.text(x + w / 2, y + height / 2, str(n), ha="center", va="center", fontsize=fontsize,
                        color="black" if label == UNKNOWN_SOURCE else "white", fontweight="bold")
        x += w


def source_legend(ax, x: float, y: float, labels: list[str], fontsize: float = 12, char_w: float = 0.33) -> float:
    """자료 종류 범례 → 끝 x 좌표 (다음 범례를 겹치지 않게 이어 붙이도록). char_w = 글자 하나의 가로 폭(축 단위)."""
    for label, color in zip(labels + [UNKNOWN_SOURCE], SOURCE_COLORS):
        ax.add_patch(plt.Rectangle((x, y - 0.15), 0.35, 0.3, fc=color))
        ax.text(x + 0.45, y, label, va="center", fontsize=fontsize)
        x += 0.45 + char_w * len(label) + 0.45
    return x


def theory_flow(stages: list[dict], labels: list[str], out: Path, approach: str) -> None:
    """같은 문헌 통계를 측정한 글자 폭과 가변 행 높이로 배치한다."""
    d = Diagram()
    y = d.title(f"기술 흐름에서 {approach} 연구의 위치 — 기존 방법과 핵심논문의 위치·근거 자료")
    label_width = d.inner_width * FLOW_LABEL_FRACTION
    col_width = (d.inner_width - label_width) / len(stages)
    box_width = col_width - ROW_GAP_PT
    text_width = box_width - 2 * CELL_PAD_PT
    headings = [d.block(st["name"], text_width, weight="bold") for st in stages]
    methods = [d.block(st["method"], text_width, color="#404040") for st in stages]
    topics = [[d.block(f"{name} {count}편", text_width) for name, count, _ in st["subtopics"]] for st in stages]
    row_labels = [d.block(label, label_width - CELL_PAD_PT, weight="bold", color=NAVY) for label in
                  ("공학적 흐름", "기존 방법\n[일반 개념]", f"{approach}\n연구 (편수)", "학습·검증 자료")]
    count_blocks = [d.block(f"{st['papers']}편", text_width) for st in stages]
    no_topics = d.block("해당 단계\n분야 없음", text_width, color="#7F7F7F")
    heights = [max(b.height for b in headings) + 2 * CELL_PAD_PT,
               max(b.height for b in methods) + 2 * CELL_PAD_PT,
               max([sum(b.height + BAR_HEIGHT_PT + 2 * TEXT_GAP_PT for b in bs) for bs in topics]
                   + [no_topics.height]) + 2 * CELL_PAD_PT,
               BAR_HEIGHT_PT + TEXT_GAP_PT + max(b.height for b in count_blocks) + 2 * CELL_PAD_PT]
    heights = [max(h, label.height + 2 * CELL_PAD_PT) for h, label in zip(heights, row_labels)]
    tops = []
    for h, label in zip(heights, row_labels):
        tops.append(y)
        d.text(label, d.left, y, h)
        y += h + ROW_GAP_PT
    peak = max([count for st in stages for _, count, _ in st["subtopics"]] or [1]) or 1
    for i, st in enumerate(stages):
        x = d.left + label_width + i * col_width
        core = any(role == "핵심" for _, _, role in st["subtopics"])
        d.cell(x, tops[0], box_width, heights[0], [headings[i]], YELLOW if core else "white")
        if i + 1 < len(stages):
            d.arrow(x + box_width + 2, tops[0] + heights[0] / 2,
                    x + col_width - 2, tops[0] + heights[0] / 2)
        d.text(methods[i], x + CELL_PAD_PT, tops[1], heights[1])
        topic_height = sum(b.height + BAR_HEIGHT_PT + 2 * TEXT_GAP_PT for b in topics[i])
        ty = tops[2] + (heights[2] - topic_height) / 2
        if not topics[i]:
            d.text(no_topics, x + CELL_PAD_PT, tops[2], heights[2])
        for block, (_, count, role) in zip(topics[i], st["subtopics"]):
            d.text(block, x + CELL_PAD_PT, ty)
            ty += block.height + TEXT_GAP_PT
            d.ax.add_patch(plt.Rectangle((x + CELL_PAD_PT, ty), text_width * count / peak, BAR_HEIGHT_PT,
                                        fc=NAVY if role == "핵심" else "#8FAADC"))
            ty += BAR_HEIGHT_PT + TEXT_GAP_PT
        if st["papers"]:
            sy = tops[3] + CELL_PAD_PT
            source_bar(d.ax, x + CELL_PAD_PT, sy, text_width, BAR_HEIGHT_PT, st["sources"])
            d.text(count_blocks[i], x + CELL_PAD_PT, sy + BAR_HEIGHT_PT + TEXT_GAP_PT)
    for top, height in zip(tops[:-1], heights[:-1]):
        d.ax.plot([d.left, d.width - OUTER_PAD_PT], [top + height + ROW_GAP_PT / 2] * 2, color="#D9D9D9", lw=0.8)
    bottom = d.legend(list(zip(labels + [UNKNOWN_SOURCE], SOURCE_COLORS)) + [("분야: 핵심", NAVY), ("분야: 활용", "#8FAADC")], y)
    d.save(out, bottom)


def limit_response(rows: list[dict], labels: list[str], out: Path, approach: str) -> None:
    """표형 그림: 왼쪽·세로 가운데 정렬, 긴 역할·대상·인용도 칸 안에서 줄바꿈."""
    d = Diagram()
    y = d.title(f"기존 방법의 한계와 {approach}의 대응 (편수는 핵심논문, 자료는 중복 포함)")
    width = (d.inner_width - 3 * ROW_GAP_PT) / 4
    content_width = width - 2 * CELL_PAD_PT
    xs = [d.left + i * (width + ROW_GAP_PT) for i in range(4)]
    headings = [d.block(t, content_width, weight="bold", color=NAVY) for t in
                ("기존 방법의 한계\n[일반 개념]", f"{approach}\n→ 예측 대상", "근거: 핵심논문 편수\n· 학습·검증 자료", "확인해야 할 성능")]
    header_height = max(b.height for b in headings) + 2 * CELL_PAD_PT
    for x, block in zip(xs, headings):
        d.text(block, x + CELL_PAD_PT, y, header_height)
    y += header_height + TEXT_GAP_PT
    peak = max((r["papers"] for r in rows), default=1) or 1
    for row in rows:
        limit = d.block(row["limit"], content_width)
        role = d.block(row["role"], content_width, weight="bold", color=NAVY)
        target = d.block(row["target"], content_width)
        check = d.block(row["check"], content_width)
        reps = d.block("예: " + ", ".join(row["reps"]), content_width, size=REFERENCE_FONT_PT, color="#404040")
        count = d.block(f"{row['papers']}편", content_width, weight="bold")
        evidence_height = count.height + 2 * BAR_HEIGHT_PT + 3 * TEXT_GAP_PT + reps.height
        height = max(limit.height, role.height + TEXT_GAP_PT + target.height, check.height, evidence_height) + 2 * CELL_PAD_PT
        d.cell(xs[0], y, width, height, [limit], GRAY_FILL)
        d.cell(xs[1], y, width, height, [role, target], edge=NAVY)
        d.cell(xs[3], y, width, height, [check], YELLOW)
        for left, right in zip(xs[:2], xs[1:3]):
            d.arrow(left + width + 2, y + height / 2, right - 2, y + height / 2)
        ey = y + (height - evidence_height) / 2
        d.text(count, xs[2] + CELL_PAD_PT, ey)
        ey += count.height + TEXT_GAP_PT
        d.ax.add_patch(plt.Rectangle((xs[2] + CELL_PAD_PT, ey), content_width * row["papers"] / peak, BAR_HEIGHT_PT, fc=NAVY))
        ey += BAR_HEIGHT_PT + TEXT_GAP_PT
        source_bar(d.ax, xs[2] + CELL_PAD_PT, ey, content_width, BAR_HEIGHT_PT, row["sources"], fontsize=REFERENCE_FONT_PT)
        ey += BAR_HEIGHT_PT + TEXT_GAP_PT
        d.text(reps, xs[2] + CELL_PAD_PT, ey)
        y += height + ROW_GAP_PT
    d.save(out, d.legend(list(zip(labels + [UNKNOWN_SOURCE], SOURCE_COLORS)), y))


TREE_MAX_METHODS, TREE_MAX_REPS = 4, 3  # 계통도: 분야당 기법 잎·대표 키 최대 수


def split_methods(text: str) -> list[str]:
    """'A·B, C(D, E), F' → ['A·B', 'C(D, E)', 'F'] — 괄호 안 쉼표는 나누지 않음."""
    return [m.strip() for m in re.split(r",\s*(?![^()]*\))", text or "") if m.strip()]


def tree_summary(s: dict) -> list[dict]:
    """역할(핵심 먼저)마다 분야: 이름·편수(논문 키 수)·기법 잎(subtopics[].approaches)·대표 키 — 기술 계통도용."""
    roles = sorted(dict.fromkeys(t.get("role", "") for t in s["subtopics"]), key=lambda r: r != "핵심")
    groups = []
    for role in roles:
        subs = [t for t in s["subtopics"] if t.get("role", "") == role]
        groups.append({"role": role, "label": role_label(subs[0], s), "subtopics": [
            {"name": t["name"], "papers": len(t["papers"]),
             "methods": split_methods(t.get("approaches", ""))[:TREE_MAX_METHODS],
             "reps": [r["key"] for r in t.get("representatives", [])][:TREE_MAX_REPS]} for t in subs]})
    return groups


def tech_tree(groups: list[dict], root: str, out: Path) -> None:
    """역할→분야→기법: 각 노드와 가지의 실제 글자 크기로 높이를 정한다."""
    d = Diagram()
    y = d.title("기술 계통도 — 역할 → 분야(핵심논문 편수·대표 연구) → 대표 기법")
    subs = [t for g in groups for t in g["subtopics"]]
    col_width = d.inner_width / len(subs)
    box_width = col_width - TEXT_GAP_PT
    content_width = box_width - 2 * CELL_PAD_PT
    root_width = d.inner_width * TREE_ROOT_FRACTION
    root_block = d.block(root, root_width - 2 * CELL_PAD_PT, weight="bold")
    root_height = root_block.height + 2 * CELL_PAD_PT
    d.cell((d.width - root_width) / 2, y, root_width, root_height, [root_block], YELLOW)
    root_bottom = y + root_height
    role_top = root_bottom + TREE_BRANCH_PT
    role_blocks = [d.block(g["label"], min(len(g["subtopics"]) * col_width - TEXT_GAP_PT, root_width) - 2 * CELL_PAD_PT,
                           weight="bold", color="white" if g["role"] == "핵심" else "black") for g in groups]
    role_height = max(b.height for b in role_blocks) + 2 * CELL_PAD_PT
    sub_top = role_top + role_height + TREE_BRANCH_PT
    names = [d.block(f"{t['name']}\n{t['papers']}편", content_width, weight="bold") for t in subs]
    reps = [d.block("예: " + ", ".join(t["reps"]), content_width, size=REFERENCE_FONT_PT, color="#595959") if t["reps"] else None for t in subs]
    sub_height = max(a.height + (TEXT_GAP_PT + b.height if b else 0) for a, b in zip(names, reps)) + 2 * CELL_PAD_PT

    def elbow(x0, y0, x1, y1):
        mid = (y0 + y1) / 2
        d.ax.plot([x0, x0, x1, x1], [y0, mid, mid, y1], color=NAVY, lw=1.1)

    index, bottom = 0, sub_top + sub_height
    for group, role_block in zip(groups, role_blocks):
        role_center = d.left + (index + len(group["subtopics"]) / 2) * col_width
        role_width = min(len(group["subtopics"]) * col_width - TEXT_GAP_PT, root_width)
        d.cell(role_center - role_width / 2, role_top, role_width, role_height, [role_block],
               NAVY if group["role"] == "핵심" else "#8FAADC")
        elbow(d.width / 2, root_bottom, role_center, role_top)
        for topic in group["subtopics"]:
            x = d.left + index * col_width + TEXT_GAP_PT / 2
            center = x + box_width / 2
            blocks = [names[index]] + ([reps[index]] if reps[index] else [])
            d.cell(x, sub_top, box_width, sub_height, blocks)
            elbow(role_center, role_top + role_height, center, sub_top)
            leaf_y = sub_top + sub_height + ROW_GAP_PT
            stem_x = x + CELL_PAD_PT
            for method in topic["methods"]:
                block = d.block(method, content_width - TEXT_GAP_PT, size=REFERENCE_FONT_PT)
                d.ax.plot([stem_x, stem_x + TEXT_GAP_PT / 2], [leaf_y + block.height / 2] * 2, color=NAVY, lw=1.1)
                d.ax.plot([stem_x, stem_x], [sub_top + sub_height, leaf_y + block.height / 2], color=NAVY, lw=1.1)
                d.text(block, stem_x + TEXT_GAP_PT, leaf_y)
                leaf_y += block.height + TEXT_GAP_PT
            bottom = max(bottom, leaf_y)
            index += 1
    d.save(out, bottom)


# ---------- 발표용 단순화 그림 (사용자 피드백 2026-10-21: 보고서 그림을 붙이지 말고 발표 스타일로 단순하게) ----------
# 양식 01처럼 진회색 띠·흰 글자·회색 선, 그림 안 제목 없음(장 제목이 있음). 장의 큰 그림 자리(약 2.2:1)에 맞춘 크기.
# 편수는 보고서 그림과 같은 요약 함수(stage_summary·role_summary·tree_summary)에서 — 자료 구성 막대·대표 연구·기법 잎은 뺌.
SLIDE_FIG_IN = (11.0, 5.0)
DARK, MID, LIGHT = "#333333", "#777777", "#B2B2B2"


def _slide_axes(width: float, height: float):
    fig, ax = plt.subplots(figsize=SLIDE_FIG_IN)
    ax.axis("off")
    ax.set_xlim(0, width)
    ax.set_ylim(0, height)
    return fig, ax


def _tab(ax, x, y, w, h, text, size=15):
    """진회색 띠 + 흰 굵은 글자 (양식의 번호·단계 띠)."""
    ax.add_patch(plt.Rectangle((x, y), w, h, fc=DARK, ec="none"))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=size, fontweight="bold", color="white", linespacing=1.1)


def _save_slide(fig, out: Path) -> None:
    fig.subplots_adjust(0.01, 0.01, 0.99, 0.99)
    fig.savefig(out, dpi=200, transparent=True)  # 양식 바탕색(옅은 회색) 위에서 네모가 보이지 않게
    plt.close(fig)


def slide_flow(stages: list[dict], out: Path) -> None:
    """기술 흐름 단계: 단계 띠 → 기존 방법 한 줄 → 핵심논문 편수·분야 수."""
    n, width, height = len(stages), 22.0, 10.0
    col, gap = width / n, 0.7
    fig, ax = _slide_axes(width, height)
    for i, st in enumerate(stages):
        x = i * col + gap / 2
        w = col - gap
        _tab(ax, x, 7.6, w, 1.6, wrap(st["name"], 8), size=16)
        if i < n - 1:
            ax.annotate("", (x + w + gap - 0.05, 8.4), (x + w + 0.05, 8.4), arrowprops=dict(arrowstyle="-|>", color=LIGHT, lw=2))
        ax.text(x + w / 2, 5.6, wrap(st["method"], 10), ha="center", va="center", fontsize=13, color=MID, linespacing=1.2)
        ax.plot([x, x + w], [3.9, 3.9], color=LIGHT, lw=1)
        ax.text(x + w / 2, 2.5, f"{st['papers']}편" if st["papers"] else "–", ha="center", va="center", fontsize=26,
                fontweight="bold", color=DARK)
        ax.text(x + w / 2, 1.1, f"분야 {len(st['subtopics'])}개" if st["subtopics"] else "분야 없음", ha="center", va="center",
                fontsize=12, color=MID)
    _save_slide(fig, out)


def slide_limits(rows: list[dict], out: Path) -> None:
    """기존 방법의 한계 → 역할(띠) → 핵심논문 편수."""
    n, width = len(rows), 22.0
    pitch = 10.0 / n
    fig, ax = _slide_axes(width, 10.0)
    for i, r in enumerate(rows):
        mid = 10.0 - (i + 0.5) * pitch
        ax.text(0.2, mid, wrap(r["limit"], 26), va="center", fontsize=13, color=MID, linespacing=1.2)
        ax.annotate("", (11.3, mid), (10.1, mid), arrowprops=dict(arrowstyle="-|>", color=LIGHT, lw=2))
        _tab(ax, 11.5, mid - pitch * 0.32, 6.6, pitch * 0.64, wrap(r["role"], 12), size=15)
        ax.text(19.0, mid, f"{r['papers']}편", va="center", fontsize=22, fontweight="bold", color=DARK)
        if i < n - 1:
            ax.plot([0.2, width - 0.2], [mid - pitch / 2, mid - pitch / 2], color=LIGHT, lw=0.8)
    _save_slide(fig, out)


def slide_tree(groups: list[dict], root: str, out: Path) -> None:
    """주제 → 역할(띠) → 분야(이름·편수). 기법 잎·대표 연구는 뺌."""
    subs = [t for g in groups for t in g["subtopics"]]
    width, height = 22.0, 10.0
    col = width / len(subs)
    fig, ax = _slide_axes(width, height)
    ax.add_patch(plt.Rectangle((width / 2 - 4.5, 8.4), 9.0, 1.4, fc="white", ec=DARK, lw=1.5))
    ax.text(width / 2, 9.1, wrap(root.replace("\n", " "), int(9.0 / 0.42)), ha="center", va="center", fontsize=15, fontweight="bold", color=DARK)
    start = 0
    for g in groups:
        centers = [(start + k + 0.5) * col for k in range(len(g["subtopics"]))]
        cx = sum(centers) / len(centers)
        role_w = min(len(centers) * col - 0.4, 7.0)
        ax.plot([width / 2, width / 2, cx, cx], [8.4, 7.7, 7.7, 7.2], color=LIGHT, lw=1.5)
        _tab(ax, cx - role_w / 2, 5.9, role_w, 1.3, wrap(g["label"], max(4, int(role_w / 0.42))), size=14)
        for x, t in zip(centers, g["subtopics"]):
            ax.plot([cx, cx, x, x], [5.9, 5.3, 5.3, 4.8], color=LIGHT, lw=1.5)
            ax.add_patch(plt.Rectangle((x - col / 2 + 0.15, 0.4), col - 0.3, 4.4, fc="white", ec=LIGHT, lw=1.2))
            ax.text(x, 3.3, wrap(t["name"], max(4, int(col / 0.42))), ha="center", va="center", fontsize=12.5,
                    fontweight="bold", color=DARK, linespacing=1.15)
            ax.text(x, 1.2, f"{t['papers']}편", ha="center", va="center", fontsize=18, fontweight="bold", color=DARK)
        start += len(g["subtopics"])
    _save_slide(fig, out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", type=Path)
    add_variant(parser)
    args = parser.parse_args()

    rules = load_config()["output"]
    plt.rcParams["font.family"] = rules["font"]
    plt.rcParams["axes.unicode_minus"] = False
    scored = read_json(args.run_dir / "scored.json")
    references = read_json(args.run_dir / "references.json")
    fig_dir = args.run_dir / "figures"
    fig_dir.mkdir(exist_ok=True)

    axis = map_axis(args.run_dir)
    unassigned = sum(r["openalex_id"] not in axis.get("assign", {}) for r in scored["records"]
                     if r["relevance"] >= rules["map_min_relevance"] and not r["exclude"])
    if axis["field"] == "text" and unassigned:
        print(f"[figures] 주의: 가로축 '{axis['name']}' AI 분류가 없는 후보 {unassigned}편은 낱말 미리보기로 나눔 — classify_axis.py 먼저")
    reference_map(scored["records"], references, rules, axis, args.run_dir / "02_literature_map.png")
    affiliations_path = args.run_dir / "affiliations.json"
    total = distribution(scored["records"], rules, axis, read_json(affiliations_path) if affiliations_path.is_file() else {},
                         fig_dir / "distribution.png")
    print(f"[figures] figures/distribution.png (논문 수 분포 {total}편" + ("" if affiliations_path.is_file()
          else " — 대륙 막대 없음: fetch_affiliations.py 먼저") + ")")
    prisma(scored["meta"], fig_dir / "prisma.png")
    pool = gap_matrix(scored["records"], rules, axis, fig_dir / "gap_matrix.png")
    print(f"[figures] 02_literature_map.png, figures/prisma.png, figures/gap_matrix.png (공백 행렬 {pool}편)")

    synthesis_path = args.run_dir / variant_name("synthesis.json", args.variant)  # 아래 두 그림만 판마다 다름
    s = read_json(synthesis_path) if synthesis_path.is_file() else {}
    labels = rules["data_source_labels"]
    if s.get("scope", {}).get("stage_methods"):
        out = variant_name("theory_flow.png", args.variant)
        theory_flow(stage_summary(s, labels), labels, fig_dir / out, display_names(args.run_dir, s, scored["meta"])["approach"])
        print(f"[figures] figures/{out} (흐름도 + 문헌)")
    if s.get("approach_roles") and all("subtopic_ids" in a for a in s["approach_roles"]):
        out = variant_name("limit_response.png", args.variant)
        limit_response(role_summary(s, labels), labels, fig_dir / out, display_names(args.run_dir, s, scored["meta"])["approach"])
        print(f"[figures] figures/{out} (한계 → 대응)")
    if s.get("subtopics"):
        out = variant_name("tech_tree.png", args.variant)
        names = display_names(args.run_dir, s, scored["meta"])
        tech_tree(tree_summary(s), f"{names['topic']}\n{names['approach']}".strip(), fig_dir / out)
        print(f"[figures] figures/{out} (기술 계통도)")
    # 발표용 단순화 그림 (사용자 피드백 2026-10-21) — 보고서 그림과 같은 요약에서
    made = []
    if s.get("scope", {}).get("stage_methods"):
        slide_flow(stage_summary(s, labels), fig_dir / "slide_flow.png")
        made.append("slide_flow.png")
    if s.get("approach_roles") and all("subtopic_ids" in a for a in s["approach_roles"]):
        slide_limits(role_summary(s, labels), fig_dir / "slide_limits.png")
        made.append("slide_limits.png")
    if s.get("subtopics"):
        names = display_names(args.run_dir, s, scored["meta"])
        slide_tree(tree_summary(s), f"{names['topic']} {names['approach']}".strip(), fig_dir / "slide_tree.png")
        made.append("slide_tree.png")
    if made:
        print(f"[figures] 발표용: {', '.join('figures/' + m for m in made)}")


if __name__ == "__main__":
    main()
