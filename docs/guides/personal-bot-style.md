# 개인봇 스타일 가이드

이 문서는 개인봇의 말투/표현 규칙을 확인하고 직접 수정하기 위한 기준 문서입니다.

## 적용 대상

- 실행 파일: [apps/personal-bot/socket_mode_runner.py](../../apps/personal-bot/socket_mode_runner.py)
- 주요 동작: DM 자유 대화, app mention 응답, /summary, /reply 보조 흐름

## 현재 스타일 정책

- 기본 톤: 당당하고 간결한 업무형
- 문장 종결: 기본적으로 다! 형태
- 기본 이모지: hamster 스타일
- 검색 응답: Perplexity 경유 시에도 개인봇 스타일 후처리 적용

## 수정 포인트

### 1) 시스템 프롬프트(말투 규칙)

- 위치: [apps/personal-bot/socket_mode_runner.py](../../apps/personal-bot/socket_mode_runner.py)
- 상수:
  - SYSTEM_PROMPT_BASE
  - SYSTEM_PROMPT_PSEARCH
  - SYSTEM_PROMPT_USDTW
- 함수:
  - _gemini_chat_dm(...)

수정 시 주의:
- 개인봇은 오케스트레이터(곰 스타일)와 분리 유지한다.
- 개인봇 스타일 변경 시 오케스트레이터 파일은 수정하지 않는다.

### 2) 응답 후처리(개인 스타일 부착)

- 위치: [apps/personal-bot/socket_mode_runner.py](../../apps/personal-bot/socket_mode_runner.py)
- 함수:
  - add_gom_emojis(...)

참고:
- 함수명은 과거 호환을 위해 유지되어도, 내부 규칙은 개인봇 스타일로 동작한다.

### 3) 검색 질의 정제와 연도 제약

- 위치: [apps/personal-bot/socket_mode_runner.py](../../apps/personal-bot/socket_mode_runner.py)
- 함수:
  - _looks_like_search_request(...)
  - _extract_search_query(...)
  - _extract_year_terms(...)
  - _perplexity_chat_dm(...)

수정 시 주의:
- 연도 표현(예: 26년, 2026년)은 검색 제약으로 우선 반영한다.
- 조건 불일치 시 임의 연도 결과를 단정하지 않도록 프롬프트를 유지한다.

## 빠른 점검 절차

1. 문법 검사

```bash
python -m py_compile apps/personal-bot/socket_mode_runner.py
python -m py_compile shared/utils/slack_formatter.py
```

2. 봇 실행

```bash
python apps/personal-bot/socket_mode_runner.py
```

3. Slack 확인

- DM: 검색해줘 요청 시 다! + hamster 스타일 유지 여부
- DM: 연도 포함 검색(예: 26년 영화 검색)에서 연도 제약 반영 여부
- 채널 멘션: 공개 응답에서도 개인봇 스타일 유지 여부

## 관련 문서

- [오케스트레이터 봇 스타일 가이드](./orchestrator-bot-style.md)
- [/psearch 운영 가이드](./psearch-guideline-management.md)
