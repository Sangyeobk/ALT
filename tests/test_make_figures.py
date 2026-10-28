import pytest

from make_figures import cell_offsets, role_summary, split_methods, stage_summary, tree_summary


def test_cell_offsets_stay_inside_cell_without_overlap():
    for n in (1, 10, 50):
        offsets = cell_offsets(n)
        assert len(offsets) == n
        assert len(set(offsets)) == n
        assert all(abs(dx) <= 0.4 and abs(dy) <= 0.4 for dx, dy in offsets)


LABELS = ["수치해석", "모형시험", "현장계측"]


def synthesis(**overrides):
    s = {
        "scope": {"flow": ["환경", "하중", "평가"], "stage_methods": ["스펙트럼", "Morison", "Miner"]},
        "subtopics": [
            {"id": "T1", "name": "하중 예측", "role": "핵심", "stage": "하중", "papers": ["A", "B"],
             "representatives": [{"key": "A"}]},
            {"id": "T2", "name": "피로", "role": "확장", "stage": "평가", "papers": ["C"], "representatives": [{"key": "C"}]},
        ],
        "method_comparison": [{"key": "A", "data_source": ["수치해석", "현장계측"]}, {"key": "B", "data_source": []},
                              {"key": "C", "data_source": ["모형시험"]}],
        "approach_roles": [{"role": "해석 대리", "target": "하중", "limit": "비용", "check": "오차", "subtopic_ids": ["T1", "T2"]}],
    }
    s.update(overrides)
    return s


def test_stage_summary_counts_papers_and_sources_by_key():
    stages = stage_summary(synthesis(), LABELS)
    assert [st["papers"] for st in stages] == [0, 2, 1]
    assert stages[1]["subtopics"] == [("하중 예측", 2, "핵심")]
    assert stages[1]["sources"] == {"수치해석": 1, "모형시험": 0, "현장계측": 1, "미기재": 1}  # 중복 포함, 빈 목록 = 미기재


def test_role_summary_unions_subtopics():
    [row] = role_summary(synthesis(), LABELS)
    assert row["papers"] == 3 and row["reps"] == ["A", "C"]
    assert row["sources"]["모형시험"] == 1


def test_unknown_stage_or_source_fails_loudly():
    bad_stage = synthesis()
    bad_stage["subtopics"][0]["stage"] = "응답"
    with pytest.raises(ValueError):
        stage_summary(bad_stage, LABELS)
    with pytest.raises(ValueError):
        stage_summary(synthesis(method_comparison=[{"key": "A", "data_source": ["CFD"]}]), LABELS)


def test_split_methods_keeps_commas_inside_parentheses():
    assert split_methods("LSTM·순방향 신경망, 최적 실험계획(OED, 설계), GPR") == ["LSTM·순방향 신경망", "최적 실험계획(OED, 설계)", "GPR"]
    assert split_methods("") == []


def test_tree_summary_core_first_with_counts_and_limits():
    s = synthesis(role_names={"핵심": "하중", "확장": "활용"})
    s["subtopics"][1].update(approaches="A, B, C, D, E", representatives=[{"key": k} for k in "CDEF"])
    s["subtopics"] = s["subtopics"][::-1]  # 확장이 먼저 나와도 핵심이 위
    groups = tree_summary(s)
    assert [(g["role"], g["label"]) for g in groups] == [("핵심", "하중"), ("확장", "활용")]
    assert groups[0]["subtopics"][0]["papers"] == 2
    extension = groups[1]["subtopics"][0]
    assert len(extension["methods"]) == 4 and extension["reps"] == ["C", "D", "E"]


def test_slide_figures_are_written(tmp_path):
    """발표용 단순화 그림 3종 (사용자 피드백 2026-10-21) — 요약 함수 결과로 파일이 만들어짐."""
    from make_figures import slide_flow, slide_limits, slide_tree
    slide_flow([{"name": "하중", "method": "BEM", "papers": 3, "subtopics": [("가", 3, "핵심")]},
                {"name": "평가", "method": "Miner", "papers": 0, "subtopics": []}], tmp_path / "f.png")
    slide_limits([{"limit": "반복 계산 부담", "role": "대리모델", "papers": 4}], tmp_path / "l.png")
    slide_tree([{"role": "핵심", "label": "하중", "subtopics": [{"name": "순방향", "papers": 2}, {"name": "역추정", "papers": 1}]}],
               "파랑하중 데이터 기반", tmp_path / "t.png")
    assert all((tmp_path / n).stat().st_size > 0 for n in ("f.png", "l.png", "t.png"))


@pytest.mark.parametrize("kind", ["limits", "flow", "tree", "prisma"])
def test_report_diagram_text_and_borders_fit_with_long_labels(tmp_path, monkeypatch, kind):
    """Check actual rendered bounds, including unspaced labels and outer borders."""
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.patches import FancyBboxPatch
    from make_figures import limit_response, theory_flow, tech_tree, prisma

    captured = []
    monkeypatch.setattr(Figure, "savefig", lambda fig, *a, **kw: captured.append(fig))
    phrase = "파랑하중·구조응답·피로누적·모델매개변수의동시예측"
    sources = dict(zip(LABELS + ["미기재"], [2, 1, 0, 0]))
    with plt.rc_context({"font.family": "Malgun Gothic"}):
        if kind == "limits":
            limit_response([dict(limit=phrase, role=phrase, target=phrase, check=phrase,
                                 papers=3, sources=sources, reps=["LongUnbrokenReferenceIdentifier2026"])],
                           LABELS, tmp_path / "limits.png", phrase)
        elif kind == "flow":
            theory_flow([dict(name=phrase, method=phrase, papers=3, sources=sources,
                              subtopics=[(phrase, 3, "핵심")] * 4)] * 5,
                        LABELS, tmp_path / "flow.png", phrase)
        elif kind == "tree":
            tech_tree([dict(role="핵심", label=phrase,
                            subtopics=[dict(name=phrase, papers=3, reps=["LongUnbrokenReferenceIdentifier2026"],
                                            methods=[phrase, "LongUnbrokenMethodIdentifier"]) for _ in range(6)])],
                      phrase * 3, tmp_path / "tree.png")
        else:
            counts = dict(reviews_listed=10, reviews_not_listed=20, institutions_listed=5,
                          institutions_not_listed=5, cocited_listed=2, cocited_not_listed=3,
                          excluded_no_abstract=20, screened=500, excluded_retracted=1,
                          selected=30, below_threshold=20, over_limit=40, identified=600,
                          duplicates_removed=100, below_relevance=300)
            prisma(dict(prisma=counts, min_relevance=4, min_total_score=0.6, max_selected=30),
                   tmp_path / "prisma.png")
        fig = captured[0]
        FigureCanvasAgg(fig)
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        for ax in fig.axes:
            frame = ax.get_window_extent(renderer)
            boxes = [p.get_window_extent(renderer) for p in ax.patches if isinstance(p, FancyBboxPatch)]
            for box in boxes:
                assert frame.x0 <= box.x0 and box.x1 <= frame.x1, "outer box border clipped"
            for text in ax.texts:
                bounds = text.get_window_extent(renderer)
                assert fig.bbox.contains(bounds.x0, bounds.y0) and fig.bbox.contains(bounds.x1, bounds.y1), text.get_text()
                anchor = text.get_transform().transform(text.get_position())
                for box in boxes:
                    if box.contains(*anchor):
                        assert (bounds.x0 >= box.x0 - 1 and bounds.x1 <= box.x1 + 1
                                and bounds.y0 >= box.y0 - 1 and bounds.y1 <= box.y1 + 1), text.get_text()
                        assert text.get_ha() == "left" and text.get_va() == "center"
