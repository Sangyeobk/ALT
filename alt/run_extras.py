"""이 조사 맞춤 결과물 만들기 (⑨ 끝): `<run>/project/extras.yaml` 목록의 스크립트를 차례로 실행한다.

    python alt/run_extras.py outputs/<run>/ [--variant 초록]

- 사용자 결정 2026-10-16: 기본 결과물(00–06)은 명령 한 줄로, 그 뒤 피드백으로 이 조사에만 새 형태 결과물을 더한다.
  기본 코드(alt/)는 고치지 않고, 스크립트는 결과 폴더 `project/extras/`에 둔다.
- extras.yaml 예:
    - name: 방법 비교 한 장 요약
      script: method_onepager.py          # project/extras/ 안 — 인자: <run> --variant <판>
      outputs: [07_방법비교.xlsx]          # 판 이름이 붙음 → 07_방법비교_초록.xlsx
      cite_check: true                    # 인용 검사 대상 (기본 true)
- 스크립트는 synthesis_<판>.json·references.json·scored.json을 읽기만 하고 결과 폴더에만 쓴다. 문헌을 새로 지어내지 않는다.
- 만든 뒤 ⑩ 인용 검사(check_citations.py)가 맞춤 결과물도 함께 본다.
"""

import argparse
import subprocess
import sys
from pathlib import Path

from common import PROJECT_SUBDIR, add_variant, extra_outputs, variant_name


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", type=Path)
    add_variant(parser)
    args = parser.parse_args()

    items = extra_outputs(args.run_dir)
    if not items:
        print("[extras] 이 조사 맞춤 결과물 없음 (project/extras.yaml)")
        return
    failed = []
    for item in items:
        script = args.run_dir / PROJECT_SUBDIR / "extras" / item["script"]
        result = subprocess.run([sys.executable, str(script), str(args.run_dir), "--variant", args.variant])
        missing = [n for n in (variant_name(o, args.variant) for o in item["outputs"]) if not (args.run_dir / n).is_file()]
        if result.returncode or missing:
            failed.append(item["name"])
            print(f"[extras] 실패: {item['name']} (종료 {result.returncode}, 없는 파일 {missing})")
        else:
            print(f"[extras] {item['name']}: {', '.join(variant_name(o, args.variant) for o in item['outputs'])}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
