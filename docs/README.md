# Docs Index

프로젝트 문서 네비게이션. 루트에는 [README](../README.md), [SETUP_GUIDE](../SETUP_GUIDE.md), [CHANGELOG](../CHANGELOG.md)만 둔다.

## 아키텍처 & 계약

- [state-machine.md](state-machine.md) — 요청 라이프사이클 상태 10개와 전이 규칙
- [request-schema.md](request-schema.md) — 요청 추적 필드 정의
- [db-schema.md](db-schema.md) — ERD + 테이블 정의 (참고: 현재 구현은 in-memory dict, SQLAlchemy 모델은 [shared/models.py](../shared/models.py)에 정의만 존재)
- [approval-policy.md](approval-policy.md) — 재시도 및 타임아웃 정책
- [test-scenarios.md](test-scenarios.md) — E2E 시나리오 명세

## 운영

- [DOCKER_GUIDE.md](DOCKER_GUIDE.md) — Docker Compose / K8s / AWS ECS 배포
- [security/API_KEYS.template.md](security/API_KEYS.template.md) — API 키 관리 템플릿
- [troubleshooting/](troubleshooting/) — 장애 대응 노트

## 봇 스타일 & 기능 가이드

- [guides/bot-common-voice.md](guides/bot-common-voice.md) — 모든 봇 공통 음성 규칙(상위 지침)
- [guides/orchestrator-bot-style.md](guides/orchestrator-bot-style.md) — 오케스트레이터 봇 페르소나 규칙
- [guides/personal-bot-style.md](guides/personal-bot-style.md) — 개인 봇 페르소나 규칙
- [guides/personal-bot-skill-development.md](guides/personal-bot-skill-development.md) — 신규 개인봇 스킬 개발 + 임곰 요청 패턴 레퍼런스
- [guides/reply-implementation-guide.md](guides/reply-implementation-guide.md), [guides/reply-command-tech-review.md](guides/reply-command-tech-review.md), [guides/reply-shortcut-setup.md](guides/reply-shortcut-setup.md) — 답장 기능
- [guides/psearch-guideline-management.md](guides/psearch-guideline-management.md) — PSearch 가이드라인
- [guides/api-cost-monitoring.md](guides/api-cost-monitoring.md) — API 사용량·비용 확인(슬랙 /cost + 대시보드)
- [guides/notion-api-field-operations.md](guides/notion-api-field-operations.md) — Notion 연동

## Notion 템플릿

- [notion-db/_template.md](notion-db/_template.md)
