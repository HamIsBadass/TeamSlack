# 개인봇 스킬 개발 가이드

> 이 문서는 **쥐피티🐹 이후에 새로운 개인봇**(예: 회계봇, 공지봇, 분석봇)을 만들 때
> 그대로 따라할 수 있도록 **스킬/엔진 모듈 작성법**과 **임곰(오케스트레이터) 연계
> 방법**을 정리한 레퍼런스다.

## 1. 개인봇 구조 한눈에

쥐피티(personal-bot)는 다음 계층으로 구성된다.

```
apps/personal-bot/
├── socket_mode_runner.py     # 엔트리 — Slack 이벤트/DM/버튼 핸들러
├── <feature>_engine.py        # 도메인 로직(규칙성 파싱, state, Slack I/O 없음)
├── skills/                    # k-skill 스타일 도구 래퍼
│   ├── _base.py
│   ├── <feature>_skill.py     # 엔진을 Slack 문맥에 연결
│   └── <feature>_skill.md     # 사람용 스킬 설명(프롬프트 힌트)
└── fortune_profiles.json      # (예시) 영구 상태 저장 JSON (gitignored)
```

### 역할 분리 원칙

| 레이어 | 책임 | 금지 |
|---|---|---|
| `*_engine.py` | 인텐트 감지 regex, state in-memory/JSON, 순수 로직 | Slack I/O, LLM 호출 |
| `skills/*_skill.py` | 엔진 + Slack WebClient + 템플릿 렌더 | 파싱 로직 재구현 |
| `socket_mode_runner.py` | Bolt 핸들러 등록, 라우팅, 사용자 응답 | 비즈니스 로직 |

엔진이 Slack 비의존이면 unit test 가 쉽고, 동일 엔진을 다른 entry(CLI 검증 스크립트,
다른 봇) 에서 재사용할 수 있다.

## 2. 새 스킬 추가 템플릿

### 2-1. `<feature>_engine.py` 기본 골격

```python
"""<feature> 도메인 엔진 — 인텐트 감지 + 파싱 + state 관리. Slack 비의존."""

from __future__ import annotations
import re, time
from typing import Optional, Dict, Any
from uuid import uuid4

# --- 인텐트 감지 ---
_KEYWORDS = ("키워드1", "키워드2")

def is_<feature>_request(text: str) -> bool:
    if not text:
        return False
    return any(kw in text for kw in _KEYWORDS)

# --- 대상 추출 ---
_RE_TARGET = re.compile(r"...")

def extract_target(text: str) -> Optional[str]:
    m = _RE_TARGET.search(text or "")
    return m.group(1) if m else None

# --- state (필요 시) ---
_PENDING: Dict[str, Dict[str, Any]] = {}
_TTL_SEC = 10 * 60

def _prune() -> None:
    now = time.time()
    for rid in [r for r, s in _PENDING.items() if now - s["created_at"] > _TTL_SEC]:
        _PENDING.pop(rid, None)

def enqueue(**payload) -> str:
    _prune()
    rid = uuid4().hex[:12]
    _PENDING[rid] = {**payload, "created_at": time.time()}
    return rid

def pop(rid: str) -> Optional[Dict[str, Any]]:
    _prune()
    return _PENDING.pop(rid, None)
```

### 2-2. DM 핸들러 라우팅

`socket_mode_runner.py` 의 DM 메인 핸들러에서 **특이성 높은 인텐트를 먼저** 배치한다.
일반 자연어 대화(Gemini fallback)는 항상 맨 마지막.

```python
# 1) multi-step workflow
# 2) direct_send
# 3) forward_request (mention 필수 → 특이성 매우 높음, 상단)
# 4) 특정 feature 요청 (예: is_<feature>_request)
# 5) fortune, weather, subway, ...
# 6) Gemini DM chat (fallback)
```

라우팅 원칙:
- **필수 요소가 많을수록 위**. 단순 키워드 인텐트(예: "운세")는 아래로.
- **옵트아웃/시스템 키워드는 최상단에서 조기 return**. 예: "전달 금지" 류는 slack-bot
  이 받아 처리하므로 personal-bot 은 조용히 return 해 Gemini 오동작 방지.

### 2-3. 영구 상태 저장

- JSON 파일을 모듈과 같은 디렉터리에 두고 `_PROFILES_FILE = Path(__file__).with_name(...)`
  로 참조.
- **개인정보가 포함되면 `.gitignore` 에 추가**하고 `*_example.json` 템플릿만 commit.
  (예: `fortune_profiles.json` 비공개, `fortune_profiles.example.json` 만 commit)
- 로드 시 `_cache` 로 메모리 복제하고 `reload_*()` 로 무효화 메커니즘 제공.

## 3. 임곰에게 요청 보내는 법 (forward 패턴)

다른 사용자에게 메시지 전달 등 **봇이 단독으로 수행하면 위험한 작업**은 모두 임곰에게
의뢰한다.

> **현 구현 상태 (2026-04-24)**: 메시지 전달은 단일 사용자 확인 플로우로
> 돌아가서 **임곰 검토 경로를 거치지 않는다**. 아래 인프라는 **향후 임곰 게이트가
> 필요한 새 기능(예: 외부 API 호출 승인, 파일 공개 승인, 공지 채널 발송)**을 만들
> 때 재사용하기 위해 코드에 남겨둔 상태다. 현재 unused.

### 재사용 가능한 임곰 검토 인프라

이미 다음 파일이 작성돼 있으며 새 event_type 을 정의하면 바로 붙여 쓸 수 있다:

| 파일 | 역할 |
|---|---|
| [`apps/slack-bot/forward_review.py`](../../apps/slack-bot/forward_review.py) | 결정론적 자동 검토 엔진 (HARD_BLOCK/ESCALATE/PASS regex 룰 + in-memory rate limiter + JSON blocklist I/O) |
| [`apps/slack-bot/socket_mode_runner.py`](../../apps/slack-bot/socket_mode_runner.py) `_handle_forward_request_event` | `@app.event("message")` 에서 `metadata.event_type` 으로 라우팅, verdict 에 따라 pass/block/escalate/deliver |
| 동 파일 `forward_escalate_approve` / `forward_escalate_reject` action handler | owner DM 에 버튼 표시 + 클릭 시 승인/거부 처리 |
| 동 파일 `_deliver_to_target`, `_escalation_blocks`, `_orchestra_voice` | 임곰 톤 래핑 + target DM 발송 + escalation UI |
| `_ESCALATION_PENDING` (모듈 전역 dict) | escalation 대기 상태 (봇 재기동 시 유실 — 현재 fortune 승인 패턴과 동일) |

### 새 임곰 게이트 기능 추가 절차

1. **event_type 새로 정의** (예: `"file_publish_request"`, `"external_post_request"`)
2. **개인봇에서 post** — `client.chat_postMessage(channel=ORCHESTRA_CHANNEL, text=..., metadata={event_type, event_payload})`. 페르소나의 `orchestrator_request_prefix` 를 첫 문장으로 복종 어감 유지
3. **검토 룰 작성** — `apps/slack-bot/<feature>_review.py` 를 `forward_review.py` 패턴대로 작성
   - `HARD_BLOCK_PATTERNS: List[Tuple[label, regex]]`
   - `ESCALATE_PATTERNS: List[Tuple[label, regex]]`
   - `review(...) -> ReviewResult(verdict, reasons)` 시그니처
4. **slack-bot 핸들러 분기 추가** — `handle_message` 상단 `metadata.event_type` 검사에 새 타입 분기 `_handle_<feature>_event(event, client, meta, channel_id)` 호출
5. **pass/block/escalate 동작 정의**
   - `pass` → 즉시 실행 + 스레드 피드백 "허가한다곰"
   - `block` → 실행 금지 + 스레드 피드백 "기각한다곰 + 사유"
   - `escalate` → owner DM 에 `허가/기각` 버튼 (action_id 별도 지정, escalation queue 에 payload 보관)
6. **owner 버튼 핸들러** — `@app.action("<feature>_escalate_approve")` / `_reject` 추가. pop queue → 실행 or 기각, owner DM 업데이트 + 오케스트라 스레드 피드백
7. **blocklist/opt-out 이 필요하면** — `forward_review.py` 의 `add_to_blocklist` / `is_recipient_blocked` / opt-out 키워드 감지 패턴을 복제 후 feature 별 JSON 파일 사용

### 재활용 체크리스트

- [ ] 새 `event_type` 문자열은 globally unique (다른 feature 와 겹치지 않게)
- [ ] HARD_BLOCK 룰은 결정론적(regex)만 사용 — LLM 호출 금지
- [ ] owner 미설정 시 escalation 은 자동 기각 (현 `_handle_forward_request_event` 패턴 유지)
- [ ] 모든 자동 실행은 orchestra channel 스레드에 사후 피드백 post (audit trail)
- [ ] personal-bot 측 opt-out 키워드 조기 return 필요 여부 확인 (단일 Slack 앱 공유 구조)
- [ ] Slack scope `metadata.message:read` 이미 활성화 상태 (forward 용으로 추가됨 — 재사용 가능)

### 중요한 설계 교훈 (2026-04-24 경험)

임곰 검토 레이어를 추가할 때는 **먼저 동일 목적의 기존 경로가 없는지** 코드베이스 전체를 확인하라. forward 는 `_handle_direct_send_request` 와 중복되어 정책 비일관 + 이중 응답 버그가 발생했다. 새 기능은 "이게 임곰 게이트가 필요한 진짜 새 도메인인가, 기존 플로우에 게이트만 추가하면 되는가" 판단이 우선.

### 3-1. 통신 규약 — Slack 채널 + metadata

별도 DB/HTTP 필요 없이 **오케스트레이션 채널 메시지 + `metadata` 필드**를 IPC 로 쓴다.
감사 로그 + 상태 기록을 겸한다.

```python
client.chat_postMessage(
    channel=os.getenv("SLACK_ORCHESTRA_CHANNEL_ID"),
    text="<봇 페르소나 톤의 1문장 + 요청 요약>",   # 사람이 읽는 본문
    metadata={
        "event_type": "forward_request",              # 임곰이 라우팅 key 로 사용
        "event_payload": {                            # 봇 간 구조화 페이로드
            "request_id": "<uuid12>",
            "sender_user_id": "<U...>",
            "target_user_id": "<U...>",
            "content": "<본문>",
            "origin_persona": "<persona_id>",         # 예: "personal"
            "requester_dm_channel": "<D...>",
        },
    },
)
```

임곰(`apps/slack-bot/socket_mode_runner.py`)은 `@app.event("message")` 에서 `metadata
.event_type` 을 먼저 검사하므로, 새 작업 타입을 추가할 때는 **새 event_type 문자열**을
정의하고 임곰 측에 분기 함수를 추가한다.

### 3-2. 첫 문장 규약 — `orchestrator_request_prefix`

각 봇의 페르소나 front-matter 에 **복종 어감의 첫 문장 템플릿**을 둔다. 말투는
봇마다 다르지만 "임곰님, …부탁드립니다" 어감은 모든 봇 공통.

```markdown
---
persona_id: personal
display_name: 쥐피티🐹
emoji: ":hamster:"
role: 개인 비서
orchestrator_request_prefix: "임곰님! {subject} 승낙 부탁드립니다요 :hamster:"
---
```

`{subject}` 는 요청 내용으로 치환된다. 호출 시:

```python
persona = get_persona("personal")
prefix = persona.orchestrator_request(
    f"<@{user}> 님의 <@{target}> 앞 메시지 전달"
)
# → "임곰님! <@U…> 님의 <@U…> 앞 메시지 전달 승낙 부탁드립니다요 :hamster:"
```

임곰 본인은 소유자(default 사용자)의 지시에만 복종하지만, **봇 간**에서는 임곰이
상위 권한자다. 신규 개인봇을 만들 때 이 prefix 필드를 반드시 추가한다.

### 3-3. 사전 사용자 확인 (1차 게이트)

임곰으로 넘기기 전 **사용자 본인의 명시적 동의**를 받는다. 이것이 없으면 "봇이
오해해서 보냈다" 알리바이가 생긴다.

권장 UX:
```
📤 아래 내용을 <@박용민>에게 전달한다!
── 미리보기 ──
```<clipped 300자>```
── 끝 ──
[📨 요청]  [❌ 취소]
```

- 버튼 `action_id` 네이밍: `<feature>_confirm` / `<feature>_cancel`
- `value` 에는 request_id 전달
- 클릭 핸들러에서 `body["user"]["id"] == state["sender_user_id"]` 로 소유권 확인
- 성공/실패 시 `chat_update` 로 미리보기 메시지를 완료 상태로 교체 (버튼 제거)

### 3-4. 임곰 측 자동 검토 (2차 게이트)

임곰은 결정론적 규칙만으로 판정한다. **LLM 호출 금지** (비용/지연/오탐 리스크 제거).

현재 `apps/slack-bot/forward_review.py` 에 정의된 세 가지 verdict:

| verdict | 의미 | 동작 |
|---|---|---|
| `pass` | 이상 없음 | 즉시 target 에게 발송 + 스레드 피드백 "허가한다곰" |
| `block` | 하드 룰 매칭 (토큰/API키/base64 덩어리 등) | 즉시 기각, 발송 X |
| `escalate` | 의심 패턴(이메일/전화번호/rate limit) | owner DM 버튼으로 판정 위임 |
| `blocked_by_recipient` | target 이 opt-out 상태 | 발송 X, 발신자에게만 안내 |

새 작업 타입을 추가할 때는 **그 작업에 맞는 HARD_BLOCK/ESCALATE 룰 세트**를 정의해
`forward_review.py` 패턴대로 별도 모듈을 만든다. 임곰 핸들러는 `event_type` 분기로
적절한 review 함수를 호출한다.

### 3-5. 피드백 체인

```
[1] 사용자 → 개인봇 DM (자연어)
[2] 개인봇 → 사용자 DM (미리보기 + 버튼, ephemeral 가능)
[3] 사용자 클릭 → 개인봇 → 오케스트레이션 채널(metadata post)
[4] 임곰 자동 검토 → target DM / owner DM
[5] 임곰 → 오케스트레이션 채널 스레드 (진행/완료/기각 피드백)
```

각 단계에서 `request_id` 를 공유 key 로 써서 audit trail 을 연결한다. 사용자는 1:1 DM
에서, 감사자는 오케스트라 채널 thread 에서 동일 요청을 추적 가능하다.

### 3-6. 재전달 금지(opt-out) 통합

target 의 의사는 `apps/slack-bot/forward_blocklist.json` 에 저장된다. 임곰이 유일한
관리자. 사용자는 임곰에게 DM 으로 아래 키워드 전송해 관리:

| 키워드 | 효과 |
|---|---|
| `전달 금지`, `전달 차단`, `포워드 금지`, `forward off` | blocklist 에 자신 등록 |
| `전달 허용`, `전달 해제`, `포워드 허용`, `forward on` | blocklist 에서 자신 제거 |

**중요**: personal-bot 과 slack-bot 이 같은 Slack 앱 토큰을 공유하므로 DM 이벤트가
양쪽에 중복 수신된다. personal-bot DM 핸들러에 opt-out 키워드 조기 return 을 추가해야
이중 응답을 방지한다 (예시: `socket_mode_runner.py` 의 `_forward_optout_kw` 튜플).

## 4. Slack 앱 스코프 체크리스트

봇 간 협업이 작동하려면 Slack 앱 manifest 에 다음 scope 이 필요하다.

| scope | 쓰임 |
|---|---|
| `chat:write` | 채널/DM 메시지 게시 |
| `chat:write.public` | (선택) 봇이 채널 멤버 아닐 때도 게시 가능 |
| `im:history` | DM 이벤트 수신 |
| `im:write` | target 에게 DM 발송 (`conversations_open` + post) |
| `channels:history` / `groups:history` | 오케스트레이션 채널 메시지 이벤트 수신 |
| `channels:read` | 채널 메타데이터 조회 |
| `metadata` | `chat_postMessage` 에 metadata 필드 전달 (기본 포함) |

그리고 env 변수:
- `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN` / `SLACK_SIGNING_SECRET`
- `SLACK_ORCHESTRA_CHANNEL_ID` — 임곰이 모니터할 채널
- `PERSONAL_BOT_OWNER_USER_ID` — escalation 승인자 (default 사용자)

## 5. 페르소나 / 공통 음성 규칙

- 페르소나 md: `shared/profile/personas/<persona_id>.md`
- 공통 음성 규칙: [`_common.md`](../../shared/profile/personas/_common.md) — loader 가
  자동 prepend
- `orchestrator_request_prefix` 는 front-matter 필수 (기본값
  `"임곰님, {subject} 승낙 부탁드립니다."` 가 자동 적용)
- 관련 문서: [bot-common-voice.md](bot-common-voice.md),
  [personal-bot-style.md](personal-bot-style.md)

## 6. 알려진 제한사항 / 향후 개선

- **pending state 메모리 저장**: 봇 재시작 시 미처리 요청 유실. 장기 TTL(예: 7일) 이
  필요하면 SQLite 로 이관 권장.
- **rate limiter 무한 축적**: `forward_review._rate_log` 는 하루 단위 GC 없음. 트래픽
  커지면 주기 cleanup 필요.
- **단일 Slack 앱 가정**: 각 봇이 별도 Slack 앱으로 분리되면 token/channel 설정 추가
  필요. 현 설계는 모노 앱 기준.
- **content 크기**: Slack metadata payload 는 2–8KB 가 안전 한계. 대용량 첨부는
  upload 후 파일 링크로 대체 권장.

## 7. 체크리스트 (신규 개인봇 생성 시)

- [ ] `apps/<new-bot>/` 디렉터리 + `socket_mode_runner.py` 엔트리
- [ ] `shared/profile/personas/<new_persona>.md` + `orchestrator_request_prefix`
- [ ] 각 기능마다 `<feature>_engine.py` (순수 로직) + `skills/<feature>_skill.py`
- [ ] 영구 상태 JSON 이 있다면 `.gitignore` + example 템플릿
- [ ] DM 핸들러 라우팅 순서 — 특이성 높은 인텐트 상단, Gemini fallback 맨 아래
- [ ] opt-out 키워드 조기 return (단일 Slack 앱 공유 구조인 경우)
- [ ] 임곰 요청이 필요하면 metadata `event_type` 새로 정의 + 임곰 측 분기 함수 추가
- [ ] Slack 앱 manifest scope 업데이트
- [ ] 관련 env 변수 `.env.example` 에 추가
- [ ] `docs/README.md` 의 가이드 인덱스에 신규 봇 스타일 가이드 추가

## 관련 문서

- [personal-bot-style.md](personal-bot-style.md) — 쥐피티 말투 규칙
- [orchestrator-bot-style.md](orchestrator-bot-style.md) — 임곰 말투 규칙
- [bot-common-voice.md](bot-common-voice.md) — 모든 봇 공통 규칙
- [k-skill 공통 설정](../../shared/profile/README.md) — skill 패키지 연동 (있다면)
