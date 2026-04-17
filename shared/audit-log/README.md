# Audit Log

요청의 모든 이벤트를 기록하고 Slack 스레드 포맷으로 변환합니다.

## 역할
- 모든 상태 변이, 오류, 승인 이벤트 로깅
- DB와 Slack 스레드에 동시 기록
- 이모지 기반 로그 레벨 시각화 (ℹ️ INFO, ⚠️ WARN, ❌ ERROR, 🟡 APPROVAL, ✅ DONE)
