"""쥐피티 활동 로거 — owner 실시간 미러 + 일간 다이제스트.

A. 실시간 미러 (mirror_to_owner): 다른 사용자가 DM 으로 보낸 입력을 owner DM 으로
   복사. 코드 블록으로 감싸 owner 자신의 입력과 시각적 구분. **2026-04-29 00:00
   KST 부터 자동 비활성화** (오늘만 테스트 요구사항).

B. 일간 다이제스트 (start_digest_scheduler): 매일 19:00 KST 에 owner DM 으로
   사용자/인텐트별 카운트 + 오늘 LLM 비용 + 이번 달 누적 비용을 전송.

저장소: 일별 LLM 비용은 `daily_cost_log.json` 에 누적해 봇 재기동/이월에도 월간
누적이 유지된다. 인텐트 카운터는 in-memory (재기동 시 초기화).
"""

from __future__ import annotations

import datetime
import json
import logging
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 영구 저장: 일별 LLM 비용 누적 (월간 합산용). gitignored 권장.
_LOG_FILE = Path(__file__).with_name("daily_cost_log.json")

# 실시간 미러 자동 만료일 — 이 날짜부터 미러 비활성화.
_MIRROR_EXPIRY = datetime.date(2026, 4, 29)

# in-memory 카운터/누계
_LOCK = threading.RLock()
_TODAY: datetime.date = datetime.date.today()
# {user_id: {label: count}}
_INTENT_STATS: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
# {user_id: [(target_display, count), ...]} — 메시지 전달 같은 target 부속 인텐트 별도
_FORWARD_STATS: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
_TODAY_COST_USD: float = 0.0


# ============ 내부 ============

def _rollover_if_new_day() -> None:
    """자정이 지났으면 오늘 비용을 영속 파일로 저장하고 카운터/누계 초기화."""
    global _TODAY, _INTENT_STATS, _FORWARD_STATS, _TODAY_COST_USD
    today = datetime.date.today()
    if today == _TODAY:
        return
    try:
        _persist_day(_TODAY, _TODAY_COST_USD)
    except Exception as exc:
        logger.warning("activity rollover persist failed: %s", exc)
    _TODAY = today
    _INTENT_STATS = defaultdict(lambda: defaultdict(int))
    _FORWARD_STATS = defaultdict(lambda: defaultdict(int))
    _TODAY_COST_USD = 0.0


def _load_log() -> dict[str, float]:
    if not _LOG_FILE.exists():
        return {}
    try:
        return json.loads(_LOG_FILE.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.warning("daily cost log parse failed: %s", exc)
        return {}


def _persist_day(date_obj: datetime.date, cost_usd: float) -> None:
    data = _load_log()
    data[date_obj.isoformat()] = round(float(cost_usd), 4)
    _LOG_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ============ 공개 API ============

def record_intent(user_id: str, label: str) -> None:
    """간단한 인텐트(운세/날씨/검색 등) 1회 기록."""
    if not user_id or not label:
        return
    with _LOCK:
        _rollover_if_new_day()
        _INTENT_STATS[user_id][label] += 1


def record_forward(user_id: str, target_display: str) -> None:
    """메시지 전달 인텐트 — target 정보 별도 보관 (다이제스트 출력 시 → @대상 표시)."""
    if not user_id:
        return
    with _LOCK:
        _rollover_if_new_day()
        _FORWARD_STATS[user_id][target_display or "?"] += 1


def record_cost(usd: float) -> None:
    """LLM 호출 비용 누적. record_llm_cost_* 헬퍼에서 호출."""
    global _TODAY_COST_USD
    if not usd or usd <= 0:
        return
    with _LOCK:
        _rollover_if_new_day()
        _TODAY_COST_USD += float(usd)
        # 매 호출마다 파일 갱신 — 봇이 디지스트 전에 죽어도 비용 보존
        try:
            _persist_day(_TODAY, _TODAY_COST_USD)
        except Exception as exc:
            logger.debug("cost persist on record failed: %s", exc)


def mirror_to_owner(client, *, sender_user_id: str, owner_user_id: str, text: str,
                    channel_id: str = "") -> None:
    """[A] 다른 사용자 DM 입력을 owner DM 으로 코드 블록 감싸 미러. 만료일 후 no-op."""
    if not owner_user_id or not sender_user_id:
        return
    if sender_user_id == owner_user_id:
        return
    if datetime.date.today() >= _MIRROR_EXPIRY:
        return
    if not text:
        return
    try:
        opened = client.conversations_open(users=owner_user_id)
        owner_ch = (opened.get("channel", {}) or {}).get("id") or ""
        if not owner_ch:
            return
        # 코드 블록으로 감싸 owner 입력창과 구분
        body = (
            f"📨 <@{sender_user_id}> → 쥐피티 DM\n"
            f"```\n{text}\n```"
        )
        client.chat_postMessage(channel=owner_ch, text=body)
    except Exception as exc:
        logger.warning("mirror_to_owner failed: %s", exc)


def build_digest_text() -> str:
    """[B] 다이제스트 문자열 생성. 19:00 자동 발송 + on-demand 호출 가능."""
    with _LOCK:
        _rollover_if_new_day()
        date_str = _TODAY.isoformat()
        lines: list[str] = [f"*{date_str} 쥐피티 활동 보고*"]

        # 사용자별 인텐트 합산
        all_users = set(_INTENT_STATS.keys()) | set(_FORWARD_STATS.keys())
        if not all_users:
            lines.append("• 활동 없음")
        else:
            for uid in sorted(all_users):
                parts: list[str] = []
                for label, count in _INTENT_STATS.get(uid, {}).items():
                    parts.append(f"{label} {count}회")
                fwd = _FORWARD_STATS.get(uid, {})
                if fwd:
                    targets = ", ".join(
                        f"→ {tgt} {cnt}회" for tgt, cnt in fwd.items()
                    )
                    parts.append(f"메시지 전달 ({targets})")
                if parts:
                    lines.append(f"• <@{uid}>: " + ", ".join(parts))

        # 비용 누계
        log = _load_log()
        # 오늘 분은 in-memory 가 최신 — 파일과 비교해 큰 쪽 사용
        log[_TODAY.isoformat()] = max(
            log.get(_TODAY.isoformat(), 0.0), _TODAY_COST_USD,
        )
        month_prefix = _TODAY.strftime("%Y-%m")
        month_total = sum(v for k, v in log.items() if k.startswith(month_prefix))

        lines.append("")
        lines.append(f"오늘 LLM 비용: ${_TODAY_COST_USD:.4f}")
        lines.append(f"이번 달({month_prefix}) 누적: ${month_total:.4f}")
        return "\n".join(lines)


def _digest_loop(client, owner_user_id: str, hour: int = 19, minute: int = 0) -> None:
    """매일 hour:minute 에 owner DM 으로 다이제스트 전송."""
    while True:
        try:
            now = datetime.datetime.now()
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= now:
                target += datetime.timedelta(days=1)
            sleep_sec = (target - now).total_seconds()
            time.sleep(max(60, sleep_sec))  # 최소 60초 대기 (안전 버퍼)
            try:
                text = build_digest_text()
                opened = client.conversations_open(users=owner_user_id)
                ch = (opened.get("channel", {}) or {}).get("id") or ""
                if ch:
                    client.chat_postMessage(channel=ch, text=text)
                # 발송 후 오늘 비용 영속화 한 번 더 보장
                with _LOCK:
                    _persist_day(_TODAY, _TODAY_COST_USD)
            except Exception as exc:
                logger.exception("digest send failed: %s", exc)
        except Exception as exc:
            logger.exception("digest loop error: %s", exc)
            time.sleep(300)


def start_digest_scheduler(client, owner_user_id: str, *, hour: int = 19,
                           minute: int = 0) -> None:
    """[B] 다이제스트 백그라운드 스레드 시작. main() 에서 1회 호출."""
    if not owner_user_id:
        logger.info("digest scheduler skipped (PERSONAL_BOT_OWNER_USER_ID 미설정)")
        return
    t = threading.Thread(
        target=_digest_loop,
        args=(client, owner_user_id),
        kwargs={"hour": hour, "minute": minute},
        daemon=True,
        name="ActivityDigestScheduler",
    )
    t.start()
    logger.info(
        "digest scheduler started: %02d:%02d daily → owner=%s",
        hour, minute, owner_user_id,
    )
