"""Socket Mode runner for the orchestrator bot (짐).

The orchestrator no longer owns user-facing slash commands — `/psearch`, `/usdtw`,
`/reply` have been transferred to the personal bot runner at
[apps/personal-bot/socket_mode_runner.py](../personal-bot/socket_mode_runner.py).

This runner keeps a Socket Mode connection alive so the orchestrator can react to
channel mentions and (future) orchestration events. Add new handlers here only if
they are orchestration-layer concerns (state fan-out, worker dispatch, status
reporting) — not feature work.
"""

import json
import os
import sys
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from shared.profile import get_persona
from shared.utils import to_slack_format

sys.path.insert(0, str(Path(__file__).resolve().parent))
import forward_review  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv(REPO_ROOT / ".env")

ORCHESTRATOR_PERSONA = get_persona("orchestrator")
PERSONAL_BOT_OWNER_USER_ID = os.getenv("PERSONAL_BOT_OWNER_USER_ID", "").strip()


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _orchestra_voice(text: str) -> str:
    """임곰 말투 래퍼. 마지막 문장에 :king_gom: 를 붙여 준다."""
    stripped = text.rstrip()
    if stripped.endswith(":king_gom:"):
        return stripped
    return stripped + " :king_gom:"


def _deliver_to_target(client, *, sender_user_id: str, target_user_id: str,
                       content: str, request_id: str) -> Optional[str]:
    """target 에게 임곰 token 으로 DM 발송. 실패 시 None 반환."""
    try:
        opened = client.conversations_open(users=target_user_id)
        ch = (opened.get("channel", {}) or {}).get("id") or ""
        if not ch:
            return None
        text = _orchestra_voice(
            f"<@{sender_user_id}> 님이 짐을 통해 다음을 전달했다곰.\n"
            "── 전달 내용 ──\n"
            f"```\n{content}\n```\n"
            "── 끝 ──\n"
            f"전달 출처: 쥐피티🐹 DM · 요청 `{request_id}`"
        )
        posted = client.chat_postMessage(channel=ch, text=text)
        return posted.get("ts")
    except Exception as exc:
        logger.exception(f"_deliver_to_target failed: {exc}")
        return None


def _escalation_blocks(*, request_id: str, sender_user_id: str,
                        target_user_id: str, content_preview: str,
                        reasons: list[str]) -> list[dict[str, Any]]:
    reason_text = "\n".join(f"• {r}" for r in reasons) or "• 특이사항 없음"
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"⚠️ 짐이 판단을 유보한다곰. 다음 전달 요청을 owner 가 확정해달라 :king_gom:\n"
                    f"• 요청자: <@{sender_user_id}>\n"
                    f"• 대상: <@{target_user_id}>\n"
                    f"• 요청 ID: `{request_id}`\n"
                    f"• 의심 사유:\n{reason_text}\n"
                    f"• 내용 미리보기:\n```\n{content_preview}\n```"
                ),
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "허가"},
                    "action_id": "forward_escalate_approve",
                    "value": request_id,
                    "style": "primary",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "기각"},
                    "action_id": "forward_escalate_reject",
                    "value": request_id,
                    "style": "danger",
                },
            ],
        },
    ]


# escalation pending queue (in-memory). request_id -> payload
_ESCALATION_PENDING: Dict[str, Dict[str, Any]] = {}


def build_app() -> App:
    bot_token = _required_env("SLACK_BOT_TOKEN")
    signing_secret = _required_env("SLACK_SIGNING_SECRET")
    orchestra_channel = os.getenv("SLACK_ORCHESTRA_CHANNEL_ID", "").strip()

    app = App(token=bot_token, signing_secret=signing_secret)

    @app.event("app_mention")
    def handle_mention(event, say, logger):
        user_id = (event.get("user") or "").strip()
        thread_ts = (event.get("thread_ts") or "").strip()
        redirect = (
            f"<@{user_id}> 짐은 오케스트레이션만 한다곰. "
            "검색·환율·답장 초안은 쥐피티(개인봇)에게 요청하라곰. :king_gom:"
        )
        say(text=to_slack_format(redirect), thread_ts=thread_ts or None)

    @app.event("message")
    def handle_message(event, client, logger):
        """오케스트레이션 채널의 forward_request metadata 메시지 + DM opt-out 명령."""
        channel_type = (event.get("channel_type") or "").strip()
        channel_id = (event.get("channel") or "").strip()
        user_id = (event.get("user") or "").strip()
        text = (event.get("text") or "").strip()
        subtype = (event.get("subtype") or "").strip()
        meta = event.get("metadata") or {}

        # forward_request metadata 메시지는 다른 봇(personal-bot)이 post 한 것이라
        # subtype="bot_message" 가 붙을 수 있다. subtype 필터보다 metadata 검사를 먼저
        # 수행해야 유실되지 않는다.
        if (meta.get("event_type") or "") == "forward_request":
            if orchestra_channel and channel_id != orchestra_channel:
                return
            _handle_forward_request_event(event, client, meta, channel_id)
            return

        # 여기부터는 사용자 발화 경로. 시스템 이벤트/봇 메시지는 모두 스킵.
        if subtype:
            return

        # DM opt-out/opt-in 명령 처리
        if channel_type == "im" or channel_id.startswith("D"):
            if not user_id or not text:
                return
            if forward_review.is_blocklist_add_request(text):
                forward_review.add_to_blocklist(user_id)
                client.chat_postMessage(
                    channel=channel_id,
                    text=_orchestra_voice(
                        "짐이 너를 전달 수신 차단 명단에 등록했다곰. "
                        "이후로는 어떤 봇도 너에게 전달 메시지를 보낼 수 없다."
                    ),
                )
                return
            if forward_review.is_blocklist_remove_request(text):
                removed = forward_review.remove_from_blocklist(user_id)
                msg = (
                    "차단을 해제했다곰. 이제 전달 수신을 허용한다."
                    if removed else "너는 이미 차단 명단에 없다곰."
                )
                client.chat_postMessage(
                    channel=channel_id,
                    text=_orchestra_voice(msg),
                )
                return
            return

    def _handle_forward_request_event(event, client, meta, channel_id):
        """오케스트라 채널에 들어온 forward_request metadata 이벤트 처리."""
        payload = meta.get("event_payload") or {}
        request_id = (payload.get("request_id") or "").strip()
        sender_id = (payload.get("sender_user_id") or "").strip()
        target_id = (payload.get("target_user_id") or "").strip()
        content = payload.get("content") or ""
        if not (request_id and sender_id and target_id and content):
            return
        source_ts = (event.get("ts") or "").strip()

        result = forward_review.review(
            sender_user_id=sender_id,
            target_user_id=target_id,
            content=content,
        )

        if result.verdict == "pass":
            delivered_ts = _deliver_to_target(
                client,
                sender_user_id=sender_id,
                target_user_id=target_id,
                content=content,
                request_id=request_id,
            )
            feedback = (
                _orchestra_voice(
                    f"<@{sender_id}> 요청 `{request_id}` 을 허가한다곰. "
                    f"<@{target_id}> 에게 전달 완료했다."
                ) if delivered_ts else _orchestra_voice(
                    f"<@{sender_id}> 요청 `{request_id}` 은 허가했으나 전달 중 오류가 발생했다곰."
                )
            )
            try:
                client.chat_postMessage(
                    channel=channel_id, text=feedback, thread_ts=source_ts,
                )
            except Exception:
                logger.exception("forward pass feedback post failed")
            return

        if result.verdict == "block":
            reason_text = ", ".join(result.reasons)
            try:
                client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=source_ts,
                    text=_orchestra_voice(
                        f"<@{sender_id}> 요청 `{request_id}` 을 기각한다곰. "
                        f"사유: {reason_text}"
                    ),
                )
            except Exception:
                logger.exception("forward block feedback post failed")
            return

        if result.verdict == "blocked_by_recipient":
            try:
                client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=source_ts,
                    text=_orchestra_voice(
                        f"<@{sender_id}> 요청 `{request_id}` 은 대상이 전달 수신을 차단했으므로 "
                        "보내지 못했다곰. 직접 연락해달라."
                    ),
                )
            except Exception:
                logger.exception("forward recipient-block feedback post failed")
            return

        # escalate
        _ESCALATION_PENDING[request_id] = {
            "sender_user_id": sender_id,
            "target_user_id": target_id,
            "content": content,
            "source_channel": channel_id,
            "source_ts": source_ts,
            "reasons": result.reasons,
        }
        if not PERSONAL_BOT_OWNER_USER_ID:
            try:
                client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=source_ts,
                    text=_orchestra_voice(
                        f"짐이 판단을 유보하나 owner 설정이 없어 기각한다곰. "
                        f"사유: {', '.join(result.reasons)}"
                    ),
                )
            except Exception:
                logger.exception("forward escalate-no-owner feedback failed")
            _ESCALATION_PENDING.pop(request_id, None)
            return
        try:
            opened = client.conversations_open(users=PERSONAL_BOT_OWNER_USER_ID)
            owner_dm = (opened.get("channel", {}) or {}).get("id") or ""
            if not owner_dm:
                raise RuntimeError("owner DM open failed")
            preview = content[:300] + ("…" if len(content) > 300 else "")
            client.chat_postMessage(
                channel=owner_dm,
                text=f"forward 요청 `{request_id}` owner 판정 필요",
                blocks=_escalation_blocks(
                    request_id=request_id,
                    sender_user_id=sender_id,
                    target_user_id=target_id,
                    content_preview=preview,
                    reasons=result.reasons,
                ),
            )
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=source_ts,
                text=_orchestra_voice(
                    f"<@{sender_id}> 요청 `{request_id}` owner 검토 중이다곰."
                ),
            )
        except Exception:
            logger.exception("forward escalate owner DM failed")
            _ESCALATION_PENDING.pop(request_id, None)

    @app.action("forward_escalate_approve")
    def handle_escalate_approve(ack, body, client, logger):
        ack()
        try:
            actor = (body.get("user", {}).get("id") or "").strip()
            rid = (body.get("actions", [{}])[0].get("value") or "").strip()
            if PERSONAL_BOT_OWNER_USER_ID and actor != PERSONAL_BOT_OWNER_USER_ID:
                return
            state = _ESCALATION_PENDING.pop(rid, None)
            if not state:
                return
            delivered_ts = _deliver_to_target(
                client,
                sender_user_id=state["sender_user_id"],
                target_user_id=state["target_user_id"],
                content=state["content"],
                request_id=rid,
            )
            # owner DM 메시지 업데이트
            try:
                msg_ts = (body.get("message", {}).get("ts") or "").strip()
                owner_ch = (body.get("channel", {}).get("id") or "").strip()
                if msg_ts and owner_ch:
                    client.chat_update(
                        channel=owner_ch, ts=msg_ts,
                        text=f"요청 `{rid}` 허가 완료",
                        blocks=[{
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": (
                                f"✅ 요청 `{rid}` owner 허가 완료. "
                                f"<@{state['target_user_id']}> 에게 전달했다곰 :king_gom:"
                            )},
                        }],
                    )
            except Exception:
                logger.warning("forward escalate-approve owner DM update failed", exc_info=True)
            # 오케스트레이션 채널 스레드 피드백
            feedback = (
                _orchestra_voice(
                    f"<@{state['sender_user_id']}> 요청 `{rid}` owner 가 허가했다곰. "
                    f"<@{state['target_user_id']}> 에게 전달 완료."
                ) if delivered_ts else _orchestra_voice(
                    f"<@{state['sender_user_id']}> 요청 `{rid}` 허가됐으나 전달 중 오류."
                )
            )
            try:
                client.chat_postMessage(
                    channel=state["source_channel"],
                    thread_ts=state["source_ts"],
                    text=feedback,
                )
            except Exception:
                logger.warning("forward escalate-approve channel feedback failed", exc_info=True)
        except Exception:
            logger.exception("forward_escalate_approve failed")

    @app.action("forward_escalate_reject")
    def handle_escalate_reject(ack, body, client, logger):
        ack()
        try:
            actor = (body.get("user", {}).get("id") or "").strip()
            rid = (body.get("actions", [{}])[0].get("value") or "").strip()
            if PERSONAL_BOT_OWNER_USER_ID and actor != PERSONAL_BOT_OWNER_USER_ID:
                return
            state = _ESCALATION_PENDING.pop(rid, None)
            if not state:
                return
            try:
                msg_ts = (body.get("message", {}).get("ts") or "").strip()
                owner_ch = (body.get("channel", {}).get("id") or "").strip()
                if msg_ts and owner_ch:
                    client.chat_update(
                        channel=owner_ch, ts=msg_ts,
                        text=f"요청 `{rid}` 기각",
                        blocks=[{
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": (
                                f"❌ 요청 `{rid}` owner 기각. 전달하지 않는다곰 :king_gom:"
                            )},
                        }],
                    )
            except Exception:
                logger.warning("forward escalate-reject owner DM update failed", exc_info=True)
            try:
                client.chat_postMessage(
                    channel=state["source_channel"],
                    thread_ts=state["source_ts"],
                    text=_orchestra_voice(
                        f"<@{state['sender_user_id']}> 요청 `{rid}` 을 owner 가 기각했다곰."
                    ),
                )
            except Exception:
                logger.warning("forward escalate-reject channel feedback failed", exc_info=True)
        except Exception:
            logger.exception("forward_escalate_reject failed")

    return app


def main() -> None:
    app_token = _required_env("SLACK_APP_TOKEN")
    app = build_app()

    logger.info("Starting orchestrator Socket Mode handler")
    SocketModeHandler(app, app_token).start()


if __name__ == "__main__":
    main()
