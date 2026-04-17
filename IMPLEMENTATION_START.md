# TeamSlack PoC - 구현 시작 가이드

**현재 상태**: Phase 1-8 스캐폴딩 완료

## 📝 구현 체크포인트

### ✅ 완료된 작업
- [x] 44개 파일 생성 (Python, docs, Docker 구성)
- [x] .env 파일 생성 (개발용 값)
- [x] shared/models.py 완성 (SessionLocal 추가)

### 🔄 진행 중
- [ ] shared/audit-log/logger.py 완성 (DB 통합)
- [ ] apps/slack-bot/main.py 단순화
- [ ] FastAPI 로컬 테스트

### ❓ 문제점 & 해결책

**문제 1: Python venv 생성 오류**
```
해결책: Docker Compose 사용 (더 간단함)
또는 WSL2에서 Python 설치
```

**문제 2: logger.py 복잡한 DB 통합**
```
해결책: 먼저 간단한 버전 실행, 점진적 개선
- Stub 모드: DB 없이 실행
- 이후 : 실제 DB 연동
```

## 🚀 지금 할 일 (2가지 옵션)

### 옵션 A: Docker Compose (권장 - 5분)

```bash
# 1. 이미 준비된 모든 파일 확인
docker-compose config

# 2. 서비스 시작 (자동으로 모든 의존성 설정)
docker-compose up -d

# 3. 상태 확인
docker-compose ps

# 4. FastAPI 헬스 체크
curl http://localhost:8000/api/health

# 5. 로그 확인
docker-compose logs -f app
```

### 옵션 B: 로컬 Python 실행 (30분)

```bash
# 1. Python 설치 확인
python --version  # 3.11+ 필요

# 2. 의존성 설치
pip install -r requirements.txt

# 3. PostgreSQL & Redis 시작 (Docker)
docker run -d -p 5432:5432 \
  -e POSTGRES_USER=teamslack \
  -e POSTGRES_PASSWORD=teamslack_dev \
  -e POSTGRES_DB=teamslack \
  postgres:15

docker run -d -p 6379:6379 redis:7-alpine

# 4. 데이터베이스 초기화
python shared/models.py

# 5. FastAPI 서버 시작
python -m uvicorn apps.slack-bot.main:app --reload

# 6. health check
curl http://localhost:8000/api/health
```

## 📊 현재 파일 상태

**준비 완료:**
- ✅ docker-compose.yml (완성)
- ✅ Dockerfile (완성)
- ✅ requirements.txt (완성)
- ✅ .env 파일 (생성됨)
- ✅ shared/models.py (완성)

**진행 중:**
- 🔄 shared/audit-log/logger.py (70% 완성)
- 🔄 apps/slack-bot/main.py (스텁)

**아직 미구현:**
- [ ] ModelGateway 실제 LLM 호출
- [ ] Worker Bot 실제 로직
- [ ] Slack 토큰 통합
- [ ] 테스트

## 🎯 다음 3단계

### 1단계: FastAPI 서버 기동 (5분)

```bash
# Docker Compose 사용
docker-compose up -d

# 또는 로컬 Python 사용
python -m uvicorn apps.slack-bot.main:app --reload
```

**검증:**
```bash
curl http://localhost:8000/api/health
# {"status": "ok", "version": "0.1.0", "timestamp": "..."}
```

### 2단계: 데이터베이스 확인 (2분)

```bash
# PostgreSQL 접속
docker-compose exec postgres psql -U teamslack -d teamslack

# 테이블 확인
\dt

# 또는 로컬 Python
python -c "from shared.models import init_db; init_db()"
```

### 3단계: Slack 통합 테스트 (10분)

1. https://api.slack.com 접속
2. Bot Token과 App Token 얻기
3. .env 파일 업데이트
4. Slack에서 DM 전송 테스트

## 🛠 구현 우선순위

**순서대로 구현해야 할 것:**

1. **Logger 완성** (10분)
   - DB 통합 (이미 stub 준비됨)
   - Query 함수 (간단함)

2. **Slack Handler** (20분)
   - DM 이벤트 수신
   - 요청 생성 로직
   - orchestrator 호출

3. **Orchestrator** (30분)
   - receive_request()
   - route_to_worker()
   - status 업데이트

4. **Worker Bots** (1시간)
   - ModelGateway 러우팅
   - meeting-bot 파싱
   - jira-bot 드래프트 생성
   - review-bot 검수

5. **통합 테스트** (30분)
   - E2E 시나리오 실행
   - 오류 처리 검증
   - 타임아웃 테스트

## 💡 빠른 시작 (가장 간단한 방법)

```bash
# 프로젝트 디렉토리
cd c:\Users\VIRNECT\Downloads\career\Private\TeamSlack

# Docker 사용 (권장)
docker-compose up -d

# 확인
docker-compose ps
curl http://localhost:8000/api/health

# 로그
docker-compose logs -f app

# 멈추기
docker-compose down
```

**이것만 하면 준비 완료!** 🎉

## 📞 지원 & 참고

- **[README.md](./README.md)** - 전체 개요
- **[QUICK_REFERENCE.md](./QUICK_REFERENCE.md)** - 명령어 정리
- **[SETUP_GUIDE.md](./SETUP_GUIDE.md)** - 상세 설정 (4가지 옵션)
- **[IMPLEMENTATION_STATUS.md](./IMPLEMENTATION_STATUS.md)** - 현황 리포트
- **[docs/state-machine.md](./docs/state-machine.md)** - 아키텍처
- **[docs/test-scenarios.md](./docs/test-scenarios.md)** - 테스트 가이드

---

**다음: Docker Compose 실행 또는 로컬 Python 셋업** 👇
