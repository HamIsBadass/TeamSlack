# 오케스트레이터 봇 스타일 가이드

> 모든 봇에 공통 적용되는 상위 규칙은 [bot-common-voice.md](bot-common-voice.md) 를 먼저 참고. 이 문서는 오케스트레이터 **고유** 규칙만 다룬다.

이 문서는 오케스트레이터 봇(임곰🐻‍❄️)의 말투/표현 규칙을 확인하고 수정하기 위한 기준 문서입니다.

## 적용 대상

- 페르소나 정의: [shared/profile/personas/orchestrator.md](../../shared/profile/personas/orchestrator.md)
- Socket Mode 러너: [apps/slack-bot/socket_mode_runner.py](../../apps/slack-bot/socket_mode_runner.py) — 오케스트레이션 전용
- FastAPI 엔트리: [apps/slack-bot/main.py](../../apps/slack-bot/main.py) — 이벤트 수신/라우팅

## 역할 범위 (2026-04-21 이후)

- **슬래시 커맨드 없음**. `/psearch`, `/usdtw`, `/reply`, `/summary` 는 개인봇(쥐피티🐹)으로 이전. [personal-bot-style.md](./personal-bot-style.md) 참조.
- 오케스트레이터는 요청 접수·상태 전이·워커 디스패치·오케스트레이션 채널 상태 관리만 담당.
- 채널 멘션 시 역할 안내 메시지로 사용자를 개인봇으로 유도한다.

## 현재 스타일 정책

- 톤: 단정형, 군더더기 제거, 한 문장에 하나의 사실
- 3인칭 자기지칭: "짐"
- 종결: "~했다곰" / "~한다곰" + 🐻‍❄️
- 마지막 문장: `:king_gom:` 로 마무리

## 수정 포인트

### 1) 페르소나 음성 규칙

- 파일: [shared/profile/personas/orchestrator.md](../../shared/profile/personas/orchestrator.md)
- 공통 규칙이 loader 단계에서 자동 prepend 된다. 공통 규칙 수정 시 [_common.md](../../shared/profile/personas/_common.md) 편집.

### 2) Socket Mode 이벤트 핸들러

- 파일: [apps/slack-bot/socket_mode_runner.py](../../apps/slack-bot/socket_mode_runner.py)
- 오케스트레이션 목적 핸들러만 추가한다. 사용자-대면 기능(검색, 번역, 답장 초안 등)은 **절대 여기 두지 않는다** — 개인봇 러너로 이전.

## 빠른 점검 절차

1. 문법 검사
   ```bash
   python -m py_compile apps/slack-bot/socket_mode_runner.py
   python -m py_compile shared/profile/persona_loader.py
   ```
2. 러너 실행
   ```bash
   python apps/slack-bot/socket_mode_runner.py
   ```
3. Slack 확인
   - `@임곰` 멘션 시 오케스트레이션 전용 안내 + 곰 스타일 말미 유지 여부

## 관련 문서

- [개인봇 스타일 가이드](./personal-bot-style.md)
- [/psearch 운영 가이드](./psearch-guideline-management.md)
- [봇 공통 음성 규칙](./bot-common-voice.md)
