# Orchestrator Service

요청 상태 전이, 역할봇 라우팅, 승인 기반 워크플로우를 담당합니다.

## 역할
- 요청 생명주기 관리 (상태 머신)
- 역할봇 (meeting/jira/review) 태스크 큐에 엔큐
- 상태 업데이트 및 Slack 채널 알림
- 승인/거부/취소 액션 처리
