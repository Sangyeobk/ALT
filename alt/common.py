"""ALT 공통 도구: 사내망 인증서 설정, 설정 파일, 개인 설정(이메일·키) 읽기."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import truststore
import yaml

# 사내망은 SSL 검사를 하므로 Windows 인증서 저장소를 쓴다 (인증서 검사를 끄지 않는다).
truststore.inject_into_ssl()
# Windows 콘솔·파이프에서 한글이 깨지지 않게 한다.
sys.stdout.reconfigure(encoding="utf-8")

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = Path.cwd()  # 결과·양식은 사용자 작업 폴더, 코드·기본 설정은 PACKAGE_DIR
CONFIG_PATH = PACKAGE_DIR / "config.yaml"
USER_DIR = Path.home() / ".alt"
OLD_USER_DIR = Path.home() / ".kr_alt"  # 2026-10-21 이름 변경 전 개인 설정 폴더 — 처음 한 번 복사해 이어 씀 (옛 폴더는 그대로)
if not USER_DIR.exists() and OLD_USER_DIR.is_dir():
    import shutil
    shutil.copytree(OLD_USER_DIR, USER_DIR)
USER_SETTINGS_PATH = USER_DIR / "settings.yaml"
USER_STYLE_PATH = Path.home() / ".alt" / "report_style.md"  # 개인 스타일 (report_guide.md보다 우선)
USER_SEARCH_PREFS_PATH = Path.home() / ".alt" / "search_prefs.md"  # 검색 취향 — ① 검색어 확장에만 (채점·검증 입력에는 넣지 않음)
PROJECT_SUBDIR = "project"  # 이 조사 맞춤 (결과 폴더 안, 사용자 결정 2026-10-16) — 우선순위: 기본 < 개인 < 이 조사
PREFERENCE_HEADERS = {
    "style": "# 개인 스타일 (ALT) — 요약·부분 수정에서 기본 지침보다 우선. 고치기·지우기는 이 파일을 직접 편집\n\n",
    "search": "# 검색 취향 (ALT) — ① 검색어 확장에만 참고 (관련성 채점·선정 기준은 바꾸지 않음). 고치기·지우기는 직접 편집\n\n",
}


def load_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def load_project_settings(run_dir: Path | None) -> dict:
    """이 조사 맞춤 설정 `<run>/project/settings.yaml` (장 목록·선정 기준). 없으면 빈 dict."""
    path = Path(run_dir) / PROJECT_SUBDIR / "settings.yaml" if run_dir else None
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path and path.is_file() else {}


def extra_outputs(run_dir: Path | None) -> list[dict]:
    """이 조사 맞춤 결과물 목록 `<run>/project/extras.yaml` (사용자 결정 2026-10-16: 피드백으로 새 형태 결과물 추가, 기본 코드는 그대로).
    항목: name, script(`project/extras/` 안 파일), outputs(파일 이름 — 판 이름이 붙음), cite_check(기본 true)."""
    path = Path(run_dir) / PROJECT_SUBDIR / "extras.yaml" if run_dir else None
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or []) if path and path.is_file() else []


def extra_files(run_dir: Path, variant: str, cite_only: bool = False) -> list[str]:
    """맞춤 결과물 파일 이름 (판 이름 붙음)."""
    return [variant_name(name, variant) for item in extra_outputs(run_dir)
            if not cite_only or item.get("cite_check", True) for name in item["outputs"]]


def sections(kind: str, run_dir: Path | None = None) -> list[str]:
    """보고서(report)·발표(slide) 장 순서: 이 조사 맞춤 → 개인 설정 → config.yaml 순으로 찾는다."""
    key = f"{kind}_sections"
    return load_project_settings(run_dir).get(key) or load_user_settings().get(key) or load_config()["output"][key]


def _flatten(tree: dict, prefix: str = "") -> dict:
    """{'weights': {'relevance': 0.5}} → {'weights.relevance': 0.5}"""
    flat = {}
    for key, value in tree.items():
        path = f"{prefix}{key}"
        flat.update(_flatten(value, path + ".") if isinstance(value, dict) else {path: value})
    return flat


def scoring_config(run_dir: Path | None = None) -> tuple[dict, list[dict]]:
    """선정 기준 = config.yaml scoring ← 개인 설정 scoring ← 이 조사 맞춤 scoring (사용자 결정 2026-10-16: 바꿀 수 있지만
    권장하지 않음). 돌려주는 것: (적용 기준, 기본값과 다른 항목 목록 — 결과에 그대로 표시)."""
    default = _flatten(load_config()["scoring"])
    applied, source = dict(default), {}
    for label, layer in (("개인 설정", load_user_settings().get("scoring")), ("이 조사 맞춤", load_project_settings(run_dir).get("scoring"))):
        for key, value in _flatten(layer or {}).items():
            if key not in default:
                raise SystemExit(f"[scoring] {label}의 '{key}'는 config.yaml scoring에 없는 항목 — 이름 확인")
            applied[key], source[key] = value, label
    rules: dict = {}
    for key, value in applied.items():  # 다시 중첩 사전으로
        node = rules
        *parents, last = key.split(".")
        for part in parents:
            node = node.setdefault(part, {})
        node[last] = value
    overrides = [{"key": k, "default": default[k], "value": applied[k], "source": source[k]}
                 for k in source if applied[k] != default[k]]
    return rules, overrides


def role_label(subtopic: dict, s: dict | None = None) -> str:
    """분야 역할 표시 이름 — 주제마다 synthesis role_names, 없으면 config output.role_labels ('핵심'이 '핵심논문'과 헷갈리지 않게)."""
    role = subtopic.get("role", "")
    return ((s or {}).get("role_names") or {}).get(role) or load_config()["output"].get("role_labels", {}).get(role, role)


def load_topic(run_dir: Path) -> dict:
    """사용자가 시작 때 확정한 주제(`<run>/topic.json`, define_topic.py) — 없으면 {} (예전 결과 폴더)."""
    path = Path(run_dir) / "topic.json"
    return read_json(path) if path.is_file() else {}


KEY_REGISTRY = "citation_keys.json"


def key_registry(run_dir: Path) -> dict[str, str]:
    """openalex_id → 인용 키. 한 번 매긴 키는 인용 목록에서 빠져도 지우지 않음 — 본문 정리(키 기준)를 다시 찾고,
    돌아온 논문이 같은 키를 받게 (10-19 결함: 상한으로 빠진 논문의 본문 정리를 못 찾음)."""
    path, refs_path = Path(run_dir) / KEY_REGISTRY, Path(run_dir) / "references.json"
    registry = read_json(path) if path.is_file() else {}
    refs = read_json(refs_path) if refs_path.is_file() else {}
    return {**registry, **{ref["openalex_id"]: key for key, ref in refs.items() if ref.get("openalex_id")}}


def verbatim_strings(run_dir: Path) -> list[str]:
    """그대로 옮겨 적는 글 — 실행한 검색어 원문(candidates meta.queries)과 주제 기록의 입력 원문·범위 결정 이유.
    바꾸면 안 되는 글이라 용어 검사(변이형)·약어 풀이에서 뺀다 (10-16 결함: 검색어가 변이형으로 잡힘, 입력 원문 약어를 풀어 씀)."""
    candidates, topic = Path(run_dir) / "candidates.json", load_topic(run_dir)
    queries = read_json(candidates).get("meta", {}).get("queries", []) if candidates.is_file() else []
    return [*queries, topic.get("input", ""), topic.get("scope_reason", ""), *(x["reason"] for x in topic.get("split_out", [])),
            *(f"{x['q']} → {x['a']}" for x in topic.get("clarifications", []))]  # 해석 확인 질의응답도 사용자 말 그대로


def topic_context(run_dir: Path, topic: str | None = None, approach: str | None = None) -> dict:
    """채점·평가·검증 입력에 넣는 주제 — 확정 주제(topic.json)의 영문명·포함·제외 범위, 없으면 받은 값.
    기준 문서(relevance_rubric·review_rubric)는 주제 중립이므로 판단 대상은 늘 이 값으로 준다 (2026-10-16 결함 수정)."""
    confirmed = load_topic(run_dir)
    context = {"topic": confirmed.get("topic_en") or topic, "approach": confirmed.get("approach_en") or approach}
    if confirmed:
        context["scope"] = {k: confirmed[k] for k in ("include", "exclude", "question")}
    return context


def display_names(run_dir: Path, s: dict, meta: dict) -> dict:
    """결과물에 쓰는 주제·접근법 이름 — '선택한 접근법' 같은 자리표시 말 대신 쓴다.
    확정 주제(topic.json) → 요약 names → 입력 주제·접근법(접근법은 config approach_labels 표시 이름) 순."""
    topic, names = load_topic(run_dir), s.get("names") or {}
    raw = meta.get("approach") or ""
    return {"topic": topic.get("topic_ko") or names.get("topic") or meta.get("topic") or "",
            "approach": topic.get("approach_ko") or names.get("approach")
            or load_config()["output"]["approach_labels"].get(raw.lower(), raw)}


def year_span(years: list[int]) -> str:
    return (f"{years[0]}–{years[-1]}" if years[0] != years[-1] else str(years[0])) if years else ""


def scope_years(topic: dict) -> str:
    """조사 범위 연도 (사용자가 정한 기간) — 올해보다 뒤 연도는 빼고 (아직 오지 않은 연도는 쓰지 않음)."""
    lo, _, hi = str(topic["years"]).partition("-")
    hi = min(int(hi or lo), date.today().year)
    return year_span(sorted({int(lo), hi}))


def topic_line(run_dir: Path, references: dict | None = None) -> str:
    """목적 장 첫 줄 '조사 주제: …' — 확정 주제 이름을 그대로 밝힘. 확정 주제가 없으면 빈 문자열.
    참고문헌을 주면 핵심논문 수록 연도도 붙인다 (제목 연도는 조사 범위 — 사용자 결정 2026-10-16)."""
    t = load_topic(run_dir)
    if not t:
        return ""
    held = year_span(sorted({r["year"] for r in (references or {}).values() if r.get("year")}))
    return (f"조사 주제: {t['topic_ko']} ({t['topic_en']}) · 접근법: {t['approach_ko']} · 기간 {scope_years(t)}"
            + (f" (핵심논문 수록 {held})" if held and held != scope_years(t) else ""))


def scope_history(run_dir: Path) -> list[tuple[str, str]]:
    """조사 범위가 정해진 과정 (사용자 피드백 2026-10-16: 입력과 제목이 달라 보임) — 입력 원문 → 범위 결정 → 따로 떼어 낸 세부 조사.
    범위를 바꾼 이유(scope_reason)·떼어 낸 조사(split_out)·상위 조사(parent_run)가 기록돼 있을 때만 — 없으면 빈 목록 (입력 = 확정)."""
    t = load_topic(run_dir)
    if not t or not (t.get("scope_reason") or t.get("split_out") or t.get("parent_run") or t.get("clarifications")):
        return []
    rows = [("입력 원문", t["input"])]
    rows += [("해석 확인", f"{x['q']} → {x['a']}") for x in t.get("clarifications", [])]  # 모호한 점 질의응답 (사용자 결정 2026-10-21)
    if t.get("parent_run"):  # 세부 조사: 어느 조사에서 떼어 냈는지 (SKILL ⑧-1 — 결과 폴더 이름 그대로)
        rows.append(("상위 조사", f"{t['parent_run']} — 이 조사는 그 조사의 한 분야를 따로 떼어 깊이 본 세부 조사"))
    if t.get("scope_reason"):
        rows.append(("범위 결정", t["scope_reason"]))
    rows += [("세부 조사로 분리", f"{x['field']} — {x['reason']}" + (f" → 결과 폴더 {x['run']}" if x.get("run") and x["run"] not in x["reason"] else ""))  # 이유에 이미 있으면 다시 붙이지 않음
             for x in t.get("split_out", [])]
    return rows


def report_title(run_dir: Path, s: dict, references: dict) -> str:
    """결과물 제목: 확정 주제가 있으면 그 이름 그대로 '{주제} — {접근법} 연구 동향 (조사 범위 연도)' (사용자 지시 2026-10-16),
    없으면 요약의 title. 주제명에 접근법 말이 이미 있으면 '— 연구 동향'만 (중복 빼기), 연도는 조사 범위 (사용자 결정 2026-10-16)."""
    topic = load_topic(run_dir)
    if not topic:
        return s["title"]
    approach = "" if topic["approach_ko"] in topic["topic_ko"] else f"{topic['approach_ko']} "
    return f"{topic['topic_ko']} — {approach}연구 동향 ({scope_years(topic)})"


def load_user_style(run_dir: Path | None = None) -> str:
    """개인 스타일 + 이 조사 맞춤 스타일(`<run>/project/style.md`, 개인보다 우선)."""
    text = USER_STYLE_PATH.read_text(encoding="utf-8") if USER_STYLE_PATH.is_file() else ""
    project = Path(run_dir) / PROJECT_SUBDIR / "style.md" if run_dir else None
    if project and project.is_file():
        text += "\n\n# 이 조사 맞춤 (개인 스타일보다 우선)\n" + project.read_text(encoding="utf-8")
    return text


def load_search_prefs() -> str:
    return USER_SEARCH_PREFS_PATH.read_text(encoding="utf-8") if USER_SEARCH_PREFS_PATH.is_file() else ""


def add_preference(kind: str, text: str, run: str | None = None) -> Path:
    """개인 취향 한 줄 추가 (kind: style | search) — 날짜·결과 폴더를 붙여 어디서 온 취향인지 남긴다."""
    path = USER_STYLE_PATH if kind == "style" else USER_SEARCH_PREFS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    origin = f" ({run})" if run else ""
    with open(path, "a", encoding="utf-8") as f:
        if not path.stat().st_size:
            f.write(PREFERENCE_HEADERS[kind])
        f.write(f"- {datetime.now():%Y-%m-%d}{origin}: {text.strip()}\n")
    return path


def load_user_settings() -> dict:
    """사용자 PC에만 있는 개인 설정. 없으면 빈 dict (이메일은 SKILL이 처음 실행 때 물어본다)."""
    if not USER_SETTINGS_PATH.is_file():
        return {}
    return yaml.safe_load(USER_SETTINGS_PATH.read_text(encoding="utf-8")) or {}


def save_user_settings(**updates) -> Path:
    settings = load_user_settings()
    settings.update({k: v for k, v in updates.items() if v})
    USER_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    USER_SETTINGS_PATH.write_text(yaml.safe_dump(settings, allow_unicode=True), encoding="utf-8")
    return USER_SETTINGS_PATH


SCORING_WARNING = ("권장하지 않음 — 기본 선정 기준은 시험 주제·교차 검증으로 정한 값이고, 바꾸면 다른 조사와 비교하기 어려워짐. "
                   "바꾼 값은 보고서 부록·엑셀에 '기본값과 다른 기준'으로 표시됨")


def set_scoring(assignment: str, run_dir: Path | None = None) -> Path:
    """선정 기준 한 항목 바꾸기 'weights.relevance=0.6' → 개인 설정, run_dir이 있으면 그 조사 맞춤(project/settings.yaml)."""
    key, _, raw = assignment.partition("=")
    if key not in _flatten(load_config()["scoring"]) or not raw:
        raise SystemExit(f"[scoring] '{assignment}' — 형식은 항목=값, 항목은 config.yaml scoring 안 이름 (예: max_selected=20)")
    path = Path(run_dir) / PROJECT_SUBDIR / "settings.yaml" if run_dir else USER_SETTINGS_PATH
    settings = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.is_file() else {}
    node = settings.setdefault("scoring", {})
    *parents, last = key.split(".")
    for part in parents:
        node = node.setdefault(part, {})
    node[last] = yaml.safe_load(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(settings, allow_unicode=True), encoding="utf-8")
    return path


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, payload) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def cite(item: dict, limit: int | None = None, with_pages: bool = True) -> str:
    """주장 항목의 근거 표시: cites → ' [Kim2025a; Lee2026]', 없으면 source(예: 일반 개념) → ' [일반 개념]'.
    전문 모드에서 pages가 있으면 쪽 번호를 붙인다: {"pages": {"Kim2025a": 7}} → ' [Kim2025a, p.7; Lee2026]'.
    limit을 주면 앞의 대표 키만 보이고 나머지는 '외 N편' (읽기 쉽게 — 전체는 엑셀 집계 근거·방법 비교 시트).
    with_pages=False면 쪽 번호 없이 키만 — 보고서 표 칸용 (사용자 피드백 2026-10-27: 표가 복잡함)."""
    keys = item.get("cites") or []
    pages = (item.get("pages") or {}) if with_pages else {}
    if keys:
        shown = keys if limit is None else keys[:limit]
        more = f" 외 {len(keys) - len(shown)}편" if len(keys) > len(shown) else ""
        return " [" + "; ".join(f"{k}, p.{pages[k]}" if k in pages else k for k in shown) + more + "]"
    source = item.get("source")
    return f" [{source}]" if source else ""


def keyword_chunks(text: str, words: list[str]) -> list[tuple[str, bool]]:
    """글을 (조각, 기술 핵심어인지) 목록으로 — 기술 핵심어를 초록색으로 쓰기 위해 (사용자 피드백 2026-10-19).
    긴 낱말 먼저 맞추고(겹침 방지), 영문·숫자 낱말 중간에서는 맞추지 않음 (PINN이 PINNs 안에서 잘리지 않게는 하지 않음 — 'PINNs'도 표시)."""
    words = sorted({w for w in words if w}, key=len, reverse=True)
    if not words or not text:
        return [(text, False)] if text else []
    pattern = re.compile("(?<![A-Za-z0-9])(" + "|".join(re.escape(w) for w in words) + ")")
    chunks, pos = [], 0
    for m in pattern.finditer(text):
        if m.start() > pos:
            chunks.append((text[pos:m.start()], False))
        chunks.append((m.group(1), True))
        pos = m.end()
    if pos < len(text):
        chunks.append((text[pos:], False))
    return chunks


def tech_keywords(s: dict) -> list[str]:
    """요약의 기술 핵심어 (본문에 그대로 쓰이는 낱말) — 없으면 빈 목록 (예전 요약)."""
    return [w.strip() for w in s.get("tech_keywords", []) if w and w.strip()]


def keyword_tag(item: dict, keywords: list[dict]) -> str:
    """주장 앞에 붙는 핵심 키워드 표시: {"keyword": "K1"} → '[검증 기준] ' (키워드 없으면 빈 문자열)."""
    term = {k["id"]: k["term"] for k in keywords}.get(item.get("keyword"))
    return f"[{term}] " if term else ""


class Abbreviations:
    """[사용자 규칙] 약어는 문서마다 처음 나올 때 풀어 쓴다: RAO → RAO(Response Amplitude Operator).
    문서 하나마다 새로 만들고, 글을 쓰는 순서대로 통과시킨다.
    - 바로 뒤에 괄호가 있으면 그 괄호 안에 풀이를 넣는다: 'RAO (응답진폭연산자)' → 'RAO (Response Amplitude Operator, 응답진폭연산자)'
    - 괄호 안에 있으면 쉼표로 붙인다: '해석(CFD 등)' → '해석(CFD, Computational Fluid Dynamics 등)'
    - 이미 풀어 쓴 경우는 그대로 둔다
    - 건드리지 않는 곳: `…` 안(수식·기호 — 10-16 결함: 연료식 기호 MF에 'Membership Function'이 붙음),
      protected 글(입력 원문·검색어처럼 그대로 옮기는 글 — 10-16 결함: 입력 원문 PINN을 풀어 씀)"""

    def __init__(self, table: dict[str, str] | None, protected: list[str] | None = None):
        self.table = table or {}
        self.protected = [p for p in (protected or []) if p]
        self.seen: set[str] = set()

    def _untouchable(self, text: str) -> list[tuple[int, int]]:
        spans = [m.span() for m in re.finditer(r"`[^`]*`", text)]
        return spans + [m.span() for p in self.protected for m in re.finditer(re.escape(p), text)]

    def __call__(self, text: str) -> str:
        for abbr, full in self.table.items():
            if abbr in self.seen or not text:
                continue
            spans = self._untouchable(text)
            match = next((m for m in re.finditer(rf"(?<![A-Za-z0-9]){re.escape(abbr)}(?![A-Za-z0-9])", text)
                          if not any(a <= m.start() < b for a, b in spans)), None)
            if not match:
                continue
            self.seen.add(abbr)
            rest = text[match.end():]
            if full in rest[:len(full) + 4]:
                continue  # 이미 풀어 쓴 경우
            paren = re.match(r"\s*\(", rest)
            if text[match.start() - 1:match.start()] == "(":
                text = text[:match.end()] + f", {full}" + rest
            elif paren:
                text = text[:match.end()] + rest[:paren.end()] + full + ", " + rest[paren.end():]
            else:
                text = text[:match.end()] + f"({full})" + rest
        return text


def structure_group(structure_type: str | None, groups: list, word_start: bool = False) -> str:
    """구조물 이름(또는 제목·초록) → 표시 묶음 (위에서부터 처음 맞는 묶음, 없으면 마지막 묶음).
    word_start: 낱말 첫머리에서만 맞춤 — 제목·초록처럼 긴 글에서 'ais'가 'basis'에 맞는 일을 막음."""
    text = (structure_type or "").lower()
    for label, words in groups:
        if any(w and (re.search("(?<![a-z0-9])" + re.escape(w.lower()), text) if word_start else w.lower() in text) for w in words):
            return label
    return groups[-1][0]


def map_axis(run_dir: Path | None) -> dict:
    """문헌지도·분포 행렬·미달 비교표의 가로축 (사용자 결정 2026-10-16 — 주제마다 다름).
    확정 주제에 축(topic.json `axis`)이 있으면 그 묶음을 제목·초록 낱말로 나누고, 없으면 config 구조물 묶음을 채점의 structure_type으로."""
    axis = load_topic(run_dir).get("axis") if run_dir else None
    if axis:
        return {**text_axis(axis), "assign": axis_assignments(run_dir, text_axis(axis))}
    output = load_config()["output"]
    return {"name": output["structure_axis_name"], "groups": output["structure_groups"], "field": "structure_type"}


def text_axis(axis: dict) -> dict:
    """topic.json axis → 축 (마지막 묶음 = config axis_unknown_label). 분류는 AI 배정(axis_assign.json), 없으면 낱말 미리보기."""
    return {"name": axis["name"], "groups": axis["groups"] + [[load_config()["output"]["axis_unknown_label"], [""]]], "field": "text"}


def axis_assignments(run_dir: Path, axis: dict) -> dict[str, str]:
    """AI 분류 결과(`<run>/axis_assign.json`, classify_axis.py) → {openalex_id: 묶음}. 지금 축과 이름·묶음이 다르면 버림 (축을 바꾼 뒤 다시 분류)."""
    path = Path(run_dir) / "axis_assign.json"
    if not path.is_file():
        return {}
    data = read_json(path)
    if data["axis"] != {"name": axis["name"], "labels": axis_labels(axis)}:
        return {}
    return {oid: a["group"] for oid, a in data["assign"].items()}


def axis_group(record: dict, axis: dict) -> str:
    """논문 하나의 가로축 묶음 (map_axis). 주제별 축은 AI 배정이 있으면 그것, 없으면 제목·초록 낱말 (미리보기 수준)."""
    if record.get("openalex_id") in axis.get("assign", {}):
        return axis["assign"][record["openalex_id"]]
    if axis["field"] == "structure_type":
        return structure_group(record.get("structure_type"), axis["groups"])
    return structure_group(f"{record.get('title') or ''} {record.get('abstract') or ''}", axis["groups"], word_start=True)


def axis_labels(axis: dict) -> list[str]:
    return [g[0] for g in axis["groups"]]


PRISMA_NOTE = [  # 문헌 선별 흐름도 설명 '머리말: 설명' — 보고서 부록·배경학습 공용 (사용자 지시 2026-10-15).
    # 약어 자동 풀이와 겹치지 않게 PRISMA는 정식 명칭과 함께 설명 쪽에 처음 쓴다
    "이름: PRISMA(Preferred Reporting Items for Systematic Reviews and Meta-Analyses) 흐름도",
    "원래 쓰는 곳: 의학·보건학·사회과학 등의 체계적 문헌고찰(Systematic Review)과 메타분석(Meta-Analysis)",
    "하는 일: 논문을 어떻게 검색하고 최종 선정했는지 그 과정을 투명하게 보여 주는 표준 순서도",
    # 무엇을 안 했는지 밝힘 (사용자 지시 2026-10-16: '형식만 참조'는 핵심 절차를 건너뛴 듯한 오해)
    "이 조사에서는: 선별 과정을 PRISMA 흐름도 양식으로 표시함 — 체계적 문헌고찰의 나머지 절차(사전 등록, "
    "연구별 비뚤림 위험 평가, 메타분석)는 하지 않은 연구 동향 조사임",
]
RELEVANCE_PASSED = ("selected", "below_threshold", "over_limit")  # 관련성 하한은 넘은 연구 논문 (총점과 무관)


def candidate_distribution(records: list[dict], rules: dict, axis: dict) -> dict:
    """선정 / 관련성 통과 / 관련성 N점 이상 후보의 가로축(map_axis) 묶음별 편수 — 분모를 밝혀 쓰기 위한 집계."""
    pools = {"선정": [r for r in records if r["status"] == "selected"],
             "관련성 기준 통과": [r for r in records if r["status"] in RELEVANCE_PASSED],
             f"관련성 {rules['gap_matrix_min_relevance']}점 이상 후보":
                 [r for r in records if r["relevance"] >= rules["gap_matrix_min_relevance"] and not r["exclude"]]}
    return {name: {"total": len(pool), "axis": axis["name"], "by_group": dict(Counter(axis_group(r, axis) for r in pool))}
            for name, pool in pools.items()}


OUTPUT_NAMES = ["00_summary.md", "01_background.pptx", "03_report.docx", "04_presentation.pptx", "05_references.xlsx", "06_context.md"]
# 판마다 따로 만드는 산출물 (02_literature_map.png는 채점 결과만으로 만들어 판과 무관 — 하나만)


def variant_name(name: str, variant: str) -> str:
    """파일 이름 그대로 — 판(초록/전문활용) 구분 없이 결과는 한 벌 (사용자 결정 2026-10-19, 2026-10-15 판 이름 붙이기를 대체).
    초록·전문 중 무엇으로 만들지는 run_reading_mode가 조사마다 정한다."""
    # ponytail: 호출부(17개 파일)를 건드리지 않으려고 이름만 남김 — 정리할 때 호출부에서 variant 인자와 함께 지움
    return name


def run_reading_mode(run_dir: Path | None) -> str:
    """요약 읽기 방식: 기본은 초록(config fulltext.reading_mode), 이 조사에서 전문을 한 번이라도 썼으면(전문 정리 기록·이전 전문 모드)
    이후 갱신도 전문 (사용자 결정 2026-10-19)."""
    if run_dir is not None:
        run_dir = Path(run_dir)
        previous = run_dir / "synthesis_input.json"
        if any(run_dir.glob("fulltext_notes_*.json")) or (
                previous.is_file() and read_json(previous).get("meta", {}).get("reading_mode") == "full"):
            return "full"
    return load_config()["fulltext"]["reading_mode"]


def add_variant(parser, default: str | None = None) -> None:
    """--variant 인자 (기본: config output.default_variant)."""
    parser.add_argument("--variant", default=default or load_config()["output"]["default_variant"],
                        help="폐지됨(2026-10-19 판 구분 없음) — 넣어도 파일 이름은 그대로. 예전 명령 호환용")


def review_info(run_dir: Path, variant: str) -> tuple[str, dict[str, str]]:
    """요약 단계가 실제로 읽은 수준 (synthesis_input_<판>.json 기준) → (산출물에 쓸 한 줄, {키: 전문/초록/제목만})."""
    data = read_json(Path(run_dir) / variant_name("synthesis_input.json", variant))
    level_of = {p["key"]: p.get("review_level", "초록" if p.get("abstract") else "제목만") for p in data["papers"]}
    counts = {lv: sum(v == lv for v in level_of.values()) for lv in ("전문", "초록", "제목만")}
    mode = data["meta"].get("reading_mode", "abstract")
    counted = f"전체 {len(level_of)}편 중 " + " · ".join(f"{lv} {n}편" for lv, n in counts.items() if n)
    line = (f"검토 수준: {counted} (전문 모드 — 받아 둔 본문을 읽고 정리)" if mode == "full"
            else f"검토 수준: {counted} (초록 모드 — 수치·검증 내용은 원문 확인 필요)")
    return line, level_of
