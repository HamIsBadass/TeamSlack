# Reply Shortcut 설정 가이드

## 개요

기존의 `/reply` 슬래시 명령어가 **메시지 Shortcut**으로 변경되었습니다.

**장점:**
- ✅ DM/비공개 채널에서도 작동 (봇이 참여하지 않은 채널도 가능)
- ✅ 생성된 초안은 본인 DM에만 전송 (개인 정보 보호)
- ✅ 메시지 우클릭 → 직관적인 UI

---

## Slack 앱 설정

### 1. Slack Workspace 관리 페이지 접속
- Workspace 좌측 상단의 워크스페이스 이름 → **Settings & Administration** → **Manage Apps**
- 또는 [api.slack.com](https://api.slack.com) → **My Apps** → 해당 앱 선택

### 2. Shortcuts 추가

**위치:** `Interactivity & Shortcuts` → `Create New`

**설정 값:**

| 항목 | 값 |
|------|-----|
| **Shortcut type** | `Message shortcut` |
| **Shortcut name** | `Reply draft 생성` |
| **Shortcut ID** | `reply_draft_shortcut` |
| **Description** | `메시지에 대한 답변 초안을 생성하고 DM으로 보냅니다.` |

**Callback URL:** (자동으로 채워짐 - Socket Mode 사용 중이므로 필수 아님)

### 3. 설정 저장

`Create` 클릭 → 앱이 자동으로 업데이트됨

---

## 사용 방법

### Shortcut 실행

1. Slack에서 메시지 우클릭 (또는 `...` 메뉴)
2. `More message shortcuts` 선택
3. `Reply draft 생성` 클릭
4. 몇 초 후 봇이 DM으로 초안 전송

### 초안 내용

수신되는 DM:
```
💬 *답변 초안* (Shortcut 생성)

[Gemini가 생성한 3문장 이내의 답변]

---
API: Google Gemini API | 모델: gemini-2.5-flash-lite
문장 제한: 최대 3문장
```

---

## 응답 방식

- **선택 옵션**: 자동으로 "중립 (대기)" 톤으로 생성
- **출력 토큰**: 최대 260개 (비용 최적화)
- **언어**: 존댓말, 간결, 실행 중심

---

## 기존 `/reply` 슬래시 명령어는 더 이상 사용 불가

| 기능 | 이전 (`/reply`) | 현재 (Shortcut) |
|------|-----------------|-----------------|
| 접근 방법 | 슬래시 명령어 | 메시지 우클릭 |
| DM 지원 | ❌ (실패) | ✅ 완벽 지원 |
| 결과 표시 | 공개 (채널 공지) | 비공개 (DM만) |
| 사용 난이도 | 높음 (링크 복사 필요) | 낮음 (우클릭) |

---

## 문제 해결

### Shortcut이 나타나지 않는 경우

1. **앱 권한 확인**
   ```
   Interactivity & Shortcuts → Shortcut 설정에서
   "Callback URL" 필드가 비어있는지 확인
   (Socket Mode 사용 중이므로 비워둔 채 저장)
   ```

2. **캐시 초기화**
   - Slack 웹앱 새로고침: `Ctrl + Shift + R` (Windows/Linux)
   - 또는 모바일 앱 재시작

3. **앱 다시 설치**
   ```
   Settings & Administration → Manage Apps
   → 해당 앱 선택 → Reinstall / Reauthorize
   ```

### DM이 도착하지 않음

- 봇과 DM 대화 확인 (이전에 봇과 대화 이력이 있는지)
- Slack 권한 확인: `chat:write`, `conversations:write`, `im:read`, `im:write`

### API 에러가 나타나는 경우

- `GEMINI_API_KEY` 환경변수 확인
- Google Gemini API 계정 활성 여부 확인
- `gemini-2.5-flash-lite` 모델 접근 권한 확인

---

## 기술 사항

- **호출 방식**: Socket Mode (webhook 불필요)
- **생성 모델**: Google Gemini 2.5 Flash Lite
- **응답 시간**: 보통 1-3초
- **출력 제한**: 최대 3문장 (자동 정렬)
- **비용**: `/reply`(기존) 대비 약 70% 절감
