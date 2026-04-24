# TeamSlack PoC - Slack Meeting Bot Orchestrator

> **개인 DM에서 회의 내용을 받고, 내부 오케스트레이션 채널에서 진행 상황을 가시화하는 Slack 봇 PoC**

## 🎯 프로젝트 개요

TeamSlack은 Slack DM을 통해 회의 내용을 입력받고, 다음의 3단계 워크플로우를 실행하는 것을 목표로 설계되었다.

1. **Meeting Bot** — 회의 내용 파싱 및 요약
2. **Jira Bot** — 액션 아이템을 Jira 이슈 드래프트로 변환
3. **Review Bot** — 생성된 이슈의 품질 검수 및 중복 확인

모든 진행 상황은 **오케스트레이션 채널**에서 가시화되며, 최종 승인 단계에서 사용자 피드백을 반영한다.

### 현재 구현 상태 (2026-04-20)

| 영역 | 상태 |
|------|------|
| Slack 어댑터 + Socket Mode runner | 동작 (DM → 오케스트레이션 채널 루트 메시지 + 스레드 업데이트) |
| Orchestrator 상태머신 + 승인 흐름 | 동작 (in-memory dict 저장, 재시작 시 유실) |
| `/api/orchestrator/submit` 엔드포인트 | 동작 |
| Block Kit 승인 메시지 + API 비용 추적 | 동작 |
| Meeting / Jira / Review worker 봇 | **TODO 스텁** — 실제 LLM 호출 미구현 |
| `shared/model-gateway` | **Stub 응답 반환** |
| Celery 태스크 | **decorator 0개** |
| PostgreSQL 영속화 | **모델만 정의, 미연결** |

자세한 변경 이력은 [CHANGELOG.md](./CHANGELOG.md) 참조.

## 📋 PoC 구조

```
TeamSlack/
├── apps/
│   └── slack-bot/                 # Slack 어댑터 + FastAPI 서버
├── services/
│   ├── orchestrator/              # 요청 라이프사이클 관리
│   ├── meeting-bot/               # 회의 내용 파싱
│   ├── jira-bot/                  # Jira 드래프트 생성
│   └── review-bot/                # 품질 검수
├── shared/
│   ├── model-gateway/             # LLM 호출 인터페이스
│   ├── audit-log/                 # 중앙 집중식 로깅
│   └── profile/                   # 사용자 프로필 & 페르소나
├── docs/
│   ├── state-machine.md           # 10개 상태 + 전환 규칙
│   ├── request-schema.md           # 요청 추적 필드
│   ├── approval-policy.md          # 재시도 & 타임아웃 정책
│   ├── db-schema.md               # ERD + 테이블 정의
│   ├── test-scenarios.md          # 8개 E2E 테스트 시나리오
│   ├── DOCKER_GUIDE.md            # Docker 배포 가이드
│   └── SETUP_GUIDE.md             # 개발 환경 설정 (← 여기서 시작!)
├── docker-compose.yml             # 4 서비스: postgres, redis, app, worker
├── Dockerfile                     # FastAPI + Celery 컨테이너
├── requirements.txt               # Python 의존성
└── setup-dev.bat                  # Windows 자동 설정 스크립트
```

## 🚀 빠른 시작

### 옵션 A: Docker 사용 (권장)

```bash
# 1. Docker Desktop 설치 (https://docker.com)

# 2. 환경 변수 설정
cp .env.example .env
# .env 파일을 열어서 Slack/Jira/LLM 토큰 입력

# 3. 서비스 시작
docker-compose up -d

# 4. 상태 확인
docker-compose ps
curl http://localhost:8000/api/health
# Output: {"status": "ok", "version": "0.1.0", "timestamp": "..."}

# 5. 로그 확인
docker-compose logs -f app
docker-compose logs -f worker

# 6. 중단
docker-compose down
```

### 옵션 B: 로컬 Python 개발

자세한 설정 방법은 **[SETUP_GUIDE.md](./SETUP_GUIDE.md)** 참조

```bash
# Python 3.11+ 필수
python -m venv venv
.\venv\Scripts\Activate.ps1  # Windows PowerShell
# 또는
venv\Scripts\activate.bat     # Windows cmd

# 의존성 설치
pip install -r requirements.txt

# FastAPI 서버 실행 (터미널 1)
# 주의: 디렉터리명에 하이픈(-)이 있어 Python 모듈 import가 안 됨.
# 현재는 스크립트로 직접 실행한다.
python apps/slack-bot/main.py

# Socket Mode runner — 오케스트레이터(임곰🐻‍❄️, 터미널 2)
python apps/slack-bot/socket_mode_runner.py

# Socket Mode runner — 개인봇(쥐피티🐹, /psearch·/usdtw·/reply·/summary, 터미널 3)
python apps/personal-bot/socket_mode_runner.py

# Celery Worker — 현재 태스크 데코레이터 없음 (Phase 5 대상)
# celery -A services.orchestrator.tasks worker --loglevel=info

# Redis 실행 (Docker 또는 WSL2)
docker run -d -p 6379:6379 redis:7-alpine

# PostgreSQL 실행 (Docker 또는 WSL2)
docker run -d -p 5432:5432 \
  -e POSTGRES_USER=teamslack \
  -e POSTGRES_PASSWORD=teamslack_dev \
  -e POSTGRES_DB=teamslack \
  postgres:15
```

## 📚 문서

- **[SETUP_GUIDE.md](./SETUP_GUIDE.md)** — Python/Docker 환경 설정 (필독)
- **[CHANGELOG.md](./CHANGELOG.md)** — 변경 이력
- **[docs/README.md](./docs/README.md)** — 전체 문서 인덱스 (상태머신, DB 스키마, 배포, 봇 스타일 가이드 등)

## 🔧 기술 스택

| 계층 | 기술 |
|------|------|
| **HTTP 프레임워크** | FastAPI + Uvicorn |
| **Slack 통합** | Slack Bolt for Python |
| **작업 큐** | Celery + Redis |
| **데이터베이스** | PostgreSQL + SQLAlchemy 2.0 |
| **AI/LLM** | OpenAI, Anthropic, Google Gemini (BYOK 지원) |
| **컨테이너** | Docker + Docker Compose |
| **배포** | AWS ECS / Kubernetes (선택사항) |

## 📊 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────────────┐
│ Slack (User DM)  ────→  Slack Bot (FastAPI)  ────→  Orchestrator   │
└────────────────────────────────────────────────────────────────────┘
                                │
                ┌───────────────┼───────────────┐
                ↓               ↓               ↓
          Meeting Bot    Jira Bot        Review Bot     (Celery Workers)
          (Transcript)   (Drafts)        (Validation)
                │               │               │
                └───────────────┼───────────────┘
                                ↓
                        ┌────────────────────┐
                        │  Model Gateway     │ (LLM Routing: BYOK or Shared)
                        │  Audit Logger      │ (Event Logging)
                        │  User Profile      │ (Personalization)
                        │  Message Templates │ (Slack UI)
                        └────────────────────┘
                                ↓
                        ┌────────────────────┐
                        │  PostgreSQL (DB)   │ (State, History)
                        │  Redis (Cache)     │ (Dedup, Locks)
                        └────────────────────┘
                                ↓
                    Slack Orchestration Channel
                    (Progress Visualization)
```

## 🔐 환경 변수 설정

`.env.example`을 복사하여 `.env` 생성 후 다음 값 입력:

```bash
# Slack (tokens from https://api.slack.com)
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
SLACK_SIGNING_SECRET=...
SLACK_ORCHESTRA_CHANNEL_ID=C...

# Jira
JIRA_BASE_URL=https://your-jira.atlassian.net
JIRA_EMAIL=your-email@company.com
JIRA_API_TOKEN=...
JIRA_PROJECT_KEY=TS

# Database
DATABASE_URL=postgresql://teamslack:teamslack_dev@localhost:5432/teamslack
REDIS_URL=redis://localhost:6379/0

# LLM Providers (선택)
OPENAI_API_KEY=sk-proj-...
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=AI...
DEFAULT_MODEL_PROVIDER=openai

# App Settings
APP_ENV=development
APP_SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
BYOK_ENABLED=false  # Bring Your Own Keys
```

## 📖 API 엔드포인트

| 메소드 | 경로 | 설명 |
|-------|------|------|
| `POST` | `/slack/events` | Slack Events API 수신 |
| `POST` | `/slack/actions` | 버튼 클릭, 모달 제출 |
| `GET` | `/api/requests/{id}` | 요청 상태 조회 |
| `GET` | `/api/health` | 헬스 체크 |

## 🧪 테스트 실행

```bash
# E2E 테스트 시나리오 확인
cat docs/test-scenarios.md

# 로컬 테스트 (Slack 토큰 필요)
# 1. Slack DM으로 메시지 전송
# 2. 오케스트레이션 채널에서 진행 상황 확인
# 3. 승인 버튼 클릭 → 완료

# 자동 테스트 (향후 추가)
pytest tests/
```

## 🚢 배포

### Docker Compose (로컬 또는 단순 배포)

```bash
docker-compose up -d
```

### AWS ECS (엔터프라이즈 규모)

```bash
# ECR에 이미지 푸시
aws ecr create-repository --repository-name teamslack-bot
docker tag teamslack-bot:latest <ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/teamslack-bot:latest
docker push <ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/teamslack-bot:latest

# ECS 서비스 배포 (자세한 방법: DOCKER_GUIDE.md)
```

### Kubernetes (멀티클러스터 스케일링)

```bash
kubectl apply -f k8s-deployment.yaml
# (자세한 설정: DOCKER_GUIDE.md)
```

## 📝 상태 흐름

```
RECEIVED  ┐
    ├─→ PARSING
PARSING   ├─→ MEETING_DONE
    └─→ JIRA_DRAFTED
          ├─→ REVIEW_DONE
          └─→ WAITING_APPROVAL
                ├─→ APPROVED
                ├─→ CANCELED
                └─→ DONE / FAILED
```

자세한 내용: [state-machine.md](./docs/state-machine.md)

## 🔄 요청 라이프사이클

1. **사용자 입력** → `alice`가 Slack DM으로 "어제 회의 요약해줄래?" 전송
2. **요청 생성** → `REQUEST ID: ts-xxx` 생성, 상태 = `RECEIVED`
3. **파싱** → Meeting Bot이 LLM으로 회의 내용 분석
4. **Jira 드래프트** → 액션 아이템을 Jira 이슈로 변환
5. **검수** → Review Bot이 품질 확인, 중복 검사
6. **승인 대기** → 오케스트레이션 채널에 "승인/수정/취소" 버튼 표시
7. **최종 승인** → 사용자 버튼 클릭 → 상태 = `DONE`
8. **결과 전달** → DM으로 Jira 링크 + 요약 전송

## 📈 PoC 검증 기준 (목표)

- [ ] 요청부터 결과까지 < 5분 (LLM 포함) — worker 미구현이라 미측정
- [x] 사용자 페르소나 스타일 정의 (PM / Developer / Designer / Concise) — `shared/profile`에 스키마만
- [ ] 중복 요청 자동 필터링 (Idempotency) — 미구현
- [ ] 재시도 정책: 3회 시도 + exponential backoff — 미구현
- [x] DM 요청이 오케스트레이션 채널 스레드에 실시간 반영
- [ ] BYOK (사용자별 API 키) — 스캐폴딩만, 실제 키 로딩 경로 미연결

## 🐛 트러블슈팅

### 1. Python 환경 문제
→ [SETUP_GUIDE.md](./SETUP_GUIDE.md#트러블슈팅) 참조

### 2. Docker 연결 실패
```bash
docker-compose logs postgres
docker-compose logs app
```

### 3. Slack 연결 실패
- SLACK_BOT_TOKEN, SLACK_APP_TOKEN 확인
- https://api.slack.com에서 토큰 재생성

### 4. Jira 연결 실패
- JIRA_BASE_URL 형식: `https://your-domain.atlassian.net`
- JIRA_API_TOKEN: Personal Access Token (not password)

## 📞 지원

문제 발생 시:
1. [SETUP_GUIDE.md](./SETUP_GUIDE.md) - 환경 설정 문제
2. [DOCKER_GUIDE.md](./docs/DOCKER_GUIDE.md) - Docker/배포 문제
3. 로그 확인: `docker-compose logs -f`
4. 상태 머신 검증: [state-machine.md](./docs/state-machine.md)

## 📄 라이센스

Internal PoC - 개발용

---

**[→ SETUP_GUIDE.md로 시작하기](./SETUP_GUIDE.md)**
