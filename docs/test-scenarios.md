# E2E 테스트 시나리오

모든 시나리오는 Given/When/Then 형식으로 작성.
각 시나리오를 PoC 완료 전에 수동 또는 자동 테스트해야 함.

## 시나리오 1: 정상 흐름 (Happy Path)

**Given**
- 사용자 alice가 user_profiles에 등록됨
- alice의 persona_style = "developer"
- 오케스트레이션 채널(SLACK_ORCHESTRA_CHANNEL_ID)이 설정됨
- meeting-bot, jira-bot, review-bot 모두 준비됨
- DB 연결 정상

**When**
1. alice가 Slack DM으로 "어제 회의 내용을 정리해줄래?" 메시지 전송
2. orchestrator가 receive_request() 호출 → request_id 생성, status=RECEIVED
3. 오케스트레이션 채널에 부모 메시지 표시 (요청 요약, request_id, 진행 상황)
4. meeting-bot이 transcript 파싱 시작 (상태: PARSING)
5. LLM 호출해서 decisions/action_items/open_questions 추출
6. 상태 전이: PARSING → MEETING_DONE
7. jira-bot이 action_items를 Jira draft로 변환
8. 상태 전이: MEETING_DONE → JIRA_DRAFTED
9. review-bot이 draft 검수 (유효성, 중복 확인)
10. 상태 전이: JIRA_DRAFTED → REVIEW_DONE
11. 상태 전이: REVIEW_DONE → WAITING_APPROVAL
12. 오케스트레이션 채널에 승인 요청 메시지 표시 (요약, "승인/수정요청/중단" 버튼)
13. alice가 "Approve" 버튼 클릭
14. 상태 전이: WAITING_APPROVAL → APPROVED → DONE
15. alice DM으로 결과 요약 전달
16. 오케스트레이션 채널 thread에 "✅ DONE" 로그

**Then**
- request_id를 추적하면:
  - requests 테이블: status=DONE, updated_at 업데이트됨
  - request_steps: 5개 step 모두 status=SUCCESS
  - audit_logs: ℹ️ INFO (시작), ✅ DONE (완료) 로그 누적
  - Slack DM: "완료되었습니다. [요약 및 Jira 링크]" 메시지
  - 오케스트레이션 채널: 부모 메시지 상태 업데이트, thread에 모든 로그

## 시나리오 2: 수정 요청 흐름 (Request Changes)

**Given**
- 시나리오 1의 준비 상태

**When**
1. alice가 승인 화면에서 "수정 요청" 클릭
2. 모달 표시: "어떤 부분을 수정하길 원하시나요?" (텍스트 입력)
3. alice가 "Priority를 High→Medium으로" 입력 후 제출
4. orchestrator가 상태를 PARSING으로 복귀
5. request_steps에 "사용자 수정 요청됨" 로그 기록
6. 원본 transcript + user_feedback을 재처리
7. meeting-bot이 수정된 파싱 실행
8. jira-bot이 수정된 draft 생성
9. review-bot 재검수
10. 다시 승인 대기 상태로 진행

**Then**
- Slack DM: "수정되었습니다. 다시 확인해주세요"
- 오케스트레이션 채널: 🔄 [시간] REVISED 로그
- request_steps에 2번의 PARSING 기록 (원본 + 수정)

## 시나리오 3: 자동 재시도

**Given**
- LLM API가 일시적으로 느림 (OpenAI timeout 또는 rate limit)

**When**
1. meeting-bot이 LLM 호출 → timeout 발생
2. orchestrator가 retry_count 증가 (exponential backoff)
3. 2초 대기 후 재시도 → 성공
4. 다음 단계로 진행

**Then**
- audit_logs에 "⚠️ WARN: Retry 1 due to LLM timeout" 로그
- request_steps.retry_count = 1
- 최종 상태는 DONE (사용자는 지연만 인지, 재시도는 투명)

## 시나리오 4: 재시도 초과 (수동 개입 필요)

**Given**
- LLM API가 완전히 다운 또는 권한 오류 (fatal error)
- 3회 재시도 모두 실패

**When**
1. orchestrator가 재시도 3회 모두 초과
2. request.status = FAILED
3. request_steps.error_message = "LLM API error after 3 retries"
4. 오케스트레이션 채널에 ❌ ERROR 메시지 발송
5. ops 채널에 alert 메시지: "@ops 요청 TS-xxx FAILED, manual intervention needed"

**Then**
- Slack ops 채널: "❌ [10:35:20] Request TS-xxx failed / User: @alice / Step: PARSING / 재시도 3회 초과"
- request_id로 DB 조회하면 error_message 확인 가능
- 운영자가 원인 파악 후 수동 조치 또는 사용자에게 안내

## 시나리오 5: 중복 이벤트 (Idempotency 검사)

**Given**
- alice의 승인 메시지

**When**
1. alice가 실수로 "Approve" 버튼을 2번 클릭 (0.5초 차이)
2. Slack에서 동일 action_id로 2개 이벤트 발송
3. orchestrator가 첫 번째 이벤트 처리: action_key 검사, 처음이므로 진행
4. orchestrator가 두 번째 이벤트 처리: 동일 action_key 발견, 무시

**Then**
- audit_logs에 "ℹ️ [10:35:15] Idempotency check passed" 로그
- 최종 상태: 정확히 1회만 진행 (2회 아님)
- DB에는 approvals 테이블에 1개 record만 존재

## 시나리오 6: 승인 타임아웃

**Given**
- 승인 대기 상태 (WAITING_APPROVAL)
- expires_at = created_at + 600초

**When**
1. 600초 경과
2. background job (check_all_timeouts)이 timeout 확인
3. request.status = CANCELED
4. expires_at 재설정

**Then**
- Slack DM: "요청이 만료되어 취소되었습니다"
- 오케스트레이션 채널: "⏱ [10:40:45] TIMEOUT after 10 minutes"
- request_steps: 상태 변화 없음 (마지막 상태에서 타임아웃)

## 시나리오 7: BYOK 전환

**Given**
- alice의 key_mode = "shared" (초기값)
- alice가 개인 API 키를 연결하고자 함 (향후 구현)

**When**
1. alice가 "/profile" 커맨드 실행 (향후 구현)
2. 설정 모달: "API 키 모드 선택" (shared vs byok)
3. alice가 "BYOK로 전환" 선택
4. alice의 OpenAI API 키 입력
5. 키는 KMS로 암호화하여 저장
6. user_profiles.key_mode = "byok", secret_ref = "kms://..."

**Then**
- 다음 요청부터 ModelGateway가 BYOK 키 사용
- 비용이 alice 계정에서 차감 (공용 계정 제외)
- audit_logs: "ℹ️ key_mode changed from shared to byok"

## 시나리오 8: 다중 페르소나 스타일

**Given**
- 3명의 사용자: alice (pm), bob (developer), charlie (designer)
- 동일한 회의 내용 (회의록 텍스트)

**When**
1. alice, bob, charlie가 순차적으로 "회의 요약해줘" 요청
2. meeting-bot이 동일 transcript 파싱 (동일한 parsed 결과)
3. format_summary(parsed, style="pm") for alice
4. format_summary(parsed, style="developer") for bob
5. format_summary(parsed, style="designer") for charlie

**Then**
- alice DM: 비즈니스 관점 (리스크, 일정, 승인자)
- bob DM: 기술 관점 (엔지니어링 태스크, 의존성)
- charlie DM: UX 관점 (디자인 결정사항, 영향)
- 모두 동일 request_id 기반이지만 다른 포맷

## E2E 테스트 체크리스트

실제 테스트 시 확인할 항목:

### 데이터 일관성
- [ ] request_id가 전체 라이프사이클에서 불변
- [ ] trace_id가 생성되고 모든 단계에서 유지
- [ ] action_key로 중복 방지 (동일 버튼 2회 클릭 시 1회만 처리)
- [ ] audit_logs에 모든 상태 전이 기록됨
- [ ] request_steps 테이블에 5개 step 모두 기록됨

### Slack UX
- [ ] DM 응답이 사용자 persona에 따라 다름 (pm vs developer vs concise)
- [ ] 오케스트레이션 채널에 부모 메시지 + thread 로그 축적됨
- [ ] 승인 버튼 클릭 후 즉시 상태 업데이트 (< 1초)
- [ ] 타임아웃 알림이 5분 전, 1분 전에 전송됨

### 오류 처리
- [ ] 재시도 로직이 3회 시도 후 멈춤
- [ ] exponential backoff 시간 간격이 2초, 4초, 8초
- [ ] 타임아웃 자동 취소됨 (600초 후)
- [ ] 권한 오류는 즉시 실패 (재시도 없음)

### 성능
- [ ] 요청 수신부터 DM 확인 시간: < 2초
- [ ] 전체 PoC 사이클 (요청 → 결과): < 5분 (LLM 포함)
- [ ] DB 조회/쓰기 응답시간: < 200ms

## 테스트 실행 순서

1. **로컬 개발 테스트**
   - 시나리오 1, 2, 5 (정상 흐름 + 중복 방지)
   - DB 구조 검증, Slack 연동 검증

2. **통합 테스트**
   - 시나리오 3, 4 (재시도, 오류 처리)
   - LLM 연동 검증, 예외 처리 검증

3. **사용자 수용 테스트 (UAT)**
   - 시나리오 6, 7, 8 (타임아웃, BYOK, 다중 페르소나)
   - 실제 사용자 피드백 수집

