# TeamSlack PoC - WSL2 실행 가이드

이 가이드는 아래 운영 방식을 기준으로 한다.

- Python 코드 작성/실행: WSL2(Ubuntu) 내부
- FastAPI 서버: WSL2에서 직접 실행
- Celery worker: WSL2에서 직접 실행
- Docker Compose: Postgres, Redis 인프라만 컨테이너로 실행
- VS Code: Remote-WSL 확장으로 WSL2에 접속해 작업

## 1) 사전 준비

### Windows에서 1회 설정

1. WSL2 설치
```powershell
wsl --install -d Ubuntu
```

2. Docker Desktop 설치
- https://www.docker.com/products/docker-desktop/
- Settings > Resources > WSL Integration에서 Ubuntu 배포판 활성화

3. VS Code 확장 설치
- Microsoft Remote Development 확장 팩 또는 Remote - WSL 확장

## 2) VS Code를 WSL2로 열기

1. VS Code에서 Command Palette 실행
2. Remote-WSL: New Window
3. WSL 터미널에서 프로젝트 열기
```bash
cd /mnt/c/Users/VIRNECT/Downloads/career/Private/TeamSlack
code .
```

주의:
- 이후 터미널 경로는 Linux 경로를 사용한다.
- 예: /mnt/c/Users/.../TeamSlack

## 3) Docker Compose로 인프라만 실행

프로젝트의 [docker-compose.yml](docker-compose.yml#L1) 은 인프라 전용으로 구성되어 있다.

```bash
cd /mnt/c/Users/VIRNECT/Downloads/career/Private/TeamSlack
docker compose up -d postgres redis
```

WSL Integration이 아직 안 켜져 있어 WSL에서 `docker` 명령이 없으면 아래 우회 명령을 사용한다.

```bash
"/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe" compose up -d postgres redis
```

상태 확인:
```bash
docker compose ps
docker compose logs -f postgres
docker compose logs -f redis
```

중지:
```bash
docker compose down
```

## 4) WSL2 Python 환경 구성

WSL2(Ubuntu)에서 실행:

```bash
cd /mnt/c/Users/VIRNECT/Downloads/career/Private/TeamSlack

sudo apt update
sudo apt install -y python3-venv python3-pip

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

참고: Windows 드라이브(`/mnt/c/...`)에서 `.venv` 생성 시 권한 오류가 나면, WSL 홈 디렉터리에 venv를 생성해 사용한다.

```bash
python3 -m pip install --user virtualenv
~/.local/bin/virtualenv ~/teamslack-venv
source ~/teamslack-venv/bin/activate
```

환경 변수 파일 생성:
```bash
cp .env.example .env
```

## 4-1) 보안 원칙과 입력 위치

비밀값은 아래에만 넣는다.

- 실제 토큰과 키: [`.env`](.env)
- 입력 예시와 자리표시자: [`.env.example`](.env.example)
- 절대 입력하지 말아야 할 곳: [README.md](README.md), [SETUP_GUIDE.md](SETUP_GUIDE.md), Git 커밋 메시지, 스크린샷, 코드 파일

권장 보안 조치:

1. `.env`는 Git에 커밋하지 않는다. 현재 [.gitignore](.gitignore) 에 포함되어 있다.
2. 토큰은 필요한 항목만 최소한으로 발급한다.
3. Slack/Jira 토큰은 공유용과 테스트용을 분리한다.
4. 가능하면 운영 토큰은 BYOK 또는 별도 비밀 저장소로 옮긴다.
5. 외부에 공유해야 하는 값은 `xoxb`, `xapp`, `sk-` 같은 실제 문자열이 아니라 마스킹한 값만 사용한다.

입력 순서:

1. `.env.example`을 복사해서 `.env` 생성
2. `.env`를 열어서 실제 값 입력
3. WSL에서 서버 실행 전 `source ~/teamslack-venv/bin/activate`
4. FastAPI/Celery 실행은 모두 이 `.env`를 읽는다

필드별 입력 위치:

- `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, `SLACK_APP_TOKEN` → `.env`
- `SLACK_ORCHESTRA_CHANNEL_ID` → `.env`
- `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, `JIRA_PROJECT_KEY` → `.env`
- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` → `.env`
- `APP_SECRET_KEY` → `.env`
- `DATABASE_URL`, `REDIS_URL` → `.env`
- 로컬 실험용 값만 넣을 경우도 `.env`에서만 관리

## 5) FastAPI 서버 실행 (WSL2)

중요: 폴더명이 slack-bot(하이픈)이므로 app-dir 방식으로 실행한다.

```bash
cd /mnt/c/Users/VIRNECT/Downloads/career/Private/TeamSlack
source ~/teamslack-venv/bin/activate

uvicorn main:app --app-dir apps/slack-bot --host 0.0.0.0 --port 8000 --reload
```

헬스 체크:
```bash
curl http://127.0.0.1:8000/api/health
```

## 6) Celery worker 실행 (WSL2)

새 터미널(WSL2)에서 실행:

```bash
cd /mnt/c/Users/VIRNECT/Downloads/career/Private/TeamSlack
source ~/teamslack-venv/bin/activate

celery -A services.orchestrator.tasks.celery_app worker --loglevel=info
```

워커 헬스 테스트:
```bash
python -c "from services.orchestrator.tasks import ping; print(ping.delay().get(timeout=10))"
```

## 6-1) `/psearch` Socket Mode 실행

출력 지침 확인/수정 문서:

- [docs/guides/psearch-guideline-management.md](docs/guides/psearch-guideline-management.md)

Socket Mode에서 슬래시 커맨드를 처리하려면 아래를 실행한다.

```bash
cd /mnt/c/Users/VIRNECT/Downloads/career/Private/TeamSlack
bash scripts/run-psearch-bot.sh
```

슬랙에서 테스트:

```text
/psearch 미국원화 환율
```

필수 환경 변수:

- `SLACK_BOT_TOKEN`
- `SLACK_APP_TOKEN`
- `SLACK_SIGNING_SECRET`
- `PERPLEXITY_API_KEY`

선택 환경 변수:

- `PERPLEXITY_MODEL` (기본값: `sonar`)

## 7) 권장 실행 순서

1. Docker 인프라 시작 (postgres, redis)
2. WSL2에서 .venv 활성화
3. FastAPI 실행
4. Celery worker 실행
5. /api/health 확인
6. `/psearch` Socket Mode 실행 및 슬랙에서 명령 테스트

## 8) 트러블슈팅

### docker compose 명령이 안 될 때
```bash
docker --version
docker compose version
```
- Docker Desktop이 실행 중인지 확인
- Docker Desktop > Settings > WSL Integration 확인

WSL Integration 활성화 전 임시 우회:

```bash
"/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe" --version
"/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe" compose version
```

### FastAPI import 오류
- [apps/slack-bot/main.py](apps/slack-bot/main.py#L1) 기준으로 반드시 아래 명령 사용:
```bash
uvicorn main:app --app-dir apps/slack-bot --reload
```

### Celery가 Redis에 연결 못 할 때
- Redis 컨테이너 상태 확인:
```bash
docker compose ps redis
docker compose logs redis
```
- [services/orchestrator/tasks.py](services/orchestrator/tasks.py#L1) 의 broker 주소 확인

### DB 연결 실패
- Postgres 컨테이너 확인:
```bash
docker compose ps postgres
docker compose logs postgres
```
- .env의 DATABASE_URL 값 확인

## 9) 다음 구현 단계

환경이 올라오면 아래 순서로 진행한다.

1. Slack 이벤트 라우팅 구현: [apps/slack-bot/slack_handler.py](apps/slack-bot/slack_handler.py#L1)
2. 오케스트레이터 상태 전이 구현: [services/orchestrator/orchestrator.py](services/orchestrator/orchestrator.py#L1)
3. 워커 봇 로직 구현: meeting/jira/review bot
4. E2E 시나리오 검증: [docs/test-scenarios.md](docs/test-scenarios.md#L1)
