# /reply 구현 가이드 (최신 운영 기준)

작성일: 2026-04-13
상태: 적용 완료 / 운영 중

---

## 1. 현재 상태

| 항목 | 상태 | 비고 |
|---|---|---|
| Gemini SDK | 완료 | `google.genai` 사용 |
| 모델 | 완료 | `gemini-2.5-flash` |
| Slash 명령 | 완료 | `/reply` |
| 누락 입력 보완 | 완료 | `/reply 대기`, `/reply <링크>` 단계 입력 지원 |
| 스레드 + 채널 동시 게시 | 완료 | `reply_broadcast=true` |
| 잘림 보정 | 완료 | 불완전 문장 시 보정 호출 1회 |

---

## 2. 지원 입력 패턴

### 2.1 단일 호출

```text
/reply <message_link> <예|아니오|대기> [선택: 추가맥락]
```

예시:

```text
/reply https://workspace.slack.com/archives/C0AS0C51H0S/p1712000000000000 예 마케팅팀 관점
```

### 2.2 단계 입력

패턴 A:

```text
/reply <message_link>
/reply 대기
```

패턴 B:

```text
/reply 대기
/reply <message_link>
```

둘 다 최종적으로 초안을 생성합니다.

---

## 3. 실행 흐름

1. `/reply` 입력 파싱
2. allowlist 검증
3. 링크/선택값 누락 시 pending 상태 저장
4. 조건 충족 시 원문 메시지 조회 (`conversations.history`)
5. Gemini 초안 생성 (`google.genai`, `gemini-2.5-flash`)
6. 스레드에 게시 + 채널 브로드캐스트 (`chat.postMessage`, `reply_broadcast=true`)
7. 사용자에게 결과/사용 API/모델 안내

---

## 4. Gemini 호출 스펙

기본 생성:

- model: `gemini-2.5-flash`
- max_output_tokens: `1024`
- temperature: `0.7`

문장 보정(잘림 대응):

- 조건: 문장 종결이 어색한 경우
- 추가 1회 호출
- max_output_tokens: `128`
- temperature: `0.2`

---

## 5. Slack 스코프/설정

필수 Bot Scope:

- `commands`
- `chat:write`
- `channels:history`
- `groups:history` (private channel)

추가 권장(일반 메시지 follow-up까지 사용 시):

- Event Subscriptions 활성화
- `message.channels`
- `message.groups` (private channel)

---

## 6. 운영 체크리스트

1. `.env`에 `GEMINI_API_KEY` 설정
2. `SLACK_ALLOWED_USER_IDS` 테스트 사용자 확인
3. `/reply` 단일 호출 테스트
4. `/reply` 단계 입력 테스트
5. 스레드 + 채널 브로드캐스트 동시 확인

---

## 7. 트러블슈팅

### 7.1 선택값 입력 뒤 무반응

원인:
- message event 미수신 또는 이벤트 설정 미활성

대응:
- 채널 메시지 대신 slash 재입력 사용
  - `/reply 대기`

### 7.2 답변이 중간에서 끊김

원인:
- 모델 출력 조기 종료

대응:
- 현재 코드에서 자동 보정 1회 수행

### 7.3 스레드만 작성되고 채널에 안 보임

확인:
- `reply_broadcast=true` 적용 여부
- 채널 권한/앱 권한 확인

---

## 8. 관련 파일

- `apps/slack-bot/socket_mode_runner.py`
- `requirements.txt`
- `shared/utils/model_router.py`
- `.env.example`
