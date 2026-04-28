# 시스템 아키텍처 개요

> 이 문서는 **2026-04-28 기준 실제 구현 상태**와 봇 간 관계를 한눈에 보기 위한 맵.
> 설계 비전(예: 10단계 state machine)과 다를 수 있고, 실제 가동 코드가 진실이다.
> 워크플로우 엔진/신규 봇 설계 시 출발점.

## 1. 가동 봇 — 2개

```
┌─────────────────────────────────────────────────────────────┐
│                Slack Workspace (단일 Slack 앱)               │
│   토큰 1개(SLACK_BOT_TOKEN) 공유 — 두 프로세스가 같은 봇 user_id   │
└──────────────┬──────────────────────────────┬───────────────┘
               │                              │
               ▼                              ▼
   ┌──────────────────────┐          ┌──────────────────────┐
   │   apps/personal-bot/ │          │    apps/slack-bot/   │
   │      쥐피티🐹        │          │     임곰🐻‍❄️         │
   │   (개인 비서)        │          │  (오케스트레이터)    │
   │                      │          │                      │
   │ DM 1:1 응대          │          │ 채널 멘션 redirect   │
   │ 다양한 스킬          │          │ forward_review 인프라│
   │ free chat (Gemini)   │          │   (현재 unused)      │
   └──────────────────────┘          └──────────────────────┘
```

> **주의**: 같은 Slack 앱 토큰을 공유하므로 DM 이벤트는 **두 프로세스가 동시 수신**.
> 응답 충돌을 막으려면 한쪽만 처리하도록 keyword 필터링 필요
> (예: forward opt-out 키워드는 personal-bot 에서 조기 return).

### 페르소나만 정의되고 코드 없음 — 3개

| 페르소나 | 파일 | 향후 의도 |
|---|---|---|
| 김비서🧐 | `shared/profile/personas/meeting.md` | 회의록 정리, 회의실 예약(ICS) |
| 한지 | `shared/profile/personas/jira.md` | Jira 이슈 초안 작성 |
| 경민쿤🦛 | `shared/profile/personas/review.md` | Jira 품질 검수, 중복 체크 |

`services/{meeting,jira,review}-bot/` 폴더는 빈 stub. **deploy 안 됨.**

## 2. 디렉터리 구조

```
TeamSlack/
├── apps/                          # 실제 가동 봇
│   ├── personal-bot/              # 쥐피티 — DM 응대, 다중 스킬
│   │   ├── socket_mode_runner.py    # 엔트리, Bolt 핸들러 등록
│   │   ├── <feature>_engine.py      # 도메인별 순수 로직 (Slack 비의존)
│   │   ├── skills/                  # k-skill 호환 래퍼
│   │   ├── forward_engine.py        # 메시지 전달 통합 플로우
│   │   ├── fortune_engine.py        # 사주 (영구: fortune_profiles.json)
│   │   ├── ktx_engine.py / srt_engine.py / subway_engine.py / stock_engine.py /
│   │   │   realestate_engine.py / hanriver_engine.py
│   │   └── fortune_profiles.json    # 영구(PII) — gitignored
│   └── slack-bot/                 # 임곰 — 오케스트레이션 채널
│       ├── socket_mode_runner.py    # 엔트리
│       ├── forward_review.py        # 임곰 검토 인프라 (현재 unused)
│       ├── slack_handler.py         # 이벤트/액션 핸들러
│       └── message_templates.py     # Block Kit 빌더
│
├── services/                      # FastAPI/worker 단(미운영, stub)
│   ├── orchestrator/                # orchestrator.py: Orchestrator 클래스 (in-memory)
│   ├── meeting-bot/                 # stub
│   ├── jira-bot/                    # stub
│   └── review-bot/                  # stub
│
├── shared/                        # 봇 공용 모듈
│   ├── profile/                     # 페르소나 로더 + md 정의
│   │   ├── persona_loader.py        # get_persona(persona_id) → Persona
│   │   └── personas/<id>.md         # front-matter + voice rules
│   ├── utils/                       # to_slack_format, parse_psearch_input 등
│   ├── api_cost_tracker.py          # LLM 비용 누적 (인메모리)
│   ├── model-gateway/               # (미사용) LLM 공용 래퍼 자리
│   ├── audit-log/                   # (미사용) 감사 로그 자리
│   └── models.py                    # SQLAlchemy 모델 정의만 — 실제 DB 미사용
│
├── docs/                          # 가이드/명세
│   ├── README.md                    # 인덱스
│   ├── state-machine.md             # 설계 비전 (10단계) — 현재 미구현
│   ├── request-schema.md            # 추적 필드 — 현재 미구현
│   ├── db-schema.md                 # ERD — 현재 미구현 (in-memory 사용)
│   ├── approval-policy.md
│   └── guides/                      # 봇별 스타일/스킬 가이드
│
└── scripts/                       # 실행 헬퍼 (run-fastapi.sh 등)
```

## 3. 데이터 영속성 현황

| 데이터 | 위치 | 영구 여부 | 비고 |
|---|---|---|---|
| Fortune profile registry | `apps/personal-bot/fortune_profiles.json` | ✓ 디스크 | PII (gitignored) |
| Forward opt-out 명단 | `apps/slack-bot/forward_blocklist.json` | ✓ 디스크 | gitignored. 현재 인프라 unused |
| Fortune approval queue | in-memory `_PENDING_APPROVALS` | ✗ 재시작 시 유실 | TTL 7일 |
| Forward pending preview | in-memory `_PENDING_FORWARDS` | ✗ 재시작 시 유실 | TTL 10분 |
| Direct-send pending state | in-memory `PENDING_DIRECT_SENDS` | ✗ deprecated dead code |
| Multi-step workflow state | in-memory `PENDING_TASK_WORKFLOWS` | ✗ |
| LLM 비용 추적 | `shared/api_cost_tracker.py` 인메모리 | ✗ |
| DB schema (`shared/models.py`) | 정의만 존재 | — | 실제 DB 미연결 |

**핵심**: 영구 저장은 **JSON 파일 2개**뿐. 나머지는 모두 인메모리 → 봇 재기동 시 진행 중 작업 유실.

## 4. LLM/외부 API 의존성

| 용도 | 모델/API | 호출 위치 |
|---|---|---|
| DM 자유 채팅 | Gemini 2.5 Flash Lite | personal-bot `_gemini_chat_dm` |
| 검색 기반 응답 | Perplexity sonar / sonar-pro | personal-bot `_perplexity_chat_dm` |
| 운세 문장 생성 | Gemini | fortune_engine |
| 날씨 geocode | Gemini | weather skill |
| K-skill 프록시 | `k-skill-proxy.nomadamas.org` (hosted) | 지하철/날씨/주식/부동산 등 |
| Slack API | Slack Bolt + Web client | 모든 봇 |
| Korean Stock / 한강 / 부동산 | 자체 hosted proxy 또는 직결 | 각 engine |

비용 누적: `shared/api_cost_tracker` 인메모리 추정치 (재기동 시 0). 실 청구는 각 대시보드.

## 5. 봇 간 통신 — 현재 패턴

### (a) 단일 Slack 앱 토큰 공유
- DM 이벤트: 두 프로세스 모두 수신 → 어느 봇이 처리할지 keyword 분기
- 같은 bot user_id 라 사용자 입장에선 봇이 1개로 보임 (멘션 시 redirect 로 페르소나 분기)

### (b) Slack 채널을 IPC 로 — 설계만 있고 미사용
**forward_review 인프라**가 이 패턴을 구현:
```
personal-bot → 오케스트레이션 채널에 metadata={"event_type": "..."} post
slack-bot → @app.event("message") 에서 metadata.event_type 분기 처리
slack-bot → 같은 채널 thread 에 결과 post (audit trail)
```
**현재 unused** (forward 가 단일 사용자 확인으로 일원화되며 우회). 향후 외부 API
승인/공지 발송 등 게이트 필요한 작업에 재사용 예정.

### (c) Cross-bot 호출 — 미구현
PM봇이 기획봇을 호출하는 식의 구조는 아직 없음. 워크플로우 엔진 신설 필요.

## 6. 환경변수/Secrets

```
~/.config/k-skill/secrets.env       # 0600 권한 plain dotenv (k-skill 공통)
.env / .env.example                 # repo root (Slack 토큰, GEMINI_API_KEY 등)
~/.config/k-skill/...               # k-skill credential resolution order 첫 fallback
```

핵심 변수:
- `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN` / `SLACK_SIGNING_SECRET`
- `SLACK_ORCHESTRA_CHANNEL_ID` — 임곰이 모니터할 채널
- `PERSONAL_BOT_OWNER_USER_ID` — 사주 승인/escalation 받는 default 사용자
- `GEMINI_API_KEY` / `PERPLEXITY_API_KEY`
- `KSKILL_PROXY_BASE_URL` (지하철·날씨 필수, 다른 기능은 hosted 폴백)

## 7. 유저 인터페이스

| 채널 | 봇 | 가능한 작업 |
|---|---|---|
| 사용자 ↔ 봇 DM | 쥐피티(personal-bot) 처리 | 검색, 환율, 답장, 사주, 날씨, 미세먼지, 지하철, 주식, 부동산, 한강, KTX/SRT 조회, 메시지 전달, 자유 채팅 |
| 채널 멘션 (`@봇`) | 임곰(slack-bot) 처리 | 오케스트레이션 안내(개인봇으로 redirect) |
| 슬래시 커맨드 (`/psearch`, `/usdtw`, `/reply`, `/summary`) | personal-bot | 검색·환율·답장·요약 |
| 임곰 채널 metadata post | slack-bot 자동 검토 | (현재 unused) 향후 게이트 작업 |

## 8. 알려진 한계 / 설계 미실현

1. **state machine 미구현** — `docs/state-machine.md` 의 10단계는 비전. 현재는 단순 함수 호출 체인.
2. **DB 미연결** — `shared/models.py` 모델만 있고 SQLAlchemy 엔진/세션 미사용. 영구 데이터는 JSON 파일.
3. **services/ 디렉터리 stub** — meeting/jira/review FastAPI 서비스는 README 만 있음.
4. **워크플로우 오케스트레이션 부재** — 임곰의 핵심 책임이 redirect 안내만. 다중 봇 협업 메커니즘 없음.
5. **모니터링/관측성 없음** — 로그는 stdout, 비용은 인메모리, 트레이싱 없음.
6. **테스트 없음** — `test_*.py` 파일 산발적, 통합 테스트 미운영.

## 9. 다음 단계 — 워크플로우 엔진 설계 시 출발점

워크플로우 엔진을 임곰에 신설할 때 결정해야 할 핵심:

1. **상태 영속화 위치** — 현재 in-memory dict 들이 지배. 워크플로우는 더 길어 SQLite 또는 외부 DB 필요?
2. **봇 간 통신 protocol** — Slack metadata 가 충분? 아니면 별도 message bus?
3. **기존 stub services/ 디렉터리 활용 vs apps/ 에 통합** — services/ 는 FastAPI worker 가정인데 현재 Bolt Socket Mode 만 사용. 일관성 위해 `apps/` 로 모으는 게 자연스러움
4. **forward_review 인프라 재활용** — 게이트 패턴은 그대로 쓸 수 있음 (HARD_BLOCK/ESCALATE/PASS + escalation queue)
5. **persona prefix 활용** — 봇 간 통신 시 "임곰님, ... 부탁드립니다요" 형식이 이미 페르소나 md 에 정의됨. 워크플로우 단계마다 사용
6. **shared/models.py + DB 연결 결단** — 더 이상 미루기 어려움. SQLite 시작 → 필요 시 PostgreSQL

---

## 관련 문서

- [state-machine.md](state-machine.md) — 원래 설계된 상태 머신 (참고용, 미구현)
- [request-schema.md](request-schema.md) — 추적 필드 명세 (미구현)
- [guides/personal-bot-skill-development.md](guides/personal-bot-skill-development.md) — 신규 봇 작성 가이드 + 임곰 게이트 재사용 절차
- [guides/orchestrator-bot-style.md](guides/orchestrator-bot-style.md) — 임곰 페르소나
- [guides/personal-bot-style.md](guides/personal-bot-style.md) — 쥐피티 페르소나
- [guides/bot-common-voice.md](guides/bot-common-voice.md) — 모든 봇 공통 톤
