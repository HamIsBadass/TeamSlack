# 요청 스키마 (Request Schema)

모든 요청과 이벤트에 포함되는 공통 추적 필드를 정의합니다.

## 공통 추적 필드

| 필드명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| request_id | UUID v4 | 요청 단위 고유 키, 생성 시점: receive_request() | 550e8400-e29b-41d4-a716-446655440000 |
| user_id | str | 요청자 Slack user ID | U12345678 |
| tenant_id | str | 팀/워크스페이스 단위 키 (현재는 고정값, BYOK 후 변동) | T_DEFAULT |
| trace_id | UUID v4 | 하나의 실행 체인 전체 추적, 생성 시점: receive_request() | 660f9501-f30c-52e5-b827-556765655111 |
| action_key | str | idempotency 방지용 복합 키, 포맷: {request_id}::{step_name}::{action} | 550e8400...::JIRA_DRAFTED::create_draft |
| created_at | ISO 8601 | 요청 생성 시각 | 2026-04-09T10:30:45.123Z |
| updated_at | ISO 8601 | 마지막 상태 변경 시각 | 2026-04-09T10:35:10.456Z |
| expires_at | ISO 8601 | 자동 취소 시각 (상태별로 다름, 보통 생성 후 24h) | 2026-04-10T10:30:45.123Z |

## 추적 흐름 예시

```
시각         event_type          request_id              trace_id                action_key
10:30:45    RECEIVE             550e8400-...           660f9501-...           550e8400...::%requested%
10:31:00    LLM_CALL            550e8400-...           660f9501-...           550e8400...::PARSING::transcribe
10:31:30    PARSING_COMPLETE    550e8400-...           660f9501-...           550e8400...::PARSING::complete
10:32:00    JIRA_DRAFT_START    550e8400-...           660f9501-...           550e8400...::JIRA_DRAFTED::draft_start
10:32:45    APPROVAL_REQUESTED  550e8400-...           660f9501-...           550e8400...::WAITING_APPROVAL::request_approval
10:35:10    APPROVED            550e8400-...           660f9501-...           550e8400...::APPROVED::user_approved
10:35:15    DONE                550e8400-...           660f9501-...           550e8400...::DONE::workflow_end
```

## Idempotency 키 패턴

중복 요청(Slack 재전송, 버튼 중복 클릭)에 대비:

```
action_key = f"{request_id}::{step_name}::{action}"
```

예시:
- Slack 메시지 재수신: action_key 동일 → 기존 요청 반환 (중복 생성 안 함)
- 승인 버튼 중복 클릭: action_key = "...::WAITING_APPROVAL::approve" → 첫 번째만 처리, 이후 무시

## 데이터 흐름

각 단계에서 request_id는 불변이며, trace_id로 전체 체인을 추적할 수 있습니다:

```
requests 테이블
├─ request_id (PK)
├─ trace_id (전체 추적용)
└─ status (RECEIVED → ... → DONE)

request_steps 테이블
├─ step_id (PK)
├─ request_id (FK)
└─ status (각 단계별 진행 상황)

audit_logs 테이블
├─ log_id (PK)
├─ request_id (FK)
├─ trace_id (참고)
└─ level (INFO/WARN/ERROR/APPROVAL/DONE)
```
