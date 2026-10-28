import sys
from pathlib import Path
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "alt"))
from package_plugin import package_plugin


def test_bundle_uses_explicit_files_and_excludes_local_results(tmp_path):
    target = tmp_path / "plugin.zip"
    names = package_plugin(target)
    with ZipFile(target) as bundle:
        assert set(bundle.namelist()) == set(names)
        assert "skills/run/SKILL.md" in bundle.namelist()
        assert "alt/config.yaml" in bundle.namelist()
        assert "alt/plugin_files.yaml" in bundle.namelist()
        assert not any(name.startswith(("outputs/", "templates/", "docs/", "inputs/")) for name in bundle.namelist())
        assert not any(".pytest_cache" in name or "__pycache__" in name or name.endswith("CLAUDE.md") for name in bundle.namelist())
