# TeamSlack PoC 빠른 참조 가이드

## 📍 지금 할 일

**1단계: 환경 설정** (선택)
- 🐳 Docker 선택: [SETUP_GUIDE.md - 옵션 3](#)
- 🐍 Python 선택: [SETUP_GUIDE.md - 옵션 1](#)

**2단계: 서비스 시작**
```bash
# Docker 사용자
docker-compose up -d

# Python 사용자
# (터미널 1) FastAPI
python -m uvicorn apps.slack-bot.main:app --reload

# (터미널 2) Celery Worker
celery -A services.orchestrator.tasks worker --loglevel=info

# (터미널 3) Redis
docker run -d -p 6379:6379 redis:7-alpine
```

**3단계: 검증**
```bash
curl http://localhost:8000/api/health
# {"status": "ok", "version": "0.1.0", "timestamp": "..."}
```

## 🗂 주요 파일 위치

```
📁 TeamSlack/
├─ README.md                    ← 프로젝트 개요 읽기
├─ SETUP_GUIDE.md              ← 환경 설정 (이걸 먼저!)
├─ docker-compose.yml          ← Docker로 실행할 때
├─ requirements.txt            ← 파이썬 의존성
│
├─ 📁 apps/slack-bot/
│  ├─ main.py                  ← FastAPI 진입점
│  ├─ slack_handler.py         ← Slack 이벤트 핸들러
│  └─ message_templates.py     ← Slack 메시지 포맷
│
├─ 📁 services/
│  ├─ orchestrator/
│  │  └─ orchestrator.py       ← 요청 라이프사이클 관리
│  ├─ meeting-bot/
│  │  └─ meeting_bot.py        ← 회의 파싱
│  ├─ jira-bot/
│  │  └─ jira_bot.py           ← Jira 드래프트 생성
│  └─ review-bot/
│     └─ review_bot.py         ← 품질 검수
│
├─ 📁 shared/
│  ├─ model-gateway/
│  │  └─ gateway.py            ← LLM 호출 (BYOK 지원)
│  ├─ audit-log/
│  │  └─ logger.py             ← 중앙 로깅
│  └─ profile/
│     └─ profile_manager.py    ← 사용자 프로필
│
└─ 📁 docs/
   ├─ state-machine.md         ← 10 상태 + Mermaid 다이어그램
   ├─ db-schema.md             ← ERD + 테이블 정의
   ├─ test-scenarios.md        ← 8개 E2E 시나리오
   ├─ approval-policy.md       ← 재시도 정책
   └─ DOCKER_GUIDE.md          ← 배포 (ECS, K8s 포함)
```

## 🔑 핵심 개념

### 요청 추적
```
request_id : 고유 요청 ID (UUID)
trace_id   : 전체 실행 경로 추적
action_key : 중복 방지 (request_id::step::action)
```

### 상태 머신
```
RECEIVED → PARSING → MEETING_DONE → JIRA_DRAFTED → REVIEW_DONE
         → WAITING_APPROVAL → APPROVED/CANCELED → DONE/FAILED
```

### Slack 메시지 류
```
1. DM (사용자 에게)
   - 요청 확인: "요청이 접수되었습니다"
   - 결과 전달: "✅ 완료. [Jira 링크]"

2. 오케스트레이션 채널
   - 부모 메시지: 요청 요약 + 진행률
   - Thread: 각 단계별 로그
```

## ⚙️ 환경 변수 설정

```bash
# 필수 (Slack)
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
SLACK_SIGNING_SECRET=...
SLACK_ORCHESTRA_CHANNEL_ID=C...

# 필수 (DB)
DATABASE_URL=postgresql://teamslack:teamslack_dev@localhost:5432/teamslack
REDIS_URL=redis://localhost:6379/0

# LLM (최소 하나 필요)
OPENAI_API_KEY=sk-proj-...
# 또는
ANTHROPIC_API_KEY=sk-ant-...
# 또는
GEMINI_API_KEY=AI...
DEFAULT_MODEL_PROVIDER=openai

# 선택
JIRA_BASE_URL=https://your-jira.atlassian.net
JIRA_EMAIL=your-email@company.com
JIRA_API_TOKEN=...
JIRA_PROJECT_KEY=TS
```

## 🧪 테스트 시나리오

8개 시나리오 포함 ([docs/test-scenarios.md](./docs/test-scenarios.md)):

1. **정상 흐름** - 요청 → 분석 → Jira → 검수 → 승인 → 완료
2. **수정 요청** - 사용자가 "수정 요청" 버튼 클릭
3. **자동 재시도** - LLM 타임아웃 시 자동 복구
4. **재시도 초과** - 3회 재시도 후 실패
5. **중복 방지** - 동일 버튼 2회 클릭 → 1회만 처리
6. **타임아웃** - 600초 후 자동 취소
7. **BYOK 전환** - 사용자 API 키로 전환
8. **다중 페르소나** - PM/Developer/Designer 맞춤 포맷

## 🔗 자주 사용하는 명령어

### Docker
```bash
docker-compose up -d          # 시작
docker-compose down           # 중단
docker-compose logs -f app    # FastAPI 로그
docker-compose logs -f worker # Celery 로그
docker-compose ps             # 상태 확인
```

### Python/Uvicorn
```bash
# 활성화
.\venv\Scripts\Activate.ps1

# FastAPI 서버
python -m uvicorn apps.slack-bot.main:app --reload --port 8000

# health check
curl http://localhost:8000/api/health
```

### Database
```bash
# PostgreSQL 직접 접속 (Docker)
docker-compose exec postgres psql -U teamslack -d teamslack

# 테이블 확인
\dt

# 테이블 내용 조회
SELECT * FROM requests LIMIT 5;
```

### Logs & 모니터링
```bash
# 전체 로그 저장
docker-compose logs > logs/debug.log 2>&1

# 특정 로그만 추적
docker-compose logs -f app | grep "ERROR"

# 요청 추적 (trace_id로 필터)
docker-compose logs -f | grep "ts-123abc"
```

## 🚨 일반적인 문제

| 문제 | 해결 |
|------|------|
| Python not found | [SETUP_GUIDE.md 옵션 1](./SETUP_GUIDE.md) 참조 |
| Docker not found | [SETUP_GUIDE.md 옵션 3](./SETUP_GUIDE.md) 참조 |
| Cannot connect to PostgreSQL | `docker-compose up postgres` 확인 |
| Cannot connect to Redis | `docker-compose up redis` 확인 |
| Slack token invalid | api.slack.com에서 토큰 재확인 |
| timeout | 네트워크/LLM 연결 확인, 로그 검사 |

## 📊 PoC 체크리스트

실행 전:
- [ ] SETUP_GUIDE.md 읽음
- [ ] Python 또는 Docker 설치됨
- [ ] .env 파일 생성 및 토큰 입력
- [ ] Slack 워크스페이스 & 앱 설정 완료

실행 중:
- [ ] docker-compose up -d 성공
- [ ] curl http://localhost:8000/api/health 응답 확인
- [ ] Slack DM으로 테스트 메시지 전송
- [ ] 오케스트레이션 채널에서 진행 상황 확인

테스트 완료:
- [ ] 정상 흐름 테스트 완료
- [ ] E2E 시나리오 최소 3개 통과
- [ ] 로그 레벨 확인 (INFO/WARN/ERROR)

## 📚 추가 리소스

- **아키텍처**: [state-machine.md](./docs/state-machine.md#아키텍처)
- **DB 설계**: [db-schema.md](./docs/db-schema.md)
- **배포**: [DOCKER_GUIDE.md](./docs/DOCKER_GUIDE.md)
- **정책**: [approval-policy.md](./docs/approval-policy.md)
- **오케스트레이터 스타일 수정**: [orchestrator-bot-style.md](./docs/guides/orchestrator-bot-style.md)
- **개인봇 스타일 수정**: [personal-bot-style.md](./docs/guides/personal-bot-style.md)

---

**다음: [SETUP_GUIDE.md](./SETUP_GUIDE.md) 에서 환경을 설정하세요!** 🚀
