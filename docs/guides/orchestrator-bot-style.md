# 오케스트레이터 봇 스타일 가이드

이 문서는 오케스트레이터 봇의 말투/표현 규칙을 확인하고 직접 수정하기 위한 기준 문서입니다.

## 적용 대상

- 실행 파일: [apps/slack-bot/socket_mode_runner.py](../../apps/slack-bot/socket_mode_runner.py)
- 주요 명령: /psearch, /usdtw, /reply

## 현재 스타일 정책

- 기본 톤: 업무형, 간결, 단정형
- 스타일 캐릭터: 곰 스타일 유지
- 후처리 규칙: 첫 문장/마지막 문장에 곰 스타일 마커 적용

## 수정 포인트

### 1) 시스템 프롬프트(말투 규칙)

- 위치: [apps/slack-bot/socket_mode_runner.py](../../apps/slack-bot/socket_mode_runner.py)
- 상수:
  - SYSTEM_PROMPT_BASE
  - SYSTEM_PROMPT_PSEARCH
  - SYSTEM_PROMPT_USDTW

수정 시 주의:
- 오케스트레이터는 곰 스타일 정책을 유지한다.
- 개인봇 스타일 문서와 혼용하지 않는다.

### 2) 응답 후처리(곰 스타일 부착)

- 위치: [apps/slack-bot/socket_mode_runner.py](../../apps/slack-bot/socket_mode_runner.py)
- 함수:
  - add_gom_emojis(...)

수정 시 주의:
- 후처리 함수는 /psearch, /usdtw 등 Perplexity 응답 경로에 공통 영향을 준다.
- 문장 종결 방식과 이모지 위치를 바꾸면 기존 테스트 스냅샷이 달라질 수 있다.

### 3) Slack 마크다운 포맷

- 위치: [shared/utils/slack_formatter.py](../../shared/utils/slack_formatter.py)
- 함수:
  - to_slack_format(...)

수정 시 주의:
- 스타일 문구를 바꾸기 전에 포맷터가 특수문자를 제거/변환하는지 확인한다.

## 빠른 점검 절차

1. 문법 검사

```bash
python -m py_compile apps/slack-bot/socket_mode_runner.py
python -m py_compile shared/utils/slack_formatter.py
```

2. 봇 실행

```bash
python apps/slack-bot/socket_mode_runner.py
```

3. Slack 확인

- /psearch 질문 후 곰 스타일 적용 여부
- /usdtw 응답의 곰 스타일 형식 유지 여부
- /reply 결과 문장 종결 톤 확인

## 관련 문서

- [개인봇 스타일 가이드](./personal-bot-style.md)
- [/psearch 운영 가이드](./psearch-guideline-management.md)
