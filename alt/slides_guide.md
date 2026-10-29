# 발표 구성안 지침 (⑨-1 — alt-writer, 사용자 결정 2026-10-21)

입력 `slides_input.json` → 출력 `slides.json` 하나 (01_background은 맨 아래 '배경학습' 절). 발표(04_presentation.pptx)를 **양식의 장 종류에 맞춰 새로 쓴다** — 보고서 문장을 옮겨 붙이지 않는다.
내용·용어·표현의 기본 규칙은 `alt/report_guide.md`를 따른다 (사실은 요약 `synthesis`에 있는 것만, 숫자를 지어내지 않음, 쉬운 말, 번역투 자제).
구성안 글은 입력 `language`의 결과물 언어로 쓴다 (`ko` 한국어, `en` 영어 — 사용자 결정 2026-10-29). 영어는 글자 수 한도가 같아도 낱말이 길어 줄이 빨리 차므로 더 짧게.

## 입력에 있는 것
- `types`: 쓸 수 있는 장 종류. `use` = 어떤 내용에 맞는 장인지, `slots` = 칸 → 문단마다 `{role, max}` (**max = 글자 수 한도**, 한글 1자 = 1, 영문·숫자·기호 = 0.55). `image: true`면 그림 한 장, `table: true`면 표 하나를 넣는 장
- `sections`: 발표에 담을 구간과 순서 (보고서와 같은 흐름) / `facts`: 선별 편수(prisma)·방법 줄(method_lines)·엑셀 시트 안내
- `figures`: 넣을 수 있는 그림 파일과 설명 (원문 그림은 출처 줄을 코드가 붙임) / `ref_keys`: 인용 가능한 키 / `synthesis`: 요약 전체

## 출력 형식
```json
{"slides": [
  {"type": "cover", "slots": {"title": ["…"], "subtitle": ["…"]}},
  {"type": "contents", "slots": {"title": ["목차"], "item1": ["장 이름", "한 줄 설명"], "...": []}},
  {"type": "section", "slots": {"title": ["장 이름", "한 줄 설명"]}},
  {"type": "figure_full", "slots": {"title": ["…"]}, "image": "02_literature_map.png"},
  {"type": "table", "slots": {"title": ["…"]}, "table": {"header": ["…"], "rows": [["…"]]}}
]}
```
- 칸 값은 **문단 목록** — `slots`의 역할 순서대로, 개수도 같게 (flexible 칸만 앞에서부터 줄여도 됨, 빈 문단 금지)
- 마무리(Thanks) 장은 코드가 붙인다. 장 구분 번호도 코드가 매긴다

## 구성 규칙
1. 순서: cover → contents → (구간마다) section → 내용 장들. **장 구분은 6개** — `contents`의 item1–6과 같은 이름·순서. `sections`가 6개보다 많으면 묶는다 (권장: 목적·범위 / 핵심 인사이트 / 연구 흐름·분포 / 분야별 연구 / 쟁점과 결론 / 부록)
2. **한 장에 메시지 하나.** 제목은 그 장의 요지를 한 줄로 (장 이름 되풀이 금지). 같은 종류를 세 장 연속 쓰지 않는다 — 내용 모양에 맞는 종류를 고름:
   - 숫자가 핵심 → `big_number`·`numbers3` (예: 핵심논문 편수·분야 수·미검증 쟁점 수 — `facts`·`synthesis`에 있는 숫자만)
   - 세·네·여섯 갈래 → `items3`·`items4`·`items6`·`points3` / 두 갈래 비교 → `two_columns` / 단계 → `steps4`
   - 한계·쟁점 → `problems3`·`discussion` / 결론 한 문장 → `quote`(출처 칸: 인용 키 또는 '이 조사의 판단') / 전환 → `statement`
   - 비교 표 → `table` (머리 행 + 최대 6행·5열, 칸 40자 이하 — 더 많으면 표를 나누지 말고 핵심 행만, 나머지는 '엑셀 시트' 안내)
   - 그림: 넓은 그림(문헌지도·계통도·분포) → `figure_full`, 세로로 긴 그림(선별 흐름도)·원문 그림 → `figure_side`
   - **원문 그림 소개 장(사용자 2026-10-22)**: `figure_side`도 일반 본문 장과 같은 상단 제목을 쓴다. 왼쪽 제목을 크게 세워 공간을 차지하지 않는다. `headline`은 기존 구성안 호환용 제목 칸이며, `text`에는 그림 소개·읽는 순서·확인할 지점을 짧은 문단으로 쓴다(입력의 문단별 한도 준수). 입력·처리·출력 흐름 또는 축·곡선·조건 중 해당 그림에 실제로 보이는 내용을 설명한다. '그림을 확인' 같은 일반 안내로 분량을 채우지 않는다. 원문 캡션·본문·그림에서 확인한 사실만 쓰고 그림만으로 성능 우위나 적용 범위를 단정하지 않는다. 오른쪽 그림은 종횡비를 유지하고 아래 출처를 남긴다.
3. 꼭 담을 것 (구간별):
   - 목적·범위: 조사 질문, 범위 결정 과정(`scope_history`가 있으면), 핵심 키워드(있으면)
   - 핵심 인사이트: `key_messages` 전부 (장을 나눠도 됨)
   - 연구 흐름·분포: 문헌지도 + 관찰(`map_observations`), 선별 흐름도 + 방법 요점(`facts.method_lines`). 기술 흐름(`background.big_picture`·`approach_roles`)과 분야 구성(역할 → 분야 → 대표 기법)은 **그림 없이 장 종류로** — `steps4`(흐름 단계)·`items4`/`items6`(역할·분야)·`problems3`(기존 방법의 한계). **발표용 단순화 그림(`figures/slide_flow.png`·`slide_limits.png`·`slide_tree.png`)은 `figure_full`로** — 같은 내용을 글로 되풀이하는 장은 따로 만들지 않고, 그림 장 제목에 요지를 쓴다. 보고서용 그림(흐름도·계통도·한계→대응)은 쓰지 않음 (사용자 피드백 2026-10-21)
   - 분야별 연구: **분야마다 1–2장** — 목적·방법 → 주요 결과(`reported`) → 남은 과제(`unverified`). 원문 그림이 있는 분야는 `figure_side`로 1장
   - 쟁점과 결론: `issues`(우선순위 순), `conclusion.points`, `conclusion.closing`
   - 부록: 엑셀 시트 안내(`facts.excel_sheets`), 주목할 인접 문헌(`adjacent_guide`가 있으면)
4. **글자 수 한도를 넘지 않는다** — 넘을 것 같으면 문장을 줄이거나 장을 나눈다 (글자를 줄여 억지로 넣지 않음). 명사형 종결(~함, ~필요, ~부재) 개조식
5. 인용: 주장 끝에 `[Key]` 또는 `[Key1; Key2]` — `ref_keys`에 있는 키만, 한 문단에 최대 2개 (글자 수에 포함). 요약에 근거 키가 있는 주장은 키를 붙인다. 일반 개념은 `[일반 개념]` (영어 출력이면 `[general concept]` — 2026-10-29)
6. 약어는 이 발표에서 처음 나올 때 구성안에 직접 `CFD(전산유체역학)`처럼 풀어 쓰고 이후 약어만 (제목·장 이름은 풀지 않음 — 구성안 글은 코드가 풀어 주지 않음). 엔지니어가 영어로 아는 용어(black-box·fine-tuning·noon report 등)는 영어 원어 그대로 — 한국어 조어를 만들지 않음 (2026-10-27)
7. 기술 핵심어(`synthesis.tech_keywords`)는 본문에 그대로 쓴다 (코드가 굵게 표시)

## 끝 확인
`python alt/prepare_slides.py <run>/ --check`가 통과할 때까지 고친다 (한도 초과·칸 개수·없는 그림·없는 인용 키를 알려 줌). 통과하면 장 수와 종류별 개수를 짧게 보고한다.

## 배경학습 (01_background.pptx — 입력에 `"deck": "learn"`, 사용자 결정 2026-10-21)
입력 `slides_learn_input.json` → 출력 `slides_learn.json`. 문헌조사 결과가 아니라 **결과물을 쉽게 읽기 위한 배경 설명** — 처음 공부하는 사람에게 설명하듯 쓴다. 출력 형식·글자 수 한도·인용·약어·기술 핵심어 규칙(위 '출력 형식', '구성 규칙' 4–7)은 같다.
- 입력: `background`(목적·큰 그림·개념·접근법 비교·기본 단계, `leads` = 장 요지), `subtopics`(분야 이름·역할·요지)·`role_names`·`approach_roles`, `reviews_guide`(참고할 문헌조사논문), `names`(주제·접근법 이름), `figures`(발표용 단순화 그림만)
- 순서: cover → contents → (구간마다) section → 내용 장들. **장 구분은 5개**(`sections_count`), `contents`의 item1–5는 그 이름·순서, **item6은 `tail_section` 그대로**(장 이름 `용어와 읽는 법` — 용어 표·읽는 법 장은 코드가 마지막에 붙인다. 용어 장·읽는 법 장을 따로 만들지 않는다)
- 권장 장 구분: 이 자료 안내 / 큰 그림 / 핵심 개념 / 방법 비교와 기본 단계 / 더 공부할 자료
- 꼭 담을 것:
  - 안내: `background.purpose`, '문헌조사 결과가 아니라 결과물을 읽기 위한 배경 설명', 결과물 읽는 순서(00_summary → 01_background → 02_literature_map → 03_report·04_presentation → 05_references·06_context — `steps4`나 `list`)
  - 큰 그림: `big_picture` 단계와 `big_picture_note` (`steps4` — 단계가 5개 이상이면 묶거나 `figures/slide_flow.png`를 `figure_full`로), 분야 구성(역할 → 분야: `figures/slide_tree.png` `figure_full` 또는 `items4`/`items6`)
  - 핵심 개념: `concepts` **전부** — 개념마다 쉬운 설명 + 왜 중요한가 (`points3`·`two_columns`·`items3` 등, 근거 줄 `source`가 논문이면 인용 키)
  - 방법 비교와 기본 단계: `approach_comparison` 전부(원리·장점·한계 — `table`은 칸 40자 이하라 줄여 쓰거나 `items4`), `data_driven_basics`(`steps4`, 5단계 이상이면 묶음). 기존 방법의 한계는 `problems3`도 좋음
  - 더 공부할 자료: `reviews_guide` 전부(인용 키 + 읽으면 좋은 이유 — `list`). `reviews_guide`가 비어 있으면 이 구간은 '다음에 읽을 것'으로 결과물 안내(03_report·05_references·06_context) 한 장
- 숫자는 입력에 있는 것만
- 끝 확인: `python alt/prepare_slides.py <run>/ --deck learn --check`
