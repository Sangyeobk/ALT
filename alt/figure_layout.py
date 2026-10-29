"""Measured report diagram layout. Coordinates are physical points, from top left."""

from dataclasses import dataclass
import re

import matplotlib.pyplot as plt
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.font_manager import FontProperties
from matplotlib.patches import FancyBboxPatch

from common import output_language

POINTS_PER_INCH = 72
FIGURE_WIDTH_PT = 756
OUTER_PAD_PT = 14
CELL_PAD_PT = 8
ROW_GAP_PT = 16
TEXT_GAP_PT = 7
BAR_HEIGHT_PT = 16
BODY_FONT_PT = 12
TITLE_FONT_PT = 14
REPORT_DPI = 220
SAVE_PAD_IN = 0.14
LINE_SPACING = 1.2
MEASURE_SAFETY_PT = 2


@dataclass
class TextBlock:
    text: str
    height: float
    size: float
    weight: str
    color: str


class Diagram:
    def __init__(self):
        self.width = FIGURE_WIDTH_PT
        self.left = OUTER_PAD_PT
        self.inner_width = self.width - 2 * OUTER_PAD_PT
        self.fig, self.ax = plt.subplots(figsize=(self.width / POINTS_PER_INCH, 8))
        self.ax.set_position([0, 0, 1, 1])
        self.ax.axis("off")
        FigureCanvasAgg(self.fig)
        self.renderer = self.fig.canvas.get_renderer()

    def block(self, text, width, size=BODY_FONT_PT, weight="normal", color="black"):
        """Preserve explicit newlines; split even unspaced Korean/English tokens."""
        font = FontProperties(family=plt.rcParams["font.family"], size=size, weight=weight)
        limit = width - MEASURE_SAFETY_PT
        if limit <= 0:
            raise ValueError("Text column must have positive width")

        def measured(value):
            return self.renderer.get_text_width_height_descent(value, font, False)[0] * POINTS_PER_INCH / self.fig.dpi

        lines = []
        for paragraph in str(text).split("\n"):
            line = ""
            # 한국어 밖에서는 붙임표 뒤에서도 줄을 나눔 ('physics-inform/ed'처럼 낱말 중간에서 끊기지 않게, 2026-10-29)
            pattern = r"\s+|\S+" if output_language() == "ko" else r"\s+|[^\s-]*-+|[^\s-]+"
            for token in re.findall(pattern, paragraph):
                if measured(line + token) <= limit:
                    line += token
                    continue
                if line.strip():
                    lines.append(line.rstrip())
                line = token.lstrip()
                if measured(line) > limit:
                    remaining, line = line, ""
                    for char in remaining:
                        if line and measured(line + char) > limit:
                            lines.append(line)
                            line = ""
                        line += char
            lines.append(line.rstrip())
        wrapped = "\n".join(lines)
        probe = self.ax.text(0, 0, wrapped, fontproperties=font, linespacing=LINE_SPACING, parse_math=False)
        height = probe.get_window_extent(self.renderer).height * POINTS_PER_INCH / self.fig.dpi
        probe.remove()
        return TextBlock(wrapped, height, size, weight, color)

    def text(self, block, x, top, height=None):
        return self.ax.text(x, top + (block.height if height is None else height) / 2,
                            block.text, ha="left", va="center", fontsize=block.size,
                            fontweight=block.weight, color=block.color, linespacing=LINE_SPACING,
                            parse_math=False)

    def cell(self, x, top, width, height, blocks, fill="white", edge="black"):
        self.ax.add_patch(FancyBboxPatch((x, top), width, height, boxstyle="round,pad=0,rounding_size=2",
                                       fc=fill, ec=edge, lw=1))
        content_height = sum(b.height for b in blocks) + TEXT_GAP_PT * max(0, len(blocks) - 1)
        y = top + (height - content_height) / 2
        for block in blocks:
            self.text(block, x + CELL_PAD_PT, y)
            y += block.height + TEXT_GAP_PT

    def title(self, text):
        block = self.block(text, self.inner_width, TITLE_FONT_PT)
        self.text(block, self.left, OUTER_PAD_PT)
        return OUTER_PAD_PT + block.height + ROW_GAP_PT

    def arrow(self, x0, y0, x1, y1, color="#002060"):
        self.ax.annotate("", (x1, y1), (x0, y0), arrowprops=dict(arrowstyle="-|>", color=color, lw=1.2))

    def legend(self, entries, top):
        """Each entry gets measured space; overflow continues on another row."""
        x, y, row_height = self.left, top, 0
        swatch, gap = BODY_FONT_PT, TEXT_GAP_PT
        for label, color in entries:
            block = self.block(label, self.inner_width - swatch - gap)
            probe = self.text(block, 0, 0)
            text_width = probe.get_window_extent(self.renderer).width * POINTS_PER_INCH / self.fig.dpi
            probe.remove()
            width = swatch + gap + text_width + ROW_GAP_PT
            if x > self.left and x + width > self.width - OUTER_PAD_PT:
                x, y, row_height = self.left, y + row_height + gap, 0
            self.ax.add_patch(plt.Rectangle((x, y + (block.height - swatch) / 2), swatch, swatch, fc=color))
            self.text(block, x + swatch + gap, y)
            x += width
            row_height = max(row_height, block.height)
        return y + row_height

    def save(self, out, bottom):
        height = bottom + OUTER_PAD_PT
        self.fig.set_size_inches(self.width / POINTS_PER_INCH, height / POINTS_PER_INCH)
        self.ax.set_xlim(0, self.width)
        self.ax.set_ylim(height, 0)
        self.fig.savefig(out, dpi=REPORT_DPI, bbox_inches="tight", pad_inches=SAVE_PAD_IN)
        plt.close(self.fig)
