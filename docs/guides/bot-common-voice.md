# 봇 공통 음성 규칙

모든 봇 페르소나(오케스트레이터/개인봇/meeting/jira/review)에 자동 적용되는 상위 지침입니다. 개별 페르소나 스타일(예: [orchestrator-bot-style.md](orchestrator-bot-style.md), [personal-bot-style.md](personal-bot-style.md))보다 상위 계층에 있으며, 페르소나별 음성 규칙과 **함께** 시스템 프롬프트에 주입됩니다.

## 공통 규칙

```
불필요한 수식어 금지: 인삿말, 과도한 리액션, 칭찬, 스몰토크 없이 본론만 답변한다.
맥락 격리: 질문 주제와 무관한 개인 취향이나 사적 맥락은 언급하지 않는다.
효율적 구조: 질문의 핵심에 즉시 답하며 군더더기 서론/결론을 생략한다.
```

"담백한 어조" 항목은 공통에 포함하지 않습니다. 페르소나별(한지의 들뜬 톤, 에르빈의 무거운 톤, 햄스터의 당당한 반말 등)로 달라지기 때문입니다.

## 저장 위치와 주입 방식

- 단일 원천: [shared/profile/personas/_common.md](../../shared/profile/personas/_common.md)
  - front-matter 없이 규칙 본문만 작성
  - 파일명이 `_` 로 시작해 `get_persona("_common")` 으로는 로드되지 않음
- 주입 코드: [shared/profile/persona_loader.py](../../shared/profile/persona_loader.py) 의 `_load_common_rules()` 와 `_parse()` 내부 merge 로직
  - 각 페르소나 MD를 파싱할 때 `voice_rules = common + "\n\n" + persona_specific` 형태로 합성
  - 첫 호출 시 캐시. `reload_personas()` 호출 시 공통 캐시도 함께 초기화

## 추가·수정 절차

1. [_common.md](../../shared/profile/personas/_common.md) 본문을 편집
2. 런타임에 반영하려면 프로세스 재시작 또는 `shared.profile.reload_personas()` 호출
3. 변경 의도가 "특정 봇 한정"이라면 공통이 아닌 해당 페르소나 MD 파일에 추가한다
4. 스모크 검증:
   ```python
   from shared.profile import get_persona
   for pid in ("orchestrator","personal","meeting","jira","review"):
       assert "불필요한 수식어 금지" in get_persona(pid).voice_rules
   ```

## 관련 문서

- [guides/orchestrator-bot-style.md](orchestrator-bot-style.md) — 오케스트레이터(짐) 페르소나 규칙
- [guides/personal-bot-style.md](personal-bot-style.md) — 개인봇(햄스터) 페르소나 규칙
