"""공개 가능한 코드·지침만 배포 ZIP으로 묶는다 (원자료·결과·개인 문서·양식 제외).

    python alt/package_plugin.py --out outputs/alt-plugin.zip
"""
import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
import yaml


def package_plugin(destination: Path) -> list[str]:
    root = Path(__file__).resolve().parent.parent
    names = yaml.safe_load((root / "alt/plugin_files.yaml").read_text(encoding="utf-8"))["files"]
    for name in names:
        path = root / name
        if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
            raise ValueError(f"배포 목록의 파일이 없거나 범위 밖임: {name}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(destination, "w", ZIP_DEFLATED) as bundle:
        for name in sorted(names):
            bundle.write(root / name, name)
    return sorted(names)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    names = package_plugin(args.out)
    print(f"[plugin] {len(names)} files → {args.out}")


if __name__ == "__main__":
    main()
