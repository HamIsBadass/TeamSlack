# /psearch 운영 가이드

이 문서는 현재 코드 기준으로 `/psearch` 모델 라우팅, 응답 스타일, 운영 절차를 빠르게 확인하기 위한 문서입니다.

## 1) 실제 동작 구조

- Slash command 진입점: [apps/slack-bot/socket_mode_runner.py](apps/slack-bot/socket_mode_runner.py)
- Perplexity 호출: `_perplexity_search(...)`
- 모델 라우팅: [shared/utils/model_router.py](shared/utils/model_router.py)
  - `parse_psearch_input(...)`
  - `select_perplexity_model(...)`
- Slack 출력 포맷 변환: [shared/utils/slack_formatter.py](shared/utils/slack_formatter.py)

응답 파이프라인은 아래 순서로 동작합니다.

1. `/psearch` 입력 파싱
2. 모델 선택(명시 프리픽스 우선, 없으면 자동)
3. Perplexity API 호출
4. 출처 표기 `[1][2]` 제거
5. 곰 스타일 후처리
6. Slack 마크다운 포맷 변환
7. 2800자 제한 후 응답

## 2) 모델 선택 규칙

### A. 사용자가 모델을 명시한 경우(최우선)

`/psearch` 뒤 첫 토큰이 아래 중 하나면 해당 모델을 강제 사용합니다.

- `pro` -> `sonar-pro`
- `reasoning` -> `sonar-reasoning`
- `reasoning-pro` -> `sonar-reasoning-pro`
- `sonar` -> `sonar`

예시:

```text
/psearch reasoning-pro 팀봇 장애 시나리오 분석
/psearch pro 2026년 Slack API 정책 변경사항
```

### B. 명시가 없는 경우(자동)

`select_perplexity_model(query)`가 키워드 기반으로 선택합니다.

1. reasoning-pro 키워드: `아키텍처`, `설계 검토`, `장애 분석`, `트레이드오프`
2. reasoning 키워드: `단계별`, `원인`, `비교`, `코드 리뷰`, `디버깅`, `분석`, `설계`
3. pro 키워드: `최신`, `뉴스`, `동향`, `정책`, `법령`, `출처`, `경쟁사`, `시장`, `공식`
4. 매칭 없음: `sonar`

## 3) 어떤 파일을 수정해야 하는가

| 수정 목적 | 파일 | 핵심 함수/상수 |
|---|---|---|
| 모델 선택 규칙 변경 | [shared/utils/model_router.py](shared/utils/model_router.py) | `select_perplexity_model`, `parse_psearch_input` |
| 말투/출력 지침 변경 | [apps/slack-bot/socket_mode_runner.py](apps/slack-bot/socket_mode_runner.py) | `SYSTEM_PROMPT_*` |
| Slack 서식 동기화 | [shared/utils/slack_formatter.py](shared/utils/slack_formatter.py) | `to_slack_format` |
| 길이 제한 변경 | [apps/slack-bot/socket_mode_runner.py](apps/slack-bot/socket_mode_runner.py) | `content[:2800]` |

스타일 문서 참조:

- 오케스트레이터: [orchestrator-bot-style.md](./orchestrator-bot-style.md)
- 개인봇: [personal-bot-style.md](./personal-bot-style.md)

## 4) 운영 원칙

- 기본 모델은 항상 저비용 모델(`sonar`)로 시작
- 최신성/출처 중요 질문만 `sonar-pro` 이상 사용
- 고급 추론이 필요한 경우에만 reasoning 계열 사용
- 검색이 필요 없는 문서/코드/요약 작업은 Gemini 라우팅 대상으로 분리

참고: Gemini 선택 함수는 [shared/utils/model_router.py](shared/utils/model_router.py)에 `select_gemini_model(...)`로 준비되어 있습니다.

## 5) 점검 절차

1. 문법 검사

```bash
python -m py_compile apps/slack-bot/socket_mode_runner.py
python -m py_compile shared/utils/model_router.py
python -m py_compile shared/utils/slack_formatter.py
```

2. 봇 실행

```bash
python apps/slack-bot/socket_mode_runner.py
```

3. Slack 테스트

```text
/psearch FastAPI rate limiting 설정
/psearch pro 한국 개인정보보호법 최신 개정 내용
/psearch reasoning Redis pub/sub vs Celery 선택 기준
/psearch reasoning-pro 오케스트레이터 장애 시나리오 분석
```

4. 확인 항목

- 프리픽스 입력 시 모델 강제 선택이 되는지
- 프리픽스 없이도 자동 라우팅이 기대대로 동작하는지
- Slack에서 볼드/이탤릭 서식이 원본 의도와 동일한지
- 출처 표기 제거, 길이 제한, 곰 스타일이 유지되는지

## 6) /usdtw 입력 확장 규칙

`/usdtw`는 두 가지 모드로 동작합니다.

- 기본 모드: `/usdtw`
  - 현재 USD/KRW 환율 + 6개월 관점 의견
- 변환 모드: `/usdtw [금액][화폐]` 또는 `/usdtw [금액] [화폐]`
  - 한 줄 형식으로 KRW 환산값 반환

지원 예시:

```text
/usdtw 0.1
/usdtw 1달러
/usdtw 10 usd
/usdtw 20 eur
/usdtw 100 엔
```

변환 모드 출력 예시:

```text
지금 기준으로 0.1달러는 약 147.8원이다곰.:polar_bear:
```
