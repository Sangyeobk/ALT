# 관련성 채점 기준 (0–5점) — [제안] 사용자 확정 전 초안

판단 대상: 입력 주제(topic)와 접근법(approach)에 이 논문이 얼마나 직접 기여하는가.
입력에 `scope`(사용자가 확정한 포함·제외 범위, 조사 질문)가 있으면 그 범위로 판단한다 — 제외 범위에 해당하면 주제가 비슷해도 낮게.
근거는 제목·초록에 **쓰여 있는 것만** 쓴다. 추측으로 점수를 올리지 않는다.

| 점수 | 기준 |
|---|---|
| 5 | 주제와 접근법 모두 핵심 (입력 접근법으로 주제의 대상을 직접 예측·추정·평가) |
| 4 | 주제 핵심 + 접근법 일부 해당, 또는 접근법 핵심 + 주제와 밀접 (주제와 직결되는 인접 물리량·성능을 입력 접근법으로 다룸) |
| 3 | 관련 주제 — 결과를 주제에 활용 가능 (주제의 입력·전 단계를 다룸, 또는 주제를 다루지만 입력 접근법은 보조) |
| 2 | 간접 관련 — 같은 분야지만 다른 문제 |
| 1 | 용어만 겹침 |
| 0 | 무관 |

추가 규칙
- 초록이 없으면 제목으로만 판단하고 `low_confidence: true`로 표시한다.
- 리뷰 논문은 주제가 맞으면 점수를 깎지 않는다.
- `reason`은 입력 `language`의 언어(ko 한국어, en 영어; 없으면 한국어)로 한 문장, 점수의 근거가 된 초록 내용을 짚는다.
- `approach`: 논문이 쓴 접근법 (theory / experiment / CFD / data-driven / hybrid / other 중 해당하는 것 모두)
- `is_review`: 리뷰·서베이·state-of-the-art 논문(다른 연구를 모아 정리한 논문)이면 true
- `axis_group`·`axis_reason` (입력에 `axis`가 있을 때만): `axis.groups` 묶음 이름 하나를 글자 그대로 (`hints` 낱말은 예시일 뿐 — 같은 뜻이면 그 묶음, 여러 묶음에 걸치면 논문의 중심 하나). 제목·초록에 근거가 없으면 `axis.unknown_label` — 추측 배정 안 함. `axis_reason`은 `reason`과 같은 언어로 한 문장 (근거 문구)
- `structure_type`: 연구 대상 (구조물·선종·장치 등 주제에 맞는 것. 해양구조물 예: monopile, jacket, FPSO, TLP, spar, semi-submersible, floating wind, fixed platform, vessel, generic, none)
