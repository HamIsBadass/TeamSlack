# 승인 및 실패 정책

요청 처리 중 승인이 필요한 작업, 재시도 정책, 실패 처리 방법을 정의합니다.

## 작업 분류표

| 작업 유형 | 승인 필요 | 담당 서비스 | 예시 |
|---|---|---|---|
| 읽기/요약 | ❌ 아니오 | meeting-bot | 회의록 요약, 결정사항 추출 |
| 검수 | ❌ 아니오 | review-bot | draft 검수, 중복 확인 |
| 쓰기 후보 (Jira) | ✅ 예 | jira-bot → Slack approval | Jira 초안 생성, 레이블 추가 |
| 외부 API 연동 | ✅ 예 | (확장 범위) | Slack 채널 생성, 달력 일정 추가 |

## 전체 플로우

### 승인 필수 작업 (Jira 초안 생성)

```
REVIEW_DONE
  ↓
[승인 화면 표시]
  - 요약 + 경고 표시
  - 승인, 수정요청, 중단 버튼
  ↓
사용자 선택 (600초 타임아웃)
  ├→ APPROVED (즉시 처리)
  │    ↓
  │   [실행 단계 또는 완료]
  │    ↓
  │   DONE
  │
  ├→ "수정 요청" (수정 사항 텍스트 입력)
  │    ↓
  │   [PARSING 상태로 복귀, user_feedback 저장]
  │    ↓
  │   [처음부터 재처리]
  │
  └→ CANCELED
       ↓
      (terminal state, 취소됨)

또는 600초 경과 → 자동 CANCELED
```

## 실패/재시도 정책

| 오류 타입 | 원인 예시 | 재시도 | 최대 횟수 | 실패 처리 |
|---|---|---|---|---|
| **재시도 가능** | Slack API timeout, LLM rate limit, 일시 네트워크 오류 | ✅ 지수 백오프 | 3회 | 3회 초과 후 ops 채널 alert |
| **즉시 실패** | 권한 오류, 잘못된 입력 형식, user_id 미등록, 400-level 에러 | ❌ | 0 | 사용자에게 오류 메시지 + 중단 |
| **수동 개입 필요** | 재시도 초과, 승인 만료, 알 수 없는 오류 (500-level) | - | - | ops 채널 alert + 운영자 판단 대기 |

## Retry 정책 (재시도 가능 오류)

```python
retry_count = 0
max_retries = 3

while retry_count < max_retries:
    try:
        result = call_llm_or_api()
        break  # 성공
    except RetriableError as e:
        retry_count += 1
        wait_time = 2 ** retry_count  # 2초, 4초, 8초 (exponential backoff)
        log_warn(f"Retry {retry_count}/{max_retries}: {e}")
        sleep(wait_time)

if retry_count >= max_retries:
    # 모두 실패
    transition_to(FAILED)
    log_event(level=ERROR, message="Max retries exceeded")
    notify_ops_channel(f"Request {request_id} failed after 3 attempts")
```

## 시간아웃 정책

각 상태별 타임아웃 설정:

| 상태 | 타임아웃 | 조치 |
|---|---|---|
| PARSING | 120초 | → FAILED |
| MEETING_DONE | 180초 | → FAILED |
| JIRA_DRAFTED | 120초 | → FAILED |
| REVIEW_DONE | 90초 | → FAILED |
| WAITING_APPROVAL | 600초 (10분) | → CANCELED (자동) |

### WAITING_APPROVAL 타임아웃 상세

```
t=0s      → 승인 화면 표시 + timer 시작
t=300s    → 5분 경과, Slack DM: "5분 남았습니다"
t=540s    → 9분 경과, Slack DM: "1분 남았습니다"
t=600s    → 10분 경과, 자동으로 CANCELED 상태로 전이
           → audit_logs: "⏱ TIMEOUT after 10 minutes"
           → Slack DM: "요청이 만료되어 취소되었습니다"
```

## 사용자 수정 요청 흐름

1. 승인 화면에서 사용자가 "수정 요청" 클릭
2. 모달: "어떤 부분을 수정하길 원하시나요?" (텍스트 입력)
3. orchestrator가 상태를 PARSING으로 복귀, user_feedback 필드에 저장
4. request_steps에 "수정 요청됨" 로그 기록
5. meeting-bot이 원본 transcript + user_feedback을 재처리
6. 새로운 draft 생성
7. 재검수 후 다시 승인 대기 화면 표시

## 중단 (Cancel) 흐름

1. 사용자가 "중단" 클릭 (또는 600초 타임아웃)
2. orchestrator가 상태를 CANCELED로 전이
3. 진행 중인 worker task 중단 신호 발송 (if any, Celery task revoke)
4. Slack DM: "요청이 취소되었습니다"
5. 오케스트레이션 채널 thread: "❌ CANCELED by @user" 로그 + thread lock
6. requests.updated_at 업데이트, expires_at은 현재 시각으로 설정

## 에러 메시지 가이드

### 사용자 대면 (DM)

```
❌ 오류가 발생했습니다: {user_friendly_message}

처리중 문제가 있었습니다:
- 입력 텍스트가 너무 짧습니다 (최소 10글자 필요)
- 권한이 없습니다
- 시스템 일시 오류 (재시도 중입니다...)
```

### 운영자 대면 (ops 채널)

```
❌ [ERROR] Request TS-{short_id} failed

User: @alice
Step: JIRA_DRAFTED
Error: LLM timeout after 3 retries
Details: {error_message}

Action: Please investigate or retry manually
```

