from fetch_open_access import download_todo, match_reference

REFS = {
    "Tan2025": {"doi": "https://doi.org/10.1016/j.marstruc.2024.103775",
                "title": "Data-driven modelling of fully nonlinear wave loads on offshore wind monopiles"},
    "Zou2025": {"doi": "https://doi.org/10.3390/jmse13071211", "title": "A neural network for wave forces on floating platforms"},
}


def test_match_by_doi_on_first_page():
    text = "Marine Structures 99 (2025) 103775\nhttps://doi.org/10.1016/j.marstruc.2024.103775.\nAbstract ..."
    assert match_reference(text, REFS) == "Tan2025"


def test_match_by_title_when_no_doi():
    text = "Journal of Marine Science\nA Neural Network for Wave\nForces on Floating Platforms\nKim, Lee"
    assert match_reference(text, REFS) == "Zou2025"


def test_no_match_when_ambiguous_or_unknown():
    both = "doi 10.1016/j.marstruc.2024.103775 and 10.3390/jmse13071211"
    assert match_reference(both, REFS) is None
    assert match_reference("some other paper 10.1000/xyz", REFS) is None


def test_download_todo_gives_link_for_each_paper_to_fetch():
    references = {
        "A2025": {"pdf_status": "manual_needed", "oa_landing_url": "https://repo.example/a", "doi": "https://doi.org/10.1/a", "venue": "J", "title": "A"},
        "B2025": {"pdf_status": "not_oa", "oa_landing_url": None, "doi": "https://doi.org/10.1/b", "venue": "J", "title": "B"},
        "C2025": {"pdf_status": "downloaded", "doi": "https://doi.org/10.1/c", "title": "C"},
    }
    rows = download_todo(references)
    assert len(rows) == 2
    assert "https://repo.example/a" in rows[0] and "https://doi.org/10.1/b" in rows[1]


def _run_with_pdf(run, key, ref, content=b"%PDF-1.4 x"):
    import json
    (run / "papers").mkdir(parents=True)
    (run / "papers" / f"{key}.pdf").write_bytes(content)
    (run / "references.json").write_text(json.dumps({key: {**ref, "pdf_file": f"papers/{key}.pdf"}}), encoding="utf-8")


def test_library_name_has_author_year_and_doi():
    """레퍼런스 폴더 파일 이름은 저자로 알아보게 '저자성연도_DOI' (사용자 지시 2026-10-22), DOI가 없으면 제목 앞부분."""
    from library import library_name
    ref = {**REFS["Tan2025"], "authors": ["Weikai Tan", "Pu Ren"], "year": 2025}
    assert library_name(ref) == "Tan2025_10.1016_j.marstruc.2024.103775.pdf"
    assert library_name({"doi": None, "title": "Graph networks: mooring", "authors": ["Ji-ho Kim"], "year": 2026}) == "Kim2026_graphnetworksmooring.pdf"


def test_library_registers_runs_and_new_run_copies_without_download(tmp_path):
    """한 곳에 모아 두고(처음 등록된 판이 기준), 새 조사는 거기서 복사 — 다시 받지 않음 (사용자 결정 2026-10-22). DOI 없으면 제목으로 같은 논문."""
    from fetch_open_access import reuse_library_pdfs
    from library import Library, sync_run
    lib = Library(tmp_path / "references")
    _run_with_pdf(tmp_path / "a", "Tan2025", {**REFS["Tan2025"], "authors": ["Weikai Tan"], "year": 2025}, b"%PDF first")
    _run_with_pdf(tmp_path / "b", "Tan2025", {**REFS["Tan2025"], "authors": ["Weikai Tan"], "year": 2025}, b"%PDF second")
    _run_with_pdf(tmp_path / "c", "Kim2026", {"doi": None, "title": "Graph networks for mooring line tension forecasting", "year": 2026})
    assert [sync_run(tmp_path / r, lib)[0] for r in "abc"] == [1, 0, 1]
    papers = tmp_path / "child" / "papers"
    papers.mkdir(parents=True)
    refs = {"Tan2025b": dict(REFS["Tan2025"]), "Zou2025": dict(REFS["Zou2025"]),
            "Kim2026a": {"doi": "", "title": "Graph Networks for Mooring-Line Tension Forecasting"}}
    assert sorted(reuse_library_pdfs(refs, papers, lib)) == ["Kim2026a", "Tan2025b"]
    assert (papers / "Tan2025b.pdf").read_bytes() == b"%PDF first"
    assert refs["Tan2025b"]["pdf_status"] == "manual" and refs["Tan2025b"]["manual_source"].startswith("레퍼런스 폴더")
    assert "pdf_status" not in refs["Zou2025"] and reuse_library_pdfs(refs, papers, lib) == []  # 이미 있으면 다시 복사하지 않음


def test_library_notes_only_for_identical_pdf(tmp_path):
    """맥락 정리도 한 곳에서 — 쪽 번호가 PDF 기준이라 PDF가 똑같을 때만 등록·사용 (사용자 결정 2026-10-22)."""
    import json
    from extract_fulltext import reuse_library_notes
    from library import Library, sync_run
    lib = Library(tmp_path / "references")
    other = tmp_path / "other"
    _run_with_pdf(other, "Tan2025", REFS["Tan2025"], b"%PDF same")
    (other / "fulltext_notes_1.json").write_text(json.dumps({"notes": {"Tan2025": {"depth": "맥락"}}}), encoding="utf-8")
    assert sync_run(other, lib) == (1, 1)
    child = tmp_path / "child"
    (child / "papers").mkdir(parents=True)
    (child / "papers" / "Tan2025b.pdf").write_bytes(b"%PDF same")
    (child / "papers" / "Tan2025c.pdf").write_bytes(b"%PDF other version")  # 같은 논문, 다른 판
    mine = {"Tan2025b": {**REFS["Tan2025"], "pdf_file": "papers/Tan2025b.pdf"},
            "Tan2025c": {**REFS["Tan2025"], "pdf_file": "papers/Tan2025c.pdf"}}
    assert reuse_library_notes(child, mine, ["Tan2025b", "Tan2025c"], lib) == {"Tan2025b": ({"depth": "맥락"}, "other/Tan2025")}


def test_edge_gets_links_directly_without_shell(monkeypatch, tmp_path):
    import fetch_open_access as foa
    edge = tmp_path / "msedge.exe"
    edge.write_text("", encoding="utf-8")
    calls = []
    monkeypatch.setattr(foa.shutil, "which", lambda name: str(edge))
    monkeypatch.setattr(foa.subprocess, "run", lambda args, check: calls.append(args))
    foa.open_in_edge(["https://a.org/x?p=1&q=2"])
    assert calls == [[str(edge), "--new-window", "https://a.org/x?p=1&q=2"]]  # cmd 안 거침 — '&'가 잘리지 않음
