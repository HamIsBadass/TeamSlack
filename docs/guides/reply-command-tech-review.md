# /reply 명령어 기술 검토서 (최신 반영본)

작성일: 2026-04-13
대상: TeamSlack Slack Bot `/reply`
상태: 운영 반영 완료

---

## 1) 현재 구현 요약

- 명령어: `/reply`
- 목적: Slack 메시지 링크 기준 답변 초안 생성
- LLM: Google Gemini API (`google.genai`)
- 기본 모델: `gemini-2.5-flash`
- 출력 방식: 스레드 작성 + 채널 브로드캐스트(`reply_broadcast=true`)

---

## 2) 실제 동작 시나리오

### A. 한 번에 입력

```text
```

예시:
### B. 누락 파라미터 단계 입력 (현재 반영)
1. `/reply <message_link>` 입력
2. 봇이 선택값 요청
3. `/reply 대기` 처럼 이어서 입력
4. 초안 생성

반대 순서도 가능:

1. `/reply 대기`
2. `/reply <message_link>`
3. 초안 생성

주의:
- 일반 채널 메시지("대기"만 입력) follow-up은 Slack message event 설정 영향이 있음
- 설정이 없어도 slash command 재입력(`/reply 대기`) 경로는 동작하도록 구현됨

---

## 3) API/모델/파라미터 (실구현 기준)

### Gemini 생성

- SDK: `google.genai`
- API: `client.models.generate_content(...)`
- 모델: `gemini-2.5-flash`
- 생성 파라미터:
  - `max_output_tokens=1024`
  - `temperature=0.7`

### 잘림 보정
- 보정 파라미터:
  - `temperature=0.2`

### Slack 게시

- 원본 조회: `conversations.history`
  - `thread_ts=<원본 ts>`
  - `reply_broadcast=true`


| 항목 | 필수 | 검증 |
|---|---|---|
| choice | 예 | `예`, `아니오`, `대기` |
| context | 아니오 | 자유 텍스트 |


- `chat:write`
- `channels:history`
- `groups:history` (private channel 사용 시)

message event follow-up까지 쓰려면 이벤트 설정 추가 필요:

- `message.channels`
- `message.groups` (private channel)

---

## 6) 주요 에러 원인과 대응

1. 선택값 입력 후 무반응
- 원인: message event 미수신
- 대응: `/reply 대기` 형태로 slash 재입력
2. 답변이 문장 중간에서 절단
- 원인: 모델 출력 중간 종료
- 대응: max tokens 상향 + 종결 보정 1회 호출 적용 완료

3. 스레드에는 작성되지만 채널에 안 보임
- 원인: `reply_broadcast` 미사용
- 대응: `reply_broadcast=true` 적용 완료

---

## 7) 코드 참조

- `apps/slack-bot/socket_mode_runner.py`
- `requirements.txt`
- `shared/utils/model_router.py`
