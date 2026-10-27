"""피드백 부분 수정: 요약(synthesis_<판>.json)에서 고칠 부분만 뽑아 alt-writer에게 주고, 고친 결과만 다시 합친다.

    python alt/revise_synthesis.py outputs/<run>/ --extract "subtopics#T3" conclusion --feedback "..." [--variant 초록]
        → revision_input_<판>.json  (+ feedback_log.jsonl 기록)
    (alt-writer: revision_input_<판>.json → revision_output_<판>.json)
    python alt/revise_synthesis.py outputs/<run>/ --merge [--variant 초록]
        → 검사를 모두 통과하면 synthesis_<판>.json에 대상만 바꿔 넣음 (백업 먼저)

- 대상: 최상위 키(conclusion) 또는 항목 하나(subtopics#T3 — 목록은 항목의 id·key로, 사전은 키로 찾음). 여러 개를 함께 줄 수 있다.
- 합치기는 전부 아니면 전무: 작성자가 affected(함께 바뀌어야 할 다른 부분)를 적었거나, 구조가 바뀌었거나,
  목록에 없는 인용 키가 새로 생기면 아무것도 바꾸지 않는다. affected가 두 번째에도 나오면 사용자에게 선택지를 묻는다 (SKILL '피드백').
- 바뀐 부분에 인용이 붙은 글이 있으면 '교차 검증 필요'를 알린다 (cross_verify.py --outputs).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import uuid
from datetime import datetime
from pathlib import Path

from check_citations import KEY_PATTERN
from common import add_variant, load_config, load_user_style, read_json, variant_name, write_json

SHAPE = load_config()["revision"]
RULES = [
    "출력의 request_id에는 입력의 request_id를 그대로 쓴다 (다른 요청의 결과가 섞이지 않게).",
    "targets에 있는 대상만 고친다. 고친 값은 지금 값과 같은 구조(항목 이름·자료형)를 유지한다.",
    "이 수정 때문에 다른 부분(outline 참고)도 바뀌어야 하면 직접 고치지 말고 affected에 대상과 이유를 적는다. 없으면 빈 목록 []을 반드시 쓴다.",
    "인용은 citable에 있는 키만 쓴다. 주장·수치·해석을 바꿀 때는 papers의 논문 기록을 근거로 확인하고, 검토 수준을 넘는 단정은 하지 않는다.",
    "user_style이 있으면 기본 지침보다 우선한다 (인용 규칙·지어내기 금지·검토 수준·분모 표시는 바꾸지 않음).",
]
OUTPUT_FORMAT = {"request_id": "<입력의 request_id 그대로>",
                 "changes": {"<대상>": "<고친 값 — 지금 값과 같은 구조>"},
                 "affected": [{"target": "<다른 대상, 예: conclusion 또는 count_claims>", "why": "<이유>"}],
                 "summary": "<무엇을 왜 바꿨는지 한두 줄>"}


def split_target(target: str) -> tuple[str, str | None]:
    top, _, item = target.partition("#")
    return top, item or None


def _item_index(items: list, item: str) -> int:
    for i, entry in enumerate(items):
        if isinstance(entry, dict) and item in (entry.get(f) for f in SHAPE["identity_fields"]):
            return i
    raise KeyError(item)


def get_part(synthesis: dict, target: str):
    top, item = split_target(target)
    if top not in synthesis:
        raise SystemExit(f"[revise] 요약에 없는 대상: {target}")
    value = synthesis[top]
    if item is None:
        return value
    try:
        return value[_item_index(value, item)] if isinstance(value, list) else value[item]
    except (KeyError, TypeError):
        raise SystemExit(f"[revise] 요약에 없는 항목: {target}") from None


def set_part(synthesis: dict, target: str, new) -> None:
    top, item = split_target(target)
    if item is None:
        synthesis[top] = new
    elif isinstance(synthesis[top], list):
        synthesis[top][_item_index(synthesis[top], item)] = new
    else:
        synthesis[top][item] = new


def cited_in(value, known: set[str] | None = None) -> set[str]:
    """값 안에 나온 인용 키처럼 생긴 말 (known을 주면 그중 목록에 있는 것만)."""
    found = set(KEY_PATTERN.findall(json.dumps(value, ensure_ascii=False)))
    return found & known if known is not None else found


def outline(synthesis: dict, width: int = 50) -> dict:
    """요약 전체의 개요 — affected 판단용 (전체 내용보다 훨씬 작게: 키, 항목 id, 첫 줄)."""
    def head(entry) -> str:
        text = next((v for v in entry.values() if isinstance(v, str)), "") if isinstance(entry, dict) else str(entry)
        return text[:width]
    view = {}
    for key, value in synthesis.items():
        if isinstance(value, list):
            view[key] = [(f"{e.get('id') or e.get('key')}: " if isinstance(e, dict) and (e.get("id") or e.get("key")) else "")
                         + head(e) for e in value]
        elif isinstance(value, dict):
            view[key] = list(value)
        else:
            view[key] = str(value)[:width]
    return view


def _counterpart(old: list[dict], entry: dict, index: int) -> dict | None:
    """고친 항목의 고치기 전 짝: 식별 칸(config identity_fields)이 같은 항목, 식별 칸이 없으면 같은 순서의 항목. 새 항목이면 None."""
    for field in SHAPE["identity_fields"]:
        if entry.get(field) is not None and any(field in o for o in old):
            return next((o for o in old if o.get(field) == entry[field]), None)
    return old[index] if index < len(old) else None


def _against(refs: list, new, path: str, free: bool) -> list[str]:
    """같은 칸의 기존 값 여러 개 중 자료형이 같은 것과 비교 — 기존에 섞여 있던 자료형은 모두 허용 (예: 쪽 7 / '10–11')."""
    nullable = any(r is None for r in refs)  # 기존에도 비어 있던(또는 없던) 칸 → 계속 비어 있어도 됨
    refs = [r for r in refs if r is not None]
    if new is None:
        return [] if nullable or not refs else [f"{path}: 값이 비었음 (기존 {type(refs[0]).__name__})"]
    if not refs:
        return []
    same = [r for r in refs if type(r) is type(new)]
    if not same:
        kinds = "/".join(sorted({type(r).__name__ for r in refs}))
        return [f"{path}: 자료형이 바뀜 ({kinds} → {type(new).__name__})"]
    if isinstance(new, list):  # 여러 기존 목록의 원소를 모아 기준으로
        return shape_errors([x for r in same for x in r], new, path, free)
    if isinstance(new, dict) and free:  # 여러 기존 사전의 값을 모아 기준으로
        return [e for k, v in new.items() for e in _against([x for r in same for x in r.values()], v, f"{path}.{k}", True)]
    if isinstance(new, dict):  # 키 모음이 같은 기존 사전이 있으면 그것과
        return shape_errors(next((r for r in same if r.keys() == new.keys()), same[0]), new, path, free)
    return []


def shape_errors(old, new, path: str, free: bool = False) -> list[str]:
    """같은 구조인지 끝까지(재귀) 검사: 자료형, 빈 값(None)으로 지우기 금지, 사전은 같은 키(키가 데이터인 사전은 값만),
    목록은 기존 원소의 자료형 — 사전 목록은 모든 기존 항목에 있던 키는 필수, 기존에 없던 키는 금지(config optional_fields 빼고).
    기존 값이 비어(None) 있으면 빈 칸을 채우는 수정이라 기준이 없다 → config optional_fields에 예시가 있는 칸만 그 자료형으로 검사.
    ponytail: 예시 없는 빈 칸(예: 원소가 전부 null인 목록)은 아무 자료형이나 허용 — 실제 요약 파일에는 없음, 생기면 예시를 config에 추가"""
    if old is None:
        return []
    if new is None:
        return [f"{path}: 값이 비었음 (기존 {type(old).__name__})"]
    if type(old) is not type(new):
        return [f"{path}: 자료형이 바뀜 ({type(old).__name__} → {type(new).__name__})"]
    if isinstance(old, dict):
        if free:  # 키가 데이터(논문 키·약어·id) → 값 자료형만
            return [e for k, v in new.items() for e in _against(list(old.values()), v, f"{path}.{k}", True)]
        errors = [f"{path}: 빠진 항목 {sorted(old.keys() - new.keys())}"] if old.keys() - new.keys() else []
        errors += [f"{path}: 새 항목 {sorted(new.keys() - old.keys())}"] if new.keys() - old.keys() else []
        return errors + [e for k in old.keys() & new.keys()
                         for e in shape_errors(old[k], new[k], f"{path}.{k}", free or k in SHAPE["free_key_fields"])]
    if not isinstance(old, list) or not old:
        return []
    if all(isinstance(e, dict) for e in old):
        optional = SHAPE["optional_fields"]
        examples = {**SHAPE["nullable_examples"], **optional}
        required = set.intersection(*(set(e) for e in old)) - set(optional)
        allowed = set.union(*(set(e) for e in old)) | set(optional)
        refs = {k: [e.get(k) for e in old] + ([examples[k]] if k in examples else []) for k in allowed}
        errors = []
        for i, entry in enumerate(new):
            where = f"{path}[{i}]"
            if not isinstance(entry, dict):
                errors.append(f"{where}: 항목이 사전이 아님")
                continue
            if required - entry.keys():
                errors.append(f"{where}: 빠진 항목 {sorted(required - entry.keys())}")
            if entry.keys() - allowed:
                errors.append(f"{where}: 새 항목 {sorted(entry.keys() - allowed)}")
            before = _counterpart(old, entry, i)  # 같은 항목에 값이 있던 칸은 비우지 못함 (다른 항목이 비어 있어도)
            cleared = sorted(k for k, v in (before or {}).items() if v is not None and k in entry and entry[k] is None)
            errors += [f"{where}.{k}: 값이 비었음 (이 항목의 기존 값 있음)" for k in cleared]
            errors += [e for k in (entry.keys() & allowed) - set(cleared)
                       for e in _against(refs[k], entry[k], f"{where}.{k}", free or k in SHAPE["free_key_fields"])]
        return errors
    return [err for i, e in enumerate(new) for err in _against(old, e, f"{path}[{i}]", free)]  # 원소마다 끝까지


def log_event(run_dir: Path, **event) -> None:
    with open(Path(run_dir) / "feedback_log.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"time": datetime.now().isoformat(timespec="seconds"), **event}, ensure_ascii=False) + "\n")


def attempt_number(run_dir: Path, variant: str, feedback: str) -> int:
    """같은 피드백으로 affected 때문에 거부된 횟수 + 1 (마지막 합치기 이후)."""
    path = Path(run_dir) / "feedback_log.jsonl"
    count = 0
    for line in (path.read_text(encoding="utf-8").splitlines() if path.is_file() else []):
        event = json.loads(line)
        if event.get("variant") != variant or event.get("feedback") != feedback:
            continue
        count = 0 if event["event"] == "merged" else count + (event["event"] == "affected")
    return count + 1


def file_hash(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def extract(run_dir: Path, variant: str, targets: list[str], feedback: str) -> dict:
    synthesis_path = run_dir / variant_name("synthesis.json", variant)
    raw = synthesis_path.read_bytes()  # 내용과 해시를 같은 바이트에서 (사이에 다른 수정이 끼지 않게)
    synthesis = json.loads(raw.decode("utf-8"))
    references = read_json(run_dir / "references.json")
    parts = {t: get_part(synthesis, t) for t in targets}
    cited = cited_in(parts, set(references))
    papers = [p for p in read_json(run_dir / variant_name("synthesis_input.json", variant))["papers"] if p["key"] in cited]
    payload = {
        "request_id": uuid.uuid4().hex[:12], "source_hash": hashlib.sha256(raw).hexdigest(),  # 응답 짝·원본 변경 확인용
        "feedback": feedback, "attempt": attempt_number(run_dir, variant, feedback),
        "targets": parts, "papers": papers,
        "citable": [{"key": k, "title": r.get("title")} for k, r in references.items()],
        "keywords": synthesis.get("keywords"), "terms": synthesis.get("terms"),
        "outline": outline(synthesis), "user_style": load_user_style(run_dir),
        "rules": RULES, "output_file": variant_name("revision_output.json", variant), "output_format": OUTPUT_FORMAT,
    }
    write_json(run_dir / variant_name("revision_input.json", variant), payload)
    log_event(run_dir, event="extract", variant=variant, feedback=feedback, targets=targets)
    return payload


def request_errors(request: dict, output, synthesis_path: Path) -> list[str]:
    """응답이 이 요청의 것인지, 뽑은 뒤 요약이 바뀌지 않았는지, 필수 칸(changes 사전·affected 목록)이 있는지."""
    if not isinstance(output, dict):
        return ["결과 파일이 JSON 객체가 아님"]
    errors = []
    if output.get("request_id") != request["request_id"]:
        errors.append(f"요청 번호 불일치 (요청 {request['request_id']} / 결과 {output.get('request_id')}) — 이전 요청의 결과일 수 있음")
    if file_hash(synthesis_path) != request["source_hash"]:
        errors.append("뽑은 뒤 요약 파일이 바뀜 — 다시 뽑기(--extract)부터")
    if not isinstance(output.get("changes"), dict):
        errors.append("changes(사전)가 없음")
    if not isinstance(output.get("affected"), list):
        errors.append("affected(목록)가 없음 — 함께 바뀔 부분이 없으면 빈 목록 []")
    return errors


def save_atomic(path: Path, payload) -> None:
    """임시 파일에 쓴 뒤 바꿔 끼움 → 쓰는 도중 끊겨도 원본이 반쯤 쓰인 채로 남지 않음."""
    temp = path.with_name(path.name + ".tmp")
    write_json(temp, payload)
    os.replace(temp, path)


def merge(run_dir: Path, variant: str) -> dict:
    """검사 → 통과하면 대상만 바꿔 넣음. 반환: {"merged": bool, "errors": [...], "affected": [...], "cross_verify": bool, ...}"""
    request = read_json(run_dir / variant_name("revision_input.json", variant))
    output = read_json(run_dir / variant_name("revision_output.json", variant))
    synthesis_path = run_dir / variant_name("synthesis.json", variant)
    base = {"feedback": request["feedback"], "variant": variant, "targets": list(request["targets"])}
    lock = synthesis_path.with_name(synthesis_path.name + ".lock")
    try:
        lock.open("x").close()  # 동시에 두 합치기가 같은 요약을 덮어쓰지 않게
    except FileExistsError:
        return {"merged": False, "affected": [], "errors": [f"다른 합치기가 진행 중 ({lock.name} — 진행 중인 것이 없으면 지우고 다시)"]}
    try:
        errors = request_errors(request, output, synthesis_path)
        if errors:
            log_event(run_dir, event="rejected", errors=errors, **base)
            return {"merged": False, "affected": [], "errors": errors}
        changes, affected = output["changes"], output["affected"]
        if affected:
            log_event(run_dir, event="affected", affected=affected, **base)
            return {"merged": False, "affected": affected, "errors": [], "attempt": request["attempt"]}

        synthesis = read_json(synthesis_path)
        known = set(read_json(run_dir / "references.json"))
        if set(changes) != set(request["targets"]):
            errors.append(f"대상 불일치: 요청 {sorted(request['targets'])} / 결과 {sorted(changes)}")
        for target in set(changes) & set(request["targets"]):
            old, new = get_part(synthesis, target), changes[target]
            errors += shape_errors(old, new, target, free=split_target(target)[0] in SHAPE["free_key_fields"])
            new_unknown = (cited_in(new) - known) - (cited_in(old) - known)
            if new_unknown:
                errors.append(f"{target}: 목록에 없는 인용 키 {sorted(new_unknown)}")
        if errors:
            log_event(run_dir, event="rejected", errors=errors, **base)
            return {"merged": False, "affected": [], "errors": errors}

        backup = synthesis_path.with_name(f"{synthesis_path.stem}_before_revise_{datetime.now():%Y%m%d%H%M%S%f}.json")
        with open(backup, "x", encoding="utf-8") as f:  # 같은 이름 백업이 있으면 덮어쓰지 않고 실패
            json.dump(synthesis, f, indent=2, ensure_ascii=False)
        old_parts = {t: get_part(synthesis, t) for t in changes}
        changed = {t: (len(json.dumps(old_parts[t], ensure_ascii=False)), len(json.dumps(v, ensure_ascii=False)))
                   for t, v in changes.items() if old_parts[t] != v}
        # 고치기 전·후 어느 쪽에든 인용이 붙은 글이 있으면 교차 검증 (인용을 지우며 주장을 바꾼 경우 포함)
        needs_verify = any(cited_in(changes[t], known) or cited_in(old_parts[t], known) for t in changed)
        for target, value in changes.items():
            set_part(synthesis, target, value)
        save_atomic(synthesis_path, synthesis)
        log_event(run_dir, event="merged", changed=list(changed), cross_verify=needs_verify, summary=output.get("summary"), **base)
        return {"merged": True, "affected": [], "errors": [], "changed": changed, "cross_verify": needs_verify, "backup": backup.name}
    finally:
        lock.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", type=Path)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--extract", nargs="+", metavar="대상", help="고칠 대상 (예: conclusion \"subtopics#T3\")")
    group.add_argument("--merge", action="store_true", help="revision_output_<판>.json을 검사하고 합친다")
    parser.add_argument("--feedback", help="사용자 피드백 원문 (--extract 때 필수)")
    add_variant(parser)
    args = parser.parse_args()

    if args.extract:
        if not args.feedback:
            parser.error("--extract에는 --feedback이 필요함")
        payload = extract(args.run_dir, args.variant, args.extract, args.feedback)
        size = len(json.dumps(payload, ensure_ascii=False))
        print(f"[revise] 대상 {len(args.extract)}개, 근거 논문 {len(payload['papers'])}편, 입력 약 {size // 1000}k 글자 "
              f"(시도 {payload['attempt']}번째) -> {variant_name('revision_input.json', args.variant)}")
        return
    result = merge(args.run_dir, args.variant)
    if result["affected"]:
        targets = " ".join(f'"{a["target"]}"' for a in result["affected"])
        print(f"[revise] 합치지 않음 — 함께 바뀌어야 할 부분: {targets}")
        print("  → 사용자에게 선택지: ① 대상 더 넓히기 ② 요약 전체 다시 쓰기 ③ 이번 수정 취소" if result["attempt"] >= 2 else
              f"  → 기존 대상에 이 부분을 더해 다시 뽑기: --extract <기존 대상> {targets} --feedback \"<같은 피드백>\"")
        raise SystemExit(2)
    if result["errors"]:
        print("[revise] 합치지 않음 — 검사 실패:\n  " + "\n  ".join(result["errors"]))
        raise SystemExit(1)
    for target, (before, after) in result["changed"].items():
        print(f"[revise] {target}: {before:,} → {after:,} 글자")
    print(f"[revise] 합침 (백업 {result['backup']}). 다음: ⑨ 산출물 재생성 → ⑩ 인용·용어 검사"
          + (" → 인용이 붙은 글이 바뀜: cross_verify.py --outputs 교차 검증 필요 (비용 먼저 알림)" if result["cross_verify"]
             else " (인용이 붙은 글은 안 바뀜 — 교차 검증 생략 가능, 완료 보고에 적기)"))


if __name__ == "__main__":
    main()
