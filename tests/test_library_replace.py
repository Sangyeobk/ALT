import json
import sys
from pathlib import Path

import pytest
from pypdf import PdfWriter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "alt"))
from library import Library


def test_replacing_pdf_preserves_old_version_and_drops_old_page_notes(tmp_path):
    ref = {"doi": "10.1/example", "title": "Example paper", "year": 2026, "authors": ["Kim"]}
    old, new = tmp_path / "old.pdf", tmp_path / "new.pdf"
    for path, width in [(old, 100), (new, 200)]:
        writer = PdfWriter()
        writer.add_blank_page(width=width, height=200)
        writer.write(path)
    lib = Library(tmp_path / "library")
    lib.add_pdf(ref, old, "old")
    lib.add_note(ref, old, {"method": {"page": 1}}, "old")
    backup = lib.replace_pdf(ref, new, "publisher")
    lib.save()
    assert backup.read_bytes() == old.read_bytes()
    assert lib.pdf_of(ref).read_bytes() == new.read_bytes()
    assert lib.note_of(ref, new) is None
    saved = Library(lib.root)
    assert saved.pdf_of(ref).read_bytes() == new.read_bytes()
    assert json.loads(backup.with_suffix(".json").read_text(encoding="utf-8"))["note_from"] == "old"
    lib.replace_pdf(ref, old, "return to old")
    lib.add_note(ref, old, {"method": {"page": 99}}, "new annotation")
    lib.replace_pdf(ref, new, "publisher again")
    metadata = [json.loads(p.read_text(encoding="utf-8")) for p in (lib.root / "_versions").rglob("*.json")]
    assert any(item.get("note_from") == "new annotation" for item in metadata)


def test_invalid_replacement_does_not_change_registered_pdf(tmp_path):
    ref = {"doi": "10.1/example"}
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=200)
    old = tmp_path / "old.pdf"
    writer.write(old)
    lib = Library(tmp_path / "library")
    lib.add_pdf(ref, old, "old")
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    with pytest.raises(ValueError):
        lib.replace_pdf(ref, bad, "bad")
    assert lib.pdf_of(ref).read_bytes() == old.read_bytes()
