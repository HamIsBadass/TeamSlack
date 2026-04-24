---
name: srt
description: SRT 좌석 조회 (SRTrain 라이브러리 직결). 예약/결제는 자동화하지 않음 — 조회 전용
trigger_keywords: [SRT, srt, 에스알티]
---

# SRT (수서고속철도)

## 동작 개요

1. intent 판정: `is_srt_query(text)` — `SRT`/`srt`/`ＳＲＴ`/`에스알티` 문자열 포함 시 매치
2. 힌트 추출:
   - 출발역/도착역: `_STATION_ALIASES` 사전 매칭 (서울 → 수서로 normalize)
   - 날짜: `오늘/내일/모레/글피` · `2026-03-28` · `3월 28일` (지난 날짜면 내년 roll)
   - 시각: `HH:MM` · `N시` · `오후 N시` → `HHMMSS`. 미지정 시 `000000`
3. SRTrain 호출:
   - `SRT(id, pwd)` 로그인
   - `srt.search_train(dep, arr, date, time, available_only=False)` — 매진 포함
4. 결과 렌더: 상위 5편 (편번호 / 출도착 / 일반·특실 좌석 상태)

## k-skill 통합

**활용 스킬**: `srt-booking` (`~/.agents/skills/srt-booking/SKILL.md`)

**라이브러리**: `SRTrain` (PyPI, `pip install SRTrain`). k-skill-proxy 미경유 — **클라이언트 직결**

**credential**:
- `KSKILL_SRT_ID`, `KSKILL_SRT_PASSWORD` 환경변수 필수
- `~/.config/k-skill/secrets.env` 에서 자동 로드 (socket_mode_runner 부팅 시)
- 값 바꾸면 bot 재기동 필요

**지원 역 (SRT 정차역)**:

| 축약 | 정식명 |
|---|---|
| 서울 | 수서 (SRT 서울역 미정차) |
| 수서 · 동탄 · 평택 · 오송 · 대전 | 동일 |
| 천안 · 아산 | 천안아산 |
| 김천 · 구미 | 김천구미 |
| 동대구 · 대구 | 동대구 |
| 경주 | 신경주 |
| 통도사 | 울산 |
| 부산 · 익산 · 정읍 · 공주 · 목포 | 동일 |
| 광주 · 송정리 | 광주송정 |

## 트리거 예시

```
SRT 수서 부산 내일 9시
SRT 수서에서 동대구 오늘 오전 10시
SRT 수서 광주송정 2026-05-10 14:30
에스알티 서울 부산 모레  ← 서울은 수서로 자동 치환
```

## 예약 자동화 안 하는 이유

1. k-skill SKILL.md 정책: "결제 완료까지는 자동화하지 않는다"
2. 예약은 side-effecting → 사용자 확인 없이 실행 위험
3. 실결제·좌석 확정은 SRT 앱에서 사용자가 직접 수행이 원칙

## 응답 포맷

```
**🚄 SRT 수서 → 부산 · 2026-05-10**
• 18편 조회 (상위 5편)
  - 301편 · 05:30 → 08:10 · 일반 10 · 특실 3
  - 303편 · 06:00 → 08:41 · 일반 매진 · 특실 5
  - ...

`실결제는 SRT 앱에서 직접 — 조회 전용`
```

## 실패 모드

- **KSKILL_SRT_ID/PASSWORD 미설정**: 안내 후 secrets.env 편집 유도
- **SRTrain 미설치**: `pip install SRTrain` 안내
- **로그인 실패**: `SRT 로그인 실패!` + 예외 문자열. 계정 잠금 방지 위해 자동 재시도 없음
- **조회 실패/매진**: 빈 결과는 "조건에 맞는 SRT 가 없어!" 로 안내

## 관련 파일

- [srt_engine.py](../srt_engine.py) — 로직
- `~/.agents/skills/srt-booking/SKILL.md` — upstream k-skill 명세
