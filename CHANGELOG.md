# Changelog

모든 주요 변경 사항은 이 파일에 기록한다. 커밋 이력은 `git log`에, 세션 단위 상세 기록은 각 커밋 메시지에 둔다.

---

## 2026-04-20 — Phase 4: Orchestration 통합 + API 비용 추적

### Added
- **`POST /api/orchestrator/submit`** 엔드포인트 ([apps/slack-bot/main.py](apps/slack-bot/main.py))
  - worker 봇 산출물(`meeting_summary` / `jira_draft` / `quality_review` / `query_response`)을 오케스트레이터로 제출
  - 신규 요청 자동 생성 + 기존 `request_id`로 링크도 지원
- **`shared/api_cost_tracker.py`** — 스레드 안전 메모리 기반 비용 추적기
  - per-user/session/request 3단계 집계, `format_cost_footer()` Slack 포맷팅
  - COST_MAPPING: perplexity_research/_standard, gemini_flash/pro, openai_gpt4_turbo/gpt35
- **Block Kit 승인 메시지** ([apps/slack-bot/message_templates.py](apps/slack-bot/message_templates.py))
  - `approval_message` 블록 리스트화, Approve/Request Changes/Cancel 버튼
  - 취소 버튼에 confirmation dialog, 하단 비용 footer + 타임아웃 경고
- **Orchestrator 메서드**
  - `store_worker_output()` — worker 산출물 저장 + 누적 비용 집계
  - `route_to_next_step()` — output_type 기반 다음 상태 라우팅
- Slack ↔ Orchestrator 스레드 연결 (`attach_slack_context`, `_notify_orchestration_channel`, `update_orchestration_message`, `send_approval_request`)

### Routing rules
| source_bot | output_type | next status |
|---|---|---|
| personal_bot | query_response | DONE |
| meeting_bot | meeting_summary | JIRA_DRAFTED |
| jira_bot | jira_draft | REVIEW_DONE |
| review_bot | quality_review | WAITING_APPROVAL |

### Fixed
- `services/orchestrator/orchestrator.py`: `store_worker_output`/`route_to_next_step` 두 메서드가 `list_user_requests` 내부에 잘못 들여쓰기되어 있어 dead code였다. 클래스 레벨로 승격.
- `shared/models.py`: 중복된 `init_db` 정의 제거. 앞 정의는 return 이후에 `_engine=None` 을 두어 도달 불가였고 뒷 정의가 import 시점에 조용히 덮어쓰고 있었다. 모듈 레벨 상태로 승격 후 단일 `init_db` 유지.
- `.gitignore`: `.claude/settings.local.json` 제외 추가.

### Known gaps (Phase 5 대상)
- Worker 봇 3종(meeting/jira/review)은 scaffolding만, 실제 LLM 호출 미구현
- `shared/model-gateway`는 하드코딩 stub 응답 반환
- `services/orchestrator/tasks.py`에 Celery task decorator 0개
- Orchestrator 저장소가 in-memory dict → 재시작 시 요청 유실
- personal-bot과 slack-bot 간 코드 중복 정리 필요

---

## 2026-04-09 — Initial scaffolding

최초 프로젝트 구조 생성. 상세는 커밋 `d73eded` 및 [README.md](README.md) 참조.
