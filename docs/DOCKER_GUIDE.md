# Docker 실행 가이드

## 사전 준비

1. **환경 변수 설정**
   ```bash
   cp .env.example .env
   # .env 파일을 열어서 실제 값 입력:
   # - Slack tokens (SLACK_BOT_TOKEN, SLACK_APP_TOKEN, etc.)
   # - Jira credentials (JIRA_EMAIL, JIRA_API_TOKEN, etc.)
   # - LLM API keys (OPENAI_API_KEY, etc.)
   # - APP_SECRET_KEY (생성: python -c "import secrets; print(secrets.token_urlsafe(32))")
   ```

2. **Docker & Docker Compose 설치**
   - [Docker Desktop](https://www.docker.com/products/docker-desktop) 설치
   - 확인: `docker --version`, `docker-compose --version`

## 실행 명령어

### 1단계: 로컬 실행 (개발)

```bash
# 1. 프로젝트 디렉토리로 이동
cd /path/to/TeamSlack

# 2. 컨테이너 빌드 및 시작
docker-compose up -d

# 3. 로그 확인
docker-compose logs -f app

# 4. DB 마이그레이션 (필요 시)
docker-compose exec app python -c "from shared.models import init_db; init_db()"

# 5. 상태 확인
curl http://localhost:8000/api/health
# Output: {"status": "ok", "version": "0.1.0", "timestamp": "2024-01-15T10:30:00Z"}
```

### 2단계: 개발 중 코드 변경 감지

docker-compose.yml에서 `--reload` 플래그가 enabled되어 있으므로,
코드 변경 시 FastAPI 자동 재시작됨.

```bash
# 실시간 로그 관찰
docker-compose logs -f app

# 특정 서비스만 확인
docker-compose logs -f worker
docker-compose logs -f postgres
```

### 3단계: 테스트 실행

```bash
# 시나리오 1: 정상 흐름 테스트
# - Slack에서 DM으로 메시지 전송
# - 오케스트레이션 채널에서 진행 상황 확인

# E2E 테스트 (자동, pytest)
docker-compose exec app pytest tests/e2e/

# 단위 테스트
docker-compose exec app pytest tests/unit/ -v
```

## 트러블슈팅

### 포트 충돌
```bash
# 8000 포트 사용 중 (FastAPI)
# docker-compose.yml에서 변경:
ports:
  - "8001:8000"  # 외부:내부

# 5432 포트 사용 중 (PostgreSQL)
ports:
  - "5433:5432"  # 외부:내부
```

### DB 연결 실패
```bash
# DB 상태 확인
docker-compose exec postgres pg_isready -U teamslack

# DB 로그 확인
docker-compose logs postgres

# 명령어로 직접 접속 테스트
docker-compose exec postgres psql -U teamslack -d teamslack -c "SELECT 1"
```

### Redis 연결 실패
```bash
# Redis 상태 확인
docker-compose exec redis redis-cli ping
# Output: PONG

# Redis에 저장된 키 확인
docker-compose exec redis redis-cli KEYS "*"
```

### 0.0.0.0 바인딩 오류 (Windows)
```bash
# docker-compose.yml에서 변경:
command: uvicorn apps.slack-bot.main:app --host 127.0.0.1 --port 8000 --reload
```

## 프로덕션 배포 (AWS ECS/Kubernetes)

### 1. Docker 이미지 빌드
```bash
docker build -t teamslack-bot:latest .
```

### 2. ECR에 푸시 (AWS)
```bash
# ECR 저장소 생성
aws ecr create-repository --repository-name teamslack-bot

# 로그인
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com

# 태그 지정 및 푸시
docker tag teamslack-bot:latest <ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/teamslack-bot:latest
docker push <ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/teamslack-bot:latest
```

### 3. Kubernetes 배포 (k8s-deployment.yaml 예시)
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: teamslack-bot
spec:
  replicas: 2
  selector:
    matchLabels:
      app: teamslack-bot
  template:
    metadata:
      labels:
        app: teamslack-bot
    spec:
      containers:
      - name: app
        image: <ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/teamslack-bot:latest
        ports:
        - containerPort: 8000
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: teamslack-secrets
              key: database-url
        - name: SLACK_BOT_TOKEN
          valueFrom:
            secretKeyRef:
              name: teamslack-secrets
              key: slack-bot-token
        # ... 기타 환경변수
        livenessProbe:
          httpGet:
            path: /api/health
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 30
```

## 로그 수집

### 로컬 (Docker Compose)
```bash
# 전체 로그
docker-compose logs > logs/all.log 2>&1

# 특정 서비스만
docker-compose logs app > logs/app.log 2>&1
docker-compose logs worker > logs/worker.log 2>&1

# 실시간 날짜/시간 포함
docker-compose logs -f --timestamps
```

### 프로덕션 (CloudWatch, ELK)
- CloudWatch Logs Groups:
  - `/teamslack/app`
  - `/teamslack/worker`
  - `/teamslack/postgres`
  - `/teamslack/redis`
- 각 로그는 request_id로 태그됨 (전체 추적 가능)

## 모니터링

### Health Checks
```bash
# 10초마다 /api/health 체크 (docker-compose에서 자동)
docker-compose ps

# 또는 수동 확인
curl http://localhost:8000/api/health
```

### 메트릭 수집 (Prometheus, 향후 추가)
```bash
# Endpoint: http://localhost:8000/metrics
# Prometheus scrape_interval: 15s
```

## 정리

### 컨테이너 중지
```bash
docker-compose down

# 볼륨까지 삭제 (주의!)
docker-compose down -v
```

### 캐시 삭제 및 재빌드
```bash
docker-compose build --no-cache
docker-compose up -d
```
