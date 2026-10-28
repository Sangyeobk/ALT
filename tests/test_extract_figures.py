import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "alt"))
from extract_figures import captions, figure_box


def test_captions_keep_real_captions_only():
    page = "\n".join([
        "Fig. 2. Comparison between the experimental data and numerical results.",
        "Fig. 1 illustrates the computational domain and mesh used in the model.",
        "as shown in Fig. 3, the force increases",
        "Figure 4: Workflow of the surrogate model",
        "Table 1",
        "TABLE 2. Sea states used for training",
    ])
    assert captions(page) == [
        "Fig. 2. Comparison between the experimental data and numerical results.",
        "Figure 4: Workflow of the surrogate model",
        "Table 1",
        "TABLE 2. Sea states used for training",
    ]


def test_figure_picks_join_notes_and_attach_to_synthesis_by_subtopic(tmp_path):
    """그림 고르기는 맥락 정리 뒤 따로 (사용자 결정 2026-10-16): 정리에 합쳐지고, 요약 figures에 세부 주제로 붙되 두 번 넣지 않음."""
    import json
    from extract_figures import attach_figures
    from prepare_synthesis import load_fulltext_notes

    def put(name, data):
        (tmp_path / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    put("fulltext_notes_1.json", {"notes": {"A": {"depth": "맥락", "method": {"text": "m", "page": 2}},
                                            "Old": {"figures": [{"fig": "Fig. 1", "page": 3, "file": "x.jpg"}]}}})
    pick = {"fig": "Fig. 4", "page": 5, "image": 1, "caption": "결과 비교", "file": "figures/src/A/p5_1.jpg"}
    put("figure_picks_1.json", {"notes": {"A": {"figures": [pick]}, "Gone": {"figures": [pick]}}})
    notes = load_fulltext_notes(tmp_path)
    assert notes["A"]["figures"] == [pick] and notes["A"]["method"]["page"] == 2 and "Gone" not in notes
    assert notes["Old"]["figures"][0]["fig"] == "Fig. 1"  # 예전 깊은 정리 그대로
    put("synthesis.json", {"subtopics": [{"id": "T1", "papers": ["A"]}], "figures": []})
    assert attach_figures(tmp_path, "초록") == 1 and attach_figures(tmp_path, "초록") == 0
    figs = json.loads((tmp_path / "synthesis.json").read_text(encoding="utf-8"))["figures"]
    assert figs == [{"key": "A", "fig": "Fig. 4", "page": 5, "file": pick["file"], "caption": "결과 비교", "subtopic": "T1"}]


CROP_RULES = {"figure_crop_first_gap": 90, "figure_crop_gap": 45, "figure_crop_line_gap": 14,
              "figure_crop_page_band": 0.1, "figure_crop_margin": 8}
PAGE = (600, 800)


def test_caption_box_matches_full_figure_name_for_abbreviated_pick():
    from extract_figures import caption_box

    class TextPage:
        text = "Body mentions Figure 3.\nFigure 3: Actual caption"

        def search(self, label, match_case=False):
            import re
            found = iter((m.start(), len(label)) for m in re.finditer(re.escape(label), self.text, re.I))

            class Search:
                def get_next(self):
                    return next(found, None)
            return Search()

        def get_text_range(self, index, count):
            return self.text[index:index + count]

        def get_charbox(self, index):
            return (index, 300, index + 5, 306)

    assert caption_box(TextPage(), "Fig. 3") == (24, 300, 29, 306)
    TextPage.text = "Fig. 30: Other\nFigure 3: Correct"
    assert caption_box(TextPage(), "Figure 3") == (15, 300, 20, 306)


def test_figure_box_takes_graphics_above_figure_caption_and_skips_header_rule():
    caption = (100, 300, 105, 306)
    graphics = [(100, 330, 500, 450), (100, 460, 500, 560),  # 그림 두 줄 (간격 10)
                (40, 760, 560, 761),                         # 머리글 줄 (위 띠)
                (100, 640, 500, 700)]                        # 멀리 떨어진 다른 그림 (간격 80 > 45)
    left, bottom, right, top = figure_box(caption, graphics, [], False, PAGE, CROP_RULES)
    assert top == 560 + 8 and bottom == 300 - 8 and left == 92 and right == 508


def test_figure_box_table_runs_down_through_text_to_last_rule():
    caption = (50, 600, 55, 606)
    rules_ = [(50, 590, 550, 591), (50, 560, 550, 561), (50, 470, 550, 471)]  # 위·머리 아래·맨 아래 줄
    texts = [(50, 575 - 12 * i, 500, 585 - 12 * i) for i in range(9)] + [(50, 300, 550, 310)]  # 표 안 글 + 멀리 본문
    left, bottom, right, top = figure_box(caption, rules_, texts, True, PAGE, CROP_RULES)
    assert bottom == 470 - 8 and top == 606 + 8


def test_figure_box_none_when_nothing_found():
    assert figure_box((100, 300, 105, 306), [], [], False, PAGE, CROP_RULES) is None
    assert figure_box((100, 300, 105, 306), [], [(100, 280, 500, 290)], True, PAGE, CROP_RULES) is None
